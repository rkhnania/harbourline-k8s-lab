# kind cluster access

There are **two** kind clusters, and they are not interchangeable.

| Cluster | What it is | Reachable from |
|---|---|---|
| `kind-harbourline` | the working cluster - everything lives here | WSL **and** PowerShell |
| `kind-harbourline-tf` | the Terraform lab cluster, rebuilt on demand | **WSL only** |

**They are in different kubeconfigs.** `kind-harbourline-tf` was created by kind
running inside WSL, so it is registered in WSL's `~/.kube/config` and nowhere
else. Running `kubectl --context kind-harbourline-tf ...` in PowerShell gives:

    error: context "kind-harbourline-tf" does not exist

That is not a broken cluster. It is the wrong terminal. Use WSL.

---

## kind-harbourline (the working cluster)

Ingress is handled in-cluster, so these are ordinary URLs. `*.localtest.me`
resolves to `127.0.0.1` by public DNS - nothing to add to a hosts file.

| Service | URL |
|---|---|
| Argo CD | http://argocd.localtest.me |
| Grafana | http://grafana.localtest.me |
| Harbourline | http://harbourline.localtest.me |

Argo CD admin password: whatever it was set to. If the bootstrap secret still
exists:

```
kubectl --context kind-harbourline -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo
```

`NotFound` means it was deleted after first login. The reset procedure is the
same as the VM cluster's - see
[`vm-cluster-access.md`](vm-cluster-access.md#resetting-a-lost-admin-password),
substituting the context.

---

## kind-harbourline-tf (the Terraform lab cluster)

Created by [`terraform/kind-bootstrap`](../terraform/kind-bootstrap/). **No
Ingress controller**, so there is no hostname and no URL until a port-forward
is running. Argo CD **v3.5.6**, pinned in `variables.tf`.

### Step 1 - start the tunnel, in WSL, and leave it alone

```
kubectl --context kind-harbourline-tf -n argocd port-forward --address 0.0.0.0 svc/argocd-server 8080:80
```

It prints two `Forwarding from ...` lines and then sits there doing nothing
visible. **That is correct.** It looks hung; it is working.

- `--address 0.0.0.0` is required because kubectl runs in WSL and the browser
  runs in Windows. Without it, kubectl binds only to WSL's internal loopback
  and Windows cannot always reach it.
- **This terminal is now dedicated to the tunnel.** Open a second tab for
  everything else.

### Step 2 - the password, in a second WSL tab

```
kubectl --context kind-harbourline-tf -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo
```

Roughly 16 random characters. The trailing `; echo` matters - the Secret holds
no newline, so without it the password runs into the shell prompt and you
cannot see where it ends.

### Step 3 - the link

**http://localhost:8080** — user `admin`, that password.

### When the UI says "Failed to load data"

**The port-forward died.** The page itself is static and still renders; its API
calls are what fail.

Almost always because `Ctrl-C` was pressed in the tunnel's terminal - including
by running another command there. Confirm the cluster is actually fine:

```
kubectl --context kind-harbourline-tf -n argocd get pods
```

Seven pods `Running` with no restarts means nothing crashed. Restart the
tunnel and leave that terminal alone.

> **A port-forward is a tunnel tied to one terminal session, not a service.**
> That is the practical difference between it and the Ingress on the working
> cluster, and the reason `argocd.localtest.me` survives closing a window
> while `localhost:8080` does not.

---

## Rebuilding or removing the lab cluster

```
cd terraform/kind-bootstrap
terraform destroy     # removes it entirely
terraform apply       # back in ~4 minutes
```

It is disposable by design. See [`rebuild-test.md`](rebuild-test.md) for what
does and does not come back.
