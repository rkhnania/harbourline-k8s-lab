# Cluster triage — first 60 seconds

## 1. What's not healthy?
kubectl get pods -A --field-selector status.phase!=Running
kubectl get pods -A --sort-by=.status.containerStatuses[0].restartCount | tail -10
kubectl get nodes

## 2. What just happened?
kubectl get events -A --sort-by=.lastTimestamp | tail -25

## 3. Why is this pod unhappy?
kubectl describe pod <pod> -n <ns>        # Events at the bottom; Last State for crashes
kubectl logs <pod> -n <ns> --previous     # logs of the CRASHED container
kubectl top pods -n <ns> --sort-by=memory

## 4. Why can't traffic reach it?
kubectl get endpoints <svc> -n <ns>       # empty = selector matches nothing
kubectl get svc <svc> -n <ns> -o jsonpath='{.spec.selector}'
kubectl get pods -n <ns> --show-labels    # compare with the selector
kubectl describe ingress <ing> -n <ns>    # 404 = no rule matched; 503 = no healthy backend

## 5. Test from the affected pod, not from anywhere else
POD=$(kubectl get pod -n <ns> -l <label> -o name | head -1)
kubectl debug -n <ns> $POD --image=nicolaka/netshoot --target=<container> -c dbg -- \
  sh -c 'nslookup <svc>; nc -zv <svc> <port>'
kubectl logs -n <ns> $POD -c dbg

## Symptom → first suspect
| Symptom | Look at |
|---|---|
| Pending | describe pod Events: selector / taint / cordon / capacity / unbound PVC |
| ImagePullBackOff | image name, registry auth, imagePullSecrets |
| CrashLoopBackOff | describe -> Last State (OOMKilled 137?), logs --previous |
| Running but 0/1 | readiness probe |
| 503 via Ingress | endpoints empty, or pods not Ready |
| 404 via Ingress | host/path rule, or ingressClassName |
| Works then fails | events, node pressure, rollout in progress |

## Exit codes
0 clean · 1 app error · 125-127 container/command problem · 137 SIGKILL (OOM) · 143 SIGTERM

## Worked examples (drills)

### Status `Error` / `CrashLoopBackOff`, RESTARTS climbing
The container started and the process exited — so logs exist.
    kubectl logs <pod> --previous --tail=20
    kubectl describe pod <pod> | grep -B4 -A12 "Last State"
Read the exit code: 137 = killed from outside (OOM). 1 or 2 = the app chose to exit.
Started and Finished in the same second = a startup problem (missing file, bad config,
can't bind a port). Dying after minutes/hours = runtime (leak, dependency).
Then check what Kubernetes actually asked it to run:
    kubectl get deploy <d> -o jsonpath='{.spec.template.spec.containers[0].command}'
A `command:` override can point at a file that doesn't exist in the image.
If `kubectl logs -l <label>` says "unable to retrieve container logs", name a single
pod instead, and fall back to `describe` — that data lives in the API server.

### Pods Running 1/1 but callers get "connection refused"
    kubectl get endpoints <svc>
Endpoints populated proves only that the SELECTOR matched pods. It proves nothing
about the port. Compare the two sides:
    kubectl get svc <svc> -o jsonpath='{.spec.ports}'
    kubectl get deploy <d> -o jsonpath='{.spec.template.spec.containers[0].ports}'
targetPort must match containerPort.
refused = packet arrived, nothing listening. timed out = packet went nowhere
(NetworkPolicy, routing, or the destination doesn't exist).

### Pending — policy vs capacity
    kubectl get events --field-selector reason=FailedScheduling --sort-by=.lastTimestamp
"didn't match node affinity/selector" / "untolerated taint" / "were unschedulable"
  -> POLICY. Fix the selector, add a toleration, or uncordon the node.
"Insufficient cpu" / "Insufficient memory"
  -> CAPACITY. Lower requests, or add nodes (Cluster Autoscaler / Karpenter on EKS).
Unbound PVC -> VOLUME. Check `kubectl get pvc` and the storageClassName.
On a kind cluster, ignore the "1 node(s) had untolerated taint(s)" line — that's always
the control plane. Read what the WORKER nodes say.
Compare against allocatable:
    kubectl describe node <node> | grep -A8 Allocatable

## Pending has two families

Check `PodScheduled` in `kubectl describe pod` first — it splits the problem in half.

| Evidence | Who is stuck | Where to look |
|---|---|---|
| `PodScheduled: False` + `FailedScheduling` events | scheduler, cannot place it | capacity, nodeSelector/affinity, taints, unbound PVC |
| `PodScheduled: True`, no container events at all | kubelet, placed but never started | kubelet on that node, `crictl pods` on the node, Node-authorizer errors |

The second one is quiet — no events, no logs, nothing in `describe` but a lone
`Scheduled` line. Go to the node:

    docker exec <node> crictl pods --name <pod-prefix>
    docker exec <node> journalctl -u kubelet --since "10 min ago" --no-pager | tail -40

`kubectl logs` on any Pending pod returns `pods/log not found` — no container has
started, so there is no log endpoint. Not a permissions problem.

See docs/etcd-restore.md gotcha 3 for the case that produced this.
