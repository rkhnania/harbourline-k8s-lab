#!/usr/bin/env bash
# Answers CIS Kubernetes Benchmark 5.1.7 - 5.1.13: who holds the permissions
# that let a subject become more powerful than it was granted.
#
#   usage:  bash k8s/labs/rbac/audit-privileged-rbac.sh [kube-context]
#
# WHAT THIS IS AND IS NOT
# It is a first-pass inventory: it lists every ClusterRole carrying a dangerous
# verb or resource so a human can review them. It is NOT a pass/fail check.
# Kubernetes ships built-in `system:` roles that legitimately hold most of
# these - the controller manager must create PersistentVolumes, the CSR
# approver must approve CSRs. The finding is never "this verb exists", it is
# "something OUTSIDE the built-ins holds it, and nobody decided that".
#
# So read the output in two passes: ignore `system:*` and the handful of
# built-in aggregates (admin / edit / view / cluster-admin), then ask of
# whatever remains: who asked for this, and when was it last reviewed.
set -uo pipefail
CTX="${1:-kind-harbourline}"
K=(kubectl --context "$CTX")

hr()  { printf '\n%s\n' "────────────────────────────────────────────────────────────"; }
head2(){ hr; printf '%s\n\n' "$1"; }

head2 "5.1.7  Subjects bound to cluster-admin (effectively system:masters)"
"${K[@]}" get clusterrolebindings \
  -o custom-columns='BINDING:.metadata.name,ROLE:.roleRef.name,KIND:.subjects[*].kind,SUBJECT:.subjects[*].name' \
  --no-headers 2>/dev/null | awk '$2=="cluster-admin"'
echo
echo "Expected: system:masters (the bootstrap group) and kubeadm's own bindings."
echo "A human user or a ServiceAccount here is a finding. system:masters in"
echo "particular bypasses RBAC entirely - the authorizer short-circuits before"
echo "any Role is consulted, so its access cannot be revoked by RBAC and does"
echo "not appear in 'kubectl auth can-i' reasoning."

head2 "5.1.8  ClusterRoles holding escalate, bind or impersonate"
"${K[@]}" get clusterroles \
  -o custom-columns='NAME:.metadata.name,VERBS:.rules[*].verbs' \
  --no-headers 2>/dev/null | grep -E 'escalate|impersonate|[^a-z]bind[^a-z]' || echo "(none)"
echo
echo "These three are privilege-escalation primitives:"
echo "  escalate    - grant yourself permissions you do not hold. Without it,"
echo "                RBAC refuses to let you create a Role more powerful than"
echo "                your own. With it, that guardrail is gone."
echo "  bind        - attach an existing Role to a subject, which reaches any"
echo "                permission that Role holds without needing escalate."
echo "  impersonate - act as another user, group or ServiceAccount. Equivalent"
echo "                to holding every permission any of them has, and the"
echo "                audit log records the impersonated identity."

head2 "5.1.9  create on persistentvolumes"
"${K[@]}" get clusterroles \
  -o custom-columns='NAME:.metadata.name,RES:.rules[*].resources' \
  --no-headers 2>/dev/null | grep -E '[^a-z]persistentvolumes[^a-z/]' || echo "(none)"
echo
echo "A PersistentVolume can mount a hostPath. Creating one is a documented"
echo "route to reading any file on a node, including kubelet credentials."

head2 "5.1.10  nodes/proxy"
"${K[@]}" get clusterroles \
  -o custom-columns='NAME:.metadata.name,RES:.rules[*].resources' \
  --no-headers 2>/dev/null | grep 'nodes/proxy' || echo "(none)"
echo
echo "Reaches the kubelet API directly, bypassing the API server's"
echo "authorization for pod exec and logs on that node."

head2 "5.1.11  certificatesigningrequests/approval"
"${K[@]}" get clusterroles \
  -o custom-columns='NAME:.metadata.name,RES:.rules[*].resources' \
  --no-headers 2>/dev/null | grep 'certificatesigningrequests/approval' || echo "(none)"
echo
echo "Approving your own CSR mints a client certificate for any identity the"
echo "cluster CA will sign - including a group such as system:masters."

head2 "5.1.12  validating/mutatingwebhookconfigurations"
"${K[@]}" get clusterroles \
  -o custom-columns='NAME:.metadata.name,RES:.rules[*].resources' \
  --no-headers 2>/dev/null | grep -E 'validatingwebhookconfigurations|mutatingwebhookconfigurations' || echo "(none)"
echo
echo "Write access here disables admission control - including the Kyverno"
echo "policies this cluster relies on - or redirects it to an attacker's"
echo "endpoint that mutates every object admitted."

head2 "5.1.13  serviceaccounts/token"
"${K[@]}" get clusterroles \
  -o custom-columns='NAME:.metadata.name,RES:.rules[*].resources' \
  --no-headers 2>/dev/null | grep 'serviceaccounts/token' || echo "(none)"
echo
echo "Mints a token for any ServiceAccount, which is lateral movement to every"
echo "permission any workload in the cluster holds. This is why Module 1's"
echo "per-workload ServiceAccounts matter: they bound the blast radius of this"
echo "permission rather than eliminating it."

hr
echo "Reverse lookup - 'who can read Secrets in harbourline?' - is not"
echo "answerable with kubectl alone; auth can-i only tests a subject you name."
echo "krew + kubectl-who-can, or rbac-tool, answers it properly."
