# 07: On/off and reset

**What to build:** a colleague can switch the dev environment off with one command when nobody uses it, and on again with one command, after which all data is still there. A separate command tears the environment down completely and also cleans up the files in the bucket. A runbook describes all three, with the costs in each state.

**Blocked by:** 06 (A pipeline in the cloud).

**Status:** ready-for-agent

- [ ] `just dev-off` scales both node pools to zero. This recipe is built in this ticket.
- [ ] `just dev-on` scales them back, and after a few minutes everything works again with the same data and the same logins. This recipe is built in this ticket.
- [ ] `just dev-reset` tears down the spoke and empties the prefix in the bucket. This recipe is built in this ticket.
- [ ] All three commands have been tested at least once.
- [ ] `docs/05-deployment.md` describes switching on, switching off, resetting, and the costs in each state.
- [ ] The vision doc is updated under "Cloud infra" and in the tables about Kubernetes, the Helm chart and the Scaleway blueprint.

## PRs

**PR 7a: `dev-off`, `dev-on` and `dev-reset`.**
This PR adds the three recipes to the blueprint's `Justfile`.
Put the output of a full off-and-on cycle in the description, with proof that the data is still there.
The reviewer focuses on `dev-reset`, because it deletes data.
Check that it asks for confirmation, that it releases the load balancer first, and that it only empties the dev prefix.

**PR 7b: runbook and vision doc.**
This PR contains only documentation, namely the additions to `docs/05-deployment.md` and the updated lines in the vision doc.
Preferably ask a colleague who did not build the environment to review it by actually following the steps.
7b is blocked by 7a.

## Why this ticket

The environment costs about €35 to €55 per month when it is on.
Most of the time nobody uses it, so switching it off saves most of the cost.
When off, it still costs about €15 per month, mostly for the load balancer.

There are two ways to switch it off, and the difference matters.

- **Node pools to zero.** The cluster, the volumes, the bucket and the IP address stay. Only the machines disappear. When you switch on, Kubernetes reattaches the volumes, and all data is back.
- **Tear everything down.** Then the Postgres data disappears too, including the DuckLake catalog, the Zitadel users and the Dagster history. The Parquet files stay in the bucket, but no catalog knows about them any more. That is why a reset must also empty the bucket.

## What happens, step by step

### 1. Switching off and on

The number of nodes per pool is set in the blueprint's Terraform settings.
Build `dev-off` and `dev-on` in the blueprint's `Justfile`, so they set those numbers to zero or back to the normal value, and then run `apply`.
If you prefer the Scaleway CLI, `scw k8s pool update` does the same, but then the Terraform state falls behind.
Choose the Terraform route, so the state matches reality.

Test the following.

- Switch the environment off and check that no nodes remain.
- Switch it on again and wait until all pods are `Running`.
- Log in and check that the data from the last run is still there.

### 2. Resetting

A reset tears down the spoke with Terraform, and empties the DuckLake prefix in the bucket.
Take care of the following first.

- Kubernetes must release the load balancer before Terraform deletes the cluster, otherwise it gets stuck and the teardown fails. The old stack solved that by deleting the Traefik Service first and waiting a moment. Do the same here.
- Ask for confirmation, because a reset cannot be undone.

Test the reset once, fully, followed by rebuilding with tickets 3 to 6.
Record how long that takes.

### 3. Write the runbook

In `docs/05-deployment.md`, write for each of the three commands when you use it, what it does, how long it takes, and what it costs.
Also describe what to do when something goes wrong.

### 4. Update the vision doc

In `20260906_srdp-status-and-vision.md`, update the lines that still say "not started" or "not tested" about Kubernetes, the Helm chart and the Scaleway blueprint.

## What you need to know or install first

- Ticket 6 must be done, so there is real data to check after switching on.

## How to check that it works

After `just dev-off`, `kubectl get nodes` shows no nodes, and the website is unreachable.
After `just dev-on`, the nodes are back within a few minutes, and Dagster shows the runs from before switching off.
After a few days, Scaleway's billing shows the lower costs.

## Pitfalls

- **The load balancer stays.** Even with zero nodes you pay for the load balancer. That is the price of a fixed IP address, which keeps the nip.io names and the Zitadel settings valid.
- **Volumes and zones.** A Block Storage volume lives in one zone. If Scaleway creates the new node in another zone, the volume cannot attach. Keep the node pool in a single zone.
- **A reset without cleaning the bucket.** Then the bucket holds files no catalog knows about, and storage grows unnoticed.
