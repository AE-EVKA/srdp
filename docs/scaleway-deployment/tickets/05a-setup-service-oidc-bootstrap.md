# 05a: OIDC bootstrap in the setup service

**What to build:** the setup service from issue #60 creates the Zitadel OIDC app for oauth2-proxy and hands the client credentials to oauth2-proxy, in Compose and in kind. Nobody opens the Zitadel console or runs `provision-oidc.sh` any more. A fresh `just docker-up` or `just local-deploy` ends with a working login.

**Blocked by:** 01 (Chart parity and external secrets), and the database bootstrap part of #60 being merged into `main` or into this integration branch.

**Issues:** Part of #60 (the "OIDC credential bootstrap" item). Closes #35.

**Status:** needs-coordination

- [ ] The setup service finds or creates the `srdp` project and the `oauth2-proxy` app in Zitadel.
- [ ] The app has a redirect URI for every hostname, read from one list of hostnames in the config.
- [ ] In Compose the client ID and secret are written to a file that oauth2-proxy reads through a `_FILE` variable.
- [ ] In kind the setup Job writes them to a Kubernetes Secret with the name from the secret table of ticket 01, and oauth2-proxy reads that Secret.
- [ ] oauth2-proxy waits for the credentials, so it no longer sits in `CrashLoopBackOff` after a fresh install.
- [ ] A second run changes nothing, and says so in its log.
- [ ] `deploy/docker/provision-oidc.sh` is deleted, and no doc or recipe refers to it.
- [ ] No secret appears in a log line, in the repo or in a values file.

## PRs

**PR 5a-1: OIDC bootstrap in Compose.**
This PR adds the OIDC step to the setup service, writes the credentials to a file, and points oauth2-proxy at it with `_FILE` variables.
Test with an empty Compose stack, then run the setup service a second time, and put both logs in the description.

**PR 5a-2: OIDC bootstrap in kind.**
This PR runs the same step in the setup Job, writes a Kubernetes Secret, and gives the Job a ServiceAccount that may only write that one Secret.
It deletes `provision-oidc.sh`.
Test with `just local-delete` and `just local-deploy`, and put `kubectl get pods -n srdp` and a screenshot of an app behind the login in the description.
The reviewer checks the Role, because the Job must not be able to read or change other Secrets.

5a-2 is blocked by 5a-1.

## Why this ticket

oauth2-proxy needs a client ID and a client secret from Zitadel.
Those only exist once Zitadel runs and someone creates the OIDC app.
Today that is `provision-oidc.sh`, which is written for Compose and runs by hand.

Issue #60 replaces that script with a setup service that runs before the rest of the stack, in Compose as a one-off service and in Kubernetes as a Job.
Its database bootstrap is already built.
Its OIDC step is not, and ticket 5 needs it in the cloud.
This ticket builds that step in Compose and kind first, where a mistake costs nothing, so ticket 5 only has to switch it on.

This ticket covers only the OIDC step of #60.
The password propagation and the readiness gate from #60 stay in #60, because ticket 5 does not need them.

## What happens, step by step

### 1. Get the #60 work

The database bootstrap of #60 is not on a pushed branch yet.
Ask the author of #60 to push it, and merge it into `feature/kubernetes-scaleway-deployment` before starting.
It touches the same chart templates as ticket 01, so settle the order with them.

Read the setup service code and the Job template first, because this ticket adds a step to both.

### 2. Find or create the OIDC app

Move the logic of `deploy/docker/provision-oidc.sh` into the setup service.
It logs in to Zitadel with the admin token, finds or creates the `srdp` project and the `oauth2-proxy` app, and makes sure every hostname has a redirect URI.

The hostnames come from the static domain step of #60, which reads them from config.
That static step is enough for Scaleway as well, because ticket 4 reserves the load balancer IP, so the `nip.io` hostnames are known in advance.

### 3. Hand the credentials to oauth2-proxy

In Compose, write the client ID and secret to a file on a shared volume, and set `OAUTH2_PROXY_CLIENT_SECRET_FILE` and the matching client ID setting on oauth2-proxy.
This follows the `_FILE` convention that `ZITADEL_SERVICE_USER_TOKEN_FILE` already uses.

In Kubernetes, write a Secret with the name and keys from the secret table of ticket 01.
Give the Job a ServiceAccount with a Role that may only `get`, `create` and `patch` that one Secret by name.

These client credentials are derived from Zitadel, and the setup service recreates them after every reset.
That is why they live in a Kubernetes Secret written by the Job, and not in Scaleway Secret Manager.
Record this in [ADR-0010](../../adr/0010-secret-management.md) as the one kind of secret that has its home inside the cluster.

### 4. Make oauth2-proxy wait

oauth2-proxy must not start before the credentials exist.
In Compose, gate it with `depends_on: condition: service_completed_successfully` on the setup service.
In Kubernetes, give it an init container that waits for the Secret, like the `wait-for-ducklake-db` init containers from #60.

### 5. Delete the old script

Delete `deploy/docker/provision-oidc.sh`, and update every reference in the `Justfile` and the docs.

## How to check that it works

```bash
just local-delete
just local-deploy
kubectl get pods -n srdp
kubectl logs job/<setup-job> -n srdp
```

All pods are `Running` or `Completed`, and oauth2-proxy has no restarts.
Open `https://srdp.localhost:18443` in a private window, log in, and open the other hostnames without logging in again.

Run `helm upgrade` again and check that the setup Job log reports no changes to the OIDC app.
Do the same for Compose with an empty stack and `just docker-up`.

## Pitfalls

- **Two owners of one piece of work.** #60 has an author who has built most of the setup service. Agree on who builds this step before starting.
- **A Secret the chart also renders.** If the chart's local Secret template from ticket 01 also renders the oauth2-proxy Secret, Helm and the Job overwrite each other. Leave the client credentials out of that template.
- **Hooks run after the Deployments start.** A `post-install` Job does not block the other pods. The init container on oauth2-proxy is what makes it wait.
- **A new IP means new redirect URIs.** Put the reserved IP from ticket 4 in the config before the first cloud run.
