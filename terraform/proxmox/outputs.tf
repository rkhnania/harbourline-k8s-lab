output "vm_id" {
  value = proxmox_virtual_environment_vm.probe.vm_id
}

output "vm_name" {
  value = proxmox_virtual_environment_vm.probe.name
}

output "ssh" {
  description = "How to reach it once cloud-init has finished."
  value       = "ssh debian@${split("/", var.vm_ipv4)[0]}"
}
