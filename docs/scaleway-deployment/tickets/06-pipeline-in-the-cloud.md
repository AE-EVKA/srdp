# 06: A pipeline in the cloud

**What to build:** a Dagster run started from the cloud UI writes Parquet to the dev Scaleway bucket. marimo, streamlit, the api and duckdb-ui read that data back, and the run's lineage appears in Marquez. This is the demo we show to customers.

**Blocked by:** 02 (DuckLake on object storage), 05 (Login via Zitadel).

**Issues:** Part of #37. This ticket delivers the working demo.

**Status:** ready-for-agent

- [ ] The DuckLake settings in the HelmRelease point to the dev bucket, with the keys from Secret Manager.
- [ ] The blueprint creates a second, read-only key for the lake prefix, and only Dagster gets the writer key.
- [ ] A Dagster run materializes the cbs-example assets.
- [ ] The run executes in its own pod on the compute pool, and that pool scales back to zero afterwards.
- [ ] The Parquet files are visible in the bucket in the Scaleway console.
- [ ] All four apps show the data.
- [ ] The run's lineage is in Marquez.
- [ ] The demo steps are briefly described in this ticket.

## PRs

**PR 6: DuckLake in the cloud writing to the bucket.**
This PR sets `ducklakeStorage.backend: s3` in the HelmRelease, fills in the bucket details, extends the blueprint with a read-only lakehouse key, adds the ExternalSecrets for the reader and writer keys, and sends Dagster runs to the compute pool.
It is a small PR, but it deploys on merge.
After the rollout, paste screenshots of the successful run in Dagster, of the files in the bucket, and of the lineage in Marquez as a comment on the PR.
The demo description can go in the same PR, as a short text in the ticket.
This PR is blocked by 2b and 5b.

## Why this ticket

So far the apps are online, but no data flows through them.
This ticket brings ticket 2 (the S3 backend) and ticket 5 (the online stack) together.
Once this works, you have a complete proof of concept in the cloud.

It is also the first time the `K8sRunLauncher` does real work.
It starts a separate pod for every Dagster run.
In the blueprint such a pod lands on the compute pool, which starts a heavy node for it and removes it again afterwards.

## What happens, step by step

### 1. Point DuckLake at the bucket

The blueprint has created a lakehouse bucket, and keys that may read and write there.
Those keys live in Secret Manager as `srdp-dev-lakehouse-access-key` and `srdp-dev-lakehouse-secret-key`.

- Set `ducklakeStorage.backend` to `s3` in the HelmRelease values.
- Fill in `ducklakeStorage.s3`: the bucket name, a prefix per environment, the endpoint and the region.
- Have External Secrets create `srdp-ducklake-s3-writer` and `srdp-ducklake-s3-reader`, each with the keys `DUCKLAKE_S3_KEY_ID` and `DUCKLAKE_S3_SECRET`.
  The chart has read these names since ticket 2.

Ticket 2 splits the keys into a writer pair and a reader pair, following #56.
The blueprint only creates the writer pair so far.
Add a second IAM application with a read-only key, and scope it to the lake prefix with a bucket policy.
Store it in Secret Manager next to the writer key, for example as `srdp-dev-lakehouse-reader-access-key` and `srdp-dev-lakehouse-reader-secret-key`.
Check in the Scaleway documentation how a bucket policy limits an IAM application to one prefix.
This also covers part of #43, which asks to scope the lakehouse key instead of `ObjectStorageFullAccess`.

### 2. Send runs to the compute pool

A Dagster run should execute on the compute pool, so the system pool can stay small.
Kubernetes picks the node based on labels and *tolerations* in the pod settings.
Look up in the blueprint which labels and taints the compute pool has, and give Dagster's run pods those settings.

The first run takes longer, because Scaleway has to start a node first.
Expect a few minutes.

### 3. Start a run and check

Open Dagster at `https://dagster.<LB_IP>.nip.io`, start a cbs-example run, and then check everything.

- The Scaleway console shows new Parquet files in the bucket.
- marimo, streamlit, the api and duckdb-ui show the new data.
- Marquez shows the run with its inputs and outputs.

### 4. Describe the demo

Write in this ticket, in a few steps, how to show the demo to a customer.
Describe which run you start, which app you open next, and what you point out.

## What you need to know or install first

- Tickets 2 and 5 must be done.
- The POP2 quota from ticket 3 must be approved, otherwise the compute pool cannot start a node.

## How to check that it works

```bash
kubectl get pods -n srdp -w
kubectl get nodes -w
```

While the run is in progress, you see a new node appear and a pod for the run.
Afterwards the pod disappears, and after a while the node does too.
In the Dagster UI the run has status `Success`.

## Pitfalls

- **The run stays `Pending`.** The pod finds no matching node. Check the labels and tolerations, and whether the POP2 quota has been approved.
- **A wrong endpoint.** A mistake in the endpoint or region gives a connection error in the run's logs. Compare with the settings you recorded in ticket 2.
- **The compute node stays around.** The autoscaler waits a while before it removes an empty node. If the node is still there after half an hour, check whether a pod is still running on it.
- **One run at a time.** Since ticket 1, Dagster runs at most one run at a time. A second run waits in the queue, which is intended.
