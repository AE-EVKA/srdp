set shell := ["bash", "-c"]
set dotenv-load := false

namespace := "srdp"
# Registry prefix of every image this repo builds. local-deploy passes it to the
# chart as global.srdpRegistry and as the Dagster code location's repository.
registry := "rg.nl-ams.scw.cloud/srdp-registry"
registry_args := "--set-string 'global.srdpRegistry=" + registry + "' --set-string 'dagster.dagster-user-deployments.deployments[0].image.repository=" + registry + "/srdp-etl'"
kubeconfig := justfile_directory() + "/deploy/opentofu/scaleway/kubeconfig.yaml"

default: help

# List all available commands
help:
	@just --list

# ─── Scaleway landing zone (deploy/scaleway) ─────────────────────────────────

# Delegate to deploy/scaleway's own Justfile
scaleway *args:
	@just -f deploy/scaleway/Justfile -d deploy/scaleway {{args}}

# ─── Local development ────────────────────────────────────────────────────────

# Generate mkcert TLS certs for the local Docker Compose stack
docker-tls:
	mkdir -p deploy/docker/certs
	mkcert -cert-file deploy/docker/certs/selfsigned.crt -key-file deploy/docker/certs/selfsigned.key "srdp.localhost" "auth.srdp.localhost" "marimo.srdp.localhost" "dagster.srdp.localhost" "streamlit.srdp.localhost" "marquez.srdp.localhost" "api.srdp.localhost" "duckdb.srdp.localhost"

# Create (or reuse) the local kind cluster
kind-up:
	kind get clusters 2>/dev/null | grep -qx srdp || kind create cluster --config deploy/kubernetes/kind-config.yaml
	kubectl config use-context kind-srdp

# Delete the local kind cluster
kind-down:
	kind delete cluster --name srdp

# Build all images and load them into kind
kind-load-images: kind-up
	docker build -t {{registry}}/marimo:v1.0 -f projects/cbs-example/notebooks/Dockerfile .
	docker build -t {{registry}}/srdp-etl:v1.0 -f projects/cbs-example/Dockerfile .
	docker build -t {{registry}}/srdp-api:v1.0 -f projects/cbs-example/api/Dockerfile .
	docker build -t {{registry}}/duckdb-ui:v1.0 -f services/duckdb-ui/Dockerfile .
	docker build -t {{registry}}/hub:v1.0 services/hub
	docker build -t {{registry}}/streamlit:v1.0 -f projects/cbs-example/streamlit/Dockerfile .
	docker build -t {{registry}}/srdp-setup:v1.0 -f deploy/docker/srdp-setup.Dockerfile .
	kind load docker-image \
		{{registry}}/marimo:v1.0 \
		{{registry}}/srdp-etl:v1.0 \
		{{registry}}/srdp-api:v1.0 \
		{{registry}}/duckdb-ui:v1.0 \
		{{registry}}/hub:v1.0 \
		{{registry}}/srdp-setup:v1.0 \
		{{registry}}/streamlit:v1.0 \
		--name srdp

# Generate local TLS certs for the kind stack
local-tls: kind-up
	mkdir -p deploy/kubernetes/certs
	mkcert -cert-file deploy/kubernetes/certs/selfsigned.crt -key-file deploy/kubernetes/certs/selfsigned.key "srdp.localhost" "auth.srdp.localhost" "marimo.srdp.localhost" "dagster.srdp.localhost" "streamlit.srdp.localhost" "marquez.srdp.localhost" "api.srdp.localhost" "duckdb.srdp.localhost"
	kubectl create namespace {{namespace}} --dry-run=client -o yaml | kubectl apply -f -
	kubectl create secret tls custom-ingress-cert --namespace {{namespace}} --key deploy/kubernetes/certs/selfsigned.key --cert deploy/kubernetes/certs/selfsigned.crt --dry-run=client -o yaml | kubectl apply -f -

# Deploy the full stack to local kind via Helm (extra args go to helm, e.g. -f srdp-chart/values-local-s3.yaml)
local-deploy *args: kind-load-images
	cd deploy/kubernetes/srdp-chart && helm dependency update
	cd deploy/kubernetes && helm upgrade --install srdp srdp-chart --namespace {{namespace}} --create-namespace -f srdp-chart/values.yaml -f srdp-chart/values-local.yaml {{registry_args}} {{args}}
	@echo "Reading Traefik's assigned ClusterIP to wire it into oauth2-proxy's hostAliases..."
	@TRAEFIK_IP=$(kubectl get svc srdp-traefik -n {{namespace}} -o jsonpath='{.spec.clusterIP}'); \
	echo "Traefik ClusterIP: $TRAEFIK_IP"; \
	cd deploy/kubernetes && helm upgrade srdp srdp-chart --namespace {{namespace}} -f srdp-chart/values.yaml -f srdp-chart/values-local.yaml {{registry_args}} {{args}} --set-string "oauth2-proxy.hostAliases[0].ip=$TRAEFIK_IP"

# Uninstall the local Helm release and its PVCs
local-delete:
	helm uninstall srdp -n {{namespace}} || true
	# Dagster run Jobs are created by the run launcher, not by Helm, and their
	# pods keep the ducklake-data PVC in Terminating until they are gone.
	kubectl delete jobs --all -n {{namespace}} || true
	kubectl delete pvc --all -n {{namespace}} || true

# Start the Docker Compose stack (local dev). Attached by default; pass -d to detach.
docker-up *args:
	cd deploy/docker && docker compose up --build {{args}}

# Stop the Docker Compose stack
docker-down:
	cd deploy/docker && docker compose down

# ─── Production / infra ───────────────────────────────────────────────────────

# Provision the Scaleway cluster with OpenTofu
prod-apply:
	cd deploy/opentofu/scaleway && source ./secrets.sh && tofu apply -auto-approve

# Tear down the Scaleway cluster
prod-destroy:
	just prod-uninstall || echo "Helm uninstall skipped (cluster may already be down)"
	cd deploy/opentofu/scaleway && source ./secrets.sh && tofu destroy -auto-approve

# Write the Scaleway kubeconfig locally
prod-use-kubeconfig:
	cd deploy/opentofu/scaleway && tofu output -raw kubeconfig > "{{kubeconfig}}" && echo "kubeconfig written to {{kubeconfig}}"

# Print Traefik's LoadBalancer IP
prod-get-values:
	@echo "Fetching dynamic values..."
	@if [ ! -f "{{kubeconfig}}" ]; then echo "kubeconfig not found, run 'just prod-use-kubeconfig' first"; exit 1; fi
	@KUBECONFIG="{{kubeconfig}}" kubectl get svc srdp-traefik -n {{namespace}} -o jsonpath='{.status.loadBalancer.ingress[0].ip}' | xargs -I{} printf "LOAD_BALANCER_IP:\t%s\n" "{}"

# Deploy only Traefik, to get the first LoadBalancer IP
prod-traefik-only:
	cd deploy/kubernetes && \
		if [ ! -f "{{kubeconfig}}" ]; then echo "kubeconfig not found, run 'just prod-use-kubeconfig' first"; exit 1; fi; \
		export KUBECONFIG="{{kubeconfig}}"; \
		helm upgrade --install srdp srdp-chart --namespace {{namespace}} --create-namespace -f srdp-chart/values-prod.yaml --set zitadel.enabled=false --set oauth2-proxy.enabled=false --set dagster.enabled=false --set marimo.enabled=false --set quarto.enabled=false

# Deploy Traefik plus the auth stack only
prod-auth-only:
	cd deploy/kubernetes && \
		if [ ! -f "{{kubeconfig}}" ]; then echo "kubeconfig not found, run 'just prod-use-kubeconfig' first"; exit 1; fi; \
		export KUBECONFIG="{{kubeconfig}}"; \
		helm upgrade srdp srdp-chart --namespace {{namespace}} --reset-values -f srdp-chart/values-prod.yaml --set zitadel.enabled=true --set oauth2-proxy.enabled=true --set dagster.enabled=false --set marimo.enabled=false --set quarto.enabled=false

# Deploy the complete production stack
prod-full:
	cd deploy/kubernetes && \
		if [ ! -f "{{kubeconfig}}" ]; then echo "kubeconfig not found, run 'just prod-use-kubeconfig' first"; exit 1; fi; \
		export KUBECONFIG="{{kubeconfig}}"; \
		helm upgrade srdp srdp-chart --namespace {{namespace}} --reset-values -f srdp-chart/values-prod.yaml

# Uninstall the production Helm release and release the LoadBalancer
prod-uninstall:
	cd deploy/kubernetes && \
		if [ ! -f "{{kubeconfig}}" ]; then echo "kubeconfig not found, run 'just prod-use-kubeconfig' first"; exit 1; fi; \
		export KUBECONFIG="{{kubeconfig}}"; \
		echo "Deleting LoadBalancer service (releases Scaleway LB)..." && \
		kubectl delete svc srdp-traefik -n {{namespace}} --ignore-not-found && \
		echo "Waiting 30s for LB cleanup..." && sleep 30 && \
		helm uninstall srdp -n {{namespace}} || true && \
		kubectl delete jobs --all -n {{namespace}} --ignore-not-found && \
		kubectl delete pvc --all -n {{namespace}} --ignore-not-found

# ─── Images ───────────────────────────────────────────────────────────────────

# Build and push images to the Scaleway registry
build-and-push:
	source deploy/opentofu/scaleway/secrets.sh && bash deploy/opentofu/scaleway/build-and-push.sh

# ─── Development ──────────────────────────────────────────────────────────────

# Install all dependencies and set up pre-commit
init:
	uv sync --all-groups --all-extras
	uv run pre-commit install

# Run ruff check and format check
lint:
	uv run ruff check src/ projects/
	uv run ruff format --check src/ projects/

# Run ty on src/srdp
typecheck:
	uv run ty check src/srdp

# Run pytest if tests/ has any, skip with a warning otherwise
test:
	@if [ -d tests ] && find tests -name 'test_*.py' -o -name '*_test.py' 2>/dev/null | grep -q .; then \
		uv run pytest tests --cov=srdp; \
	else \
		echo "warning: no tests/ found, skipping."; \
	fi

# Run lint + typecheck + test
ci: lint typecheck test

# Auto-fix all ruff lint + format issues
fix:
	uv run ruff check --fix src/ projects/
	uv run ruff format src/ projects/

# Cut a release: bump version, run CI, commit, tag
release version:
	./scripts/release.sh "{{version}}"
