output "kubectl_context" {
  description = "Context name kind registers. Note the kind- prefix; the resource name alone is not a context."
  value       = "kind-${kind_cluster.this.name}"
}

output "next_steps" {
  value = <<-EOT
    Cluster:  kind-${kind_cluster.this.name}

      kubectl --context kind-${kind_cluster.this.name} get nodes
      kubectl --context kind-${kind_cluster.this.name} -n argocd get applications

    Argo CD admin password (bootstrap secret, delete it after first login):

      kubectl --context kind-${kind_cluster.this.name} -n argocd \
        get secret argocd-initial-admin-secret \
        -o jsonpath='{.data.password}' | base64 -d; echo

    UI, no Ingress on this cluster, so port-forward:

      kubectl --context kind-${kind_cluster.this.name} -n argocd \
        port-forward svc/argocd-server 8080:80
  EOT
}
