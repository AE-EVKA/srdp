# 05: Login via Zitadel

**What to build:** Postgres, Zitadel and oauth2-proxy run in the dev cluster. The setup service from ticket 5a creates the OIDC app that oauth2-proxy uses to log in to Zitadel, and writes the client credentials to a Secret in the cluster. All apps are online, and every hostname is only reachable after logging in.

**Blocked by:** 04 (The hub page live via Flux), 05a (OIDC bootstrap in the setup service).

**Issues:** Part of #60. Ticket 5a builds the OIDC step of #60 and closes #35. This ticket runs it in the cloud.

**Status:** ready-for-agent

- [ ] Postgres runs in the cluster, and its data lives on a persistent volume.
- [ ] Zitadel is reachable at `auth.<LB_IP>.nip.io`.
- [ ] The setup Job creates the OIDC app with a redirect URI for every `nip.io` hostname.
- [ ] The setup Job writes the client ID and client secret to the oauth2-proxy Secret, and oauth2-proxy starts without restarts.
- [ ] A second Flux reconcile runs the setup Job again, and its log reports no changes.
- [ ] All hostnames (hub, auth, dagster, marimo, quarto, streamlit, marquez, api and duckdb) load only after logging in.

## PRs

**PR 5: enable Zitadel, the setup Job, oauth2-proxy and the apps.**
This PR enables Postgres, Zitadel, the setup Job, oauth2-proxy and the apps in the HelmRelease, and puts the `nip.io` hostnames in the setup service config.
This one also deploys on merge.
After the rollout, paste the setup Job log, a screenshot of the login page and the list of hostnames that work behind the login as a comment on the PR.
PR 5 is blocked by 4b and by ticket 5a.

## Why this ticket

Without a login, everything in the environment is publicly visible.
Traefik first sends every request to oauth2-proxy, which checks whether you are logged in to Zitadel.
This is called *forward auth*, and it already works this way in Compose.

The tricky part is a chicken-and-egg problem.
oauth2-proxy needs a client ID and a client secret from Zitadel.
Those only exist once Zitadel runs and someone creates the OIDC app.
In the old plan that was manual work in the Zitadel console, which came back after every reset.
Ticket 5a moves that step into the setup service from issue #60, and this ticket switches it on in the cloud.

## What happens, step by step

### 1. Enable Postgres and Zitadel

Enable Postgres and Zitadel in the HelmRelease.
Postgres stores its data on a PVC, which becomes a Block Storage volume on Scaleway.
That volume stays when you switch the nodes off later (ticket 7).

Zitadel needs a master key of exactly 32 characters.
The blueprint has already generated it in Secret Manager, and ticket 4 has put it in the cluster.

Set `global.postgresqlHost` to the Service name of this Postgres.
It defaults to `db-postgresql`, which is right for a standalone Postgres. With a primary and replicas the name is `db-postgresql-primary`.
With the wrong name the setup Job cannot connect, and every `wait-for-*-db` init container waits forever.

The setup Job from #64 now also runs, and creates the `dagster`, `marquez` and `ducklake` databases.
Its passwords come from the Secrets of ticket 4, with the names from the secret table of ticket 01.
Check that it completed with `kubectl get jobs -n srdp`.

Wait until Zitadel runs and check that `https://auth.<LB_IP>.nip.io` shows the login page.

### 2. Let the setup Job create the OIDC app

The setup Job already runs since step 1. Ticket 5a added the OIDC step to it, which needs Zitadel.
Put the `nip.io` hostnames in its config, for every app from step 3.
Those hostnames are known in advance, because ticket 4 reserved the load balancer IP.

After Zitadel runs, the Job finds or creates the `srdp` project and the `oauth2-proxy` app, and writes the client credentials to the oauth2-proxy Secret.
Check its log with `kubectl logs job/<setup-job> -n srdp`.

The client credentials do not go into Scaleway Secret Manager.
They are derived from Zitadel, and the Job recreates them after every reset.
[ADR-0010](../../adr/0010-secret-management.md) records this exception.

### 3. Enable oauth2-proxy and the apps

Then enable oauth2-proxy and the remaining apps in the HelmRelease: dagster, marimo, quarto, streamlit, marquez, the api and duckdb-ui.
Each app gets an Ingress that goes through oauth2-proxy's forward auth.

## What you need to know or install first

- Ticket 4 must be done, with a fixed IP address. The redirect URIs contain the IP, so a new IP means updating the setup service config and reconciling again.
- Ticket 5a must be done, so the setup service has the OIDC step.

## How to check that it works

Open each hostname in a private browser window.
Each time you are sent to the Zitadel login page.
After logging in you land on the right app, and the next hostnames open without logging in again.

Trigger a second reconcile with `flux reconcile helmrelease srdp -n srdp`, and check that the setup Job log reports no changes.

## Pitfalls

- **The project and app names are fixed.** The setup service looks for the `srdp` project and the `oauth2-proxy` app. It does not find other names.
- **The redirect URI must match exactly.** One character off, or `http` instead of `https`, gives an error from Zitadel at login.
- **The oauth2-proxy cookie.** If the cookie secret changes, everyone is logged out. The blueprint generates it once and keeps it in Secret Manager, so leave it there. Only the client ID and secret come from the setup Job.
- **Waiting HelmRelease.** If the release hangs until it times out, with pods in `Init` and no setup Job, check that `disableWait` from ticket 4 is still set.
- **Zitadel starts slowly.** The first start can take several minutes. The pod can temporarily show `CrashLoopBackOff` while it waits for Postgres.
