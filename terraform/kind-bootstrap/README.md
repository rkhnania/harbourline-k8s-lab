# kind bootstrap

Creates a Kubernetes cluster from nothing, installs Argo CD, and hands over.
Everything else in the cluster arrives because Argo CD pulled it from this
repository.

```
terraform init
terraform plan
terraform apply
```

Four minutes. `terraform destroy` removes the cluster entirely.

## Accessing Argo CD on this cluster

No Ingress controller here, so there is no hostname - it needs a port-forward,
run **in WSL**, left running in its own terminal:

```
kubectl --context kind-harbourline-tf -n argocd port-forward --address 0.0.0.0 svc/argocd-server 8080:80
```

Then **http://localhost:8080**, user `admin`, password from a *second* tab:

```
kubectl --context kind-harbourline-tf -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo
```

Full notes, including why "Failed to load data" is almost never a broken
cluster: [`docs/kind-cluster-access.md`](../../docs/kind-cluster-access.md).

## What this owns, and where it stops

| Owner | Scope |
|---|---|
| **Terraform** | The cluster. Argo CD. The root Application. |
| **Argo CD** | Everything else, pulled from `k8s/argocd/apps`. |

The handover is **one object** - the root Application - and Terraform does not
reach past it.

### Why the boundary is there

Two controllers that both own a field produce permanent drift, and both are
behaving correctly. This project has hit that twice already: an HPA against a
declared `replicas` (2026-10-11), and a Kyverno mutating policy against a value
in Git (2026-10-15). Same trap, third doorway.

The usual way in is letting Argo CD manage its own installation while Terraform
also manages it. Terraform reverts Argo's self-updates on the next apply; Argo
reverts Terraform's. So the rule here is explicit: **Argo CD manages everything
except itself.** Its version is pinned in `variables.tf`, in code, reviewed like
any other change.

## What this fixes

The existing kind cluster's Argo CD was installed from the `stable` manifest
URL. `stable` is a **mutable tag**: nobody can say which version is running, and
re-running the same command next month produces a different cluster. `helm list
-A` on that cluster does not even show Argo CD, because it was never a release.

Here it is chart `10.11.6`, Argo CD `v3.5.6`, on node image
`kindest/node:v1.37.0`, pinned to match the working cluster rather than
drifting to whatever is newest on the day.

## What will fail, deliberately

The new cluster syncs the real app-of-apps, so it tries to deploy all of
Harbourline - and stops at three things that have never been in Git, listed in
[`docs/cluster-state-not-in-git.md`](../../docs/cluster-state-not-in-git.md):

| Missing | Effect |
|---|---|
| `harbourline-db-secret` | Postgres will not start |
| TLS certificate | Ingress serves nothing |

**That failure is the point of this stack, not a defect in it.** "Reproducible
except for three secrets nobody can recreate" is the honest state of this
project, and watching Terraform stop exactly there is a better argument for
External Secrets Operator than any backlog entry.

Closing that gap - sealed-secrets, External Secrets Operator, or Vault - is the
next piece of work, and only then is the claim "a stranger can rebuild this"
actually true.

## Design decisions

**The cluster is named `harbourline-tf`, never `harbourline`.** `terraform
destroy` is a loaded gun and the most effective safety measure available is
that this stack has no way to name the working cluster. State files have been
pointed at the wrong environment by people with far more experience than
whoever reads this.

**Three resources, not two: CRD-then-CR always needs two steps.**

`kubernetes_manifest` performs a server-side dry-run at **plan** time, against
a cluster this same apply has not created yet, so it cannot create the root
Application. The first attempt avoided that by putting the Application in the
argo-cd release's `extraObjects` - and failed:

    Error: unable to build kubernetes objects from release manifest:
    resource mapping not found for name: "root" namespace: "argocd"
    no matches for kind "Application" in version "argoproj.io/v1alpha1"
    ensure CRDs are installed first

Same class of problem, different door. Helm builds **every** manifest in a
release against API discovery before applying **any** of them, so one release
cannot both install a CRD and create a custom resource of that kind.

The fix is a second Helm release from a one-template local chart
(`charts/root-app`), ordered with `depends_on`. This is worth internalising:
in Terraform and Kubernetes, a custom resource and the CRD that defines it
cannot be created in the same step. Every workaround - two applies, two
releases, `-target`, the `kubectl` provider - is a way of saying the same
thing.

The Application still ends up owned by a Helm release, so `destroy` removes it
in the right order rather than orphaning everything beneath it.

**`.terraform.lock.hcl` is committed.** The constraints in `versions.tf` say
what is *acceptable*; the lock file records what was *selected*, with
checksums. Without it, two people on the same commit can get different
providers. This is the file that makes the build reproducible - the constraint
is not.

**`server.insecure = true`.** argocd-server speaks plain HTTP and lets a proxy
terminate TLS. Without it, its own HTTP→HTTPS redirect fights the proxy's and
the browser gives up with `ERR_TOO_MANY_REDIRECTS` - already hit on the VM
cluster.

## Known debt

- **The provider depends on a resource in the same state.** The `helm`
  provider is configured from `kind_cluster.this`'s attributes, so any plan
  that *replaces* the cluster cannot configure it - the attributes are unknown
  until apply. Adding a node label on 2026-11-08 produced:

      Error: Kubernetes cluster unreachable: invalid configuration:
      no configuration has been provided
        with helm_release.argocd

  The first apply worked because nothing existed to refresh. This is the
  canonical argument for splitting infrastructure and application layers into
  **separate stacks with separate state**: one owns the cluster, the other
  owns what runs on it, and neither can make the other unplannable.

  Workaround for a disposable cluster: `terraform destroy && terraform apply`,
  or `terraform apply -target=kind_cluster.this` first. Neither is a fix.

- **Changing a node label replaces the cluster.** kind cannot relabel a
  running node, so `labels` is marked `# forces replacement`. Fine here;
  worth knowing before doing it to something that holds data.

- **Local state.** Fine for a cluster that rebuilds in four minutes. For
  anything shared or stateful this belongs in a remote backend with locking -
  two people running `apply` against local state is a race with no referee.
  State also holds cluster credentials in **plaintext**, which is why
  `*.tfstate` is gitignored and why "just commit the state file" is never the
  answer.
- **`tehcyx/kind` is a community provider, self-signed.** `terraform init`
  prints `(self-signed, key ID A8CCEA05E06A4307)` where HashiCorp's providers
  print `(signed by HashiCorp)`. A provider is code that runs locally with
  access to the Docker socket. Acceptable for a lab; worth a deliberate
  decision anywhere else, and worth knowing the difference exists.
- **No CNI step.** This cluster uses kindnet, which does enforce NetworkPolicy
  on current kind. The VM cluster runs Cilium, installed by hand with `--set`
  flags that exist only in shell history - that is the next Terraform target.
- **Creating the cluster switches your kubeconfig current-context.** Always
  pass `--context` explicitly.
