# 03: A lean, empty dev environment

**What to build:** Scaleway hosts a hub and one spoke called `dev`. An empty Kapsule cluster runs, and `kubectl` works from our own IP. The bucket, the registry and the keys in Secret Manager exist. The mesh, the Public Gateway and the managed database are switched off through toggles, so the environment stays within budget.

**Blocked by:** None (can start immediately).

**Issues:** Related to #43 (scoping the `ObjectStorageFullAccess` key, mesh hardening) and #40 (the mesh decision). This ticket switches the mesh off and leaves both issues open.

**Status:** ready-for-agent

- [ ] The blueprint has an `enable_mesh` toggle for Headscale, the mesh router and the Public Gateway.
- [ ] The blueprint has an `enable_managed_postgres` toggle for the managed database.
- [ ] Both default to `true`, and are set to `false` in the dev settings.
- [ ] `just scaleway plan dev` shows no virtual machines, no gateway and no managed database.
- [ ] Hub and dev are applied, and `kubectl get nodes` works from our IP.
- [ ] The generated secrets are visible in Scaleway Secret Manager.
- [ ] A budget alert is set at €100 per month.
- [ ] The real costs after one week are recorded in this ticket.

## PRs

**PR 3a: toggles in the blueprint.**
This PR adds `enable_mesh` and `enable_managed_postgres`, both defaulting to `true`.
With the defaults nothing changes.
Put the output of `terraform validate` in the description, plus a trimmed `plan` for dev with both toggles on `true` and on `false`.
The reviewer focuses on references between modules, for example from the mesh router to the gateway, which break when a module is off.
Ask Andrea to review, since the modules originally come from Andrea.

**PR 3b: dev settings.**
This PR sets the dev toggles to `false`, sets the node size, and documents `SPOKE_ENVS=dev`.
It contains no secrets or Project IDs, because those live in `.env`.
After the merge you run `just scaleway bootstrap-all`, and paste the summary of `apply` and the output of `kubectl get nodes` as a comment on the PR.
3b is blocked by 3a.

## Why this ticket

This is the first time the blueprint is actually applied.
Nobody has done that before, so this is where most of the unknowns are.
That is why we first apply only the infrastructure, without the SRDP stack on top.
If something goes wrong, you know for sure it is the infrastructure.

The blueprint currently always creates a managed database, a Headscale machine, a mesh router and a Public Gateway.
Together that costs about €35 to €45 per month, and this proof of concept does not need them.
The toggles keep those components available for later, without paying for them now.

Read the sections on the blueprint, node pools and Terraform in the [Kubernetes primer](../kubernetes-primer.md).

## What happens, step by step

### 1. Prepare Scaleway

You do these steps in the Scaleway console.
The full list is in `deploy/scaleway/docs/DEPLOYMENT.md`, under "Prerequisites".

- Create two Projects, one for the hub and one for dev.
- Verify your identity and request a quota increase for the POP2 machine type. New accounts may have a default quota of zero for those machines, and then creating the compute pool fails.
- Create an API key with the Editors, `ObjectStorageFullAccess` and `IAMManager` permissions. Set the key's preferred Project to the hub, otherwise Terraform cannot find the state bucket.

### 2. Build the toggles

In Terraform you switch a component on or off with `count`.
The blueprint already does this for `enable_hub_peering`, so follow that example.

- `enable_mesh` controls whether the Headscale machine in the hub and the mesh router and Public Gateway in the spoke are created.
- Without the mesh, the ACL on the Kubernetes API must fall back to the `api_extra_allowed_cidrs` list, which holds your own IP address.
- `enable_managed_postgres` controls whether the managed database is created.

Watch out for components that reference each other.
The mesh router, for example, uses the gateway's IP address.
If you switch the gateway off, that reference has to go too.

### 3. Fill in the dev settings

In `deploy/scaleway/envs/dev/terraform.tfvars` you set the following.

- Both toggles to `false`.
- The system pool to one node of about 8 GB, or whatever the measurement from ticket 1 indicates.
- Your own IP address in `api_extra_allowed_cidrs`.
- Your SSH key and the Git repository URL in place of the placeholders.

In `deploy/scaleway/.env` you set `SPOKE_ENVS=dev`, the Project IDs and the API key.
That file is in `.gitignore` and must never be committed.

### 4. Apply

First look at what would happen.

```bash
just scaleway doctor
just scaleway plan dev
```

Check in the `plan` output that it contains no machines, no gateway and no database.
Then apply everything.

```bash
just scaleway bootstrap-all
```

This first creates the state bucket, then the hub, and then the spoke.
On a brand-new cluster you sometimes have to create only the cluster first, because Terraform needs the cluster to install Flux.
The runbook describes that step under "Cold-cluster note".

### 5. Check and set a budget

Fetch the kubeconfig and check that you can reach the cluster.
Set a budget alert of €100 per month in the Scaleway console.
After one week, look at the billing to see what the environment really costs, and record it in this ticket.

## What you need to know or install first

- Terraform 1.10.3, `just`, `kubectl` and `helm`.
- Access to the Scaleway organisation with permission to create Projects and API keys.
- Your public IP address. It changes when you switch networks, and then you have to update the ACL.

## How to check that it works

```bash
kubectl get nodes
kubectl get pods -A
```

You expect one node with status `Ready`.
The list of pods shows only system components, Flux and External Secrets, and nothing from SRDP yet.
The Scaleway console shows the bucket, the registry and the secrets with the `srdp-dev` prefix.

## Pitfalls

- **Quota.** Without a quota increase, creating the POP2 pool fails with `Quota exceeded`. Request the increase well in advance.
- **Preferred Project.** If your API key's preferred Project is not the hub, Terraform cannot find the state.
- **Changing IP.** When you work from another network, the ACL blocks you. Add the new IP and run `apply` again.
- **The state contains secrets.** The generated passwords are stored in the Terraform state. Check that the state bucket is private and has versioning.
- **Flux reads `main`.** Flux is already installed in this step and reads the `main` branch by default. That only matters in ticket 4.
