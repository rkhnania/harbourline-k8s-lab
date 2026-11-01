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

# Provider configured from the cluster this same apply creates. Terraform
# resolves the dependency, but it is the reason the kubernetes provider is not
# used here: kubernetes_manifest performs a server-side dry-run at PLAN time,
# against a cluster that does not exist yet. The root Application therefore
# goes in through the chart rather than as its own resource.
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

    # THE HANDOVER. One object. Everything else in the cluster arrives because
    # Argo CD pulled it from Git, not because Terraform pushed it.
    #
    # It is declared through the chart rather than as a kubernetes_manifest for
    # the plan-time reason above, and it has a pleasant side effect: the
    # Application is owned by the Helm release, so `terraform destroy` removes
    # it in the right order instead of leaving an orphan that fights the
    # teardown.
    extraObjects = [
      {
        apiVersion = "argoproj.io/v1alpha1"
        kind       = "Application"
        metadata = {
          name       = "root"
          namespace  = "argocd"
          finalizers = ["resources-finalizer.argocd.argoproj.io"]
        }
        spec = {
          project = "default"
          source = {
            repoURL        = var.repo_url
            targetRevision = var.target_revision
            path           = var.apps_path
          }
          destination = {
            server    = "https://kubernetes.default.svc"
            namespace = "argocd"
          }
          syncPolicy = {
            automated = {
              prune    = true
              selfHeal = true
            }
          }
        }
      }
    ]
  })]
}
