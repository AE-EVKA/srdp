# 01: Chart parity and external secrets

**What to build:** the full SRDP stack runs in a local kind cluster, with the same services as the Docker Compose stack. Every password and key comes from a Kubernetes Secret created outside the chart. Locally everything keeps working as it does today.

**Blocked by:** None (can start immediately).

**Issues:** Related to #60, which is leading for database creation. #60 also closes #57. This ticket only brings the chart's init script in line with it.

**Status:** ready-for-agent

- [ ] `just local-deploy` brings up the whole stack in kind, including streamlit.
- [ ] All hostnames load behind the Zitadel login on `https://*.srdp.localhost:18443`.
- [ ] A Dagster run materializes assets, and the apps read that data back.
- [ ] The chart no longer contains any password as a plain value in `values.yaml`. For kind the development values live in `values-local.yaml`.
- [ ] The registry of all SRDP images can be changed with a single value.
- [ ] Dagster runs at most one run at a time.
- [ ] The memory usage of every pod is recorded in this ticket.

## PRs

**PR 1a: chart matches Compose.**
This PR adds streamlit, makes the chart's Postgres init script create all four databases, fixes the Dagster module path, and sets the run coordinator to one run at a time.
It does not touch secrets.
Test with `just local-deploy`, and put the output of `kubectl get pods -n srdp` and a screenshot of streamlit behind the login in the description.
The reviewer focuses on the init script, because a mistake there only shows up on an empty database.

**PR 1b: secrets and registry from outside the chart.**
This PR removes all passwords from `values.yaml`, makes the apps read them from Secrets, and makes the registry configurable.
For kind a local template creates the Secrets.
Put a table of every secret name and key in the description, because ticket 4 builds on it.
The reviewer uses `helm template` to check that no password remains in the rendered templates, and that kind still works.

1b is blocked by 1a, because both touch the same templates.

## Why this ticket

The Helm chart describes the stack for Kubernetes, and it lags behind the Compose stack.
Anything missing or wrong in the chart will also go wrong in the cloud.
Finding such a mistake in kind costs nothing.
In the cloud it costs money and time.

This ticket also prepares the ground (a prefactor) for later tickets.
In the cloud the passwords come from Scaleway Secret Manager, and the images come from a registry with a different name.
If the chart supports that from now on, later tickets only have to fill in the right values.

Read the sections on pods, Deployments, Services, Secrets and Helm in the [Kubernetes primer](../kubernetes-primer.md) before you start.

## What happens, step by step

### 1. Install kind and look at the current state

Install kind with `brew install kind`.
Give Docker Desktop at least 8 GB of memory, under Settings, Resources.
Then run `just kind-up` and `just local-tls`.

Run `just local-deploy` once before changing anything, and use `kubectl get pods -n srdp` to see what goes wrong.
That way you know what was broken at the start, and you recognise later what you fixed.

### 2. Add streamlit

The Compose stack has a streamlit app, but the chart does not.
You add three things.

- A template for streamlit (a Deployment and a Service), modelled on the api template.
- A `streamlit:` block in `values.yaml` with the image name.
- An Ingress rule, so `streamlit.<domain>` is reachable behind the login, next to the other apps.

Also add streamlit to the `kind-load-images` recipe in the `Justfile`, so its image ends up in kind.

### 3. Create all databases

Postgres creates databases on first start through an init script.
In the chart that script currently only creates the `dagster` database.
The chart needs four: `zitadel`, `dagster`, `marquez` and `ducklake`.
Issue #60 is leading here.
Its setup service replaces `deploy/docker/initdb/` in Compose and adds a repair Job in Kubernetes, but it keeps the chart's init script as the source for a fresh install.
So this ticket only extends the chart's init script to all four databases and users, and does not touch Compose.
Use the database and role names from the #60 setup service, so both create exactly the same thing.
If the #60 work has landed first, check whether its PR already extended the init script.

An init script only runs against an empty database.
If you deployed before, remove the old storage with `just local-delete` before deploying again.

### 4. Fix the Dagster module path

The chart tells Dagster that the pipeline code lives in the `definitions` module.
In Compose it is `etl.definitions`.
With the wrong path the Dagster code location does not start, and the Dagster UI shows no assets.

### 5. At most one run at a time

The chart uses the `K8sRunLauncher`, which starts every Dagster run in its own pod.
Locally in Compose everything ran in one container, so two runs never wrote to DuckLake at the same time.
We do not know yet whether DuckLake safely handles two concurrent writers.
So configure Dagster's run coordinator for at most one concurrent run.
That is a single setting in the Dagster block of the values.

### 6. Secrets from outside the chart

Look in `values.yaml` for every place with a password or key, for example `srdpTest123`, the Zitadel master key, the oauth2-proxy client secret and the oauth2-proxy cookie secret.
Make every app read that value from an existing Kubernetes Secret with a fixed name.
Most dependency charts have an option for this called `existingSecret`.
For our own templates you use `secretKeyRef` in the environment variables.

For kind someone has to create those Secrets.
The simplest approach is a small template that only renders when a local toggle is on, filled with the development values from `values-local.yaml`.
In the cloud that toggle is off, and External Secrets creates the Secrets (ticket 4).

Write the secret names and keys down in this ticket, because ticket 4 needs exactly those names.

### 7. Make the registry configurable

All SRDP images are currently hardcoded as `rg.nl-ams.scw.cloud/srdp-registry/...`.
The registry in the blueprint's hub gets a name that depends on your organisation prefix.
Turn the registry prefix into one value (for example `global.imageRegistry`) that every image reference uses.
Also add an `imagePullSecrets` option, so the nodes in the cloud can pull images with a key.

### 8. Measure memory usage

Once everything runs, record how much memory each pod uses.
Without a metrics server in kind you can use `docker stats` on the kind node, or temporarily set low `resources` limits per pod and see what crashes.
Ticket 3 uses this number to choose the node size in the cloud.

## What you need to know or install first

- `kind`, `kubectl`, `helm` and `mkcert`.
- Docker Desktop with at least 8 GB of memory.
- The Compose stack uses ports 80 and 443. kind uses 18080 and 18443, so both can run side by side.

## How to check that it works

```bash
just local-deploy
kubectl get pods -n srdp
```

You expect only pods with status `Running` or `Completed`.
Then open `https://srdp.localhost:18443` in your browser.
You are redirected to Zitadel, and after logging in you see the hub page.
Start a run in Dagster and check in marimo, streamlit, the api and duckdb-ui that the data is visible.

`helm template` shows the YAML Helm produces without installing anything.
Search it for `srdpTest123`, `masterkey`, `clientSecret` and `cookieSecret` to check that no password or key remains in the regular templates.

## Pitfalls

- **oauth2-proxy and Traefik.** The `local-deploy` recipe runs `helm upgrade` twice, because oauth2-proxy needs to know Traefik's IP address inside the cluster. Do not remove that second step.
- **Old volumes.** After changing the init script you must delete the PVCs with `just local-delete`, otherwise the script does not run again.
- **Memory.** If pods stay `Pending`, the kind node lacks memory. Give Docker Desktop more memory.
- **Building images takes time.** `kind-load-images` rebuilds every image. If you only change the chart, `helm upgrade` is enough.
