# VM cluster - access

Three-node kubeadm cluster `harbourline-vm` on Hyper-V. Every browser endpoint is
reached by **hostname**, through a single Traefik front door on `192.168.0.241`
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

**One address, three names.** Traefik ([`k8s/vm-cluster/traefik-values.yaml`](../k8s/vm-cluster/traefik-values.yaml))
holds `192.168.0.241` and routes by `Host` header. Routing is declared in
[`k8s/vm-cluster/platform-ingress.yaml`](../k8s/vm-cluster/platform-ingress.yaml).

| Service | URL | User | Password |
|---|---|---|---|
| Argo CD | https://argocd.hl.internal | `admin` | see below |
| Longhorn UI | https://longhorn.hl.internal | `admin` | BasicAuth - **cannot be read back**, see below |
| Prometheus | https://prometheus.hl.internal | - | **none - known gap, see Security** |

**No credentials are stored in this repository.**

> **Grafana is not on this cluster.** There is exactly ONE Grafana for the whole
> project, on the kind cluster at http://grafana.localtest.me, with this
> cluster's Prometheus as a second datasource. The VM cluster ran a second,
> redundant Grafana until 2026-10-16; it showed the same data to the same person
> and cost 10Gi of the Longhorn pool.

TLS is one self-signed wildcard certificate for `*.hl.internal`, held by Traefik's
`TLSStore` in the `traefik` namespace. Browsers warn; that is expected.
**Debt:** replace with cert-manager and a local CA issuer.

### Why `.internal`

ICANN reserved `.internal` for private use. **Not `.local`** - that is
mDNS/Bonjour, and using it for unicast DNS causes intermittent resolution
failures that are miserable to debug. **Not `.lan`** - unreserved, and could be
delegated as a real gTLD.

### Name resolution: two clients, two mechanisms

A hostname is only canonical if the **client** can resolve it, and there are two
kinds of client:

| Client | Resolves via | Configured in |
|---|---|---|
| Your browser | Windows hosts file | `C:\Windows\System32\drivers\etc\hosts` |
| A pod (e.g. Grafana) | the **kind** cluster's CoreDNS | [`k8s/kind/coredns.yaml`](../k8s/kind/coredns.yaml) |

Both point `argocd`/`longhorn`/`prometheus`.`hl.internal` at `192.168.0.241`.

Hosts file entries must sit **below** Docker Desktop's `# End of section`
marker - Docker rewrites everything inside that block, and your entries vanish
on its next restart with no warning.

Add them from an **administrator** PowerShell:

```
$h="$env:WINDIR\System32\drivers\etc\hosts"; $c=@((Get-Content $h) -notmatch 'hl\.internal'); $c+="192.168.0.241 argocd.hl.internal","192.168.0.241 longhorn.hl.internal","192.168.0.241 prometheus.hl.internal"; Set-Content -Encoding ASCII $h $c
```

If a name fails to resolve in Chrome but `ping` resolves it, the cause is
Chrome's own DNS cache or its **Secure DNS** setting, which bypasses the hosts
file. Clear `chrome://net-internals/#dns` and turn off Secure DNS in
`chrome://settings/security`.

### Testing routing without DNS

```
curl -sSk -o /dev/null -w '%{http_code}\n' --resolve argocd.hl.internal:443:192.168.0.241 https://argocd.hl.internal/
```

`--resolve` sends the real `Host` header and TLS SNI while skipping DNS, which
**separates "routing is broken" from "the name does not resolve"**. Prove the
proxy first, add DNS second.

Expected: Argo CD `200`, Longhorn `401` (BasicAuth), Prometheus `302`.
A `404` means Traefik has no router for that Host; a `503` means the router
exists but the backing Service has no endpoints.

### Confirming which addresses are in use

```
kubectl --context harbourline-vm get svc -A --field-selector spec.type=LoadBalancer \
  -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,IP:.status.loadBalancer.ingress[0].ip'
```

Should return exactly one row: `traefik` on `192.168.0.241`.

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

## Longhorn UI password

**It cannot be read back.** The `longhorn-basic-auth` Secret holds an `apr1`
hash, which is one-way - nothing in the cluster, and nobody, knows the
plaintext. There is no bootstrap Secret to fall back on, unlike Argo CD. If you
do not remember it, setting a new one is the only option. Do not go looking.

### Set or reset it - one command

Change the password on the first line and run the whole thing. It writes the
Secret, waits for Traefik to reload it, then logs in with the password it just
set and prints the result.

```
LHPW='Harbourline2026' && printf 'admin:%s\n' "$(openssl passwd -apr1 "$LHPW")" > /tmp/users && kubectl --context harbourline-vm -n longhorn-system create secret generic longhorn-basic-auth --from-file=/tmp/users --dry-run=client -o yaml | kubectl --context harbourline-vm -n longhorn-system apply -f - && rm -f /tmp/users && sleep 5 && curl -k -s -o /dev/null -w 'login test: %{http_code}\n' -u admin:"$LHPW" https://longhorn.hl.internal/
```

`login test: 200` - done. Log in as `admin` with that password **in an incognito
window**. A normal tab caches BasicAuth credentials per origin and keeps
replaying the old ones, which is indistinguishable from a wrong password.

`login test: 401` on a password you just set means Traefik is holding a stale
copy of the Secret:

```
kubectl --context harbourline-vm -n traefik rollout restart deploy/traefik
```

### Two things that cause a permanent 401

- **The Secret's key must be exactly `users`.** Traefik ignores any other key,
  so a Secret built with `--from-file=auth` authenticates nobody, whatever
  password you type. Check with
  `kubectl --context harbourline-vm -n longhorn-system get secret longhorn-basic-auth -o jsonpath='{.data}'`.
- **`create --dry-run=client -o yaml | apply -f -` is not decoration.**
  `kubectl create secret` refuses to touch an object that already exists, and
  `kubectl apply` cannot build a Secret from a file. Neither rotates a
  file-based Secret alone, so `create` renders the YAML without sending it and
  `apply` submits it.

### Is the password wrong, or is the proxy stale?

A BasicAuth `401` has two causes that look identical. Hash the candidate
password against the **stored salt** to tell them apart - it is the only thing
that does. Read the stored line:

```
kubectl --context harbourline-vm -n longhorn-system get secret longhorn-basic-auth -o jsonpath='{.data.users}' | base64 -d
```

It looks like `admin:$apr1$<salt>$<digest>`. Take the salt - the field between
the second and third `$` - and recompute:

```
openssl passwd -apr1 -salt '<salt>' '<candidate password>'
```

Same digest means the password is correct and the fault is Traefik or the
browser cache. Different digest means the password is wrong, and no amount of
restarting will help.

**Debt:** `apr1` is Apache's MD5 variant. Traefik also accepts bcrypt, which is
stronger - `htpasswd -nbB admin "$LHPW"` produces it.

## Gotchas

- **`argocd-server` runs with `--insecure`.** It speaks plain HTTP inside the
  cluster and Traefik terminates TLS at the edge. Without this it issues its own
  HTTP->HTTPS redirect, which fights the proxy's and produces
  `ERR_TOO_MANY_REDIRECTS` - the most-reported Argo CD issue. Set in the
  `argocd-cmd-params-cm` ConfigMap; externally you still get HTTPS.
- **The old addresses are gone on purpose.** `https://192.168.0.242` now gives
  `ERR_CONNECTION_RESET`, because something *is* listening and it rejected a TLS
  handshake it no longer speaks. Refused = nothing on that port; timeout =
  nothing at that address; **reset = listening, but rejected what you sent**.
- **The Longhorn UI is behind BasicAuth** (Traefik `Middleware`, credentials in
  the `longhorn-basic-auth` Secret, never in Git). It previously had no
  authentication at all while reachable by anything on the LAN. Longhorn itself
  has no authentication whatsoever - that Middleware is the entire protection,
  and anything that bypasses it can delete volumes and backups. The password
  **cannot be recovered**, only replaced: see *Longhorn UI password*.
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
