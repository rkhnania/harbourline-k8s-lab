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

Apply the key **before** the controller starts, or it generates a fresh one and
adopts that instead:

```bash
kubectl --context <new> apply -f ~/sealed-secrets-key-kind-harbourline.yaml
kubectl --context <new> -n kube-system delete pod -l name=sealed-secrets-controller
```

The controller picks up every key it finds on startup and uses the most recent
to seal, so restoring an old key alongside a new one makes previously sealed
secrets decryptable again without re-sealing anything.

### Not yet tested

The restore above is **written, not performed**. Until it has been run on a
rebuilt cluster, it is a plan rather than a backup — and this project has
already learned the difference twice: `cluster-state-not-in-git.md` was only
known to be accurate once something tried to rebuild without it, and the
smoke test only counted once it had failed on a genuinely broken deployment.

**Test:** `terraform destroy && terraform apply` on
[`terraform/kind-bootstrap`](../terraform/kind-bootstrap/), restore the key,
and confirm the sealed secret decrypts on a cluster that has never seen it.

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
