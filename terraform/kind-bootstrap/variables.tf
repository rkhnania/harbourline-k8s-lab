variable "cluster_name" {
  description = "kind cluster name. Deliberately NOT 'harbourline' - this stack must never be able to destroy the working cluster."
  type        = string
  default     = "harbourline-tf"
}

variable "kubernetes_version" {
  description = "kind node image, pinned by digest-bearing tag. 'latest' here would mean the cluster differs depending on when you ran apply."
  type        = string
  default     = "kindest/node:v1.37.0"
}

variable "argocd_chart_version" {
  description = "argo-cd Helm chart version. Pinned because the existing kind cluster was installed from the 'stable' manifest URL - a mutable tag - and nobody can say what version it runs."
  type        = string
  default     = "10.11.6" # Argo CD v3.5.6
}

variable "repo_url" {
  description = "Git repository Argo CD reconciles from."
  type        = string
  default     = "https://github.com/rkhnania/harbourline-k8s-lab.git"
}

variable "target_revision" {
  description = "Branch or tag Argo CD tracks. Note: whoever can commit here can change the cluster, which makes branch protection an access control, not a workflow nicety."
  type        = string
  default     = "main"
}

variable "apps_path" {
  description = "Repository path holding the Argo CD Applications - the app-of-apps root."
  type        = string
  default     = "k8s/argocd/apps"
}
