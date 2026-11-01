# WHAT THIS STACK OWNS, AND WHERE IT STOPS
#
# Terraform owns what must exist before anything can be reconciled: the
# cluster, and Argo CD. Argo CD owns everything after that, pulled from this
# repository. The handover is one object - the root Application - and Terraform
# does not reach past it.
#
# WHY THE BOUNDARY IS DRAWN THERE
# Two controllers that both own a field produce permanent drift, and both are
# behaving correctly. This project has already hit that twice: an HPA against a
# declared replicas, and a Kyverno mutating policy against a value in Git. The
# same trap applies here, and the usual way in is letting Argo CD manage its
# own installation while Terraform also manages it. So: Argo CD manages
# everything EXCEPT itself. Its version is pinned here, in code.
#
# ON CONSTRAINTS VS THE LOCK FILE
# These constraints say what is acceptable. .terraform.lock.hcl records what
# was actually selected, with checksums, and THAT is the file that makes a
# build reproducible. Commit it. A constraint alone still lets two people on
# the same commit get different providers.
terraform {
  required_version = ">= 1.6"

  required_providers {
    kind = {
      source  = "tehcyx/kind"
      version = ">= 0.4"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.17"
    }
  }

  # Local state, deliberately, for a cluster that can be destroyed and rebuilt
  # in four minutes. For anything shared or stateful this belongs in a remote
  # backend with locking - two people running apply against local state is a
  # race with no referee. Recorded as debt in the README.
}
