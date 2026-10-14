# Bare-metal-style Kubernetes cluster (Hyper-V)

## Diagrams

**[Harbourline VM Cluster board](https://miro.com/app/board/uXjVEaGZDfM=/)** — four sections:

1. Physical host to Kubernetes — Hyper-V switch, the three VMs, what runs on each
2. MetalLB L2 — how a request reaches a pod, including the ARP election
3. Longhorn — one volume, two replicas, and what a node failure does
4. LAN address plan — 192.168.0.0/24 carved between DHCP, nodes and MetalLB


A second cluster, built with `kubeadm` on three Ubuntu VMs, separate from the
`kind` cluster that runs the Harbourline app. This one exists because Longhorn
needs real nodes — it is distributed block storage over iSCSI and requires the
`iscsi_tcp` kernel module, which the WSL2 kernel behind `kind` does not have.

## Topology

| Node | Role | IP | Disks |
|---|---|---|---|
| `hl-cp1` | control plane | 192.168.0.201 | 60GB OS |
| `hl-w1` | worker | 192.168.0.202 | 60GB OS + 40GB raw |
| `hl-w2` | worker | 192.168.0.203 | 60GB OS + 40GB raw |

The 40GB disks are left unpartitioned — Longhorn claims them as raw block devices.

- Kubernetes **v1.37.1**, Ubuntu 24.04.5 LTS, containerd 2.2.1
- CNI: **Cilium** (`ipam.mode=kubernetes`)
- Pod CIDR `10.244.0.0/16`, Service CIDR `10.96.0.0/12`
- kubectl context: `harbourline-vm`

## Network

The LAN is `192.168.0.0/24`. The router's DHCP pool was shrunk from `.2-.254`
to **`.2-.199`**, reserving `.200-.254` for infrastructure. Without that there
is no safe address for a static node IP or a MetalLB pool — every address is
fair game for the router to lease, and a collision shows up as a service that
works intermittently depending on who answers ARP first.

Each node carries `/etc/netplan/01-static.yaml` **and**
`/etc/cloud/cloud.cfg.d/99-disable-network-config.cfg`. Without the second file
cloud-init regenerates its own config on the next boot and the static address
silently reverts.

The guest interface is `eth0` (Hyper-V netvsc), not the `ens*` naming most
guides assume.

## Rebuilding a node

1. Hyper-V: Gen 2 VM, 4 vCPU, **8GB static** memory, automatic checkpoints off,
   Secure Boot template **Microsoft UEFI Certificate Authority** (without it
   Ubuntu will not boot).
2. Install Ubuntu Server 24.04.5. **Untick LVM** — the default allocates only
   half the volume group to the root logical volume. Tick **Install OpenSSH
   server**. On a worker, leave the 40GB disk untouched.
3. `scp tools/k8s-node-prep.sh` to the node and run it with sudo.
4. Join: `kubeadm token create --print-join-command` on `hl-cp1`.

## Why Cilium and not Flannel

**Flannel does not implement NetworkPolicy.** Policies apply without error and
without enforcement — the worst kind of failure, because everything looks
healthy. Cilium and Calico both enforce. Calico's default pod CIDR is
`192.168.0.0/16`, which overlaps this LAN, so it would need reconfiguring;
Cilium with `ipam.mode=kubernetes` just uses the per-node CIDRs that
kube-controller-manager carves out of `10.244.0.0/16`.

## Getting into a node you are locked out of

GRUB's menu is hidden on these VMs and `Esc` will not catch it. Ubuntu sets a
`recordfail` flag when a boot does not complete, which forces the menu to appear
on the next boot: **reset the VM, wait ~3 seconds, reset again**. Then
*Advanced options -> (recovery mode) -> root shell*:

    mount -o remount,rw /
    passwd <user>
    reboot

## Gotchas worth remembering

- Run `sudo -v` **before** pasting a multi-command block. A block starting with
  `sudo` collides with the password prompt and the remaining lines are eaten as
  failed password attempts.
- `netplan apply` over SSH kills your own session. Backgrounding it with
  `nohup ... &` does not survive the disconnect; use
  `sudo systemd-run --on-active=5 netplan apply` so systemd owns it.
- Ubuntu's `containerd` package ships with the CRI plugin **disabled**, failing
  kubeadm preflight. The prep script regenerates `config.toml` and sets
  `SystemdCgroup = true`.
