# Logging - Loki on the kind cluster

Added 2026-10-15. Closes the last observability pillar: metrics were in place,
logs and traces were not.

| Component | Chart | Mode |
|---|---|---|
| Loki | `grafana/loki` 7.3.0 (app 3.6.x) | SingleBinary, filesystem storage |
| Alloy | `grafana/alloy` 1.13.1 | DaemonSet, scrapes pod logs per node |
| Grafana | existing `kps-grafana` | datasource added via sidecar ConfigMap |

Values: [`k8s/monitoring/loki-values.yaml`](../k8s/monitoring/loki-values.yaml)

The datasource is a ConfigMap labelled `grafana_datasource: "1"`. The
kube-prometheus-stack Grafana runs a sidecar that watches for that label, so
no Grafana config is edited and no restart is needed.

## Why this is not kubectl logs

`kubectl logs` asks the kubelet for one container's current log file. It cannot
look across pods, cannot look across namespaces, and cannot see anything after
a pod is gone.

Alloy runs one pod per node and reads container log files off the host
filesystem, attaching the pod's labels. The result is queryable across the whole
cluster and survives the pod.

## Loki indexes labels, not content

Each unique label combination is a separate stream with its own index entry.
Only four labels are set here - `namespace`, `pod`, `container`, `app` - and
that restraint is the whole discipline.

> Put a request ID, a trace ID or a pod IP in a label and you create a stream
> per value. The index explodes. Same failure mode as high-cardinality
> Prometheus labels, same cause.

Searching text inside log lines is a brute-force scan over the matched streams,
by design. That is why Loki is far cheaper to run than Elasticsearch, and why
the label selector must come first:

    {namespace="harbourline"} |= "error"

The selector narrows to the streams, then the scan runs. Grafana shows the
estimated bytes a query will process before you run it - drop the namespace
label and watch that number jump.

## Queries worth keeping

Everything in the namespace, across every pod:

    {namespace="harbourline"}

Log volume per app, as a graph:

    sum by (app) (count_over_time({namespace="harbourline"}[5m]))

The second one is the useful one, because **you do not have to know what you are
looking for**. A service that stops logging, restarts in a loop, or suddenly
logs ten times as much is a line that changes shape.

Observed on the first run: `harbourline-api` rose from ~190 to ~288 over eight
minutes. That was the third replica returning after the Kyverno mutation
exercise - a 2-to-3 replica change, visible as a 50% rise in log volume, with
nothing having told the graph that a replica change happened.

This is what was missing on 2026-10-12. During the egress NetworkPolicy break,
`kubectl logs deploy/harbourline-api` showed 20 clean 200s while the site was
down, because the break was upstream of the logs being read. A per-app volume
graph would have shown web flat while api stayed normal.

## Known gaps

- **No control-plane logs.** The Alloy DaemonSet has no toleration for the
  control-plane taint, so it runs on the two workers only. Deliberate here;
  on a real cluster it is a decision to make explicitly.
- Both Loki and Alloy are installed by hand, not under Argo CD.
- Still no tracing. Jaeger needs the application to emit spans, which means
  instrumenting the Python services with OpenTelemetry first - an application
  project, not a platform one.
