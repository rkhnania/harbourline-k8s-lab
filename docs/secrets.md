# Secrets

Four hand-made secrets were the reason this project could not be rebuilt from
Git ([`rebuild-test.md`](rebuild-test.md)). Sealed Secrets is how that is being
closed, one at a time.

| Secret | State |
|---|---|
| Grafana admin password | **sealed** (2026-11-07) |
| `ghcr-pull` image pull secret | hand-made |
| `harbourline-db-secret` | hand-made |
| `*.hl.internal` TLS certificate | hand-made (VM cluster) |

## How it works

The controller generates an RSA key pair in the cluster. `kubeseal` fetches the
**public** key and encrypts locally; the **private** key never leaves. The
resulting `SealedSecret` is safe to commit and safe to publish — the ciphertext
in this repository is on a public GitHub repo and is not a disclosure.

The controller watches for `SealedSecret` objects, decrypts them, and creates
ordinary `Secret`s. Workloads reference those Secrets and know nothing about
any of this.

**Sealing is scoped by namespace AND name by default.** A SealedSecret sealed
for `monitoring/grafana-admin` will not decrypt as `monitoring/other-name` or
in another namespace. That is a feature: it stops someone moving your
ciphertext somewhere they can read the plaintext out of it.

## Sealing a secret

```bash
read -rsp "value: " VAL; echo
kubectl create secret generic <name> -n <namespace> \
  --from-literal=<key>="$VAL" \
  --dry-run=client -o yaml \
  | kubeseal --context <context> --format yaml \
  > k8s/<path>/<name>-sealedsecret.yaml
unset VAL
```

`--dry-run=client` builds the manifest **without sending it to the cluster**,
so the plaintext exists only inside the pipe. `read -rs` keeps it out of
`~/.bash_history`. Commit the output; Argo CD applies it.

## ⚠ The sealing key is now the single point of failure

Sealed Secrets does not remove the unreproducible thing. **It reduces four of
them to one.** The private key is generated inside the cluster, so:

> Destroying the cluster destroys the ability to decrypt everything ever sealed
> for it. The ciphertext in Git becomes permanently unreadable.

This is the part people skip, and it fails late — not at `terraform destroy`,
but weeks later when someone tries to rebuild and finds a repository full of
undecryptable secrets.

### Backing it up

```bash
kubectl --context kind-harbourline -n kube-system get secret \
  -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml \
  > ~/sealed-secrets-key-kind-harbourline.yaml
```

**That file is the master key to every secret in this repository.** It is more
sensitive than any individual secret, because it opens all of them, including
ones sealed in future. It must never be committed, never be in the repository
folder, and should live somewhere encrypted — a password manager, or an
encrypted volume.

`.gitignore` carries `*sealed-secrets-key*` as a backstop, but a backstop is
not a plan.

### Restoring it onto a new cluster

```bash
kubectl --context <new> apply -f ~/sealed-secrets-key-kind-harbourline.yaml
kubectl --context <new> -n kube-system delete pod -l app.kubernetes.io/name=sealed-secrets
```

Order does not matter. The controller loads **every** key it finds at startup
and tries each when unsealing, using only the newest to seal new secrets. A
restored key sits alongside the cluster's own and makes previously sealed
secrets readable without re-sealing anything.

**The restart is required, not hygiene.** The controller retries a failed
unseal a few times and then stops:

    level=ERROR msg="Error updating, giving up" key=monitoring/grafana-admin
      error="no key could decrypt secret (admin-user, admin-password)"

A key restored after it has given up changes nothing until the controller is
restarted. The symptom - key present, Secret still missing - looks exactly
like a failed restore.

### Tested on 2026-11-08

Performed, not described. `terraform destroy && terraform apply` on
[`terraform/kind-bootstrap`](../terraform/kind-bootstrap/) produced a cluster
that had never held the key, and Argo CD applied the sealed secret from Git.

**Before the restore** - the failure that makes sealing worth anything:

    NAME            STATUS                                                   SYNCED
    grafana-admin   no key could decrypt secret (admin-password, admin-user) False

    Error from server (NotFound): secrets "grafana-admin" not found

The SealedSecret existed - it is only YAML, nothing stops it being created -
but no Secret appeared. Ciphertext and nothing else.

**After applying the backed-up key and restarting the controller:**

    NAME                                     STATUS   SYNCED   AGE
    sealedsecret.bitnami.com/grafana-admin            True     5m48s

    NAME                   TYPE     DATA   AGE
    secret/grafana-admin   Opaque   2      26s

Same ciphertext, different cluster, decrypted.

Two things the test established that writing could not:

- **The documented restart label was wrong.** This file said
  `-l name=sealed-secrets-controller`, which selects nothing. The pod carries
  `app.kubernetes.io/name=sealed-secrets`. A restore procedure that has never
  been run contains at least one command that does not work.
- **`kubectl apply` of the exported key worked unmodified**, despite the
  `resourceVersion` and `uid` that a `get -o yaml` leaves behind and that
  usually make an apply fail on an object that does not exist.

## Adopting a Secret that already exists

Sealing a secret that a cluster already has by hand fails:

    failed update: Resource "harbourline-db-secret" already exists
    and is not managed by SealedSecret

**That refusal is a security control, not an inconvenience.** If the controller
overwrote any Secret it was pointed at, anyone who could commit a SealedSecret
could replace any Secret in the cluster — including a TLS key or a cloud
credential — by sealing a value against its name. It only writes Secrets it
created, or ones explicitly handed to it:

```bash
kubectl -n <namespace> annotate secret <name> \
  sealedsecrets.bitnami.com/managed=true --overwrite
```

Hit on 2026-11-07 with `harbourline-db-secret`, which had existed since
September. The lab cluster did not hit it — nothing existed there, so the
controller created the Secret freely. **Adoption is only hard where something
is already running**, which is the same lesson as the hand-installed Helm
releases, in a different costume.

Expect the same for `*.hl.internal` on the VM cluster.

## Known weaknesses

- **Rotation is manual.** Changing a value means re-sealing and committing.
  There is no expiry and nothing warns that a secret is old.
- **A sealed secret is as strong as the cluster.** Anyone with `get secret` in
  the target namespace reads the decrypted value — sealing protects the value
  in Git, not in the cluster.
- **Git history keeps old ciphertext.** Re-sealing does not remove the previous
  value from history. If a plaintext is ever compromised, rotate the actual
  credential; removing the commit is not enough.
- **Three secrets are still hand-made.** Sealing the remaining three is the
  work that finally makes the rebuild test pass.
