# 02: DuckLake on object storage

**What to build:** with one setting, DuckLake writes its Parquet files to S3-compatible object storage instead of a local folder. Dagster and dbt write with a writer key, and marimo, streamlit, the api and duckdb-ui read the same data back with a read-only key. This works in the Compose stack and in kind, against a local MinIO. Without that setting everything keeps working as it does today.

**Blocked by:** 01 (Chart parity and external secrets).

**Issues:** #56, which is leading for the design. It asks for non-AWS endpoints as a first-class case, separate read-only and writer credentials, and one implementation instead of three per consumer. PR 2a references it with `Part of #56`. Only PR 2b says `Closes #56`, because the issue is solved once the consumers use the backend.

**Status:** ready-for-agent

- [ ] With `DUCKLAKE_STORAGE_BACKEND=s3` a Dagster run writes Parquet to the MinIO bucket.
- [ ] dbt models write to the same lake.
- [ ] All four apps read that data back, in Compose and in kind.
- [ ] With `DUCKLAKE_STORAGE_BACKEND=local` (the default) the stack behaves exactly as before.
- [ ] Unit tests cover building the S3 path and choosing between the backends.
- [ ] The query-serving apps hold only a read-only key, scoped to the lake prefix. Only the Dagster code server and dbt hold the writer key.
- [ ] A write from duckdb-ui to the bucket fails with an access error.
- [ ] The DuckDB secret and the dbt connection get their S3 settings and data path from the backend, not from their own copy. `profiles.yml` contains no endpoint, URL style, key or bucket.
- [ ] The dlt helper is covered by a unit test. This repo has no dlt pipeline, so the helper is used downstream, and the PR description says so.
- [ ] The correct DuckDB settings for Scaleway Object Storage are recorded in this ticket, checked against the official documentation.

## PRs

**PR 2a: `S3StorageBackend` with tests.**
This PR contains only Python code in `src/srdp`, namely the new backend, the extra settings with a separate reader and writer key, the function that selects the backend, the dlt helper, the dbt-duckdb plugin from step 4, and unit tests.
The default stays `local`, so nothing changes after the merge.
The description says `Part of #56`, so merging 2a does not close the issue.
Put the verified DuckDB settings for Scaleway in the description, with a link to the documentation.
The reviewer focuses on the naming of the settings, because those names come back in Compose, the chart and Secret Manager.
This PR can start right away, in parallel with ticket 1.

**PR 2b: wire Compose, MinIO, dbt and the chart.**
This PR passes the new variables to the five DuckLake consumers in Compose and in the chart, adds MinIO as an optional service with a reader and a writer user, and switches the dbt profile to the plugin from 2a.
The writers get the writer key, and the four apps get the reader key.
The description says `Closes #56`.
Test in Compose and in kind with `DUCKLAKE_STORAGE_BACKEND=s3`, and put a screenshot of the MinIO bucket in the description.
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
That is why we test it locally against MinIO, a free S3 server in a container, before anything happens in the cloud.

## What happens, step by step

### 1. Work out the DuckDB settings

DuckDB talks to object storage through the `httpfs` extension and a `SECRET` of type `s3`.
Look up in the official DuckDB documentation which fields a non-AWS S3-compatible provider needs.
Answer these questions in particular, and write the answers in this ticket.

- Does `ENDPOINT` expect a bare hostname such as `s3.nl-ams.scw.cloud`, or a full URL?
- Which `URL_STYLE` does Scaleway need, `path` or `vhost`?
- Which `REGION` goes with it, and does MinIO work with the same settings?

### 2. Write the S3 backend

Create an `S3StorageBackend` next to the existing `LocalStorageBackend` in `src/srdp/io/ducklake.py`.
It does two things.

- Return the base path, in the form `s3://<bucket>/<prefix>/`.
- Prepare the DuckDB connection by loading `httpfs` and creating the S3 secret, with the reader or the writer key depending on the role of the connection.

Treat `ENDPOINT` and `URL_STYLE` as required settings, as #56 asks, and do not fall back to AWS defaults.
Add a small helper that renders the same settings for dlt, so a downstream dlt pipeline does not build its own.
dbt gets its settings through a plugin instead of a helper, see step 4.

### 3. Extend the settings

`DuckLakeSettings` currently reads all settings from environment variables starting with `DUCKLAKE_`.
Add a `storage_backend` choice (default `local`) and the fields for bucket, prefix, endpoint, URL style and region.
Add two key pairs, a writer pair and a reader pair, and a setting for which role the process has.
A process with the reader role must not need the writer key to start.
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
Check that dbt still resolves the `ducklake` database when the plugin attaches it.
After this change `profiles.yml` contains no endpoint, URL style, key, bucket or data path.

### 5. Connect Compose and the chart

`deploy/docker/docker-compose.yml` lists the `DUCKLAKE_*` variables explicitly per service.
So a new variable does not reach the containers by itself.
Add the new variables to all five DuckLake consumers (dagster-code, marimo, streamlit, api and duckdb-ui), and to `.env.example`.

Add MinIO as an optional Compose service, with a bucket that is created automatically.
Create two MinIO users with a policy each: a writer that may read and write the lake prefix, and a reader that may only read it.
Give dagster-code the writer key and the other four the reader key.
The keys are secrets, so they follow [ADR-0010](../../adr/0010-secret-management.md).

Do the same in the chart.
Pass the variables to the same five apps, and read the keys from a Secret, as in ticket 1.

### 6. Tests

Write unit tests for building the S3 path, for choosing between the backends, for picking the reader or writer key by role, and for the output of the dlt helper.
Test that the dbt plugin creates the S3 secret on a connection when `storage_backend` is `s3`.
Follow the existing patterns in `tests/`.

## What you need to know or install first

- Ticket 1 must be done, so the chart can already read secrets from outside.
- Basic knowledge of DuckDB SQL helps with step 1.

## How to check that it works

Set `DUCKLAKE_STORAGE_BACKEND=s3` in `deploy/docker/.env`, start the stack with `just docker-up`, and start a Dagster run.
Then open the MinIO web interface and check that Parquet files are in the bucket.
Check in the four apps that they show the data.
In duckdb-ui, try `COPY (SELECT 1) TO 's3://<bucket>/<prefix>/test.parquet'` and check that it fails with an access error.

Repeat this in kind with `just local-deploy`, with the same setting in `values-local.yaml`.

Set the value back to `local` and check that the stack still works as before.

## Pitfalls

- **Two catalogs.** The catalog lives in Postgres, the files in the bucket. If two environments (for example your laptop and the cloud) write to the same bucket and prefix, two catalogs both believe they own the files. Use a separate bucket or prefix per environment.
- **Downloading extensions.** `INSTALL httpfs` downloads the extension from the internet. In a container without internet access that fails. Check whether the image already ships the extension.
- **The writer key leaking into a reader.** Compose and the chart pass variables per service. Check each service, because one copy-paste gives a SQL console write access to the lake.
- **No extra Python packages.** DuckDB handles all S3 traffic itself through `httpfs`. Only add an extra dependency if it turns out to be really needed.
