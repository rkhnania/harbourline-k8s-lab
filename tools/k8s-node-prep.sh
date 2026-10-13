#!/usr/bin/env bash
set -euo pipefail
K8S_MINOR=v1.37

echo "== swap off =="
swapoff -a
sed -i '/\sswap\s/s/^/#/' /etc/fstab

echo "== kernel modules =="
printf 'overlay\nbr_netfilter\n' > /etc/modules-load.d/k8s.conf
modprobe overlay
modprobe br_netfilter

echo "== sysctls =="
cat > /etc/sysctl.d/k8s.conf <<'EOM'
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOM
sysctl --system >/dev/null

echo "== base packages =="
apt-get update -qq
apt-get install -y -qq containerd apt-transport-https ca-certificates curl gpg

echo "== containerd =="
mkdir -p /etc/containerd
containerd config default > /etc/containerd/config.toml
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
systemctl restart containerd
systemctl enable -q containerd

echo "== kubernetes packages =="
mkdir -p /etc/apt/keyrings
rm -f /etc/apt/keyrings/kubernetes-apt-keyring.gpg
curl -fsSL "https://pkgs.k8s.io/core:/stable:/${K8S_MINOR}/deb/Release.key" | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/${K8S_MINOR}/deb/ /" > /etc/apt/sources.list.d/kubernetes.list
apt-get update -qq
apt-get install -y -qq kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl >/dev/null
systemctl enable -q --now kubelet

set +e
echo
echo "===== VERIFY on $(hostname) ====="
echo -n "swap entries: "; swapon --show | wc -l
echo -n "modules: "; lsmod | grep -cE '^(overlay|br_netfilter)'
sysctl -n net.ipv4.ip_forward net.bridge.bridge-nf-call-iptables | tr '\n' ' '; echo
grep -m1 SystemdCgroup /etc/containerd/config.toml
kubeadm version -o short
echo "===== PREP DONE ====="
