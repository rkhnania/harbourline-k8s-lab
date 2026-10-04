# etcd backup and restore (single-member)

## 1. Take the snapshot and get it off the box
## 2. Put etcdctl somewhere that survives the outage
## 3. Restore into a fresh data directory (cluster still running)
## 4. Stop the control plane
## 5. Swap the data directory
## 6. Restart the control plane
## 7. Restart the kubelets on every node
## 8. Verify with an object that postdates the snapshot

## Gotchas
x


