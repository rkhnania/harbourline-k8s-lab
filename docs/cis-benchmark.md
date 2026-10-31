# CIS Kubernetes Benchmark (kube-bench)

First run: **2026-10-31**, kind cluster `kind-harbourline`, run as a Job from
`aquasecurity/kube-bench`.

```
kubectl --context kind-harbourline apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/main/job.yaml
kubectl --context kind-harbourline logs job/kube-bench
```

## Read the summary correctly before anything else

```
== Summary policies ==
0 checks PASS    0 checks FAIL    34 checks WARN

== Summary total ==
17 checks PASS   2 checks FAIL   40 checks WARN
```

**The 34 policy WARNs are not findings.** Section 5 of the benchmark is
*manual-review* material: kube-bench cannot evaluate most of it automatically,
so it prints the remediation text for every check regardless of the cluster's
actual state. `0 PASS / 0 FAIL / 34 WARN` means **nothing in section 5 was
assessed**, not that 34 things are wrong.

This matters more than the findings themselves. A scanner that emits 34
warnings tells you nothing until you know whether those warnings were
*evaluated* or merely *printed*. Reporting "34 security warnings" from this
output would be wrong, and an interviewer would catch it.

The 2 genuine FAILs are in the node section. **Not yet captured** - see
*Outstanding* below.

## Caveat: kind is not a kubeadm cluster

kind runs the control plane differently from a conventional kubeadm node, so
control-plane file-permission and flag checks report failures that are
artefacts of the test environment rather than real misconfiguration. The
**node** and **policies** sections are the ones that transfer. Control-plane
findings here should be re-tested on the VM cluster (kubeadm, three nodes)
before being treated as real.

## What this project already satisfies

Mapped against section 5, with where each is enforced. Most predate this run;
`5.1.5` and `5.1.6` were closed on the day of it.

| Check | Requirement | Where it is satisfied |
|---|---|---|
| 5.1.5 | Workloads do not use the `default` ServiceAccount | Every workload has a named SA (`55872d3`, `ed86008`, `0cee964`) |
| 5.1.6 | Disable token automount where not needed | `automountServiceAccountToken: false` on all 10 pods and all 5 ServiceAccounts |
| 5.2.1 | Policy control system per namespace | Kyverno, `k8s/policies/harbourline-baseline.yaml` |
| 5.2.2 | No privileged containers | securityContext on every workload; Kyverno enforces |
| 5.2.6 | `allowPrivilegeEscalation: false` | Kyverno rule, Enforce |
| 5.2.7 | `runAsNonRoot` | Kyverno rule, Enforce |
| 5.2.9 | Drop all Linux capabilities | `capabilities: drop: ["ALL"]` on every container |
| 5.3.1 | CNI supports NetworkPolicy | Cilium |
| 5.3.2 | NetworkPolicy objects exist | 13 policies, `k8s/base/networkpolicies.yaml`, default-deny both directions |
| 5.6.2 | seccomp `RuntimeDefault` | Kyverno rule, Enforce |
| 5.6.3 | SecurityContexts applied | Shared Helm chart defaults |
| 5.6.4 | Namespace segregation | `harbourline`, `monitoring`, `argocd`, `kyverno` |

### 5.1.6 is worth quoting, because it is exactly the trap we hit

> If both the ServiceAccount and the Pod's `.spec` specify a value for
> `automountServiceAccountToken`, **the Pod spec takes precedence.**

Which is why it is set in both places: the pod setting is what takes effect,
and the ServiceAccount setting covers any future pod that does not declare one.
The benchmark's own compliance condition requires the pair.

## Known gaps

| Check | Requirement | Status |
|---|---|---|
| 5.4.1 | Read Secrets from mounted files, not environment variables | **Open.** `envFrom` → `secretKeyRef` on api is already on the backlog; the deeper fix is file-mounted secrets. An env var is visible in `/proc/<pid>/environ`, in `kubectl describe`, and in any crash dump. |
| 5.4.2 | External secrets management | **Open.** Postgres password is a plain Secret, base64 in etcd. External Secrets Operator or Vault. |
| 5.5.1 | Image provenance / signing | **Open.** Images are scanned (Trivy, blocking) but not *signed*, and nothing verifies provenance at admission. Cosign + a Kyverno `verifyImages` rule would close it. |
| 5.1.7 | No `system:masters` group members | **Unverified.** |
| 5.1.8 | Remove `impersonate`, `bind`, `escalate` rights | **Unverified.** These three verbs are privilege escalation primitives - `escalate` lets a subject grant itself permissions it does not have. |
| 5.1.9-5.1.13 | Restrict PV create, node proxy, CSR approval, webhook config, SA token sub-resource | **Unverified.** |

The 5.1.7-5.1.13 group is RBAC Module 2 material: each is a question about who
holds a dangerous verb, answerable with `kubectl auth can-i --list` against
real subjects.

## Outstanding

- **Capture the 2 FAILs.** `kubectl --context kind-harbourline logs job/kube-bench | grep '^\[FAIL\]'`
- Re-run on the VM cluster (kubeadm), where control-plane checks are meaningful.
- Clean up the Job: `kubectl --context kind-harbourline delete job kube-bench`
