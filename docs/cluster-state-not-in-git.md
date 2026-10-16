# Cluster state that is NOT in Git

Changes made imperatively to either cluster. If a cluster is rebuilt, these must
be reapplied by hand. This file exists because config drift is invisible until
the day you rebuild.

> ## Why this file is not just bookkeeping
>
> On 2026-10-16 a routine `helm upgrade` of the `kps` release on the VM cluster
> silently deleted a LoadBalancer. The Service had been made `type: LoadBalancer`
> by a hand-run `kubectl patch`; Helm re-applied the Service from the chart
> template, where the type is `ClusterIP`, and the address went dark.
>
> The symptom appeared somewhere else entirely: Grafana on the **kind** cluster
> showing `dial tcp 192.168.0.243:9090: i/o timeout`. Nothing in the upgrade
> output mentioned it. Nothing in Git described the thing that was lost.
>
> **An imperative change to a Helm-managed resource has a lifespan of "until the
> next upgrade", and nothing warns you.** Everything below is either a change no
> chart will overwrite, or a change that is now declared in a values file.

## Kind cluster

## 1. GHCR pull secret

    kubectl -n harbourline create secret docker-registry ghcr-pull \
      --docker-server=ghcr.io \
      --docker-username=rkhnania \
      --docker-password=<PAT with read:packages>

Referenced by `imagePullSecrets` on the api and web deployments (that part IS in
Git). Push identity is not pull identity: CI pushes with GITHUB_TOKEN, the
cluster pulls as me.

## 2. Secret encryption at rest

File: /etc/kubernetes/pki/encryption-config.yaml on the control-plane node.
Flag added to /etc/kubernetes/manifests/kube-apiserver.yaml:

    - --encryption-provider-config=/etc/kubernetes/pki/encryption-config.yaml

Provider order is aescbc then identity: writes are encrypted, reads fall back to
plaintext for anything written earlier.

After enabling, existing Secrets were rewritten to encrypt them:

    kubectl get secrets -A -o json | kubectl replace -f -

LOSING THE KEY FILE MAKES EVERY SECRET IN ETCD UNRECOVERABLE, backups included.
Back it up separately from etcd snapshots. Storing the key beside the encrypted
data defeats the purpose.

Encryption at rest is not access control. `kubectl get secret -o yaml` still
returns plaintext to anyone whose RBAC allows it.

Snapshots taken BEFORE this change are still plaintext credential dumps.

## 3. Node labels applied by hand

    harbourline-worker2: tier=database, storage-tier=nvme

## 4. Headlamp

Installed via Helm into ns `headlamp`, plus the hl-viewer ServiceAccount and its
`view` ClusterRoleBinding.

## 5. PersistentVolume reclaim policy

The PV backing the database was patched from Delete to Retain by hand during
the StatefulSet migration:

    kubectl patch pv <name> -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'

PVs are cluster-scoped and not created by any manifest here (the StorageClass
provisions them), so this cannot live in Git. On a rebuilt cluster the new PV
will default to Delete again. Check it before any PVC surgery.

Also note the StatefulSet's PVC (pgdata-harbourline-db-0) is generated from
volumeClaimTemplates and is deliberately NOT deleted when the StatefulSet is.

### 6. CoreDNS hosts entries for hl.internal

`k8s/kind/coredns.yaml` IS in Git, but **no Argo CD Application points at
`k8s/kind/`** and it is applied by hand:

    kubectl --context kind-harbourline apply -f k8s/kind/coredns.yaml

Deliberate. A pruned or malformed `coredns` ConfigMap takes DNS away from every
pod at once, and the symptom is applications failing to reach the database -
it does not look like DNS. Recreating the kind cluster resets the ConfigMap to
the kind default, so reapply it afterwards.

The `fallthrough` keyword in that file is load-bearing: without it the hosts
plugin answers authoritatively and returns NXDOMAIN for every name it does not
know, which is every Service in the cluster.

---

## VM cluster

### 1. Argo CD Service type

Argo CD was installed from the upstream raw manifest, not a Helm chart, so there
is no values file to hold this:

    kubectl --context harbourline-vm -n argocd patch svc argocd-server \
      -p '{"spec":{"type":"ClusterIP"}}'

It held MetalLB `192.168.0.242` until 2026-10-16. It is now reached through
Traefik at https://argocd.hl.internal. Nothing will `helm upgrade` over this,
which is the only reason a patch is acceptable here.

### 2. Argo CD server.insecure

    kubectl --context harbourline-vm -n argocd patch configmap argocd-cmd-params-cm \
      --type merge -p '{"data":{"server.insecure":"true"}}'
    kubectl --context harbourline-vm -n argocd rollout restart deploy/argocd-server

`argocd-server` otherwise redirects HTTP to HTTPS itself and fights Traefik's
redirect: `ERR_TOO_MANY_REDIRECTS`. With this it speaks plain HTTP in-cluster
and TLS terminates once, at the edge. Externally still HTTPS.

### 3. TLS certificate for *.hl.internal

A private key must never be in Git. One self-signed wildcard, referenced by the
`TLSStore` in `k8s/vm-cluster/platform-ingress.yaml`:

    openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
      -keyout tls.key -out tls.crt -subj "/CN=*.hl.internal" \
      -addext "subjectAltName=DNS:*.hl.internal,DNS:hl.internal"
    kubectl --context harbourline-vm -n traefik create secret tls hl-internal-tls \
      --cert=tls.crt --key=tls.key

**Debt:** replace with cert-manager and a local CA issuer.

### 4. Longhorn UI BasicAuth credentials

Referenced by the `longhorn-auth` Middleware (that part IS in Git):

    LHPW='<password>'
    printf 'admin:%s\n' "$(openssl passwd -apr1 "$LHPW")" > users
    kubectl --context harbourline-vm -n longhorn-system create secret generic \
      longhorn-basic-auth --from-file=users

Only the hash is stored. To rotate, pipe `create ... --dry-run=client -o yaml`
into `kubectl apply -f -` - `create` fails if the object exists, and `apply`
cannot build a Secret from a file, so neither works alone.

### 5. Helm releases with no values file

`cilium`, `metallb` and `kps` were installed with `--set` flags that exist only
in shell history. `longhorn` was too, until `k8s/vm-cluster/longhorn-values.yaml`
was created on 2026-10-16 from the output of:

    helm --kube-context harbourline-vm -n <ns> get values <release>

That command prints **only the user-supplied values**, and is the sole record
that anything was ever set. Capturing the remaining three is outstanding work.

