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
| `platform` | **OutOfSync** | Sync failed | `namespaces "monitoring" not found` |

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

## The fourth gap: namespaces created as a side effect

```
one or more synchronization tasks completed unsuccessfully,
reason: namespaces "monitoring" not found (retried 5 times)
```

`k8s/platform` holds two Ingresses. `grafana-ingress.yaml` targets the
`monitoring` namespace, which does not exist here - because
kube-prometheus-stack, Loki and Alloy were installed **by hand**, and the
namespace was a side effect of a `helm install` nobody recorded.

**Git contains the front door to a building that is not there.**

This is a different category from the other three. Secrets and node labels are
*known* unreproducible state, written down deliberately. This is *invisible*
state: a namespace that exists on the working cluster because of a command
someone ran in September, with nothing anywhere recording that the platform
layer depends on it.

### Why `CreateNamespace=true` is the wrong fix

Adding it to the Application's `syncOptions` makes the sync go green in about
ten seconds. It would also create an empty `monitoring` namespace containing an
Ingress that routes to a Grafana which does not exist.

**That converts a loud, accurate failure into a silent misconfiguration.** The
sync status would say everything is fine; the cluster would serve a 503 to
anyone who used the hostname. The current red status is carrying true
information - *the monitoring stack is not in Git* - and the value of a signal
is destroyed by silencing it rather than answering it.

The real fix is already on the backlog: bring kube-prometheus-stack, Loki,
Alloy and Kyverno under Argo CD. Until then this Application should stay red,
because it is right.

## Open

- **Bring the hand-installed Helm releases under Argo CD** - kube-prometheus-
  stack, Loki, Alloy, Kyverno. This is what `platform` is failing to tell us,
  and it is the same gap Kyverno was installed to close, one layer up.
- **The secrets.** Until they can be recreated from code - sealed-secrets,
  External Secrets Operator, or Vault - "a stranger can rebuild this" is false.

## The gap, measured

Not a feeling. Four things stand between this repository and a working cluster:

1. Three secrets created by hand
2. One node label (`tier=database`)
3. One namespace created as a side effect of an unrecorded `helm install`
4. One container image whose registry visibility differs from its siblings

Everything else - every manifest, every Helm value, the Argo CD install, the
cluster itself - rebuilt from `main` in four minutes with no human step.

## Why this matters more than the Terraform

The Terraform is thirty lines of resources. The value is that the claim in
`cluster-state-not-in-git.md` has been **tested**, and the gap between "we
have GitOps" and "we can rebuild this" has a number attached to it rather
than a feeling.

Re-run it any time:

```
terraform destroy && terraform apply
```

---

# Second rebuild — 2026-11-08

All four gaps from the first run were closed beforehand. The cluster was
destroyed and rebuilt from nothing.

## Every workload came up

| 2026-11-01 | 2026-11-08 |
|---|---|
| `harbourline-api` `ImagePullBackOff` ×3 | **Running ×3** — GHCR packages made public |
| `harbourline-db-0` **Pending** | **Running** — `tier=database` declared in Terraform |
| `harbourline-reports` `CreateContainerConfigError` | **Running ×2** — database password sealed |
| `harbourline-web` Running | Running |

Nine pods, all Running, on a cluster that did not exist ten minutes earlier.

**One manual step remains and always will:** restoring the Sealed Secrets
private key. That is not a flaw to fix. **You cannot have zero secrets outside
Git — you can have exactly one.** Every GitOps system has a bootstrap
credential; the work is reducing it to a single backed-up, tested thing rather
than four scattered ones nobody wrote down.

## But the application did not work — a fifth gap

The smoke test failed, and because it now reports what it actually saw, the
cause arrived with it:

    FAIL  web -> api -> db  (http://harbourline-web/api/shipments)
          status: 500
          {"error":"relation \"shipments\" does not exist ..."}

Every pod healthy, every service reachable, and no schema. `db-init` had never
run — no such pod existed — and the `harbourline` Application sat
`Progressing / Running` indefinitely.

**The cause: a health check on a resource that can never be healthy.**

`k8s/base` contains an Ingress. Argo CD rates an Ingress healthy only once its
status carries a load balancer address, and that address is written by an
ingress controller. The Terraform bootstrap installs Argo CD and nothing else,
so there is no controller, so the Ingress never goes Healthy, so the sync never
leaves its Sync phase, so the **PostSync** hook that seeds the database never
fires.

Everything behind that check is deadlocked, and nothing reports an error —
`Progressing` is not a failure state, so it never times out into one.

This is a different species from the first four. Those were missing *state*.
This is a missing *dependency*: the application layer assumes an ingress
controller that nothing declares and nothing installs.

### Not fixed yet — the options

- **Install an ingress controller in the bootstrap.** Honest, and makes the
  rebuilt cluster match the real one. Adds a component to the layer that is
  meant to stay minimal.
- **Tell Argo CD to ignore Ingress health** on this Application. One line,
  and it blinds a check that is correct on the cluster that does have a
  controller.
- **Move `db-init` out of PostSync.** Removes the ordering guarantee it exists
  to provide.

The last line of defence worked, and that is the result worth keeping: **the
smoke test caught a deployment where every Kubernetes health signal was green
and the application returned 500 to every request.** That is 12 October
exactly, and this time something said so.

---

# Third rebuild — 2026-11-14 — PASSES

```
NAME                     STATUS     COMPLETIONS   AGE
harbourline-db-init      Complete   1/1           49s
harbourline-smoke-test   Complete   1/1           21s

=== Harbourline post-deployment smoke test ===
PASS  web serves the page        (http://harbourline-web/)
PASS  web -> api -> db           (http://harbourline-web/api/shipments)
PASS  reports aggregates         (http://harbourline-reports:8080/reports/summary)

SMOKE TEST PASSED - all paths serving
```

A cluster that did not exist fifteen minutes earlier, serving real rows from a
database it seeded itself, confirmed by its own post-deployment gate. From an
empty machine: a git clone, `terraform apply`, and one key file.

## What fixed the fifth gap

The Ingress moved from `k8s/base` to `k8s/platform`. Nothing else changed.

`harbourline` reached **Healthy** instead of sitting `Progressing / Running`
forever, so its PostSync hook fired, so `db-init` created the schema, so the
smoke test found `SHP-` where it had previously found
`relation "shipments" does not exist`.

The fix was not a health override, an ignored check, or an extra component in
the bootstrap. **The resource was in the wrong Application.** An Ingress
depends on a platform component; a StatefulSet does not. Grouping them meant a
missing ingress controller silently deadlocked a database hook.

And `platform` now reports **Progressing** on this cluster, which is true and
useful: there is no ingress controller here. The old arrangement said nothing
at all while the application returned 500 to every request.

## What is still not guaranteed

**Cross-Application ordering.** `db-init` is a PostSync hook on `harbourline`;
the smoke test is a PostSync hook on `harbourline-web`. Argo CD syncs
Applications independently. This run happened to seed the database 28 seconds
before the smoke test ran. **That was luck, not design** - and on a slower
rebuild the test could still run against an empty schema and fail correctly for
the wrong reason.

The real fix remains one Application with sync waves. Until then the smoke
test's 75-second retry budget is the only thing covering the gap.

## Expected non-failures

| Application | State | Why |
|---|---|---|
| `platform` | Progressing | no ingress controller - correct |
| `kyverno` | OutOfSync / Missing | automated sync deliberately off; an admission webhook gets a human |
| `policies` | OutOfSync / Missing | its CRDs arrive with Kyverno |

## The one manual step

Restoring the Sealed Secrets private key. It does not go away, and it should
not:

> **You cannot have zero secrets outside Git. You can have exactly one.**

Every GitOps system has a bootstrap credential. The work was reducing four
scattered, undocumented ones to a single backed-up key whose restore has been
tested on a cluster that had never held it.
