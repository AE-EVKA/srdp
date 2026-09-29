# 08: Add an environment

**What to build:** a tested checklist that lets someone set up a new environment, such as `stage` or `prod`, next to `dev` without having to work things out again. The checklist lives in the runbook and has been followed at least once.

**Blocked by:** 07 (On/off and reset).

**Status:** ready-for-agent

- [ ] The checklist is in `docs/05-deployment.md`.
- [ ] It has been followed once with a temporary environment, which was then cleaned up with `reset`.
- [ ] Everything that went differently from the checklist during that test has been incorporated.
- [ ] For each toggle (`enable_mesh`, `enable_managed_postgres`) it states when it must be on.

## PRs

**PR 8: checklist for a new environment.**
This PR contains only the checklist in `docs/05-deployment.md`, with the improvements from the test run.
The temporary test environment itself does not go into Git.
Describe in the PR which steps went differently than expected during the test.
The reviewer is preferably the person who will build the next real environment.

## Why this ticket

We start with dev only, but the blueprint is built for several environments.
Right now we still know exactly which steps were needed.
In six months we will not.
A checklist that has actually been carried out once saves someone from having to figure it all out again.

## What happens, step by step

### The checklist

Use these steps as a starting point, and add what you ran into during tickets 3 to 7.

1. Create a new Scaleway Project and set `PROJECT_ID_<ENV>` in `deploy/scaleway/.env`.
2. Add the name to `SPOKE_ENVS`.
3. Copy `deploy/scaleway/envs/dev` to `envs/<env>` and adjust `terraform.tfvars`. Choose a separate network range (CIDR), the node size, and the toggle settings.
4. Copy `deploy/gitops/clusters/scaleway/dev` to `<env>`. Change the names in the ExternalSecrets so they point to `srdp-<env>-`, and adjust the HelmRelease values.
5. Apply the environment following ticket 3.
6. Reserve an IP address and fill in the domain following ticket 4.
7. Run the OIDC script from ticket 5 for the new hostnames.
8. Check the environment with the steps from ticket 6.

### When the toggles must be on

Write down for each toggle when it must be on.
Use the following as a starting point.

- `enable_mesh` must be on as soon as customer data arrives in the environment, or as soon as the Kubernetes API may no longer be reachable from individual IP addresses.
- `enable_managed_postgres` must be on as soon as the data must not be lost, because the managed database has automatic backups.

### Testing

Follow the checklist with a temporary environment, for example `test`.
Update the checklist right away where it is wrong.
Then clean up the environment with the reset from ticket 7, and delete the temporary Project.

## What you need to know or install first

- Ticket 7 must be done, so the temporary environment can be cleaned up properly.
- The Scaleway quota must have room for a second cluster.

## How to check that it works

A colleague who did not build the environment can set up a new one using only the checklist.

## Pitfalls

- **Overlapping networks.** Each spoke needs its own network range. If you use the same range as dev, connecting to the hub will fail later.
- **Costs add up.** Each environment has its own load balancer and nodes. Remove the temporary test environment straight away.
- **Separate secrets.** Each environment gets its own passwords in Secret Manager. Never copy secrets from dev to another environment.
