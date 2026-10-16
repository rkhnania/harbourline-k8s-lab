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

## Enforced by Kyverno

As of 2026-10-15 the decisions above are not only recorded here, they are an
admission control: [`k8s/policies/harbourline-baseline.yaml`](../k8s/policies/harbourline-baseline.yaml).

Four rules, all `failureAction: Enforce`, scoped to the `harbourline` namespace:
runAsNonRoot, allowPrivilegeEscalation, seccompProfile RuntimeDefault, and
readOnlyRootFilesystem - the last carrying the PostgreSQL exception below as an
explicit `exclude` block, so the accepted risk is a named object rather than a
paragraph someone has to remember.

Policies were installed in **Audit** first and the PolicyReport read before
anything was switched to Enforce. The result on the running cluster:

| Pod | Pass | Fail |
|---|---|---|
| api, web, reports (all replicas) | 4 | 0 |
| `harbourline-db-0` | 3 | 0 (one rule excluded by design) |
| `probe` - created by hand, never in Git | **0** | **4** |

Everything the pipeline creates was already compliant. The only violation was a
debug pod typed at a terminal during the NetworkPolicy work. That is the case
for admission control in one line: documents do not stop the second kind.

Two operational notes:

- Admission control has no power over objects already persisted. Switching to
  Enforce did not evict `probe`; it only blocks new requests.
- Enforce rules attach to the `validate.kyverno.svc-fail` webhook
  (`failurePolicy: Fail`). **If Kyverno is unavailable, every create and update
  of a matched resource is rejected** - an unavailable policy engine becomes an
  admission outage. `Ignore` fails open instead and silently stops enforcing.
  Scope `match` blocks narrowly and run more than one replica.

### Mutating policies fight GitOps

Demonstrated deliberately on 2026-10-15. A mutating ClusterPolicy set
`spec.replicas: 2` on `harbourline-api`, which the Helm chart declares as 3.

Argo CD applies 3, the API server accepts the request, Kyverno rewrites it to 2
before it is persisted, and the Application sits **`Sync OK` and `OutOfSync` at
the same time** - both statements true. Nothing errors. The app stays Healthy.

> Whatever mutates a field at runtime must own it, and Git must not declare it.

The same rule as the HPA conflict of 2026-10-11, reached from the opposite
direction: there an autoscaler owned `spec.replicas`, here an admission webhook
did. Three resolutions, depending on why you are mutating:

| Situation | Fix |
|---|---|
| Policy sets a field Git also declares | Do not. Pick one owner. |
| Mutation required and Git must keep declaring it | Argo `ignoreDifferences` on that path |
| Policy sets defaults on resources Git does not manage | Fine - that is what mutation is for |

The third row is the legitimate use: injecting a default securityContext onto
pods created by hand, cost-allocation labels, `imagePullSecrets`. Had such a
policy existed, the `probe` pod would have been corrected rather than rejected.

Forensics: Kyverno stamps every object it mutates with
`policies.kyverno.io/last-applied-patches`, naming the policy and rule. When a
field does not match Git and nobody knows why, that annotation is the trail.

`kyverno.io/v1 ClusterPolicy` is deprecated as of v1.19 in favour of CEL-based
`ValidatingPolicy` under `policies.kyverno.io`, aligning with upstream
`ValidatingAdmissionPolicy`. The policy here still uses ClusterPolicy, which is
what the ecosystem overwhelmingly runs today.

## Known gaps, not yet addressed

- The `fs` scan (dependency CVEs and secrets) is still report-only.
- `harbourline-db-init` is a plain Job, so it is immutable and blocks syncs
  when its spec changes. It should be an Argo CD sync hook:
  `argocd.argoproj.io/hook: Sync` with
  `argocd.argoproj.io/hook-delete-policy: BeforeHookCreation`.
- `api` uses `envFrom: secretRef`, which injects every key in the Secret and
  fails silently when one is missing. `secretKeyRef` per key fails loudly and
  is preferred.
- The policy set is not yet under Argo CD - it is applied by hand, which is the
  same gap it was written to close.

## VM cluster exposure (2026-10-16)

Every service on the VM cluster used to sit on its own MetalLB address with no
name, no TLS and, in one case, no authentication. All of it now goes through a
single Traefik front door on `192.168.0.241` - see
[vm-cluster-access.md](vm-cluster-access.md).

**Closed:** the Longhorn UI had **no authentication at all** while reachable by
anything on the LAN, and it can delete volumes. It is now behind a Traefik
`basicAuth` Middleware (`longhorn-basic-auth` Secret, hash only, not in Git).
Verified by response code, not by eyeballing the page:

    curl -sSk -o /dev/null -w '%{http_code}\n' \
      --resolve longhorn.hl.internal:443:192.168.0.241 https://longhorn.hl.internal/
    401

A `200` there would mean the Middleware silently failed to attach - the
annotation format is `<namespace>-<name>@kubernetescrd` and a typo in it does
not error, it just does nothing.

**Still open:** `prometheus.hl.internal` has **no authentication**, same as the
address it replaced. Read-only metrics rather than a delete button, so it was
left out of this change to keep it reviewable - but metrics leak topology,
hostnames and workload names. Fix is the same Middleware plus `basicAuth` in the
kind cluster's Grafana datasource config.

**Still open:** TLS is a self-signed wildcard for `*.hl.internal`, so every
browser warns and `tlsSkipVerify: true` is set on the Grafana datasource. A
warning users are trained to click through is worth little. Fix is cert-manager
with a local CA issuer, already on the backlog.

**ingress-nginx was rejected for this.** Kubernetes SIG Network retired it -
best-effort maintenance ended March 2026, with no further releases, bugfixes or
security patches, and the charts and images still download without warning. An
unpatchable edge proxy is not a reasonable thing to make the single entry point
to a cluster. Traefik is maintained and also speaks Gateway API, which is the
longer-term destination. The **kind cluster still runs ingress-nginx** and is a
known debt to migrate.
https://kubernetes.io/blog/2025/11/11/ingress-nginx-retirement/
