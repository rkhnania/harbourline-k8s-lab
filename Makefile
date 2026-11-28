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
        pve-restart deck-why render schema smoke test-api test-deck test-reports test-web

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

render: ## Prove every kustomize directory still builds before pushing
	@# Discovered, not listed. A hardcoded list silently stops covering a
	@# directory the day someone adds one - which is the same failure shape as
	@# the CI path filter that left deck unbuilt for two weeks.
	@for d in $$(find k8s -name kustomization.yaml -printf '%h\n' | sort); do \
	   $(K) kustomize $$d > /dev/null && echo "  OK   $$d" || echo "  FAIL $$d"; \
	 done

test-api: ## Run the api suite on CI's Python against a throwaway Postgres
	@# WSL python is 3.14; CI and the runtime images are 3.12. A pass on the
	@# wrong interpreter is weaker evidence than no pass at all, because it
	@# feels like proof. This runs the suite the way CI will run it.
	@docker rm -f plimsoll-test-db >/dev/null 2>&1 || true
	@docker network create plimsoll-test >/dev/null 2>&1 || true
	@docker run -d --rm --name plimsoll-test-db --network plimsoll-test \
	   -e POSTGRES_PASSWORD=postgres postgres:16-alpine >/dev/null
	@until docker exec plimsoll-test-db pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
	@docker run --rm --network plimsoll-test -v "$$PWD":/w -w /w/api \
	   -e TEST_DB_HOST=plimsoll-test-db -e TEST_DB_PASSWORD=postgres \
	   python:3.12-slim sh -c \
	   "pip install -q -r requirements.txt -r requirements-dev.txt && python -m pytest -q"; \
	 rc=$$?; \
	 docker rm -f plimsoll-test-db >/dev/null 2>&1; \
	 docker network rm plimsoll-test >/dev/null 2>&1; \
	 exit $$rc

smoke: ## Re-run the post-deployment smoke test and show the result
	@# The smoke test Job is rendered by the CHART, gated on
	@# smokeTest.enabled, which only values-web.yaml sets - so re-running it
	@# means syncing the `web` Application, not `harbourline`. That is not
	@# guessable from the Job's name or its namespace, and guessing it wrong
	@# re-runs db-init instead and reports a stale PASS from the previous run.
	@# Encoded here so nobody has to know. Note the Application is called
	@# harbourline-web, not web - the FILENAME is web.yaml, which is not the
	@# object's name. Assuming they match cost a round trip on 28 Nov.
	@$(K) -n argocd patch application.argoproj.io harbourline-web --type merge \
	  -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}' >/dev/null
	@echo "syncing harbourline-web (owner of the smoke test), waiting for the hook..."
	@sleep 60
	@$(K) -n harbourline logs job/harbourline-smoke-test --tail=30

schema: ## Objects and row counts the init Job will produce
	@$(K) -n harbourline exec sts/harbourline-db -- psql -U postgres -c "\\dt" 2>/dev/null \
	  || echo "database not reachable - is the harbourline Application synced?"

test-deck: ## Run the deck suite on CI's Python (no database needed)
	@docker run --rm -v "$$PWD":/w -w /w/deck python:3.12-slim sh -c \
	   "pip install -q -r requirements-dev.txt && python -m pytest -q"

test-web: ## Run the Portal UI checks in headless Chromium (no cluster needed)
	@# Same as the CI job: the real index.html against a mock Core and Insight.
	@# First run downloads Chromium into the container, about two minutes.
	@docker run --rm -v "$$PWD":/w -w /w -e SHOTS=web/tests/shots python:3.12-slim sh -c \
	   "pip install -q --root-user-action=ignore -r web/tests/requirements.txt \
	    && python -m playwright install --with-deps chromium >/dev/null 2>&1 \
	    && python web/tests/test_portal.py"

test-reports: ## Run the reports suite on CI's Python against a throwaway Postgres
	@docker rm -f plimsoll-test-db >/dev/null 2>&1 || true
	@docker network create plimsoll-test >/dev/null 2>&1 || true
	@docker run -d --rm --name plimsoll-test-db --network plimsoll-test \
	   -e POSTGRES_PASSWORD=postgres postgres:16-alpine >/dev/null
	@until docker exec plimsoll-test-db pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
	@docker run --rm --network plimsoll-test -v "$$PWD":/w -w /w/reports \
	   -e TEST_DB_HOST=plimsoll-test-db -e TEST_DB_PASSWORD=postgres \
	   python:3.12-slim sh -c \
	   "pip install -q -r requirements.txt -r requirements-dev.txt && python -m pytest -q"; \
	 rc=$$?; \
	 docker rm -f plimsoll-test-db >/dev/null 2>&1; \
	 docker network rm plimsoll-test >/dev/null 2>&1; \
	 exit $$rc
