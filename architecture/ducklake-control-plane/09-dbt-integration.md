# 09 — dbt integration

Users bring their own dbt models via a Git-synced workflow. The platform
provides the execution environment; the user provides the SQL.

## How it works

A user connects a GitHub or GitLab repository containing a standard dbt project.
The platform pulls the repo and runs `dbt run` inside an Oban worker — **no
local DuckDB**. A thin custom adapter submits each model's compiled SQL to the
DuckDB service over HTTP, which executes it and writes results to the refining
or reporting catalog. Users get the full dbt
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
4. Platform provisions catalogs from the template and triggers the first run.

The three catalogs (landing, refining, reporting) are created automatically by
the platform from the template YAML.

## Template YAML

Every dbt project must include a `ducklake.yml` at the repo root. This file
defines the three layers and is the source of truth for catalog provisioning.
The platform reads it and creates the catalogs accordingly.

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

- Create the three DuckLake catalogs in Postgres with the correct S3 data
  paths.
- Set snapshot retention policies per catalog.
- Validate that dbt models write to the correct layer with the expected
  partition structure.
- Generate the `profiles.yml` pointing dbt at the DuckDB service over HTTP
  (see [Platform execution](#platform-execution)).

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
   landing catalog. Cross-catalog reads from refining or reporting are not
   allowed as sources.
6. **All `ref()` outputs target `refining` or `reporting`** — models write to
   one of the two downstream catalogs. Writes to landing are not allowed.
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
4. The worker generates a `profiles.yml` that points dbt at the DuckDB service
   over HTTP using a thin custom adapter (a small fork of `dbt-duckdb` that
   overrides only the connection layer):
   ```yaml
   default:
     outputs:
       dev:
         type: duckdb_service        # custom adapter (dbt-duckdb fork)
         host: duckdb-service         # DuckDB service HTTP endpoint
         port: 8080
         # S3 credentials and data paths are injected by the service; the service
         # has all three DuckLake catalogs (landing, refining, reporting) ATTACHed.
   ```
   Because the service has all three catalogs ATTACHed, `source('landing', ...)`
   and `ref()` resolve to catalog-qualified names the service routes correctly —
   there is no per-run `dbname` switch. The adapter inherits all of `dbt-duckdb`'s
   semantics (DuckDB dialect, DuckLake `ATTACH`, `external` materialization) and
   only swaps the transport: it submits compiled SQL over HTTP instead of opening
   a local DuckDB connection.
5. The worker runs `dbt run` (or `dbt build` for models + tests). The custom
   adapter submits each model's SQL to the DuckDB service over HTTP. The service
   executes it against the ATTACHed DuckLake catalogs and serializes writes
   through its per-table writer queue.
6. dbt reads from `landing` via `source()`, writes to `refining` or `reporting`
   via `ref()` or `external` materialization.
7. Each model write publishes a new snapshot in the target catalog — same
   write-then-publish invariant as ingestion.
8. Worker records success/failure, broadcasts results over PubSub, and cleans up
   the temporary directory.

**Key architectural decision:** The Oban worker is stateless — it runs `dbt`
but **no local DuckDB**. All compute happens in the long-running DuckDB service.
A thin custom dbt adapter is the only bridge: it submits compiled SQL over HTTP
and returns results. DuckDB is never embedded in the BEAM or the Oban worker.

## dbt project conventions

Users follow these conventions so the platform can run their project without
custom configuration:

**Sources point at landing:**
```sql
-- models/staging/stg_orders.sql
{{ config(materialized='view') }}

select * from {{ source('landing', 'orders') }}
```

**dbt_project.yml maps catalogs:**
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
| DuckLake catalog connections | Platform |
| profiles.yml generation | Platform |
| Execution isolation and resource limits | Platform |
| Scheduling and retry logic | Platform |
| Model SQL and business logic | User |
| dbt_project.yml and model structure | User |
| Git repo and version control | User |

## Isolation and resource limits

Each dbt run executes in an Oban worker that submits SQL to the long-running
DuckDB service (there is no per-run DuckDB process):

- **Memory cap** — the DuckDB service enforces `DUCKDB_MEMORY_LIMIT` per query
  so a heavy model cannot exhaust the service (or its container).
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

## Scheduling and test results

- **Triggers** — runs start on git push/webhook, a manual trigger from the UI, or
  a per-project cron schedule. The cron expression is editable in the project's
  dbt settings page (LiveView), stored on the project row, and enforced by Oban's
  cron engine. Default is manual-only (no schedule), so nothing runs until the
  user opts in.
- **`dbt build` tests** — when a run uses `dbt build`, model tests execute after
  each model. Pass/fail/skip counts and per-test failure messages are captured
  from dbt's run-artifacts JSON, stored on the job row, and surfaced in the
  run-detail LiveView (a Tests tab alongside Models). A failing test blocks that
  model's downstream publishes per dbt's default indirect-selection semantics;
  the user sees which tests failed and against which rows.
- **Run history** — each run's status, duration, models built, and test results
  are retained per project and shown in a runs list, with the latest outcome
  broadcast over PubSub for live updates.

## Incremental models

dbt Core v2 (Fusion) supports incremental strategies (`merge`, `append`,
`delete+insert`, `microbatch`) on DuckLake tables. The platform supports these
out of the box — no special configuration needed. `microbatch` is particularly
effective for partitioned DuckLake tables.

## What is not supported (yet)

- **dbt sources from refining/reporting** — users can only source from landing.
  Cross-layer dependencies (refining → reporting) use `ref()` instead.
