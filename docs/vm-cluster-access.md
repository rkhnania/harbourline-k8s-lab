# VM cluster - access

Three-node kubeadm cluster `harbourline-vm` on Hyper-V. All browser endpoints are
served by MetalLB in L2 mode from the pool `192.168.0.240-.250`
([`k8s/vm-cluster/metallb.yaml`](../k8s/vm-cluster/metallb.yaml)).

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

Argo CD's bootstrap password:

```
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo
```

That Secret is a one-time bootstrap credential and sits in etcd in plaintext.
Change the password in the UI (User Info -> Update Password), then delete it:

```
kubectl -n argocd delete secret argocd-initial-admin-secret
```

## Gotchas

- **Argo CD is `https`, not `http`.** `argocd-server` redirects HTTP to HTTPS
  itself; behind a LoadBalancer that terminates nothing, hitting port 80 gives
  `ERR_TOO_MANY_REDIRECTS`. The certificate is self-signed, so the browser
  warning is expected.
- **The Longhorn UI has no authentication.** It is reachable by anything on the
  LAN and can delete volumes. Fine for a lab; in production it goes behind an
  Ingress with auth, or stays on a ClusterIP reached by port-forward.
- Addresses are assigned by MetalLB in the order Services are created, so they
  can change if the stack is reinstalled. Confirm with:

```
kubectl get svc -A -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,TYPE:.spec.type,EXTERNAL-IP:.status.loadBalancer.ingress[0].ip' | grep -E '^NS|LoadBalancer'
```

## GitOps

Argo CD manages the cluster's own platform config from this repository:

| Application | Source path | Policy |
|---|---|---|
| `vm-platform` | [`k8s/vm-cluster/`](../k8s/vm-cluster/) | automated, selfHeal on, **prune off** |

Prune is deliberately **off**. This Application owns the MetalLB IPAddressPool
that serves Argo CD's own UI - with pruning enabled, a renamed file or a bad
path would delete the load balancer and take away the way back in.

See also [monitoring.md](monitoring.md) and [vm-cluster.md](vm-cluster.md).
