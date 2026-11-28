variable "node_name" {
  description = "Proxmox node that will host the VM."
  type        = string
  default     = "pve1"
}

variable "vm_name" {
  description = "Name shown in the Proxmox UI."
  type        = string
  default     = "hl-tf-probe"
}

variable "vm_id" {
  description = "Proxmox VMID. Fixed so repeated applies address the same guest."
  type        = number
  default     = 9001
}

variable "vm_ipv4" {
  description = "Static address in CIDR form. Static, not DHCP, so the output of terraform apply is knowable before it runs."
  type        = string
  default     = "192.168.0.51/24"
}

variable "vm_gateway" {
  type    = string
  default = "192.168.0.1"
}

variable "dns_servers" {
  type    = list(string)
  default = ["192.168.0.1"]
}

variable "vm_cores" {
  type    = number
  default = 2
}

variable "vm_memory_mb" {
  type    = number
  default = 2048
}

variable "vm_disk_gb" {
  type    = number
  default = 20
}

variable "ssh_public_key_path" {
  description = "Public key injected by cloud-init. Generate one with: ssh-keygen -t ed25519 -N \"\" -f ~/.ssh/id_ed25519"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "image_datastore" {
  description = "Datastore holding the downloaded cloud image. Must be a 'dir' type - local-lvm cannot hold files."
  type        = string
  default     = "local"
}

variable "disk_datastore" {
  description = "Datastore for the VM disk. lvmthin, so it takes raw volumes."
  type        = string
  default     = "local-lvm"
}
