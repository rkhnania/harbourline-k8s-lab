# Monitoring — kube-prometheus-stack

Bundles Prometheus, Alertmanager, Grafana, node-exporter and kube-state-metrics.

## Install

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install kps prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace \
  -f kps-values.yaml \
  --set grafana.adminPassword="$GRAFANA_PASSWORD"
```

## Access Grafana

```bash
kubectl port-forward -n monitoring svc/kps-grafana 3000:80
```

Then http://localhost:3000 (user `admin`).

## Components

| Component | Role |
|---|---|
| node-exporter (DaemonSet) | Per-node CPU, memory, disk, network |
| kube-state-metrics | Kubernetes object state as metrics |
| Prometheus (StatefulSet) | Scrapes and stores time series |
| Alertmanager (StatefulSet) | Routes and de-duplicates alerts |
| Grafana | Dashboards over Prometheus |
| Prometheus Operator | ServiceMonitor / PrometheusRule CRDs |

## Useful dashboards

- Kubernetes / Compute Resources / Cluster
- Kubernetes / Compute Resources / Namespace (Pods)
- Kubernetes / Compute Resources / Node (Pods)
- Node Exporter / Nodes
