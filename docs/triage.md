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
