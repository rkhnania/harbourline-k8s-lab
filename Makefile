# Harbourline lab - operator verbs.
#
# WHY THIS FILE EXISTS.
# Every check in this repo used to be an improvised one-liner pasted into a
# terminal. Those fail in ways that have nothing to do with the cluster:
# a grep that matches the wrong Service, a "!" that bash expands as history,
# chained sleeps that stack up in a paste buffer and swallow the output.
# A target is written once, reviewed once, and is then the same every time.
#
#   make help
#
CTX ?= kind-harbourline
NS  ?= monitoring
PROM = kps-kube-prometheus-stack-prometheus
PVE  ?= 192.168.0.50
CURL = curlimages/curl:8.11.1

K = kubectl --context $(CTX)

.PHONY: help status apps sync pve-seal pve-verify pve-logs pve-targets \
        pve-restart deck-why render

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	 | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

status: ## Everything that is not Running or not Synced
	@echo "--- applications not Synced/Healthy ---"
	@$(K) -n argocd get applications.argoproj.io \
	  -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status \
	  --no-headers | grep -v "Synced *Healthy" || echo "  all green"
	@echo "--- pods not Running/Completed ---"
	@$(K) get pods -A --no-headers \
	  | awk '$$4!="Running" && $$4!="Completed" {print "  "$$1"/"$$2"  "$$4}' \
	  || echo "  all green"

apps: ## All Argo CD applications
	@$(K) -n argocd get applications.argoproj.io

sync: ## Force Argo to re-read Git now.  make sync APP=monitoring-config
	@test -n "$(APP)" || { echo "usage: make sync APP=<application>"; exit 1; }
	@$(K) -n argocd patch application.argoproj.io $(APP) --type merge \
	  -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}'

pve-seal: ## Seal the Proxmox API token (prompts, or pass PVE_TOKEN=...)
	@bash scripts/seal-pve-token.sh

pve-restart: ## Restart the exporter so it re-reads its env vars
	@$(K) -n $(NS) rollout restart deploy/pve-exporter
	@$(K) -n $(NS) rollout status deploy/pve-exporter --timeout=90s

pve-verify: ## Ask the exporter directly - isolates exporter<->Proxmox
	@$(K) -n $(NS) run pvecheck-$$$$ --rm -i --restart=Never --quiet \
	  --image=$(CURL) -- -s "http://pve-exporter:9221/pve?target=$(PVE)" \
	  | head -20

pve-targets: ## Ask Prometheus - isolates Prometheus<->exporter
	@$(K) -n $(NS) run promcheck-$$$$ --rm -i --restart=Never --quiet \
	  --image=$(CURL) -- -s \
	  "http://$(PROM):9090/api/v1/query?query=count(pve_up)" | head -c 400
	@echo

pve-logs: ## Last 40 lines from the exporter
	@$(K) -n $(NS) logs -l app.kubernetes.io/name=pve-exporter --tail=40

deck-why: ## Why is a pod not starting - image, events, last state
	@$(K) -n harbourline describe pod -l app.kubernetes.io/name=deck \
	  | grep -iE "image:|reason|message|exit code" | tail -20

render: ## Prove the monitoring directory still builds before pushing
	@$(K) kustomize k8s/monitoring/manifests > /dev/null && echo "kustomize build OK"
