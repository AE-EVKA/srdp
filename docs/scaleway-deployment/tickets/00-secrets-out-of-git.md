# 00: Secrets out of Git

**What to build:** no working secret lives in a tracked file outside the Helm chart, every secret that ever left a laptop is rotated, and CI fails when a new one gets committed.

**Blocked by:** None (can start immediately).

**Issues:** Closes #61. Related to #44, which may remove `deploy/opentofu/gcp` entirely. If #44 lands first, delete `tofu.tfvars` instead of turning it into an example.

**Status:** ready-for-agent

- [x] `deploy/opentofu/gcp/tofu.tfvars` is no longer tracked. A `tofu.tfvars.example` with empty values takes its place.
- [x] `*.tfvars` is in `.gitignore`, with an exception for `*.tfvars.example`.
- [x] The docs no longer print a working password. They point at the file where the value is set.
- [ ] Every secret below that was used on a machine outside a laptop is rotated, and the ticket records which ones.
- [x] gitleaks has custom rules that catch the secrets below, and CI fails on a test commit that adds one.
- [x] The ticket contains the output of a full-history `gitleaks detect` run.
- [x] `docs/adr/0010-secret-management.md` describes the permanent situation below, and `docs/adr/index.md` links it.
- [x] A PR template asks every PR that adds a secret to follow the fixed path.

## Scope

The repo is public, so a value in the git history is readable by anyone.
Rewriting history does not undo that, because the value may already be copied.
Rotating the secret is the real fix, and removing it from the files stops the next leak.

This ticket handles every place outside the Helm chart.
The chart itself (`values.yaml` and `values-local.yaml`) is PR 1b of [ticket 01](01-chart-parity-and-secrets.md), because that PR already rewrites those templates to read from Secrets.
Doing it twice would cause conflicts.

## The permanent situation

Cleaning up today's leaks is only half the work.
The other half is a setup where a secret has exactly one home per environment, and that home is never a tracked file.

| Environment | Where the secret value lives | How it reaches the app |
|:---|:---|:---|
| Docker Compose | `deploy/docker/.env`, which is gitignored and filled from `.env.example` | Compose reads it as environment variables. |
| kind | A gitignored file (for example `deploy/kubernetes/srdp-chart/values-secrets.local.yaml`), generated with random values by a `just local-secrets` recipe | The chart's local Secret template renders it into Kubernetes Secrets. |
| Scaleway (dev, and later stage and prod) | Scaleway Secret Manager, filled by OpenTofu or by hand | External Secrets creates the Kubernetes Secrets (ticket 4). |
| OpenTofu variables | The shell, as `TF_VAR_<name>`, or a gitignored `*.tfvars` | OpenTofu reads them at plan time. |

Git holds only three kinds of things.

- An example file with empty values or `XXXX` placeholders, which documents what is needed.
- The name of a Secret and its keys, which the chart refers to with `existingSecret` or `secretKeyRef`.
- The gitleaks rules that guard all of the above.

These rules follow from that setup.

- **Every environment generates its own values.** No value is copied from one environment to another, so a leak in one never opens another. The shared cookie secret is exactly this mistake.
- **Local values are random, not memorable.** `just local-secrets` generates them, so there is no `srdpTest123` that people start reusing.
- **A new secret follows a fixed path.** It gets a key in the example file, a Secret name in the chart, an entry in Secret Manager for the cloud, and a row in the secret table of ticket 01. A new `.github/pull_request_template.md` asks for this with a checkbox.
- **CI is the last line.** gitleaks runs on every PR with rules that match this repo, so a mistake is caught before it reaches `main`.

Write this setup down as `docs/adr/0010-secret-management.md`, so later tickets and new contributors follow it without reading this ticket.

## Known secrets

| Secret | Where | Handled by |
|:---|:---|:---|
| oauth2-proxy cookie secret | `deploy/opentofu/gcp/tofu.tfvars:10` | This ticket |
| Zitadel admin password `srdpTest123!` | `docs/02-configuration.md:137` | This ticket |
| Postgres password `srdpTest123` | `deploy/kubernetes/srdp-chart/values.yaml` | Ticket 01, PR 1b |
| Zitadel master key | `values.yaml`, `values-local.yaml` | Ticket 01, PR 1b |
| oauth2-proxy client secret | `values.yaml:168` and a different one in `values-local.yaml:49` | Ticket 01, PR 1b |
| oauth2-proxy cookie secret (same value as the GCP one) | `values.yaml`, `values-local.yaml` | Ticket 01, PR 1b |
| Zitadel master key and cookie secret (same values as the chart) | History of `local/.env.example` and `deploy/docker/.env.example`, today empty | Covered by the rotation of the chart values |

The cookie secret appears in three files with the same value.
After this ticket and PR 1b, each environment has its own value.

## What happens, step by step

### 1. Find out what was exposed

For each secret in the table, find out whether it was ever used on something reachable from outside a laptop.
Examples are the GCP VM from `deploy/opentofu/gcp/`, a shared Zitadel, or a Scaleway cluster.
Write the answer down per secret in this ticket.
A secret that only ever lived in a local kind cluster or Compose stack needs no rotation.

### 2. Rotate what was exposed

Generate a new value for each exposed secret, for example with `openssl rand -base64 32 | head -c 32` for a 32-character secret.
For the oauth2-proxy client secret, regenerate it in the Zitadel console under the OIDC application.
Pass the new value to the running environment without committing it.
If the environment no longer exists, write that down and skip the rotation.

### 3. Stop tracking the GCP tfvars

Move `deploy/opentofu/gcp/tofu.tfvars` to `tofu.tfvars.example` with every secret set to `""`.
Keep the non-secret values (project id, domain), so the example stays useful.
Add `*.tfvars` and `!*.tfvars.example` to `.gitignore`.
Mention `TF_VAR_<name>` in the example as the way to pass secrets from the shell.

### 4. Remove the password from the docs

In `docs/02-configuration.md`, replace the literal `srdpTest123!` with a reference to where it is set.
For kind that is `values-local.yaml`, once PR 1b has landed.
Search `docs/` for other literal values with `grep -rn 'srdpTest' docs/`.

### 5. Make gitleaks catch these secrets

The repo already runs gitleaks in pre-commit and CI, but its default rules do not catch any of the secrets above.
Add a `.gitleaks.toml` that extends the default config with rules for:

- the literal `srdpTest123` password,
- `cookieSecret`, `clientSecret` and `masterkey` keys with a non-empty value in YAML,
- `*_secret` variables with a non-empty value in `.tfvars` files.

Until PR 1b lands, the chart still contains these values.
Add an allowlist for `deploy/kubernetes/srdp-chart/values*.yaml` with a comment that PR 1b removes it.
PR 1b then removes the allowlist for `values.yaml`, and keeps a narrow one for the local development values.

### 6. Scan the full history

Run `gitleaks detect --source . --log-opts="--all"` and put the output in this ticket.
Any new finding goes into the table above, and through steps 1 and 2.

### 7. Record the permanent situation

Write `docs/adr/0010-secret-management.md` in the style of the existing ADRs, and add it to `docs/adr/index.md`.
It describes the table and the rules from "The permanent situation", and it names ticket 01 PR 1b and ticket 4 as the places where kind and Scaleway get their part.
Add `.github/pull_request_template.md` with a checkbox for the fixed path of a new secret.

## How to check that it works

```bash
git ls-files | grep tfvars
grep -rn 'srdpTest' docs/ deploy/opentofu/
uv run pre-commit run gitleaks --all-files
```

The first command shows only `tofu.tfvars.example`.
The second shows nothing.
The third passes.

Then check that gitleaks actually catches something.
On a throwaway branch, add `cookieSecret: "abcdefghijklmnopqrstuvwxyz123456"` to any YAML file outside the chart and commit.
The pre-commit hook must block the commit.

## Pitfalls

- **Rotation before removal.** Removing a value from the files does not make it secret again. Rotate first, then remove.
- **Existing local tfvars.** After the move, anyone with a working GCP setup needs to copy `tofu.tfvars.example` to `tofu.tfvars` and fill it in again.
- **Allowlists that are too wide.** Allow single paths, never a whole directory, or the rules will stop catching real leaks.

## Exposure and rotation record

No OpenTofu state for `deploy/opentofu/gcp/` exists in this checkout, so it cannot be shown from here whether the GCP VM was ever applied.
Each row below stays open until the owner of that environment confirms it.

| Secret | Used outside a laptop? | Rotated? |
|:---|:---|:---|
| oauth2-proxy cookie secret (GCP tfvars) | Unconfirmed. It is the same value as the chart, so it counts as exposed if any shared cluster or the GCP VM ever ran. | Pending owner confirmation. |
| Zitadel admin password | Only in the local kind chart and docs, as far as the repo shows. | Not needed for local use. The chart value goes away in ticket 01 PR 1b. |
| Chart secrets (Postgres, master key, client secret, cookie secret) | Handled by ticket 01 PR 1b. | Handled by ticket 01 PR 1b. |

## Full-history gitleaks run

`gitleaks detect --source . --log-opts="--all" --redact` with gitleaks 8.30.1 and the new `.gitleaks.toml`, run on 2026-09-29.

```text
138 commits scanned.
scanned ~45160232 bytes (45.16 MB) in 22.1s
leaks found: 40
```

Findings grouped by rule and file:

```text
1 generic-api-key    deploy/docker/.env.example
2 generic-api-key    local/.env.example
1 generic-api-key    local/opentofu/providers/gcp/tofu.tfvars
2 srdp-test-password docs/02-configuration.md
4 srdp-test-password docs/04-deployment.md
3 srdp-test-password docs/05-troubleshooting.md
3 srdp-test-password kubernetes/srdp-chart/values-local.yaml
8 srdp-test-password kubernetes/srdp-chart/values.yaml
1 srdp-test-password local/.env.example
1 srdp-tfvars-secret deploy/opentofu/gcp/tofu.tfvars
3 srdp-tfvars-secret local/opentofu/providers/gcp/tofu.tfvars
4 srdp-yaml-secret-key kubernetes/srdp-chart/values-local.yaml
2 srdp-yaml-secret-key kubernetes/srdp-chart/values-prod.example.yaml
5 srdp-yaml-secret-key kubernetes/srdp-chart/values.yaml
```

Every finding is one of the values in the known secrets table, or a placeholder such as `PASTE_THE_CLIENT_SECRET_YOU_COPIED_IN_PHASE_1`.
The only new location is the old `.env.example`, which held the same master key and cookie secret as the chart.

## Implementation notes

- The Scaleway `deploy/scaleway/envs/*/terraform.tfvars` files stay tracked through a `.gitignore` exception. They hold only sizing and network values, and their secrets are generated into Secret Manager. The tfvars gitleaks rule still scans them.
- gitleaks filters out obvious sequences, so the sample value `abcdefghijklmnopqrstuvwxyz123456` from the check above is not reported. Use a random 32-character value for that test instead.
