# CREDENTIALS COME FROM THE ENVIRONMENT, NEVER FROM A FILE.
#
# The provider reads these on its own:
#   PROXMOX_VE_ENDPOINT    https://192.168.0.50:8006/
#   PROXMOX_VE_API_TOKEN   terraform@pve!tf=<uuid>
#   PROXMOX_VE_INSECURE    true
#
# There is deliberately no terraform.tfvars holding a token. On 1 Nov a
# kubeconfig carrying a private key reached this public repository through a
# `git add -A`; the lesson taken from it was that a secret which never lands on
# disk cannot be committed by accident.
#
# PROXMOX_VE_INSECURE is needed because pve1 presents the self-signed
# certificate the installer generated. DEBT, same as the *.hl.internal wildcard:
# the honest fix is a local CA that both this provider and Grafana trust.
# WHY AN SSH BLOCK EXISTS AT ALL.
# Almost everything here is the Proxmox REST API. Importing a downloaded disk
# image into a VM is not: there is no API endpoint for it, so the provider
# opens an SSH session to the node and runs `qm importdisk`. Without this block
# the apply gets as far as creating the VM and then fails with
#   unable to authenticate user "" over SSH to "192.168.0.50:22"
# - an empty username, because API-token auth carries no shell identity.
#
# DEBT: this logs in as root. The tighter arrangement is a dedicated system
# user on the node with a narrow sudoers entry for the handful of commands the
# provider shells out to. Root-by-key is a lab convenience and is recorded as
# one, in the same spirit as the NOPASSWD sudoers entry on the VM cluster.
provider "proxmox" {
  # endpoint, api_token and insecure are all taken from the environment.
  ssh {
    agent       = false
    username    = "root"
    private_key = file(pathexpand("~/.ssh/id_ed25519"))
  }
}
