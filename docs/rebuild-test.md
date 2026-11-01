# Rebuild test

**2026-11-01.** First time this project has been rebuilt from nothing rather
than described as rebuildable.

```
cd terraform/kind-bootstrap
terraform apply     # ~4 minutes: cluster, Argo CD, root Application
```

A cluster that did not exist twelve minutes earlier was running Argo CD,
pulling the full app-of-apps from `main`, with no manual step between.

## Result

| Application | Sync | Health | Why |
|---|---|---|---|
| `root` | Synced | **Healthy** | the handover worked |
| `harbourline-web` | Synced | **Healthy** | public image, no secret needed |
| `harbourline` | Synced | Progressing | waiting on the database |
| `harbourline-api` | Synced | Progressing | `ImagePullBackOff` ×3 |
| `harbourline-reports` | Synced | **Degraded** | `CreateContainerConfigError` |
| `platform` | **OutOfSync** | Progressing | not yet diagnosed |

```
harbourline-api-bfc886d78-*        ImagePullBackOff
harbourline-db-0                   Pending
harbourline-reports-6878c6db74-*   CreateContainerConfigError
harbourline-smoke-test-pms59       Error
harbourline-web-8fd58f746-*        Running   (2/2)
```

**Every manifest synced.** Nothing failed to apply, nothing was missing from
Git, no YAML was wrong. What failed was exclusively the state that has never
been in Git - and all of it was already written down.

## The documentation held up

Each failure maps to a section of
[`cluster-state-not-in-git.md`](cluster-state-not-in-git.md) that already
existed:

| Symptom | Cause | Already documented |
|---|---|---|
| api `ImagePullBackOff` | no `ghcr-pull` secret | § 1 |
| reports `CreateContainerConfigError` | no `harbourline-db-secret` | § 1 / § 2 |
| `harbourline-db-0` **Pending** | no node carries `tier=database` | **§ 3** |

That third one is the point. A Pending database looks like a scheduling or
storage fault, and would be chased as one. It is a **node label applied by hand
a month ago**, and the only reason the cause was obvious within seconds is that
someone wrote it down at the time.

**A document describing unreproducible state is worth nothing until something
tries to reproduce without it.** This one was accurate. That was not knowable
before today.

## What the test found that the document did not

**The GHCR package visibility asymmetry is real, and now has a symptom.**
`harbourline-web` pulled its image and ran; `harbourline-api` could not. Same
cluster, same absent pull secret. So `harbourline-web`'s package is public and
`harbourline-api`'s is not - an inconsistency that had been a backlog note
with no observable consequence, and is now a reproduction step.

**The smoke test failed correctly.** `harbourline-smoke-test` ran as a PostSync
hook and errored, on a cluster where the application genuinely does not serve.
Built on 2026-10-25, first fired against a real broken deployment today, and it
caught it. A gate that has only ever seen a working system is an untested gate.

## Open

- **`platform` is OutOfSync** and has not been diagnosed. The kind cluster's
  platform layer assumes ingress-nginx and other components this stack does not
  install.
- **The three secrets remain the whole gap.** Until they can be recreated from
  code - sealed-secrets, External Secrets Operator, or Vault - "a stranger can
  rebuild this" is false, and this test measures exactly how false: one node
  label and three secrets.

## Why this matters more than the Terraform

The Terraform is thirty lines of resources. The value is that the claim in
`cluster-state-not-in-git.md` has been **tested**, and the gap between "we
have GitOps" and "we can rebuild this" has a number attached to it rather
than a feeling.

Re-run it any time:

```
terraform destroy && terraform apply
```
