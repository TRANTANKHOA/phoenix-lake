# 05 — S3 storage

The platform enforces a three-layer template. Every project gets three DuckLake
catalogs with a fixed naming convention. Users don't choose the structure —
they choose what to put in it.

```
landing/     →  raw, validated data (source of truth for incoming data)
refining/    →  transformed, enriched, joined (dbt models live here)
reporting/   →  materialized aggregations for consumption
```

Each catalog is auto-created by the platform:

```sql
-- ⚠ verify exact ATTACH parameters against the current DuckLake (v1.x) syntax.
ATTACH 'ducklake:postgres:dbname=phoenix_lake' AS landing
  (DATA_PATH 's3://<bucket>/landing/',   METADATA_SCHEMA 'ducklake_landing');
ATTACH 'ducklake:postgres:dbname=phoenix_lake' AS refining
  (DATA_PATH 's3://<bucket>/refining/',  METADATA_SCHEMA 'ducklake_refining');
ATTACH 'ducklake:postgres:dbname=phoenix_lake' AS reporting
  (DATA_PATH 's3://<bucket>/reporting/', METADATA_SCHEMA 'ducklake_reporting');
```

Staging is not a catalog — it is a plain S3 prefix managed by the ingestion
worker. The flow is: staging → landing (enforced), then landing → refining →
reporting (user-driven via dbt or materialization jobs).

### Landing

Raw but validated data. The ingestion worker promotes files from staging here,
applying partition layout. The DuckLake catalog manages snapshots of this layer.
Readers query landing tables directly for raw analytics. This is the system's
source of truth for incoming data.

### Refining

Transformed and enriched data. dbt models (or DuckDB transformation jobs) read
from landing, apply joins, filters, aggregations, and business logic, and write
results here as new DuckLake tables. Refining tables are catalog-managed and
support the same snapshot semantics as landing.

### Reporting

Materialized aggregations and pre-computed results for dashboards and
downstream consumers. Scheduled Oban jobs or dbt `external` materializations
refresh these tables on a cadence. Reporting tables are catalog-managed;
readers always see the latest published snapshot with no downtime during
refresh.

## Layout principles

- **Partition by the columns queries filter on** — typically date and a small
  number of high-selectivity dimensions (region, tenant). Good partitioning lets
  DuckDB prune most files before reading any bytes, which is what keeps
  single-node scans fast even over large tables.
- **Right-size files** — aim for files large enough to scan efficiently but small
  enough to parallelise across cores. Many tiny files destroy scan throughput;
  compaction (run by the DuckDB service) exists to fix this.
- **Treat files as immutable** — updates and deletes produce new files and a new
  snapshot rather than mutating existing objects. This is what makes snapshots,
  time travel, and concurrent reads safe.

## Snapshots and cleanup

- Each published snapshot references a specific set of files. Older snapshots keep
  referencing their older files, enabling time travel and safe concurrent reads
  during a write.
- A retention policy expires old snapshots. Once no live snapshot references a
  file, a cleanup job deletes it from S3 to reclaim storage.
- Cleanup is always catalog-driven: a file is deleted only after the catalog
  confirms nothing points at it.
- Staging files are not catalog-managed; they are cleaned up by the ingestion
  worker after promotion or on a TTL-based sweep.
- Each catalog can have independent retention and compaction policies — landing
  may keep 90 days of snapshots while reporting keeps 30.

### Retention — mechanism, defaults, and owner

Retention is a two-phase DuckLake maintenance job, run per catalog:

1. **Snapshot expiry.** `CALL ducklake_expire_snapshots('<catalog>',
   older_than => now() - INTERVAL '<retention>')` is the only way data is
   physically removed from DuckLake — it drops the time-travel reference to
   snapshots older than the retention window. (Both phases accept
   `dry_run => true` for a pre-flight report.)
2. **File cleanup.** Expiring snapshots does *not* delete files on its own: files
   no longer referenced by any live snapshot are first staged in
   `ducklake_files_scheduled_for_deletion`, then
   `CALL ducklake_cleanup_old_files('<catalog>', older_than => now() - INTERVAL '<grace>')`
   physically deletes them after a grace window so in-flight reads stay safe.

**Owner.** Per the locked topology, Phoenix schedules these as Oban cron jobs on
the `maintenance` queue and submits the SQL over HTTP; the long-running DuckDB
service — which holds the catalog writer handle — executes the `CALL`. Staging
files fall outside this path: the ingestion worker sweeps them on a TTL.

**Defaults (proposed — confirm at build).**

| Catalog | Snapshot retention | Rationale |
|---------|--------------------|-----------|
| landing | 90 days | raw source of truth; long time-travel / recovery window |
| refining | 90 days | matches landing; a bad dbt run stays recoverable |
| reporting | 30 days | rebuilt on a cadence; short history suffices |

- **File-cleanup grace:** 7 days after a file is staged for deletion (DuckLake
  recommends "more than a few days"; 7 d exceeds any expected read transaction).
- **Cadence:** daily, in the maintenance window.
- **Config:** `snapshot_retention_days` per catalog plus a global
  `file_cleanup_grace_days`, in config (env-overridable), surfaced in the catalog
  admin UI.

> **Verify against the installed DuckLake version.** The
> `ducklake_expire_snapshots` / `ducklake_cleanup_old_files` table functions and
> the `ducklake_files_scheduled_for_deletion` table are the current DuckLake
> maintenance APIs
> (<https://ducklake.select/docs/stable/duckdb/maintenance/expire_snapshots.html>,
> <https://ducklake.select/docs/stable/duckdb/maintenance/cleanup_old_files.html>);
> re-confirm signatures against the pinned version before code depends on them.

## Why this is cheap and scalable

Storage is fully decoupled from compute. Data volume grows on S3 independently of
how much DuckDB compute is running, and many DuckDB processes can read the same
Parquet concurrently with no coordination — they each just read the immutable
files their snapshot names.
