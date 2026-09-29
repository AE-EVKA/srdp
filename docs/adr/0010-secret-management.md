---
status: accepted
date: 2026-09-29
decision-makers: Thomas Start
---

# Secret management

## Context and Problem Statement

The repository is public, so any value that reaches the git history is readable by anyone and may already be copied.
Several working secrets were committed in the past: a GCP tfvars file, the Helm chart values, a Compose example file and the docs.
The same oauth2-proxy cookie secret was reused across three files and several environments, so one leak opened all of them.
Removing a value from the files does not make it secret again, and rewriting history does not undo a copy.

This ADR decides where a secret lives in each environment, what git is allowed to hold, and how a new secret enters the platform.

## Decision Outcome

A secret has exactly one home per environment, and that home is never a tracked file.

| Environment | Where the secret value lives | How it reaches the app |
|:---|:---|:---|
| Docker Compose | `deploy/docker/.env`, which is gitignored and filled from `.env.example` | Compose reads it as environment variables. |
| kind | A gitignored file (for example `deploy/kubernetes/srdp-chart/values-secrets.local.yaml`), generated with random values by a `just local-secrets` recipe | The chart's local Secret template renders it into Kubernetes Secrets. |
| Scaleway (dev, and later stage and prod) | Scaleway Secret Manager, filled by OpenTofu or by hand | External Secrets creates the Kubernetes Secrets. |
| OpenTofu variables | The shell, as `TF_VAR_<name>`, or a gitignored `*.tfvars` | OpenTofu reads them at plan time. |

Git holds only three kinds of things.

- An example file with empty values or `XXXX` placeholders, which documents what is needed.
- The name of a Secret and its keys, which the chart refers to with `existingSecret` or `secretKeyRef`.
- The gitleaks rules in `.gitleaks.toml` that guard all of the above.

### Rules

- **Every environment generates its own values.** No value is copied from one environment to another, so a leak in one never opens another.
- **Local values are random, not memorable.** A generator recipe creates them, so no shared development password starts being reused.
- **A new secret follows a fixed path.** It gets a key in the example file, a Secret name in the chart, an entry in Secret Manager for the cloud, and a row in the secret table of the chart parity ticket. The pull request template asks for this with a checkbox.
- **A leaked secret is rotated before it is removed.** Rotation is the real fix, and removal only stops the next leak.
- **CI is the last line.** gitleaks runs in pre-commit and on every PR with rules that match this repo, so a mistake is caught before it reaches `main`.

### Where each part lands

- Tracked files outside the Helm chart are cleaned up by ticket 00 of the Scaleway deployment plan.
- The chart moves its values into Secrets, including the kind local Secret template and `just local-secrets`, in ticket 01 PR 1b. That PR also narrows the gitleaks allowlist for the chart values.
- Scaleway Secret Manager and External Secrets arrive with ticket 4.

### Consequences

- Good, because a leak is contained to one environment and one value.
- Good, because gitleaks blocks the known secret shapes of this repo at commit time and in CI.
- Bad, because every contributor with an existing local setup must regenerate their gitignored files once.
- Bad, because the gitleaks allowlist must be kept narrow by hand. A path is added only one file at a time.
