# 02: DuckLake on object storage

**What to build:** with one setting, DuckLake writes its Parquet files to S3-compatible object storage instead of a local folder. Dagster and dbt write, and marimo, streamlit, the api and duckdb-ui read the same data back. This works in the Compose stack and in kind, against a local MinIO. Without that setting everything keeps working as it does today.

**Blocked by:** 01 (Chart parity and external secrets).

**Status:** ready-for-agent

- [ ] With `DUCKLAKE_STORAGE_BACKEND=s3` a Dagster run writes Parquet to the MinIO bucket.
- [ ] dbt models write to the same lake.
- [ ] All four apps read that data back, in Compose and in kind.
- [ ] With `DUCKLAKE_STORAGE_BACKEND=local` (the default) the stack behaves exactly as before.
- [ ] Unit tests cover building the S3 path and choosing between the backends.
- [ ] The correct DuckDB settings for Scaleway Object Storage are recorded in this ticket, checked against the official documentation.

## PRs

**PR 2a: `S3StorageBackend` with tests.**
This PR contains only Python code in `src/srdp`, namely the new backend, the extra settings, the function that selects the backend, and unit tests.
The default stays `local`, so nothing changes after the merge.
Put the verified DuckDB settings for Scaleway in the description, with a link to the documentation.
The reviewer focuses on the naming of the settings, because those names come back in Compose, the chart and Secret Manager.
This PR can start right away, in parallel with ticket 1.

**PR 2b: wire Compose, MinIO, dbt and the chart.**
This PR passes the new variables to the five DuckLake consumers in Compose and in the chart, adds MinIO as an optional service, and updates the dbt profile.
Test in Compose and in kind with `DUCKLAKE_STORAGE_BACKEND=s3`, and put a screenshot of the MinIO bucket in the description.
The reviewer checks that the stack works unchanged with `local`.
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
- Prepare the DuckDB connection by loading `httpfs` and creating the S3 secret.

### 3. Extend the settings

`DuckLakeSettings` currently reads all settings from environment variables starting with `DUCKLAKE_`.
Add a `storage_backend` choice (default `local`) and the fields for bucket, prefix, endpoint, region and keys.
Replace the spot that always creates a `LocalStorageBackend` with a small function that picks the right backend based on `storage_backend`.

### 4. Connect dbt

dbt writes to DuckLake through its own configuration in `projects/cbs-example/dbt/profiles.yml`.
Make that file read the same `DUCKLAKE_*` variables, so dbt writes to the same bucket as Dagster.

### 5. Connect Compose and the chart

`deploy/docker/docker-compose.yml` lists the `DUCKLAKE_*` variables explicitly per service.
So a new variable does not reach the containers by itself.
Add the new variables to all five DuckLake consumers (dagster-code, marimo, streamlit, api and duckdb-ui), and to `.env.example`.

Add MinIO as an optional Compose service, with a bucket that is created automatically.

Do the same in the chart.
Pass the variables to the same five apps, and read the keys from a Secret, as in ticket 1.

### 6. Tests

Write unit tests for building the S3 path and for choosing between the backends.
Follow the existing patterns in `tests/`.

## What you need to know or install first

- Ticket 1 must be done, so the chart can already read secrets from outside.
- Basic knowledge of DuckDB SQL helps with step 1.

## How to check that it works

Set `DUCKLAKE_STORAGE_BACKEND=s3` in `deploy/docker/.env`, start the stack with `just docker-up`, and start a Dagster run.
Then open the MinIO web interface and check that Parquet files are in the bucket.
Check in the four apps that they show the data.

Repeat this in kind with `just local-deploy`, with the same setting in `values-local.yaml`.

Set the value back to `local` and check that the stack still works as before.

## Pitfalls

- **Two catalogs.** The catalog lives in Postgres, the files in the bucket. If two environments (for example your laptop and the cloud) write to the same bucket and prefix, two catalogs both believe they own the files. Use a separate bucket or prefix per environment.
- **Downloading extensions.** `INSTALL httpfs` downloads the extension from the internet. In a container without internet access that fails. Check whether the image already ships the extension.
- **No extra Python packages.** DuckDB handles all S3 traffic itself through `httpfs`. Only add an extra dependency if it turns out to be really needed.
