# VM cluster - access

Three-node kubeadm cluster `harbourline-vm` on Hyper-V. All browser endpoints are
served by MetalLB in L2 mode from the pool `192.168.0.240-.250`
([`k8s/vm-cluster/metallb.yaml`](../k8s/vm-cluster/metallb.yaml)).

> **Every command on this page carries `--context harbourline-vm`.**
> There are two clusters in this kubeconfig and both have an `argocd` and a
> `monitoring` namespace. A command without the context flag reads from whichever
> cluster happens to be current, so it returns a confusing `NotFound` against the
> wrong cluster instead of an obvious failure.
>
> Run git commands from `~/harbourline`, not the Windows clone at
> `/mnt/c/Users/Ramsin/Claude/harbourline-k8s-lab`.

## Nodes

| Node | Address | Role |
|---|---|---|
| hl-cp1 | 192.168.0.201 | control plane |
| hl-w1 | 192.168.0.202 | worker, Longhorn replica |
| hl-w2 | 192.168.0.203 | worker, Longhorn replica |

SSH: `ssh ramsin@192.168.0.201` (and .202, .203).

## Web endpoints

| Service | URL | User | Password |
|---|---|---|---|
| Longhorn UI | http://192.168.0.240 | - | none (no auth by default) |
| Grafana | http://192.168.0.241 | `admin` | set at install with `--set grafana.adminPassword` |
| Argo CD | **https**://192.168.0.242 | `admin` | see below |

**No credentials are stored in this repository.**

MetalLB assigns addresses in the order Services are created, so they move if the
stack is reinstalled. Confirm them at any time:

```
kubectl --context harbourline-vm get svc -A \
  -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,TYPE:.spec.type,EXTERNAL-IP:.status.loadBalancer.ingress[0].ip' \
  | grep -E '^NS|LoadBalancer'
```

## Argo CD password

Bootstrap password, while the Secret still exists:

```
kubectl --context harbourline-vm -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d; echo
```

The trailing `; echo` matters - the Secret holds no newline, so without it the
password runs straight into the shell prompt and you cannot see where it ends.

That Secret is a **one-time bootstrap credential** and sits in etcd in plaintext.
Change the password in the UI (User Info -> Update Password), then delete it:

```
kubectl --context harbourline-vm -n argocd delete secret argocd-initial-admin-secret
```

### Resetting a lost admin password

`Error from server (NotFound)` means the bootstrap Secret is gone - either
deleted deliberately, or you are querying the wrong cluster. Check which:

```
kubectl config current-context
```

If it really is gone, clear the stored password fields and restart the server.
Argo CD then behaves as if freshly installed: it generates a new random password
and recreates `argocd-initial-admin-secret`. No bcrypt tooling needed.

```
kubectl --context harbourline-vm -n argocd patch secret argocd-secret \
  -p '{"data":{"admin.password":null,"admin.passwordMtime":null}}'
```

```
kubectl --context harbourline-vm -n argocd rollout restart deploy/argocd-server
```

Wait about 45 seconds, then read the new password with the command above.

## Gotchas

- **Argo CD is `https`, not `http`.** `argocd-server` redirects HTTP to HTTPS
  itself; behind a LoadBalancer that terminates nothing, hitting port 80 gives
  `ERR_TOO_MANY_REDIRECTS`. The certificate is self-signed, so the browser
  warning is expected.
- **The Longhorn UI has no authentication.** It is reachable by anything on the
  LAN and can delete volumes. Acceptable in a lab; in production it goes behind
  an Ingress with auth, or stays on a ClusterIP reached by port-forward.
- `argocd-application-controller` is a **StatefulSet**, not a Deployment - a
  deliberate singleton so two controllers never fight over the same Application.
  `kubectl rollout restart deploy/...` will not match it.

## GitOps

Argo CD manages the cluster's own platform config from this repository:

| Application | Source path | Policy |
|---|---|---|
| `vm-platform` | [`k8s/vm-cluster/`](../k8s/vm-cluster/) | automated, selfHeal on, **prune off** |

Prune is deliberately **off**. This Application owns the MetalLB IPAddressPool
that serves Argo CD's own UI - with pruning enabled, a renamed file or a bad
path would delete the load balancer and take away the way back in.

See also [monitoring.md](monitoring.md) and [vm-cluster.md](vm-cluster.md).
