# Debian 13 (trixie) generic cloud image, downloaded BY pve1, not by Terraform.
#
# The provider asks Proxmox to fetch the URL itself, so the 327 MB never
# traverses the workstation. That matters here because the workstation is a WSL
# instance behind NAT and the hypervisor is on the LAN.
#
# CHECKSUM IS LOAD-BEARING.
# The URL ends in /latest/, which Debian rebuilds roughly monthly. Without a
# checksum this resource would silently install a different operating system
# image one morning and nothing would report a change. With it, a moved
# /latest/ fails the apply loudly and a human decides what to do.
# The honest improvement is to pin the dated path as well
# (/images/cloud/trixie/20261123-xxxx/) and treat the bump as a reviewed change.
#
# RESOURCE NAME: proxmox_download_file, not the older long-form name.
# v0.124.0 deprecates the long form and removes it in v1.0. Renamed before the
# first apply, while nothing is in state - afterwards the same change needs a
# `terraform state mv`, because Terraform keys state by resource ADDRESS, and a
# renamed type is a different address, which it reads as "destroy that, create
# this". Free now, a migration later.
#
# file_name ends in .img, not .qcow2, ON PURPOSE. Proxmox only accepts .iso and
# .img under the "iso" content type; a .qcow2 name is rejected by the API with
# an error that talks about content types rather than file extensions.
resource "proxmox_download_file" "debian_13" {
  content_type = "iso"
  datastore_id = var.image_datastore
  node_name    = var.node_name

  url       = "https://cloud.debian.org/images/cloud/trixie/latest/debian-13-genericcloud-amd64.qcow2"
  file_name = "debian-13-genericcloud-amd64.img"

  checksum           = "76488ba3bea2349cc595fedad7748b8ba98d6b36da398eaf2bbbae3db896ba1017d4ff41cd277926784cef2c1c11145a0d600f9b4afde9b8f174d698db0cda03"
  checksum_algorithm = "sha512"

  overwrite_unmanaged = true
}

resource "proxmox_virtual_environment_vm" "probe" {
  name      = var.vm_name
  node_name = var.node_name
  vm_id     = var.vm_id

  description = "Created by terraform/proxmox. Safe to destroy."
  tags        = ["terraform", "harbourline"]

  # Without this, `terraform destroy` fails on a running guest and leaves the
  # stack half-removed - the exact failure mode that makes people distrust
  # destroy and start clicking in the UI instead.
  stop_on_destroy = true

  operating_system {
    type = "l26"
  }

  cpu {
    cores = var.vm_cores
    # "host" passes the physical CPU flags through. pve1 is itself nested inside
    # Hyper-V with ExposeVirtualizationExtensions on, so the flags this VM sees
    # are already a passthrough of a passthrough.
    type = "host"
  }

  memory {
    dedicated = var.vm_memory_mb
  }

  # The downloaded image becomes the boot disk: Proxmox imports and converts it
  # from the file store onto lvmthin. This is why the two datastores differ -
  # local is a directory and can hold a file; local-lvm is thin LVM and holds
  # block volumes, not files.
  disk {
    datastore_id = var.disk_datastore
    file_id      = proxmox_download_file.debian_13.id
    interface    = "virtio0"
    size         = var.vm_disk_gb
    iothread     = true
    discard      = "on"
  }

  network_device {
    bridge = "vmbr0"
  }

  # cloud-init. A static address is deliberate: the result of `terraform apply`
  # should be knowable before it runs, and a DHCP lease is neither reproducible
  # nor reviewable.
  initialization {
    datastore_id = var.disk_datastore

    ip_config {
      ipv4 {
        address = var.vm_ipv4
        gateway = var.vm_gateway
      }
    }

    dns {
      servers = var.dns_servers
    }

    user_account {
      username = "debian"
      keys     = [trimspace(file(pathexpand(var.ssh_public_key_path)))]
    }
  }

  # The guest agent is NOT enabled. With agent.enabled = true the provider waits
  # for qemu-guest-agent to answer before it considers the resource created, and
  # a stock cloud image does not have it installed - so the first apply hangs
  # for the full timeout and then fails, with an error about the agent rather
  # than about the image. Enable it once the image installs the agent.
  agent {
    enabled = false
  }
}
