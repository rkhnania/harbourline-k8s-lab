# etcd backup and restore (single-member)

etcd is the only place Kubernetes API objects exist. Nodes hold images, runtime
state and volume data, never API objects. Restoring etcd rolls the whole cluster
back in time. The cluster is DOWN for the duration — this is not a live operation.

## 1. Take the snapshot and get it off the box

    kubectl -n kube-system exec etcd-harbourline-control-plane -- etcdctl \
      --endpoints=https://127.0.0.1:2379 \
      --cacert=/etc/kubernetes/pki/etcd/ca.crt \
      --cert=/etc/kubernetes/pki/etcd/server.crt \
      --key=/etc/kubernetes/pki/etcd/server.key \
      snapshot save /var/lib/etcd/snap-$(date +%F).db

    docker cp harbourline-control-plane:/var/lib/etcd/snap-$(date +%F).db ./etcd-snapshot.db

A snapshot that only exists on the machine you are protecting is not a backup.
The snapshot contains every Secret in PLAINTEXT. Treat it as a credential store:
encrypt at rest, restrict access, audit reads. Never commit it.

## 2. Put etcdctl somewhere that survives the outage

    sudo apt-get install -y etcd-client

The etcd image is distroless and etcdctl lives only inside it. Stop the pod and
you lose the tool you need to restore it. Recovery tooling must live outside the
thing being recovered.

## 3. Restore into a fresh data directory

    ETCDCTL_API=3 etcdctl snapshot restore ./etcd-snapshot.db --data-dir ~/etcd-restore

Non-destructive, cluster still running. Produces member/snap and member/wal with
a new member and cluster ID, so the restored member cannot rejoin the old cluster
and create two sources of truth.

## 4. Stop the control plane

    docker exec harbourline-control-plane sh -c \
      'mkdir -p /etc/kubernetes/manifests-off && \
       mv /etc/kubernetes/manifests/*.yaml /etc/kubernetes/manifests-off/'

The kubelet runs the control plane from files on disk with no API server
involved. That is exactly why this works when the API server is the casualty.

Verify it is down. kubectl fails with EOF / connection reset, which is NOT the
same as connection refused: with kind's host port-forward, refused means nothing
is listening, reset means something is listening but the service behind it is gone.

## 5. Swap the data directory

    docker cp ~/etcd-restore harbourline-control-plane:/var/lib/etcd-restore

    docker exec harbourline-control-plane sh -c '
      mkdir -p /var/lib/etcd.old && \
      mv /var/lib/etcd/member /var/lib/etcd.old/ && \
      mv /var/lib/etcd-restore/member /var/lib/etcd/ && \
      chown -R root:root /var/lib/etcd && \
      chmod 700 /var/lib/etcd'

Move member/, not the whole directory: /var/lib/etcd may be a mount point and mv
on one fails with "device or resource busy". The chown is needed because the
files arrive owned by the host user; etcd runs as root and wants 0700.

## 6. Restart the control plane

    docker exec harbourline-control-plane sh -c \
      'mv /etc/kubernetes/manifests-off/*.yaml /etc/kubernetes/manifests/'

    sleep 45 && kubectl get nodes

## 7. Restart the kubelets on every node

    docker exec harbourline-worker  systemctl restart kubelet
    docker exec harbourline-worker2 systemctl restart kubelet

The step most runbooks omit. See gotcha 3.

## 8. Verify

    kubectl get ns post-snapshot-marker     # must be NotFound
    kubectl get pods -A
    curl -s http://harbourline.localtest.me/api/shipments

Verify with an object created AFTER the snapshot. If it is gone, the restore is
proven. Anything else is a guess.

## Gotcha 1 - the cluster's records lie about itself afterwards

kube-controller-manager reported "AGE 9d, RESTARTS 0" four minutes after being
destroyed and recreated. Pod ages, restart counts and event history all come back
from the snapshot and describe a cluster that no longer exists. Do not trust them
for triage immediately after a restore.

## Gotcha 2 - a restore can re-run completed Jobs

harbourline-db-init resurrected itself because the restored Job record looked
incomplete. Harmless here. Not harmless if the job drops a schema, sends email or
charges customers: etcd rolls back, but databases, mail servers and payment
processors do not. Audit Jobs and CronJobs before restoring and suspend the
dangerous ones first.

## Gotcha 3 - the Node authorizer graph goes stale

--authorization-mode=Node,RBAC builds a per-node graph of which objects each
kubelet may read, derived from pod assignments. After a restore that graph
describes the past, so the kubelet gets:

    configmaps "kube-root-ca.crt" is forbidden: User "system:node:<node>"
    cannot watch resource "configmaps" ... no relationship found between
    node '<node>' and this object

It cannot fetch the pod's ConfigMap or Secret, so the pod sits Pending with ZERO
events. Meanwhile crictl pods on the node showed a sandbox for a pod etcd no
longer knew about. Restarting the kubelets fixes both.

## Two families of Pending

| Evidence | Who is stuck | Where to look |
|---|---|---|
| PodScheduled False + FailedScheduling | scheduler, cannot place it | capacity, nodeSelector/affinity, taints, unbound PVC |
| PodScheduled True, no container events | kubelet, placed but never started | kubelet on that node, crictl pods, Node-authorizer errors |

kubectl logs on a Pending pod returns "pods/log not found" - no container has
started, so there is nothing to read.

## Not covered here

Multi-member etcd: every member must be restored from the same snapshot with a
matching --initial-cluster, or the cluster will not form. Also not in the
snapshot: the PKI in /etc/kubernetes/pki, kubeadm config, and anything outside
etcd. Back those up separately.
