# Provider pinned exactly, not with a range.
#
# This repository has been bitten three times by dependencies that were allowed
# to move on their own schedule - Trivy's policy set, SonarCloud's rule set and
# Trivy's CVE database all changed under a green build on 14 Nov. A provider is
# the same class of thing: it decides what the API calls look like. Pin it, and
# let a human choose when it moves.
terraform {
  required_version = ">= 1.6.0"

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "0.124.0"
    }
  }
}
