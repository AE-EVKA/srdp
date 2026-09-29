# 04: The hub page live via Flux

**What to build:** Flux installs the SRDP chart on the dev cluster, at first with only Traefik and the hub page. External Secrets puts the secrets from Scaleway Secret Manager into the cluster. The images come from the registry in the hub. `https://<LB_IP>.nip.io` shows the hub page with a real Let's Encrypt certificate.

**Blocked by:** 01 (Chart parity and external secrets), 03 (A lean, empty dev environment).

**Status:** ready-for-agent

- [ ] All SRDP images are in the hub registry.
- [ ] A ClusterSecretStore connects External Secrets to Scaleway Secret Manager.
- [ ] ExternalSecrets create the Secrets the chart expects, with the names from ticket 1.
- [ ] A HelmRelease in `deploy/gitops/clusters/scaleway/dev` installs the chart, with only Traefik and the hub enabled.
- [ ] The load balancer's IP address is reserved and no longer changes.
- [ ] `https://<LB_IP>.nip.io` shows the hub page with a valid certificate.
- [ ] It is recorded which branch Flux reads.

## PRs

**PR 4a: build and push images.**
This PR updates the build-and-push recipe so it builds all seven images for `linux/amd64` and pushes them to the hub registry, tagged with the commit hash.
Put the list of images as they appear in the registry in the description.
The reviewer checks that no registry key is stored in the recipe.

**PR 4b: External Secrets and HelmRelease.**
This PR adds the ClusterSecretStore, the ExternalSecrets and the HelmRelease with only Traefik and the hub to `deploy/gitops/clusters/scaleway/dev`.
This is the first PR that deploys something when merged, because Flux reads `main`.
Only merge it when you have time to check afterwards.
State in the description how to roll back, and after the merge paste the output of `kubectl get helmreleases,externalsecrets -A` and a screenshot of the hub page with its certificate.
The reviewer checks that it contains only references to secrets, and no values.
4b is blocked by 4a.

The IP address only exists after the first rollout.
Fill it in with a small follow-up PR that only changes `global.domain`.

## Why this ticket

This ticket is a *tracer bullet*.
The goal is to get one small thing all the way through the cloud as fast as possible.
The hub page is a static page without a database and without a login, so if it fails, the cause is on the cloud side.

With one page you test five components that did not exist in kind, all at once.

- Pulling images from the registry.
- Flux installing the chart from Git.
- External Secrets fetching the secrets from Scaleway.
- The Scaleway load balancer.
- Let's Encrypt certificates.

Once this works, the next tickets only need to switch on more apps.

Read the sections on GitOps with Flux and External Secrets in the [Kubernetes primer](../kubernetes-primer.md).

## What happens, step by step

### 1. Push images

In the cloud the nodes pull images from the registry, so they have to be there first.
Build all SRDP images (marimo, srdp-etl, srdp-api, duckdb-ui, hub, streamlit and quarto) and push them to the hub registry.
The existing `just build-and-push` recipe builds only some of the images and points at the old stack's registry.
Update it, or add a new recipe, that uses the registry from the blueprint.

Use a fixed version as the tag, for example the short commit hash.
With `latest` you cannot tell which version is running, and Kubernetes does not notice a new one.

### 2. Connect External Secrets to Scaleway

The blueprint has already installed External Secrets, and has put a key for ESO in the cluster.
What is missing is the connection.

- Create a **ClusterSecretStore** with the Scaleway provider, using the ESO key.
- Create an **ExternalSecret** for each Secret from ticket 1 that fetches the values from Secret Manager. The names in Secret Manager start with `srdp-dev-`, for example `srdp-dev-postgres-password`.

The OIDC values do not really exist yet, because Zitadel is not running.
They are filled in during ticket 5.

### 3. Write the HelmRelease

Create a HelmRelease for the SRDP chart in `deploy/gitops/clusters/scaleway/dev`, and add it to the `kustomization.yaml` in that folder.
Because the chart lives in our own repository, Flux can fetch it directly from the Git source it already knows.

In the HelmRelease values, enable only Traefik and the hub, and disable the rest.
Also fill in the following.

- `global.domain` with `<LB_IP>.nip.io`. You only know the IP after step 4, so start with a placeholder.
- The registry from the blueprint in `global.imageRegistry`, and the pull secret.
- A real email address for Let's Encrypt. The current `john@doe.com` is rejected.

### 4. Pin the IP address

The first time Traefik runs, Scaleway creates a load balancer with a random IP address.
Reserve that address as a fixed IP (a *flexible IP*) and tell Traefik to use it.
Otherwise the environment gets a new address after a reset, and you have to redo all nip.io names and the Zitadel settings.

Then fill the real IP into `global.domain` and push the change.

### 5. Which branch Flux reads

Flux reads the `main` branch by default.
This work still lives on another branch.
Choose one of these two options, and record the choice in this ticket.

- Merge to `main` first, so Flux sees the work.
- Temporarily point Flux at another branch through the blueprint's `git_branch` setting.

## What you need to know or install first

- Tickets 1 and 3 must be done.
- Docker must be able to build images for the processor architecture of the Scaleway nodes (`amd64`). On a Mac with an Apple chip you use `docker buildx build --platform linux/amd64`.
- You log in to the registry with a Scaleway key through `docker login rg.nl-ams.scw.cloud`.

## How to check that it works

```bash
kubectl get helmreleases -A
kubectl get externalsecrets -A
kubectl get pods -n srdp
```

The HelmRelease and the ExternalSecrets have status `Ready`.
The Traefik and hub pods have status `Running`.
Open `https://<LB_IP>.nip.io` in your browser.
You see the hub page, and the padlock in the address bar shows a Let's Encrypt certificate.

To make Flux check right away instead of waiting, use `flux reconcile kustomization` with the name from `kubectl get kustomizations -A`.

## Pitfalls

- **`ImagePullBackOff`.** The image name or tag is wrong, or the pull secret is missing. Look at the details with `kubectl describe pod`.
- **Wrong architecture.** An image built on a Mac with an Apple chip without `--platform linux/amd64` does not start on the nodes, and shows `exec format error` in the logs.
- **Let's Encrypt limits.** Let's Encrypt issues only a limited number of certificates per domain per week. Test with the Let's Encrypt staging environment first if you redeploy often.
- **Flux sees nothing.** Flux only reads what has been pushed. A local commit without `git push` does nothing.
- **An ExternalSecret stays on `SecretSyncedError`.** The name in Secret Manager is wrong, or the ClusterSecretStore cannot log in. `kubectl describe externalsecret` shows the reason.
