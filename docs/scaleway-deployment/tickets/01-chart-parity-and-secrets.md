# 01: Chart parity and external secrets

**What to build:** the full SRDP stack runs in a local kind cluster, with the same services as the Docker Compose stack. Every password and key comes from a Kubernetes Secret created outside the chart. Locally everything keeps working as it does today.

**Blocked by:** None (can start immediately).

**Issues:** Closes #66. Related to #60, which is leading for database creation. Its database bootstrap landed in #64, which also closes #57. This ticket only checks that the chart's setup Job covers all four databases.

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
This PR adds streamlit, checks that the setup Job creates all four databases, fixes the Dagster module path, and sets the run coordinator to one run at a time.
It does not touch secrets.
Test with `just local-deploy`, and put the output of `kubectl get pods -n srdp` and a screenshot of streamlit behind the login in the description.
The reviewer focuses on the database list in `setup.databases`, because a missing entry only shows up as a pod that waits forever.

**PR 1b: secrets and registry from outside the chart.**
This PR removes all passwords from `values.yaml`, makes the apps read them from Secrets, and makes the registry configurable.
For kind a local template creates the Secrets.
If [ticket 0](00-secrets-out-of-git.md) has landed, this PR also removes its gitleaks allowlist for `values.yaml`.
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

The chart has no Postgres init script any more.
Since #64 the setup Job (`templates/setup-job.yaml`) creates every database and role from `setup.databases` in `values.yaml`, on a fresh install and on an existing volume alike.
It runs on every `helm install` and `helm upgrade`, so no `just local-delete` is needed to pick up a change.
Each app that uses a database waits in a `wait-for-*-db` init container until its database exists.

The chart needs four databases: `zitadel`, `dagster`, `marquez` and `ducklake`.
Check that `setup.databases` lists all four.
The `zitadel` entry is disabled on purpose, because the Bitnami `zitadel-db` subchart already creates that role and database through its `auth.*` values.
Only add an entry if a new service needs its own database.

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
#64 added two more: `marquez.dbPassword`, and the `SETUP_PASSWORDS__<ROLE>` environment variables of the setup Job, one per role in `setup.databases`.
The setup Job and Marquez must read the same Secret key for the Marquez password, otherwise the Job resets the role to a value Marquez does not know.
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

## Results

### Memory usage per pod

Measured on 2026-09-30 in kind with `crictl stats` on the node, after a successful `srdp_etl_job` run.
The values are the working set in MiB, with the stack idle.

| Pod | Memory (MiB) |
|:---|---:|
| dagster-daemon | 1167 |
| dagster-webserver | 992 |
| dagster-webserver-read-only | 971 |
| marquez | 549 |
| dagster-user-deployments-srdp-etl | 239 |
| db-postgresql | 121 |
| marquez-web | 113 |
| duckdb-ui | 113 |
| api | 101 |
| zitadel | 95 |
| zitadel-login | 85 |
| marimo | 63 |
| streamlit | 57 |
| traefik | 42 |
| oauth2-proxy | 7 |
| hub | 5 |
| **Total** | **4718** |

A Dagster run pod comes on top of this total.
A full `srdp_etl_job` run peaks at about 1030 MiB.
The old run limit of 512Mi in `src/srdp/resources/k8s.py` got every run OOMKilled, so the base profile now requests 512Mi with a limit of 1536Mi.
The Bitnami default limit of 192Mi also got Postgres OOMKilled, so `zitadel-db.primary.resources` now sets a limit of 1Gi.
Ticket 3 should therefore plan for at least 6 GiB of allocatable memory, before any headroom.

### Secret names and keys

Ticket 4 creates these Secrets with External Secrets.
In kind, `templates/local-secrets.yaml` creates them from `localSecrets` in `values-local.yaml`.

| Secret | Key | Read by |
|:---|:---|:---|
| `srdp-postgres` | `postgres-password` | zitadel-db, srdp-setup, every DuckLake client and `wait-for-*-db` init container |
| `srdp-postgres` | `password` | zitadel-db (zitadel user) |
| `srdp-postgres` | `replication-password` | zitadel-db, only with `architecture: replication` |
| `srdp-zitadel` | `masterkey` | Zitadel, exactly 32 characters |
| `srdp-zitadel` | `config-yaml` | Zitadel, a config fragment with both database passwords and `FirstInstance.Org.Human.Password` |
| `srdp-oauth2-proxy` | `client-id`, `client-secret`, `cookie-secret` | oauth2-proxy |
| `srdp-dagster-postgresql` | `postgresql-password` | Dagster webserver, daemon, code location, run pods and srdp-setup |
| `srdp-marquez` | `db-password` | Marquez and srdp-setup |
| `srdp-ducklake-s3-writer` | `DUCKLAKE_S3_KEY_ID`, `DUCKLAKE_S3_SECRET` | Dagster code location and run pods, only with `ducklakeStorage.backend: s3` (added in ticket 2) |
| `srdp-ducklake-s3-reader` | `DUCKLAKE_S3_KEY_ID`, `DUCKLAKE_S3_SECRET` | marimo, streamlit, api and duckdb-ui, only with `ducklakeStorage.backend: s3` (added in ticket 2) |

The two database passwords inside `config-yaml` must equal `password` and `postgres-password` in `srdp-postgres`.

### Registry

`global.srdpRegistry` prefixes every image the chart's own templates use.
The Dagster code location image is a value of the Dagster subchart, which the chart cannot template.
The `registry` variable in the `Justfile` therefore sets both `global.srdpRegistry` and that repository.
A cloud values file sets both as well, next to `global.imagePullSecrets`.

### Findings from the kind run

- The Dagster module path was already `etl.definitions`, so step 4 needed no change.
- `setup.databases` already lists all four databases, with `zitadel` disabled on purpose.
- A run pod writes its Parquet files inside its own container unless it shares a volume with the apps.
  The chart now has a `ducklake-data` volume, mounted read-write in the code location and its run pods and read-only in the apps.
  It is `ReadWriteOnce`, which works on a single kind node.
  A multi-node cluster needs `ReadWriteMany` or object storage.
- The login redirect points at `https://auth.srdp.localhost` without the `:18443` port, because Zitadel has `ExternalPort: 443`.
  That behaviour predates this ticket.

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
- **A pod stuck in `Init`.** A `wait-for-*-db` init container waits until the setup Job has created its database. Check the Job log with `kubectl logs job/srdp-setup -n srdp`. A missing password makes the Job fail before it creates anything.
- **Memory.** If pods stay `Pending`, the kind node lacks memory. Give Docker Desktop more memory.
- **Building images takes time.** `kind-load-images` rebuilds every image. If you only change the chart, `helm upgrade` is enough.
