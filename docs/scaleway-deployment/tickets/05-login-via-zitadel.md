# 05: Login via Zitadel

**What to build:** Postgres, Zitadel and oauth2-proxy run in the dev cluster. The OIDC app that oauth2-proxy uses to log in to Zitadel is created automatically, and the client credentials go into Scaleway Secret Manager. All apps are online, and every hostname is only reachable after logging in.

**Blocked by:** 04 (The hub page live via Flux).

**Status:** ready-for-agent

- [ ] Postgres runs in the cluster, and its data lives on a persistent volume.
- [ ] Zitadel is reachable at `auth.<LB_IP>.nip.io`.
- [ ] A script or Kubernetes Job creates the OIDC app with a redirect URI for every hostname.
- [ ] The client ID and client secret are in Secret Manager, and External Secrets puts them in the cluster.
- [ ] Running the script again changes nothing when everything is already correct.
- [ ] All hostnames (hub, auth, dagster, marimo, quarto, streamlit, marquez, api and duckdb) load only after logging in.

## PRs

**PR 5a: generic OIDC script.**
This PR makes `provision-oidc.sh` usable for both Compose and the cluster, and makes it write the client credentials to Secret Manager.
The behaviour for Compose stays the same.
Test against the Compose stack that a second run changes nothing, and put that output in the description.
The reviewer checks that the script never writes a secret to the terminal or to a file in the repo.
This PR can start right away, in parallel with the other tickets.

**PR 5b: enable Zitadel, oauth2-proxy and the apps.**
This PR enables Postgres, Zitadel, oauth2-proxy and the apps in the HelmRelease.
This one also deploys on merge.
After Zitadel is rolled out, run the script, and then paste a screenshot of the login page and the list of hostnames that work behind the login as a comment on the PR.
5b is blocked by 4b and 5a.

## Why this ticket

Without a login, everything in the environment is publicly visible.
Traefik first sends every request to oauth2-proxy, which checks whether you are logged in to Zitadel.
This is called *forward auth*, and it already works this way in Compose.

The tricky part is a chicken-and-egg problem.
oauth2-proxy needs a client ID and a client secret from Zitadel.
Those only exist once Zitadel runs and someone creates the OIDC app.
In the old plan that was manual work in the Zitadel console, which came back after every reset.
This ticket automates that step.

## What happens, step by step

### 1. Enable Postgres and Zitadel

Enable Postgres and Zitadel in the HelmRelease.
Postgres stores its data on a PVC, which becomes a Block Storage volume on Scaleway.
That volume stays when you switch the nodes off later (ticket 7).

Zitadel needs a master key of exactly 32 characters.
The blueprint has already generated it in Secret Manager, and ticket 4 has put it in the cluster.

Wait until Zitadel runs and check that `https://auth.<LB_IP>.nip.io` shows the login page.

### 2. Create the OIDC app automatically

A script already exists for the Compose stack, `deploy/docker/provision-oidc.sh`.
It creates an admin user, finds the `srdp` project with the `oauth2-proxy` app, and makes sure every hostname has a redirect URI.
It is idempotent, so running it again changes nothing when everything is already correct.

The script is currently written for Compose.
It reads the hostnames from `docker-compose.yml`, talks to `auth.srdp.localhost`, and writes to `deploy/docker/.env`.
Make it usable for the cluster.
Choose one of these two approaches.

- Make the script generic, so it takes the hostnames and the Zitadel address as input and runs from your laptop against the cloud.
- Create a Kubernetes Job that does the same inside the cluster, right after Zitadel is installed.

Write the result, the client ID and the client secret, to Scaleway Secret Manager, with the Scaleway CLI or the API.
Never put a secret in Git or in a values file.

### 3. Enable oauth2-proxy and the apps

External Secrets fetches the new client credentials and updates the Secret.
Then enable oauth2-proxy and the remaining apps in the HelmRelease: dagster, marimo, quarto, streamlit, marquez, the api and duckdb-ui.
Each app gets an Ingress that goes through oauth2-proxy's forward auth.

## What you need to know or install first

- Ticket 4 must be done, with a fixed IP address. The redirect URIs contain the IP, so a new IP means running the script again.
- The Scaleway CLI (`scw`), if you write to Secret Manager from your laptop.

## How to check that it works

Open each hostname in a private browser window.
Each time you are sent to the Zitadel login page.
After logging in you land on the right app, and the next hostnames open without logging in again.

Run the script a second time and check that it reports no changes.

## Pitfalls

- **The project and app names are fixed.** The script looks for the `srdp` project and the `oauth2-proxy` app. It does not find other names.
- **The redirect URI must match exactly.** One character off, or `http` instead of `https`, gives an error from Zitadel at login.
- **The oauth2-proxy cookie.** If the cookie secret changes, everyone is logged out. The blueprint generates it once and keeps it in Secret Manager, so leave it there.
- **Zitadel starts slowly.** The first start can take several minutes. The pod can temporarily show `CrashLoopBackOff` while it waits for Postgres.
