# ── Layer 0: the cluster ──────────────────────────────────────────────────────
#
# Node image pinned to v1.37.0 to match the working cluster. An unpinned image
# means the cluster you get depends on the day you ran apply, which is the
# opposite of what this stack exists to prove.
resource "kind_cluster" "this" {
  name           = var.cluster_name
  node_image     = var.kubernetes_version
  wait_for_ready = true

  kind_config {
    kind        = "Cluster"
    api_version = "kind.x-k8s.io/v1alpha4"

    node {
      role = "control-plane"
    }
    node {
      role = "worker"
    }
  }
}

# Provider configured from the cluster this same apply creates.
#
# The kubernetes provider is absent for a specific reason: kubernetes_manifest
# performs a server-side dry-run at PLAN time, against a cluster this apply has
# not created yet, so it cannot be used to create the root Application here.
provider "helm" {
  kubernetes {
    host                   = kind_cluster.this.endpoint
    client_certificate     = kind_cluster.this.client_certificate
    client_key             = kind_cluster.this.client_key
    cluster_ca_certificate = kind_cluster.this.cluster_ca_certificate
  }
}

# ── Layer 1: Argo CD, and the single object that hands over ───────────────────
resource "helm_release" "argocd" {
  name             = "argocd"
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  version          = var.argocd_chart_version
  namespace        = "argocd"
  create_namespace = true

  # Block until the controller is actually up. Without this the root
  # Application can be submitted before the CRDs are established and the apply
  # fails on a race rather than on anything real.
  wait    = true
  timeout = 900

  values = [yamlencode({
    configs = {
      params = {
        # argocd-server speaks plain HTTP and lets a proxy terminate TLS.
        # Without it, its own HTTP->HTTPS redirect fights the proxy's and the
        # browser gives up with ERR_TOO_MANY_REDIRECTS - the single
        # most-reported Argo CD issue, and one this project has already hit.
        "server.insecure" = true
      }
    }
  })]
}

# ── The handover ─────────────────────────────────────────────────────────────
#
# ONE object: the Application that points Argo CD at this repository.
# Everything else in the cluster arrives because Argo CD pulled it.
#
# WHY A SEPARATE RELEASE, AND NOT extraObjects ON THE ARGO CD RELEASE
# That was the first attempt and it failed:
#
#   Error: unable to build kubernetes objects from release manifest:
#   resource mapping not found for name: "root" ... no matches for kind
#   "Application" in version "argoproj.io/v1alpha1" - ensure CRDs are
#   installed first
#
# Helm builds every manifest in a release against API discovery BEFORE
# applying any of them, so a release cannot both install a CRD and create a
# custom resource of that kind. Same class of problem as kubernetes_manifest's
# plan-time dry-run, reached through a different door: in Terraform and
# Kubernetes, CRD-then-CR always needs two steps. depends_on is what orders
# them.
resource "helm_release" "root_app" {
  name      = "root-app"
  chart     = "${path.module}/charts/root-app"
  namespace = "argocd"

  depends_on = [helm_release.argocd]

  values = [yamlencode({
    repoURL        = var.repo_url
    targetRevision = var.target_revision
    path           = var.apps_path
  })]
}
