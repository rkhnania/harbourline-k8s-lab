# Cluster state that is NOT in Git

Changes made imperatively to the harbourline kind cluster. If the cluster is
rebuilt, these must be reapplied by hand. This file exists because config drift
is invisible until the day you rebuild.

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
