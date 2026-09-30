# Checklist for ticket 01

This checklist accompanies [ticket 01](tickets/01-chart-parity-and-secrets.md).
Work through it by hand after each PR (1a and 1b) to learn what changed, where it is configured, and how to confirm it works.
Tick a box only when you have seen the result yourself.

The chart lives in `deploy/kubernetes/srdp-chart/`.
All `kubectl` commands below assume the namespace `srdp`.

## 0. Before you start

Read these sections of the [Kubernetes primer](kubernetes-primer.md) first.

- [ ] I have read "Pod", "Deployment" and "Service".
- [ ] I have read "Ingress" and "PersistentVolumeClaim (PVC)".
- [ ] I have read "Secret and ConfigMap" and "Namespace".
- [ ] I have read "Helm" and "kind and Kapsule".
- [ ] I have the "kubectl cheat sheet" and "Statuses you will see often" open in a tab.

Check your tools.

- [ ] `kind version`, `kubectl version --client`, `helm version` and `mkcert -help` all print something.
- [ ] Docker Desktop has at least 8 GB of memory under Settings, Resources.
- [ ] `just kind-up` finishes, and `kubectl config current-context` prints `kind-srdp`.
- [ ] `just local-tls` finishes, and `kubectl get secret custom-ingress-cert -n srdp` shows the TLS Secret.

## 1. Get to know the chart

Read these files once, without changing anything.

- [ ] `Chart.yaml` lists the dependency charts (traefik, zitadel, postgresql, oauth2-proxy and dagster). Each one is a chart written by someone else, which we configure through a block in `values.yaml`.
- [ ] `values.yaml` has one top-level block per component. The block name matches the dependency name in `Chart.yaml`, or one of our own templates.
- [ ] `values-local.yaml` overrides `values.yaml` for kind. Helm merges the two files, and the last file on the command line wins.
- [ ] `templates/` holds our own components (api, marimo, quarto, duckdb-ui, hub, marquez) and the ingress wiring.
- [ ] The `local-deploy` recipe in the `Justfile` runs `helm upgrade` twice. I understand why (oauth2-proxy needs Traefik's ClusterIP, which only exists after the first install).

Record the starting state before the PRs land.

- [ ] I ran `just local-deploy` on `main` and saved the output of `kubectl get pods -n srdp`.
- [ ] For each pod that was not `Running` or `Completed`, I looked at `kubectl describe pod <name> -n srdp` and `kubectl logs <name> -n srdp`, and noted the cause.

## 2. PR 1a: the chart matches Compose

### Streamlit

What changed is a new template for streamlit, a `streamlit:` block in `values.yaml`, an ingress rule, and a line in `kind-load-images`.

- [ ] I read the new streamlit template and compared it with `templates/api.yaml`. I can point out the Deployment part and the Service part.
- [ ] `docker exec srdp-control-plane crictl images | grep streamlit` shows that the image is loaded into kind.
- [ ] `kubectl get deploy,svc -n srdp | grep streamlit` shows both a Deployment and a Service.
- [ ] `https://streamlit.srdp.localhost:18443` sends me to the Zitadel login, and shows the app after login.

### Databases

Nothing changes in the chart for the databases. Since #64 the setup Job creates them from `setup.databases` in `values.yaml`, on every install and upgrade.

- [ ] I read `setup.databases` in `values.yaml` and `templates/setup-job.yaml`, and I can explain why the `zitadel` entry is disabled.
- [ ] `kubectl get jobs -n srdp` shows `srdp-setup` as completed after the deploy.
- [ ] `kubectl exec -it <postgres-pod> -n srdp -- psql -U postgres -c '\l'` lists `zitadel`, `dagster`, `marquez` and `ducklake`.
- [ ] No pod stayed in `Init` on a `wait-for-*-db` init container.

### Dagster module path

What changed is the code location module in the `dagster:` block, from `definitions` to `etl.definitions`.

- [ ] I found the setting in `values.yaml` and the matching value in `deploy/docker/docker-compose.yml`.
- [ ] `kubectl logs` on the Dagster user-code pod shows no `ModuleNotFoundError`.
- [ ] The Dagster UI at `https://dagster.srdp.localhost:18443` shows the code location as loaded, with assets.

### One run at a time

What changed is the run coordinator in the `dagster:` block, with a maximum of one concurrent run.

- [ ] I found the setting, and I can explain why it exists (DuckLake may not handle two concurrent writers).
- [ ] I started two runs quickly after each other. The second one stays `Queued` until the first one finishes.
- [ ] While a run is active, `kubectl get pods -n srdp` shows exactly one run pod. This comes from the `K8sRunLauncher`, which starts each run in its own pod.

### End to end

- [ ] `kubectl get pods -n srdp` shows only `Running` or `Completed`.
- [ ] A Dagster run materializes the assets.
- [ ] Marimo, streamlit, the api and duckdb-ui all show the data from that run.
- [ ] The PR description contains the pod list and a screenshot of streamlit behind the login.

## 3. PR 1b: secrets and registry from outside the chart

### Secrets

What changed is that passwords and keys (`srdpTest123`, the Zitadel master key, the oauth2-proxy client secret and cookie secret) no longer live in `values.yaml`. Each app reads them from a Kubernetes Secret with a fixed name. For kind, a small template creates those Secrets from `values-local.yaml` when a local toggle is on.

- [ ] `grep -nE 'srdpTest|masterkey|clientSecret|cookieSecret' deploy/kubernetes/srdp-chart/values.yaml` finds no real values.
- [ ] I found the local toggle in `values-local.yaml`, and it is off (or absent) in `values.yaml`.
- [ ] I read the local Secret template, and I understand it only renders when the toggle is on.
- [ ] For a dependency chart, I found where it uses `existingSecret`. For one of our own templates, I found a `secretKeyRef` under `env`.
- [ ] `kubectl get secrets -n srdp` lists every Secret from the table in the PR description.
- [ ] `kubectl get secret <name> -n srdp -o jsonpath='{.data}'` shows the expected keys. The values are base64, which is an encoding and not encryption.

Check the rendered output without installing anything.

- [ ] `helm template srdp deploy/kubernetes/srdp-chart -f deploy/kubernetes/srdp-chart/values.yaml | grep -c srdpTest123` prints `0`.
- [ ] The same command with `-f deploy/kubernetes/srdp-chart/values-local.yaml` added does contain the development values, but only inside the local Secret template.
- [ ] After `just local-delete` and `just local-deploy`, the whole end-to-end check from section 2 still passes.

### Registry

What changed is that every SRDP image uses one registry value (for example `global.imageRegistry`), and there is an `imagePullSecrets` option.

- [ ] `grep -rn 'rg.nl-ams.scw.cloud' deploy/kubernetes/srdp-chart` only finds the single default value.
- [ ] `helm template ... --set global.imageRegistry=example.test/foo | grep 'image:'` shows the new prefix on every SRDP image.
- [ ] `helm template ... --set` with a pull secret shows `imagePullSecrets` on the SRDP pods.

## 4. Memory usage

- [ ] `docker stats srdp-control-plane --no-stream` shows the total memory of the kind node.
- [ ] I recorded the memory of each pod in the ticket, for example from `docker exec srdp-control-plane crictl stats`.
- [ ] I added the total, because ticket 3 uses it to pick the node size.

## 5. When something goes wrong

- [ ] A pod in `Pending` usually means the node lacks memory. `kubectl describe pod` shows the reason under Events.
- [ ] A pod in `CrashLoopBackOff` has a problem in the app itself. `kubectl logs <pod> -n srdp --previous` shows the log of the crashed attempt.
- [ ] `ImagePullBackOff` in kind means the image was not loaded, or the name in the chart differs from the name in `kind-load-images`.
- [ ] `CreateContainerConfigError` often means a Secret or key that the pod refers to does not exist.
- [ ] A missing database after a deploy means an old PVC survived. Run `just local-delete` and deploy again.
