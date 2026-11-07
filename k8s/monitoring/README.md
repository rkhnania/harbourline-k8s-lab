# Monitoring — kube-prometheus-stack

Prometheus, Alertmanager, Grafana, node-exporter, kube-state-metrics and the
Prometheus Operator, on the kind cluster.

## Access Grafana

**http://grafana.localtest.me** — user `admin`.

`*.localtest.me` resolves to `127.0.0.1` by public DNS, so there is nothing to
add to a hosts file. The Ingress is at
[`k8s/platform/grafana-ingress.yaml`](../platform/grafana-ingress.yaml).

Only if the Ingress controller is down:

```bash
kubectl --context kind-harbourline port-forward -n monitoring svc/kps-grafana 3000:80
```

Then http://localhost:3000. **`--context` is not optional** — two kind clusters
share one kubeconfig, and without it kubectl falls back to `localhost:8080` and
reports `connection refused`, which looks like a dead cluster and is not.
A port-forward also holds its terminal: close it or press Ctrl-C and the tunnel
dies, with no warning beyond the browser refusing to connect.

### The admin password

Sealed into Git at
[`manifests/grafana-admin-sealedsecret.yaml`](manifests/grafana-admin-sealedsecret.yaml)
— ciphertext only this cluster can decrypt. The controller turns it into a
Secret named `grafana-admin`, which the chart reads via
`grafana.admin.existingSecret`.

To read the current password:

```bash
kubectl --context kind-harbourline -n monitoring get secret grafana-admin \
  -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

To change it, re-seal — do not edit the Secret, `selfHeal` will revert it:

```bash
read -rsp "New password: " GFPW; echo
kubectl create secret generic grafana-admin -n monitoring \
  --from-literal=admin-user=admin --from-literal=admin-password="$GFPW" \
  --dry-run=client -o yaml \
  | kubeseal --context kind-harbourline --format yaml \
  > k8s/monitoring/manifests/grafana-admin-sealedsecret.yaml
unset GFPW
```

Commit, push, and Argo CD applies it. The plaintext never touches disk:
`--dry-run=client` builds the manifest without sending it anywhere, and the
value exists only inside the pipe.

> **Grafana stores the admin user in its own database**, so a changed password
> may not take effect until the Grafana pod restarts. If a new password does
> not work, delete the pod before assuming the seal failed.

## Install

**There is no install command.** Argo CD owns this — see
[`k8s/argocd/apps/kps.yaml`](../argocd/apps/kps.yaml). The chart is pulled from
upstream and this directory's `kps-values.yaml` is supplied as a second source.

Until 2026-11-07 this file documented:

```
helm install kps prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace -f kps-values.yaml \
  --set grafana.adminPassword="$GRAFANA_PASSWORD"
```

Two things were wrong with it, and both are worth keeping on the record.

**It was not the command that was used.** `helm get values kps` showed no
`defaultDashboardsTimezone`, so Grafana served UTC while this directory's
values file had claimed `Australia/Sydney` since 15 October. A documented
install command nobody re-runs drifts silently from the one that was.

**`--set` has no home in GitOps.** Argo CD renders what is in Git and nothing
else; there is no install time at which to pass a flag. That single line is why
the monitoring stack could not be adopted until the password was sealed.

## Files

| File | What it is |
|---|---|
| `kps-values.yaml` | chart input, pulled by the `kps` Application |
| `loki-values.yaml` | chart input, pulled by the `loki` Application |
| `manifests/` | objects **applied** to the namespace — kept apart from values files, which are not Kubernetes objects and would fail a directory sync |

## Components

| Component | Role |
|---|---|
| node-exporter (DaemonSet) | per-node CPU, memory, disk, network |
| kube-state-metrics | Kubernetes object state as metrics |
| Prometheus (StatefulSet) | scrapes and stores time series |
| Alertmanager (StatefulSet) | routes and de-duplicates alerts |
| Grafana | dashboards over Prometheus and Loki |
| Prometheus Operator | ServiceMonitor / PrometheusRule CRDs |

## Useful dashboards

- Kubernetes / Compute Resources / Cluster
- Kubernetes / Compute Resources / Namespace (Pods)
- Kubernetes / Compute Resources / Node (Pods)
- Node Exporter / Nodes

## Known

**Nothing alerts.** Alertmanager is deployed and routes nothing — there are no
PrometheusRules of this project's own. Monitoring without alerting is a
dashboard nobody is watching, which is how 12 October happened.
