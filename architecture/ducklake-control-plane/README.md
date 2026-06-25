# Phoenix Lake — Design

A "minimum viable lakehouse" built around Elixir as the control plane and DuckDB
as the analytical engine. The goal is fewer moving parts than a Spark / Glue /
Athena / Airflow stack, while still giving SQL, Parquet, snapshots, and object
storage.

This is a greenfield design sketch. It is **not** a replacement for the existing
Iceberg + Athena + Glue platform. It targets workloads where the largest query
intermediate fits comfortably in one machine's RAM and concurrency is bounded —
internal analytics, operational BI, embedded reporting, small-tomid data marts.

## The shape

```
Phoenix                 DuckDB Service           Postgres            S3
 ├─ API                  ├─ Query execution       ├─ App metadata     ├─ staging/ (enforced)
 ├─ LiveView             ├─ Data ingestion        ├─ DuckLake:        ├─ landing/ (enforced)
 ├─ Oban                 ├─ dbt transformation    │   ├─ landing      ├─ refining/ (enforced)
 └─ Auth                 └─ Parquet management    │   ├─ refining     └─ reporting/ (enforced)
                                                 │   └─ reporting
```

Each component is aligned to its strength:

- **Elixir / Phoenix** — long-lived workflows, concurrency, real-time UI, auth, orchestration.
- **DuckDB** — columnar scans, joins, aggregations, Parquet read/write. Executes dbt models.
- **Postgres** — transactions, app metadata, and three DuckLake catalogs (landing, refining, reporting) — snapshots, schema, file lists.
- **S3** — a plain S3 prefix (staging) for incoming files, plus three enforced DuckLake databases (landing, refining, reporting) for data storage.

## How data flows

1. **Ingestion** — producers drop Parquet files into `s3://<bucket>/staging/<table>/`. The ingestion worker validates, promotes to `landing`, and publishes a DuckLake snapshot.
2. **Query** — small queries run synchronously against DuckDB; expensive ones become Oban jobs. DuckDB reads the current snapshot from the catalog and scans only the needed Parquet.
3. **Transformation** — dbt models read from `landing` via `source()`, transform data, and write to `refining` or `reporting`. Each run publishes a new DuckLake snapshot.

The invariant across all three: **write immutable Parquet first, then publish via a Postgres transaction.** Readers always see a consistent snapshot.

## Database template

Every project gets three DuckLake databases with a fixed naming convention, defined in a `ducklake.yml` at the repo root:

```yaml
layers:
  landing:
    description: "Raw validated data from ingestion"
    retention_days: 90
    partition_columns: [...]
  refining:
    description: "Transformed and enriched data"
    retention_days: 180
    partition_columns: [...]
  reporting:
    description: "Materialized aggregations for consumption"
    retention_days: 30
    partition_columns: []
```

The platform reads this file to provision databases, set retention policies, and validate dbt projects.

## dbt integration

Users bring their own dbt models via Git-synced repos. The platform provides the execution environment; the user provides the SQL.

- **User provides** — GitHub/GitLab repo with `dbt_project.yml`, `ducklake.yml`, and model SQL files.
- **Platform provides** — DuckDB execution, S3 credentials, DuckLake connections, `profiles.yml` generation, resource isolation, scheduling, and retry logic.

Models must follow the enforced template: `source()` targets `landing`, `ref()` targets `refining` or `reporting`.

## Documents

- [01 — Architecture](01-architecture.md) — layers, responsibilities, and the rationale for each boundary.
- [02 — Phoenix application](02-phoenix-app.md) — API, LiveView, Oban, Auth.
- [03 — DuckDB service](03-duckdb-service.md) — query execution, ingestion, dbt transformation, Parquet management, process isolation.
- [04 — Postgres & DuckLake catalog](04-postgres-ducklake.md) — app metadata and three DuckLake catalogs in one database.
- [05 — S3 storage](05-s3-storage.md) — plain S3 staging prefix, three-layer database template, partitioning, snapshots.
- [06 — Data flows](06-data-flows.md) — ingestion, query, and transformation paths end to end.
- [07 — Scaling boundaries](07-scaling-boundaries.md) — where this design breaks and when to reach for a distributed engine.
- [08 — Design validation](08-validation.md) — the design checked against current DuckLake/DuckDB docs, with sources.
- [09 — dbt integration](09-dbt-integration.md) — Git-synced workflow, template YAML, project conventions, isolation.
- [10 — Partitioning strategy](10-partitioning-strategy.md) — partition strategies by table type, grain selection, DuckLake-specific behavior.
