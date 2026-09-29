---
status: accepted
date: 2026-06-08
revised: 2026-09-27
decision-makers: Yannick Vinkesteijn
---

# Deployment and project isolation model

> **Revised 2026-09-27**, a material amendment: the catalog default changed from
> per-project to per-tenant (see "Project as a DuckLake catalog, tenant as the catalog default" and
> "Mapping onto DuckDB three-level naming" below), and the project-to-code-location relationship
> changed from 1:1 to a project being a bundle of any number of code locations, services, and
> endpoints (see [ADR-0011](./0011-project-onboarding-and-extension.md)). The original 2026-06-08
> decision (deployment as the isolation unit, catalogs over row/column security) still stands, what
> changed is the granularity below the deployment level.

## Context and Problem Statement

SRDP is a self-hostable data platform. A running instance holds data from multiple sources, the pipelines that process it, and the users who consume it. Two questions need a clear architectural answer before authorization (see [ADR-0005](./0005-authorization-and-data-access.md)) and the catalog layout (see [ADR-0003](./0003-data-catalog-lineage-and-observability.md), [ADR-0004](./0004-data-organization-and-ingestion.md)) can be finalized:

1. What is the unit of isolation? When SRDP serves more than one customer or domain, where is the boundary that separates one body of data from another?
2. How is data subdivided inside a single instance? A team's working set of sources and pipelines needs its own access boundary and its own slice of the catalog, without giving every team a full copy of the platform.

The answer drives the DuckLake catalog layout, the IO manager's asset-key mapping, and the granularity of access grants. It cannot stay implicit.

## Considered Options

1. Deployment is the isolation unit; a project is its own DuckLake catalog. One deployment is one data lake (sources, pipelines, users). Multiple customers means multiple deployments. Inside a deployment, data is divided into projects, and each project is a separate DuckLake catalog (its own metadata schema and storage prefix).
2. Single shared catalog per deployment; projects separated by a schema-naming convention. One catalog holds every project, kept apart by prefixing schema names.
3. Tenant partitioning within a shared data plane. One catalog and shared tables, with tenants separated by row or column scoping enforced at query time.

## Decision Outcome

Chosen option: "Deployment is the isolation unit; a project is its own DuckLake catalog", because it gives a hard isolation boundary between customers without a multi-tenant security model, and a clean, native subdivision inside a deployment that maps directly onto DuckDB's three-level naming. DuckLake and DuckDB have no per-row or per-column security, so any in-data-plane tenant separation (option 3) would have to be enforced entirely in application code over shared tables, which is both fragile and the wrong place for an isolation boundary.

> **Isolation vs. minimization.** The rejection above is about the *isolation* boundary between customers and projects, which stays hard (separate catalogs, separate deployments). It does **not** rule out fine-grained data *minimization* within a project, meaning which columns and rows a given consumer may see. [ADR-0008](./0008-identity-propagation-and-data-contracts.md) adds that via a constrained evaluator on mediated read paths.
>
> The two are different jobs. The evaluator is defence-in-depth inside the catalog boundary, never a replacement for it. A bug in it stays contained to within-project data and within-project principals, tenant boundaries hold regardless. Option 3 was rejected because it would make row/column scoping the isolation boundary, where that fragility is unacceptable. As a minimization layer, the isolation load stays entirely on the catalog boundary described above.

### Deployment as the isolation unit

One deployment is one data lake: a single set of sources, pipelines, and users that belong together. This keeps the strongest boundary (separate processes, separate storage, separate identity stack) between bodies of data that must not mix, and it means the platform never has to enforce cross-customer isolation inside a shared query engine.

**Multi-tenant deployments are the owner's choice.** A deployment is owned by one tenant (the deployment owner), which decides whether to stay single-tenant or admit additional tenants (see [ADR-0005](./0005-authorization-and-data-access.md)). Single-tenant per deployment remains the recommended default and the only configuration that gives hard isolation. When the owner admits multiple tenants, they are separated *inside* the deployment by catalog/project boundaries plus RBAC (and data contracts for shared data), which is softer than separate deployments; parties that must be hard-isolated still get their own deployments. This refines "serving multiple customers means multiple deployments" into a recommended default rather than a hard requirement, and does not reintroduce option 3: in-deployment separation is by catalog/project, never by row/column scoping over shared tables.

### Project as a DuckLake catalog, tenant as the catalog default

Inside a deployment, data is divided into projects. A project is a team's working set of sources and pipelines, and it is the unit of access (see [ADR-0005](./0005-authorization-and-data-access.md)). A project is a bundle, it can contain any number of Dagster code locations, services, and API endpoints, see [ADR-0011](./0011-project-onboarding-and-extension.md) for how a project registers what it contains. Client projects live in their own repositories and import `srdp` as a dependency (see [ADR-0001](./0001-platform-architecture-and-distribution.md)); `projects/cbs-example/` in the srdp repo is only a reference example, real client code lives in each project's own repository.

The catalog default is **per tenant**: a tenant's projects share one DuckLake catalog unless that tenant chooses to split one out. A dedicated catalog remains available per project when needed:

- its own metadata schema in the shared PostgreSQL catalog database (for example `ducklake_sales`),
- its own storage prefix (for example `DATA_PATH/sales/`),
- its own lifecycle: it can be created, granted, backed up, and retired independently.

Each project's IO manager resource is configured with whichever catalog it uses (the tenant's shared one by default, or its own once split out), so the catalog is supplied entirely by the code location's configuration, kept out of the asset key.

**Consequence for access control, stated plainly:** the "attach or detach, no row/column rules" grant boundary described below only holds at whatever level has its own catalog. Inside a shared tenant catalog, separating one project's data from another project in the *same* tenant is schema-scoped and application-enforced, a minimization concern (see the isolation-vs-minimization note above). The harder isolation guarantee belongs to a dedicated catalog instead. Splitting a project into its own catalog is how it moves from the softer tier to the harder one. This mirrors the same isolation-vs-minimization split this ADR already draws for the cross-tenant case, applied one level down, to projects within a tenant.

### Mapping onto DuckDB three-level naming

DuckDB supports exactly three levels: `catalog.schema.table`. Which two of the three carry the
project dimension depends on whether a project shares its tenant's catalog (the default) or has split
into its own:

| Level | Shared tenant catalog (default) | Dedicated project catalog (split out) |
|:---|:---|:---|
| catalog | tenant | project |
| schema | `project_layer` (e.g. `sales_raw`) | layer (e.g. `raw`) |
| table | entity (unchanged from ADR-0004) | entity (unchanged from ADR-0004) |

A dedicated catalog leaves [ADR-0004](./0004-data-organization-and-ingestion.md)'s fixed mapping
exactly as written: catalog = project, schema = the asset key's layer segment, table = the remaining
segments joined (`sales.raw.orders`). ADR-0004 gives project no role in the schema/table derivation at
all today, it comes entirely from which catalog is attached. Sharing a tenant catalog removes that free
project boundary: two projects both writing an asset key `["raw", "orders"]` would otherwise collide on
the identical `raw.orders` table inside the one shared catalog. The fix is a one-line addition to
ADR-0004's mapping for the shared case only: the physical schema name is the project name and the
layer joined (`sales_raw` instead of the bare layer name), resolved from the project's registered configuration
(ADR-0011), the asset key itself is untouched either way. ADR-0004's table derivation (domain segments
joined with `_`) is genuinely unchanged in both cases, only the schema level gains a project prefix,
and only when sharing a catalog.
A single-project deployment (such as the `projects/cbs-example/` reference) is just one catalog either
way, the distinction only matters once a tenant has more than one project.

### Multiple catalogs

DuckDB natively supports attaching multiple catalogs in a single connection. Beyond the tenant default described above, a deployment can attach additional catalogs as needed: a shared reference catalog (country codes, lookup tables), a catalog per medallion zone, a dedicated catalog for one project, or any other arrangement. This is purely deployment configuration. The platform does not restrict how catalogs are organized beyond the default recommendation.

### Access and the read path

Access grants are scoped to projects (see [ADR-0005](./0005-authorization-and-data-access.md)). For a
project with its own dedicated catalog, a user's read connection attaches only the catalogs they are
permitted to read, read-only, attach or detach, no row/column rules needed (see
[ADR-0002](./0002-api-and-access-strategy.md) for the read and write split). For a project sharing its
tenant's default catalog, the same grant is schema-scoped inside that one attached catalog instead, the
softer tier described above.

### Consequences

- Good, because customer isolation is a hard boundary (separate deployment) rather than an application-enforced policy over shared data.
- Good, because a project with a dedicated catalog gets a clean grant boundary: access is attach or detach, with no per-row or per-column rules to maintain in an engine that does not support them.
- Good, because the model fits DuckDB's three levels exactly (catalog, layer, entity) with no naming contortions, for a project that has split into its own catalog.
- Good, because a project's code locations, services, and endpoints are registered through ADR-0011, so the catalog dimension stays out of asset keys regardless of how many of each a project has.
- Good, because per-project lifecycle (create, back up, retire, set retention) is available on demand by splitting a project into its own catalog, without forcing every project to pay that overhead by default.
- Bad, because serving many small customers means many deployments to operate; this is a deliberate trade of per-instance overhead for isolation simplicity.
- Bad, because cross-project queries inside a deployment require attaching multiple catalogs and cannot assume a single namespace; shared reference data must be handled explicitly (for example a dedicated shared-reference catalog) rather than implicitly joined.

## Pros and Cons of the Options

### Single shared catalog, schema-name convention

- Good, because it is the least infrastructure: one catalog, one storage prefix.
- Bad, because the project boundary becomes a naming convention rather than an enforced boundary, so a misconfigured grant or query can cross it.
- Bad, because it consumes the schema level for project separation, leaving only two levels for layer and entity and forcing the medallion layers into table-name prefixes.

### Tenant partitioning within a shared data plane

- Good, because a single instance could serve many tenants with less per-tenant overhead.
- Bad, because DuckLake and DuckDB have no native row or column security, so the entire isolation boundary would live in application code over shared tables.
- Bad, because it puts the platform's hardest security guarantee in its most fragile place, and a single query bug becomes a cross-tenant data leak.
