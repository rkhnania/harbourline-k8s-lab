# Security decisions

Findings from `trivy config` on the rendered Kustomize output, and what was
done about each. Re-run with:

    kubectl kustomize k8s/base > /tmp/rendered.yaml
    trivy config /tmp/rendered.yaml --severity HIGH,CRITICAL

Scan the RENDERED output, not the bases. Scanning templates produces findings
that the template system was going to fix anyway (wrong namespace, missing
image tags).

## Fixed

| Finding | Workloads | What was done |
|---|---|---|
| KSV-0118 default security context | api, reports, web, db, db-init | Explicit pod and container securityContext on all five |
| KSV-0012 runAsNonRoot | api, reports, web, db, db-init | `runAsNonRoot: true` with an explicit uid: 1001 (api, reports), 101 (web), 70 (postgres) |
| KSV-0001 allowPrivilegeEscalation | all | `allowPrivilegeEscalation: false` |
| KSV-0104 seccomp | all | `seccompProfile: RuntimeDefault` |
| KSV-0014 readOnlyRootFilesystem | api, reports, web, db-init | `true`, with emptyDir mounts for the paths each image genuinely writes |
| DS-0002 no USER in Dockerfile | web | Moved to `nginxinc/nginx-unprivileged:alpine` |
| KSV-0117 containerPort < 1024 | web | nginx now listens on 8080; Service targetPort updated, Ingress unchanged |

### Things that were not guessable

- The uid differs per image. `postgres:16-alpine` is **70**; the Debian-based
  Postgres image is 999. Wrong uid means the database cannot read its own
  data directory.
- `fsGroup: 70` is required for non-root Postgres on a PVC, so the kubelet
  sets group ownership on the mounted volume.
- Python writes `__pycache__` next to its source on import. With a read-only
  root that fails, so `PYTHONDONTWRITEBYTECODE=1` is required.
- Shell heredocs are written to a temporary file. The db-init Job's `<<'SQL'`
  block needs a writable `/tmp` or it dies on a line that looks unrelated.
- `nginx-unprivileged` redirects its temp paths under `/tmp`, which is why a
  single emptyDir there is enough.

## Accepted

### KSV-0014 — readOnlyRootFilesystem on PostgreSQL

**Accepted.** PostgreSQL writes its unix socket to `/var/run/postgresql` and
scratch files to `/tmp`, neither of which is on the data volume. It is
achievable with two more emptyDir mounts, but the value is low: this is a
single-tenant stateful workload whose data volume must be writable in any
case, so an immutable root filesystem removes little attacker capability here.

Revisit if the database is ever multi-tenant or internet-reachable.
Review date: 2027-01-07.

## Noise, not accepted-with-reason

These were judged false positives for this environment and are not tracked:

- **KSV-0125 untrusted registry** — means `ghcr.io` is not on Trivy's default
  allow-list. Configure the list rather than change anything.
- **KSV-01010 sensitive value in ConfigMap** — flags `DB_PORT`. A port number
  is not a secret.
- **KSV-0013 no image tag** — an artefact of scanning the base rather than the
  rendered output; Kustomize sets the tag.

## Known gaps, not yet addressed

- The `fs` scan (dependency CVEs and secrets) is still report-only.
- `harbourline-db-init` is a plain Job, so it is immutable and blocks syncs
  when its spec changes. It should be an Argo CD sync hook:
  `argocd.argoproj.io/hook: Sync` with
  `argocd.argoproj.io/hook-delete-policy: BeforeHookCreation`.
- `api` uses `envFrom: secretRef`, which injects every key in the Secret and
  fails silently when one is missing. `secretKeyRef` per key fails loudly and
  is preferred.
- No PodDisruptionBudgets and no topologySpreadConstraints anywhere.
- No NetworkPolicies on the harbourline namespace.
