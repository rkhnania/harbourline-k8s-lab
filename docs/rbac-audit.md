# Privileged RBAC audit

First run: **2026-10-31**, kind cluster `kind-harbourline`.

```
python3 k8s/labs/rbac/audit-privileged-rbac.py kind-harbourline
```

Covers CIS Kubernetes Benchmark **5.1.7 - 5.1.13**, the checks `kube-bench`
leaves unverified because they ask a question no automated pass/fail can
answer: *who holds a permission that lets a subject become more powerful than
it was granted.*

## The headline number is wrong, and that is the first finding

The script reported **18 findings**. There are **six decisions**, and one of
them accounts for seven of the eighteen.

`argocd-application-controller` appears in *every single check* - escalate,
bind, impersonate, create PersistentVolumes, nodes/proxy, approve CSRs, write
webhook configurations, mint ServiceAccount tokens. No legitimately scoped role
holds all eight. That pattern means one thing: its ClusterRole is a wildcard
(`apiGroups: ["*"], resources: ["*"], verbs: ["*"]`), so it matches every check
by construction.

Counting those as eight findings is the same error as reading kube-bench's
"34 WARN" as 34 problems. **A tool that counts symptoms rather than decisions
manufactures alarm fatigue**, and alarm fatigue is how real findings get
ignored. The script needs to group by subject and list the checks each one
trips - recorded under *Tool limitations* below.

Verify the wildcard rather than trusting the inference:

    kubectl --context kind-harbourline get clusterrole argocd-application-controller -o yaml

## Findings

| # | Subject | Disposition |
|---|---|---|
| 1 | `argocd-application-controller` (argocd) | **Accept, document** - inherent to pull-based GitOps |
| 2 | `argocd-server` (argocd) | **Review** - narrower, but holds nodes/proxy and CSR approval |
| 3 | `headlamp` (headlamp) | **Act** - UI ServiceAccount bound to cluster-admin |
| 4 | `ingress-nginx-admission` (ingress-nginx) | **Act** - unmaintained software holding admission-control write |
| 5 | `kyverno-admission-controller`, `kyverno-cleanup-controller` | **Accept** - it *is* admission control |
| 6 | `local-path-provisioner` (local-path-storage) | **Accept** - it *is* the storage provisioner |

### 1. Argo CD's application controller is cluster-admin in all but name

Not a misconfiguration - a consequence of the architecture. Argo CD applies
arbitrary manifests from Git to arbitrary namespaces, so it must be able to
create arbitrary resources. A pull-based GitOps controller is, by construction,
the most privileged thing in the cluster.

**This is the trade the design makes, and it should be stated out loud rather
than discovered.** The CI pipeline deliberately holds no cluster credentials -
a compromised runner cannot reach a cluster, which is the best security
property of the whole pipeline. That privilege did not disappear; it moved into
the cluster, into this ServiceAccount. Anyone who can commit to the tracked
path, or compromise this controller, has the cluster.

What follows from that, and is not yet true here:

- **Branch protection on `main` is a security control**, not a workflow nicety.
  It is the actual access control on this ServiceAccount.
- `AppProject` restrictions can bound which namespaces, repositories and
  resource kinds an Application may touch. Default `default` project allows
  everything.
- Argo CD supports namespaced installs and `--application-namespaces` to avoid
  a cluster-wide grant for clusters that do not need one.

### 2. `argocd-server` holds nodes/proxy and CSR approval

Narrower than the controller, but these two deserve a question. `nodes/proxy`
reaches the kubelet API directly - that is what powers the UI's pod logs and
terminal. CSR approval is harder to justify for an API server, and mints client
certificates for any identity the cluster CA will sign.

Not acted on. Recorded so the next person asks Argo CD's maintainers rather
than assuming.

### 3. Headlamp's ServiceAccount is bound to cluster-admin  **(act)**

```
[FINDING] ServiceAccount/headlamp in headlamp via headlamp-admin
```

The only non-built-in subject on `cluster-admin`. A web UI whose ServiceAccount
holds unrestricted cluster access is the exact shape of the 2018 Tesla
cryptojacking incident: an exposed Kubernetes dashboard with full credentials
behind it. The UI is not the risk; the credential it carries is.

Decide one of three:

- Remove Headlamp if it is not being used.
- Bind it to `view` instead, accepting that write actions in the UI stop
  working.
- Keep cluster-admin and record *why*, with a review date, the way
  `docs/security-decisions.md` records the database's writable filesystem.

Whichever is chosen, it must be a decision. Right now it is a default.

### 4. `ingress-nginx-admission` holds write access to webhook configurations  **(act)**

ingress-nginx reached end of maintenance in **March 2026**: no releases, no
bugfixes, no security patches. It is still installed on this cluster - the VM
cluster was migrated to Traefik on 2026-10-16, kind was not - and its admission
ServiceAccount can write `validatingwebhookconfigurations`, which is admission
control itself.

Unmaintained software holding the permission that can switch off Kyverno is a
combination worth ending rather than documenting. The kind cluster should
follow the VM cluster to Traefik.

### 5 and 6. Kyverno and local-path-provisioner: accepted

Kyverno writes webhook configurations because managing admission webhooks is
precisely its job; a Kyverno that could not would not function. The storage
provisioner creates PersistentVolumes for the same reason.

Both are the intended design. They are listed because *the permission is still
real* - compromising Kyverno's admission controller still disables policy
enforcement cluster-wide - not because they are wrong.

Note the two `[latent]` entries: `kyverno:admission-controller:core` and
`kyverno:cleanup-controller:core` exist but no binding references them. Latent,
not active. Worth knowing the difference: an unbound ClusterRole grants nothing
until something binds it, which is why the audit resolves bindings rather than
listing roles.

## What this says about the built-ins

Two things surfaced that are not findings but are worth carrying into any
interview:

**`system:masters` bypasses RBAC entirely.** The authorizer short-circuits
before any Role is consulted. Access granted through that group cannot be
narrowed by RBAC, only removed - and it does not show up in `kubectl auth
can-i` reasoning the way a normal binding does.

**The built-in `edit` role is far more powerful than its name.** It carries
`impersonate` on `serviceaccounts` and `create` on `serviceaccounts/token`. So
"just give them `edit` in their namespace" actually means *you may become any
workload in that namespace and inherit everything it can do*. `edit` is not a
safe default for untrusted users.

## Tool limitations

- **Counts symptoms, not subjects.** A wildcard ClusterRole trips every check
  and is reported once per check. Group by subject and list the checks tripped.
- **No reverse lookup.** "Who can read Secrets in `harbourline`?" is not
  answerable with kubectl, which only tests a subject you name. `krew` plus
  `kubectl-who-can`, or `rbac-tool`, answers it.
- **No aggregation following.** ClusterRoles built by `aggregationRule` are
  evaluated as stored, which is correct at audit time but hides *why* a role
  holds a permission.
- **Groups and users are not resolved.** A binding to a Group is reported as
  the group name; who is in it depends on the authenticator, which the cluster
  cannot enumerate.

## Outstanding

- Decide Headlamp (finding 3).
- Migrate the kind cluster off ingress-nginx to Traefik (finding 4).
- Record the Argo CD privilege trade in `docs/security-decisions.md` with a
  review date, and enable branch protection on `main`.
- Group the audit output by subject.
- Run against the VM cluster, which has a different workload set.
