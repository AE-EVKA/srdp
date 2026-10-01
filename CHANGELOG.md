# Changelog

All notable changes to SRDP are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- `S3StorageBackend` stores the DuckLake data files in S3-compatible object storage (Scaleway, Hetzner, MinIO) when `DUCKLAKE_STORAGE_BACKEND=s3` is set. Its settings live in their own `S3StorageSettings` (`DUCKLAKE_S3_*`), apart from the Postgres catalog settings. Endpoint, URL style and region are required, with no AWS defaults, and the DuckDB secret is scoped to the lake prefix. The default stays `local`, so nothing changes without the setting. Part of #56.
- `srdp.io.dbt_plugin`, a dbt-duckdb plugin that attaches DuckLake with the same storage settings as Dagster, so a dbt profile no longer needs its own copy of them.
- `S3StorageBackend.dlt_filesystem_config()` renders the same bucket, endpoint and key for a dlt filesystem destination.

### Security

- A DuckLake settings error no longer prints the values it was given, so a misconfigured start cannot write the Postgres password or the S3 secret to the logs.

### Changed

- CI installs the `dbt` extra, so `ty` can resolve the dbt-duckdb plugin's imports.

## [0.3.1] - 2026-09-27

### Fixed

- `README.md` (the content PyPI renders as the project description) rewritten to be accurate and professional. It previously claimed Quarto and dlt as active components, Quarto is optional and disabled by default, dlt isn't integrated yet.
- Duplicated content between `README.md` and `docs/index.md` removed. `README.md` is now a short intro linking to the docs site instead of a second copy of the component table, so the two can't drift out of sync again.

### Added

- `docs/00-about.md`: the original tone-of-voice component roster (credit: Daniel Kapitan), preserved and moved out of `README.md`/`docs/index.md` rather than deleted.

### Documentation

- Branch-naming and CHANGELOG-entry requirements added to `CONTRIBUTING.md`/`AGENTS.md`/the PR template.

## [0.3.0] - 2026-09-27

### Security

- Traefik no longer mounts the Docker socket. Routing moved from Docker label auto-discovery to a static file provider (`config/traefik/traefik.yml`), since a read-only socket mount does not restrict the Docker API reachable through it.

### Added

- OpenLineage bridge emits Dagster run and asset events to Marquez for lineage tracking.
- `cbs-example` project (renamed from `default-etl`): a dbt pipeline, income enrichment assets, a Marimo notebook with a push-based enrichment demo, and a Streamlit dashboard.
- Core FastAPI surface (`srdp.api`): catalog reads, Dagster status, and a bearer-token page for calling the API outside the browser.
- DuckDB UI reverse-proxied through Traefik, with its own background API calls exempted from the SSO redirect rewrite.
- Static hub landing page linking every platform service.
- Idempotent Zitadel OIDC redirect-URI provisioning script (`deploy/docker/provision-oidc.sh`).
- Local Kubernetes testing via `kind`, replacing Colima's built-in k3s.
- DuckLake IO manager wired into both the Helm chart and the Docker Compose deployment targets.
- Release management: `scripts/release.sh`, and GitHub Actions workflows that draft GitHub Releases and publish to PyPI via Trusted Publishing.
- ADRs on RBAC and authentication accepted; other ADRs updated for compliance.

### Changed

- Local domains renamed from `*.local.dev` to `*.srdp.localhost`. The `.localhost` TLD auto-resolves to loopback, so no `/etc/hosts` edit is needed.
- Quarto removed from the default stack.
- Marquez, the API, DuckDB UI, and the hub wired into `docker-compose.yml`, with database passwords externalized.

### Fixed

- Dagster module name corrected in `values-local.yaml`.
- `dagster` made executable in the Dockerfile without `uv run` by adding the venv to `PATH`.

### Documentation

- `cbs-example` README documents the built architecture.
- All `local.dev` references updated to `srdp.localhost`.

### Dependencies

- CVE remediation dependency upgrades.
- `api`, `dbt`, `openlineage`, and `dagster-postgres` extras added, build-system pinned, `python<3.13` pinned.

## [0.2.0] - 2026-06-12

### Changed

- Restructured the repository into a monorepo layout: platform library in `src/srdp/`, client ETL projects in `projects/`, service images in `services/`, and all deployment manifests under `deploy/` (Docker Compose, Helm chart, OpenTofu). Prior layout had these spread across `docker/`, `kubernetes/`, and `docker/apps/`.
- Expanded `just` task runner with recipes for local dev, production deployment, linting, testing, and CI.
- Updated `AGENTS.md` with comprehensive coding conventions for contributors and AI assistants.

### Added

- `src/srdp/io/ducklake.py` provides the DuckLake IO manager, backed by DuckDB and PostgreSQL.
- `src/srdp/io/storage.py` defines the abstract storage backend interface. Only the local filesystem implementation exists so far. Azure and S3 backends are tracked separately.
- `src/srdp/resources/k8s.py` defines Kubernetes resource definitions for Dagster.
- `pyproject.toml` sets up a proper monorepo package with `uv`.
- Architecture decision records (ADRs) in `docs/adr/` covering platform architecture, deployment model, auth, compute, and data organization.
- `.github/instructions/` holds domain-specific coding instructions for Python, Dagster, and deploy targets.
- `SECURITY.md`, `CONTRIBUTING.md`, issue templates, and PR template.

## [0.1.0] - 2024-01-01

Initial release.

[Unreleased]: https://github.com/srdp-hub/srdp/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/srdp-hub/srdp/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/srdp-hub/srdp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/srdp-hub/srdp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/srdp-hub/srdp/releases/tag/v0.1.0
