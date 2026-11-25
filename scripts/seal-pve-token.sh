#!/usr/bin/env bash
#
# Seals the Proxmox API token and activates the Proxmox monitoring resources.
#
#   bash scripts/seal-pve-token.sh        (run from the repo root)
#
# The token is READ FROM A PROMPT, not taken as an argument. An argument lands
# in your shell history and is visible in the process table to every other user
# on the box for as long as the command runs. `read -rs` avoids both. Same
# reasoning as docs/secrets.md.
#
# The plaintext never reaches the cluster: `--dry-run=client` builds the Secret
# manifest locally, and it exists only inside the pipe between kubectl and
# kubeseal. kubeseal fetches the controller's PUBLIC key and encrypts here; the
# private key never leaves the cluster.
set -euo pipefail

CTX="${CTX:-kind-harbourline}"
OUT="k8s/monitoring/manifests/pve-exporter-sealedsecret.yaml"
KUST="k8s/monitoring/manifests/kustomization.yaml"

[ -f "$KUST" ] || { echo "ERROR: run this from the repo root."; exit 1; }
command -v kubeseal >/dev/null || { echo "ERROR: kubeseal not on PATH."; exit 1; }
kubectl --context "$CTX" get ns monitoring >/dev/null \
  || { echo "ERROR: cannot reach the monitoring namespace on context $CTX."; exit 1; }

# PVE_TOKEN may be supplied in the environment when a hidden prompt is awkward
# (some terminals swallow a paste into `read -rs`). That is a deliberate
# trade-off: an environment variable set on the command line DOES land in shell
# history, so prefer the prompt, and rotate the token afterwards if you use this.
if [ -z "${PVE_TOKEN:-}" ]; then
  read -rsp "PVE token value for monitoring@pve!prometheus: " PVE_TOKEN; echo
fi
[ -n "${PVE_TOKEN:-}" ] || { echo "ERROR: empty token."; exit 1; }

# Strip whitespace a paste may have carried in. A trailing newline or space is
# invisible, survives base64, and comes back as a flat 401 from Proxmox with no
# hint that the value is merely dirty rather than wrong.
PVE_TOKEN="$(printf '%s' "$PVE_TOKEN" | tr -d '[:space:]')"

# PVE tokens are UUIDs. Catch a truncated paste here rather than three layers
# downstream in an exporter traceback.
if ! printf '%s' "$PVE_TOKEN" | grep -Eq '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'; then
  echo "ERROR: that does not look like a PVE token UUID (got ${#PVE_TOKEN} chars)."
  exit 1
fi

kubectl create secret generic pve-exporter-credentials -n monitoring \
  --from-literal=PVE_USER='monitoring@pve' \
  --from-literal=PVE_TOKEN_NAME='prometheus' \
  --from-literal=PVE_TOKEN_VALUE="$PVE_TOKEN" \
  --from-literal=PVE_VERIFY_SSL='false' \
  --dry-run=client -o yaml \
  | kubeseal --context "$CTX" --format yaml > "$OUT"
unset PVE_TOKEN

# A kubeseal that cannot reach the controller can still exit 0 and emit
# something useless. Check for ciphertext before trusting the file.
grep -q 'encryptedData' "$OUT" || { echo "ERROR: no ciphertext produced."; rm -f "$OUT"; exit 1; }

sed -i \
  -e 's|^  # - pve-exporter-sealedsecret.yaml|  - pve-exporter-sealedsecret.yaml|' \
  -e 's|^  # - pve-exporter.yaml|  - pve-exporter.yaml|' \
  -e 's|^  # - pve-dashboard.yaml|  - pve-dashboard.yaml|' \
  "$KUST"

kubectl kustomize k8s/monitoring/manifests >/dev/null \
  || { echo "ERROR: kustomize build failed - do not push."; exit 1; }

echo
echo "Sealed   -> $OUT"
echo "Activated-> 3 resources in $KUST"
echo "Build    -> OK"
echo
echo "Next:  git add -A && git commit -m 'Activate Proxmox monitoring' && git push"
