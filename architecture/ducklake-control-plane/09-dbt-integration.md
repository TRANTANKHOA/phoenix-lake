# 09 — dbt integration

Users bring their own dbt models via a Git-synced workflow. The platform
provides the execution environment; the user provides the SQL.

## How it works

A user connects a GitHub or GitLab repository containing a standard dbt project.
The platform pulls the repo, runs `dbt run` in an isolated DuckDB process, and
writes results to the refining or reporting database. Users get the full dbt
experience — version control, PRs, CI, `dbt docs`, lineage — while the platform
handles execution and storage.

```
User's repo (GitHub/GitLab)
  └── dbt_project.yml
  └── models/
      └── staging/        ← sources from landing
      └── marts/          ← outputs to refining
      └── reporting/      ← outputs to reporting (external materialization)
```

## User-facing setup

1. User connects their GitHub/GitLab repo via the Phoenix UI (OAuth or deploy
   key).
2. User selects which branch to sync (default: `main`).
3. Platform clones the repo and validates the dbt project against the enforced
   template (see validation below).
4. Platform provisions databases from the template and triggers the first run.

The three databases (landing, refining, reporting) are created automatically by
the platform from the template YAML.

## Template YAML

Every dbt project must include a `ducklake.yml` at the repo root. This file
defines the three layers and is the source of truth for database provisioning.
The platform reads it and creates the databases accordingly.

```yaml
# ducklake.yml
layers:
  landing:
    description: "Raw validated data from ingestion"
    retention_days: 90
    partition_columns:
      - name: year
        expression: "year(ordered_at)"
      - name: month
        expression: "month(ordered_at)"
      - name: day
        expression: "day(ordered_at)"

  refining:
    description: "Transformed and enriched data"
    retention_days: 180
    partition_columns:
      - name: year
        expression: "year(ordered_at)"
      - name: month
        expression: "month(ordered_at)"

  reporting:
    description: "Materialized aggregations for consumption"
    retention_days: 30
    partition_columns: []
```

**Field reference:**

| Field | Required | Description |
|---|---|---|
| `layers.<name>.description` | yes | Human-readable description shown in the UI |
| `layers.<name>.retention_days` | no | Snapshot retention policy (default: 90) |
| `layers.<name>.partition_columns` | no | Partition columns applied during writes |

The platform uses this file to:

- Create the three DuckLake databases in Postgres with the correct S3 data
  paths.
- Set snapshot retention policies per database.
- Validate that dbt models write to the correct layer with the expected
  partition structure.
- Generate the `profiles.yml` with the correct `attach` entries.

## Template validation

When a dbt project is registered (and on each subsequent sync), the platform
validates it against the enforced template:

**`ducklake.yml` validation:**
1. **File exists** at the repo root and is valid YAML.
2. **All three layers are defined** — `landing`, `refining`, `reporting`.
3. **Required fields present** — each layer has a `description`.

**dbt project validation:**
4. **`dbt_project.yml` exists** and is parseable.
5. **All `source()` references target `landing`** — models may only read from the
   landing database. Cross-database reads from refining or reporting are not
   allowed as sources.
6. **All `ref()` outputs target `refining` or `reporting`** — models write to
   one of the two downstream databases. Writes to landing are not allowed.
7. **Reporting models use `external` materialization** — models targeting
   reporting must write Parquet to `s3://<bucket>/reporting/...` via the
   `external` materialization strategy.
8. **No hardcoded S3 paths or credentials** — the platform injects S3 secrets
   and data paths; user models must not reference them directly.

If validation fails, the project is rejected with a clear error message
explaining which rule was violated and how to fix it. The project is not run
until it passes validation.

## Platform execution

When a run is triggered (by git push, webhook, cron schedule, or manual trigger):

1. Phoenix enqueues an Oban job on the `transform` queue (unique by project_id,
   replace args if pending). If a dbt run is already active for this project,
   the new push replaces the waiting job's args — latest push always wins.
2. The worker clones or pulls the user's repo to a temporary directory.
3. The worker validates the project against the template (same checks as
   registration). If validation fails, the job fails immediately with a clear
   error.
4. The worker generates a `profiles.yml` that connects to the DuckDB service
   via Postgres wire protocol (through load balancer):
   ```yaml
   default:
     outputs:
       dev:
         type: postgres
         host: duckdb-lb
         port: 5432
         dbname: landing
         user: duckdb
         pass: duckdb
   ```
   Multiple databases (landing, refining, reporting) are handled by switching
   the `dbname` or using schema prefixes — the DuckDB service routes to the
   correct catalog.
5. The worker runs `dbt run` (or `dbt build` for models + tests). dbt submits
   SQL to the DuckDB service via Postgres wire protocol. The service handles
   execution across multiple DuckDB containers.
6. dbt reads from `landing` via `source()`, writes to `refining` or `reporting`
   via `ref()` or `external` materialization.
7. Each model write publishes a new snapshot in the target catalog — same
   write-then-publish invariant as ingestion.
8. Worker records success/failure, broadcasts results over PubSub, and cleans up
   the temporary directory.

**Key architectural change:** The Oban worker is stateless — it does not run
DuckDB locally. All compute happens in the DuckDB service. Workers just run
dbt which submits SQL to the service.

## dbt project conventions

Users follow these conventions so the platform can run their project without
custom configuration:

**Sources point at landing:**
```sql
-- models/staging/stg_orders.sql
{{ config(materialized='view') }}

select * from {{ source('landing', 'orders') }}
```

**dbt_project.yml maps databases:**
```yaml
name: 'my_project'
version: '1.0.0'

models:
  my_project:
    staging:
      +schema: landing
    marts:
      +schema: refining
```

**Reporting models use external materialization:**
```sql
-- models/reporting/daily_revenue.sql
{{ config(
    materialized='external',
    location='s3://<bucket>/reporting/daily_revenue/',
    format='parquet',
    partition_by=['year', 'month']
) }}

select
  date_trunc('day', ordered_at) as day,
  sum(amount) as total_revenue
from {{ ref('fct_orders') }}
group by 1
```

## What the platform controls

| Concern | Owner |
|---|---|
| DuckDB version and extensions | Platform |
| S3 credentials and secrets | Platform |
| DuckLake database connections | Platform |
| profiles.yml generation | Platform |
| Execution isolation and resource limits | Platform |
| Scheduling and retry logic | Platform |
| Model SQL and business logic | User |
| dbt_project.yml and model structure | User |
| Git repo and version control | User |

## Isolation and resource limits

Each dbt run executes in a short-lived, isolated DuckDB process:

- **Memory cap** — the worker sets `DuckDB_MEMORY_LIMIT` per run so a heavy
  model cannot exhaust the host.
- **Timeout** — Oban job timeout kills runaway runs; the user can configure a
  per-project timeout in the UI (default: 30 minutes).
- **One writer per table** — the platform serializes writes to the same
  partition of the same table, preventing concurrent dbt runs from conflicting.
- **Temp directory cleanup** — the cloned repo and any local artifacts are
  deleted after each run, regardless of success or failure.

## Failure handling

- **dbt run fails** — the Oban job records the error, broadcasts it via PubSub,
  and surfaces it in the LiveView UI. No partial writes are published (dbt
  atomicity per model).
- **Git pull fails** — the job retries with backoff; after 3 consecutive
  failures, the user is notified.
- **Schema mismatch** — if a model reads from a landing table whose schema has
  changed, dbt fails with a clear error. The user fixes the model and pushes a
  new commit.

## Incremental models

dbt Core v2 (Fusion) supports incremental strategies (`merge`, `append`,
`delete+insert`, `microbatch`) on DuckLake tables. The platform supports these
out of the box — no special configuration needed. `microbatch` is particularly
effective for partitioned DuckLake tables.

## What is not supported (yet)

- **dbt sources from refining/reporting** — users can only source from landing.
  Cross-layer dependencies (refining → reporting) use `ref()` instead.
