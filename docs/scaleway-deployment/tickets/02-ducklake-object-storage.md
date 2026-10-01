# 02: DuckLake on object storage

**What to build:** with one setting, DuckLake writes its Parquet files to S3-compatible object storage instead of a local folder. Dagster and dbt write with a writer key, and marimo, streamlit, the api and duckdb-ui read the same data back with a read-only key. This works in the Compose stack and in kind, against a local Garage server. Without that setting everything keeps working as it does today.

**Blocked by:** 01 (Chart parity and external secrets).

**Issues:** #56, which is leading for the design. It asks for non-AWS endpoints as a first-class case, separate read-only and writer credentials, and one implementation instead of three per consumer. PR 2a references it with `Part of #56`. Only PR 2b says `Closes #56`, because the issue is solved once the consumers use the backend.

**Status:** ready-for-agent

- [ ] With `DUCKLAKE_STORAGE_BACKEND=s3` a Dagster run writes Parquet to the Garage bucket.
- [ ] dbt models write to the same lake.
- [ ] All four apps read that data back, in Compose and in kind.
- [ ] With `DUCKLAKE_STORAGE_BACKEND=local` (the default) the stack behaves exactly as before.
- [ ] Unit tests cover building the S3 path and choosing between the backends.
- [ ] The query-serving apps hold only a read-only key, scoped to the lake. Only the Dagster code server and dbt hold the writer key, plus the local Garage setup step that imports it.
  Garage scopes a key to a bucket, so locally the lake has its own bucket; in the cloud a bucket policy scopes the key to the lake prefix (ticket 6).
- [ ] A write from duckdb-ui to the bucket fails with an access error.
- [ ] The DuckDB secret and the dbt connection get their S3 settings and data path from the backend, not from their own copy. `profiles.yml` contains no endpoint, URL style, key or bucket.
- [ ] The dlt helper is covered by a unit test. This repo has no dlt pipeline, so the helper is used downstream, and the PR description says so.
- [ ] The correct DuckDB settings for Scaleway Object Storage are recorded in this ticket, checked against the official documentation.

## PRs

**PR 2a: `S3StorageBackend` with tests.**
This PR contains only Python code in `src/srdp`, namely the new backend, the extra settings, the function that selects the backend, the dlt helper, the dbt-duckdb plugin from step 4, and unit tests.
The default stays `local`, so nothing changes after the merge.
The description says `Part of #56`, so merging 2a does not close the issue.
Put the verified DuckDB settings for Scaleway in the description, with a link to the documentation.
The reviewer focuses on the naming of the settings, because those names come back in Compose, the chart and Secret Manager.
This PR can start right away, in parallel with ticket 1.

**PR 2b: wire Compose, Garage, dbt and the chart.**
This PR passes the new variables to the five DuckLake consumers in Compose and in the chart, adds Garage as an optional service with a reader and a writer key, and switches the dbt profile to the plugin from 2a.
The writers get the writer key, and the four apps get the reader key.
The description says `Closes #56`.
Test in Compose and in kind with `DUCKLAKE_STORAGE_BACKEND=s3`, and put the list of Parquet files in the Garage bucket in the description.
The reviewer checks that the stack works unchanged with `local`, and that no read-only app has the writer key in its environment.
2b is blocked by 1b and 2a.

## Why this ticket

DuckLake has two parts.
The catalog lives in Postgres and tracks which tables and versions exist.
The data itself lives as Parquet files in a folder.

In Compose five containers share one Docker volume for that folder.
One container writes and four read.
In Kubernetes those apps run in separate pods, possibly on different nodes.
A regular disk can only be attached to one node at a time, so that no longer works.
Object storage (a bucket) can be read and written by everyone at once over the network, which is why it is the standard solution.

The code already has an abstraction for this, `StorageBackend` in `src/srdp/io/storage.py`.
Only the local variant exists so far.
This ticket adds the S3 variant.

Issue #56 adds a security reason.
With data on a local volume, a query connection can be sandboxed with `enable_external_access=false`.
With data in a bucket it cannot, because DuckDB needs network access to read Parquet through `httpfs`.
So every SQL query runs with the full authority of the container's S3 key.
A SQL console like duckdb-ui must therefore hold a key that can only read, and only the lake prefix.

#56 also found that downstream projects implement the S3 configuration three times: a DuckDB `CREATE SECRET`, a `secrets:` block in the dbt profile, and a dlt `FilesystemConfiguration`.
The backend becomes the one place that knows the endpoint, the URL style and the keys, and the three consumers ask it.

This is the riskiest new code in the whole plan.
That is why we test it locally against Garage, a free S3 server in a container, before anything happens in the cloud.
The plan first named MinIO, but MinIO stopped publishing its Docker images, so PR 2b switched to Garage.

## What happens, step by step

### 1. Work out the DuckDB settings

DuckDB talks to object storage through the `httpfs` extension and a `SECRET` of type `s3`.
Look up in the official DuckDB documentation which fields a non-AWS S3-compatible provider needs.
These answers were checked against the official documentation during PR 2a.

- `ENDPOINT` takes a bare `host` or `host:port` without a scheme, and `USE_SSL` picks HTTPS or HTTP.
  Every example in the [DuckDB S3 API docs](https://duckdb.org/docs/current/core_extensions/httpfs/s3api.html) is scheme-less, for example `ENDPOINT 'seaweedfs-host:8333', USE_SSL false`.
- `URL_STYLE` defaults to `vhost` for `TYPE s3`, also with a custom `ENDPOINT`.
  [Scaleway](https://www.scaleway.com/en/docs/object-storage/concepts/) accepts both styles.
  A bucket name with a dot needs `path`, because the wildcard certificate `*.s3.nl-ams.scw.cloud` does not cover it ([FAQ](https://www.scaleway.com/en/docs/object-storage/faq/)).
- `REGION` defaults to `us-east-1` and is used to sign requests.
  Scaleway signs with the region slug, for example `nl-ams` ([signature docs](https://www.scaleway.com/en/docs/object-storage/api-cli/generate-aws4-auth-signature/)).
- Garage, the local test server, uses `path` style and signs with the region in its `s3_region` setting, `garage` in this repo.
- From a Private Network, Kapsule can use the private endpoint `s3-vpc.<region>.scw.eu` instead of the public one ([docs](https://www.scaleway.com/en/docs/object-storage/how-to/use-obj-stor-with-private-networks/)).
  Ticket 6 decides which one to use.

| Setting | Scaleway (nl-ams) | Garage in Compose and kind |
|:---|:---|:---|
| `DUCKLAKE_S3_ENDPOINT` | `s3.nl-ams.scw.cloud` | `garage:3900` |
| `DUCKLAKE_S3_URL_STYLE` | `vhost` (or `path` for a dotted bucket name) | `path` |
| `DUCKLAKE_S3_REGION` | `nl-ams` | `garage` |
| `DUCKLAKE_S3_USE_SSL` | `true` | `false` |

### 2. Write the S3 backend

Create an `S3StorageBackend` next to the existing `LocalStorageBackend` in `src/srdp/io/ducklake.py`.
It does two things.

- Return the base path, in the form `s3://<bucket>/<prefix>/`.
- Prepare the DuckDB connection by loading `httpfs` and creating an S3 secret scoped to the lake root.

Treat `ENDPOINT`, `URL_STYLE` and `REGION` as required settings, as #56 asks, and do not fall back to AWS defaults.
An empty value counts as missing, because Compose turns an unset `${VAR:-}` into an empty string.
Refuse an endpoint with a scheme, because DuckDB would build a broken URL from it.
Add a small helper that renders the same settings for dlt, so a downstream dlt pipeline does not build its own.
dbt gets its settings through a plugin instead of a helper, see step 4.

### 3. Extend the settings

`DuckLakeSettings` currently reads all settings from environment variables starting with `DUCKLAKE_`.
Add a `storage_backend` choice (default `local`) to it.
Keep it for the Postgres catalog and the storage choice, so it stays clear which setting belongs to which part.
Put the S3 fields in a separate `S3StorageSettings` with the prefix `DUCKLAKE_S3_`: bucket, prefix, endpoint, URL style, region, `use_ssl` and one key pair.
It is only read when `storage_backend` is `s3`, so its fields can be truly required.
Its validation errors must not print the values they were given, because they end up in the logs.
Each process gets exactly one key pair, `DUCKLAKE_S3_KEY_ID` and `DUCKLAKE_S3_SECRET`.
The deploy configuration decides whether that is the reader or the writer key.
So no container holds both keys, and there is no role setting that could disagree with the key.
Two places always create a `LocalStorageBackend`, in `create_connection()` and in `setup_ducklake()`.
Replace both with a small function that picks the right backend based on `storage_backend`.

### 4. Connect dbt

dbt writes to DuckLake through its own configuration in `projects/cbs-example/dbt/profiles.yml`.
If that file read the S3 variables itself with `env_var()`, the endpoint, URL style and keys would be handled a second time in YAML, which is the duplication #56 wants to remove.
So dbt asks the backend instead, through a dbt-duckdb plugin.

A dbt-duckdb plugin is a Python module with a class named `Plugin` that subclasses `dbt.adapters.duckdb.plugins.BasePlugin`.
Its `configure_connection(conn)` hook runs on every new connection, after the extensions and before the `attach:` entries from the profile.
Put the plugin in `src/srdp` and let that hook select the backend and call `configure_duckdb(conn)` on it.
Reference it in the profile under `plugins:` by its module path.

The `data_path` in the profile must also come from the backend, because for S3 it is `s3://<bucket>/<prefix>/`.
The simplest way is for the plugin to run the same `ATTACH` that `create_connection()` runs, and to drop the `attach:` block from the profile.
PR 2a checked this with a real `dbt run`: dbt resolves the `ducklake` database when the plugin attaches it.
After this change `profiles.yml` contains no endpoint, URL style, key, bucket or data path.

### 5. Connect Compose and the chart

`deploy/docker/docker-compose.yml` lists the `DUCKLAKE_*` variables explicitly per service.
So a new variable does not reach the containers by itself.
Add the new variables to all five DuckLake consumers (dagster-code, marimo, streamlit, api and duckdb-ui), and to `.env.example`.

Add Garage as an optional Compose service in an `s3` profile, with a bucket that is created automatically.
A setup step imports two keys.
The writer may read and write the bucket, and the reader may only read it.
Garage grants rights per bucket, not per prefix, so the lake gets its own bucket.
The Garage image has no shell, so the setup talks to Garage's admin API from `src/srdp/setup/garage.py`.
Give dagster-code the writer pair as `DUCKLAKE_S3_KEY_ID` and `DUCKLAKE_S3_SECRET`, and the other four the reader pair under the same names.
The keys are secrets, so they follow [ADR-0010](../../adr/0010-secret-management.md).

Do the same in the chart.
A `ducklakeStorage` block in `values.yaml` renders one `srdp-ducklake-storage` ConfigMap that all five consumers read.
The keys come from two Secrets, `srdp-ducklake-s3-writer` for Dagster and its run pods and `srdp-ducklake-s3-reader` for the apps.
`values-local-s3.yaml` switches kind to S3 and turns on the bundled Garage.

### 6. Tests

Write unit tests for building the S3 path, for choosing between the backends, for refusing incomplete S3 settings, and for the output of the dlt helper.
Test that the dbt plugin creates the S3 secret on a connection when `storage_backend` is `s3`.
Follow the existing patterns in `tests/`.

## What you need to know or install first

- Ticket 1 must be done, so the chart can already read secrets from outside.
- Basic knowledge of DuckDB SQL helps with step 1.

## How to check that it works

Set `COMPOSE_PROFILES=s3` and `DUCKLAKE_STORAGE_BACKEND=s3` in `deploy/docker/.env`, fill in the writer and reader key and Garage's own `GARAGE_RPC_SECRET` and `GARAGE_ADMIN_TOKEN` (see `.env.example`), start the stack with `just docker-up`, and start a Dagster run.
Then list the bucket with the writer key and check that Parquet files are in it.
Check in the four apps that they show the data.
In duckdb-ui, try `COPY (SELECT 1) TO 's3://<bucket>/<prefix>/test.parquet'` and check that it fails with an access error.

Repeat this in kind with `just local-deploy -f srdp-chart/values-local-s3.yaml`.

Set the value back to `local` and check that the stack still works as before.

## Pitfalls

- **Two catalogs.** The catalog lives in Postgres, the files in the bucket. If two environments (for example your laptop and the cloud) write to the same bucket and prefix, two catalogs both believe they own the files. Use a separate bucket or prefix per environment.
- **Downloading extensions.** `INSTALL httpfs` downloads the extension from the internet. In a container without internet access that fails. Check whether the image already ships the extension.
- **The writer key leaking into a reader.** Compose and the chart pass variables per service. Check each service, because one copy-paste gives a SQL console write access to the lake.
- **No extra Python packages.** DuckDB handles all S3 traffic itself through `httpfs`. Only add an extra dependency if it turns out to be really needed.
