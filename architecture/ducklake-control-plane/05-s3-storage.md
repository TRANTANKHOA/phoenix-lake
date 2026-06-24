# 05 — S3 storage

The platform enforces a three-layer template. Every project gets three DuckLake
databases with a fixed naming convention. Users don't choose the structure —
they choose what to put in it.

```
landing/     →  raw, validated data (source of truth for incoming data)
refining/    →  transformed, enriched, joined (dbt models live here)
reporting/   →  materialized aggregations for consumption
```

Each database is auto-created by the platform:

```sql
CREATE DATABASE landing   (TYPE ducklake, DATA_PATH 's3://<bucket>/landing/');
CREATE DATABASE refining  (TYPE ducklake, DATA_PATH 's3://<bucket>/refining/');
CREATE DATABASE reporting (TYPE ducklake, DATA_PATH 's3://<bucket>/reporting/');
```

Staging is not a database — it is a plain S3 prefix managed by the ingestion
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
- Each database can have independent retention and compaction policies — landing
  may keep 90 days of snapshots while reporting keeps 30.

## Why this is cheap and scalable

Storage is fully decoupled from compute. Data volume grows on S3 independently of
how much DuckDB compute is running, and many DuckDB processes can read the same
Parquet concurrently with no coordination — they each just read the immutable
files their snapshot names.
