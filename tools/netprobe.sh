#!/usr/bin/env bash
# Probe outbound reachability from a pod in the harbourline namespace.
# Usage: tools/netprobe.sh [pod-name]   (default: probe)
POD="${1:-probe}"
kubectl exec -i -n harbourline "$POD" -- sh -s <<'INNER'
dnsq() { nslookup "$1" 2>/dev/null | grep -q '^Name:' && echo OK || echo FAIL; }
http() { c=$(curl -sk -o /dev/null -w '%{http_code}' -m 5 "$1" 2>/dev/null); r=$?; echo "HTTP $c (curl exit $r)"; }
printf '%-13s %s\n' dns-internal "$(dnsq harbourline-db.harbourline.svc.cluster.local)"
printf '%-13s %s\n' dns-external "$(dnsq github.com)"
printf '%-13s %s\n' api          "$(http http://harbourline-api:8080/health)"
printf '%-13s %s\n' db-5432      "$(nc -z -w3 harbourline-db.harbourline.svc.cluster.local 5432 && echo OPEN || echo closed)"
printf '%-13s %s\n' internet     "$(http https://github.com)"
printf '%-13s %s\n' k8s-api      "$(http https://kubernetes.default.svc:443/version)"
INNER
