# 06 — Data flows

Three paths exercise the whole system: ingestion, query, and transformation.
Each one shows how the control plane, data plane, Postgres, and S3 cooperate.

## Ingestion

The ingestion path accepts flat Parquet files delivered to a staging S3 prefix
and promotes them into the **landing** DuckLake database.

**Ingestion is append-only.** The ingestion worker validates schema conformance
and row limits, then promotes files as-is. It does not clean, deduplicate,
filter, or transform data. Data cleaning happens in dbt models during the
transformation step. This keeps ingestion fast, predictable, and idempotent.

**Staging conventions.** The target table is inferred from the staging path —
the last segment after `staging/` is the table name (e.g.
`s3://<bucket>/staging/orders/file.parquet` → table `orders`). Files are
preferably named `<YYYYMMDD>_<HHMMSS>_<uuid4>.parquet`, where the timestamp is
the ingestion time. If the filename doesn't match this pattern, the worker
extracts the timestamp from Parquet file metadata (row group statistics or
custom metadata fields). Non-conforming names are tolerated — the worker
processes any valid Parquet file regardless of naming. All files land flat in
the table's staging prefix with no sub-directory structure.

**Deduplication.** Ingestion is idempotent. Multiple layers prevent duplicate
data:

- **UUID in filename** — the `<uuid4>` in the naming pattern guarantees each
  file has a unique identity. Two producers writing to the same table cannot
  produce the same filename.
- **Oban job uniqueness** — the ingest job is configured with `unique` by args
  (table name + filename). If the same file is detected twice, the second job
  is discarded.
- **Catalog-level idempotency** — promoting a file that is already in the
  landing catalog is a no-op. The worker checks the catalog for the file's
  S3 path before writing; duplicates are skipped.
- **ACID transactions** — the catalog update is atomic. A partial ingestion
  that fails before commit leaves no trace; a retry produces the same result.

**Schema evolution.** DuckLake supports files with different schemas in the same
table via field identifiers. Each column has a unique `field_id` stored in the
catalog and in each Parquet file's metadata. When reading, DuckLake maps
columns by `field_id`, not by name or position. This means:

- Files with additional columns are readable — missing columns return NULL.
- Files with fewer columns are readable — extra columns are ignored.
- Columns renamed or type-promoted are handled transparently.

This validates append-only ingestion: producers can evolve their schema
independently, and DuckLake reconstructs the correct table view per snapshot
without rewriting any files.

1. A producer writes one or more Parquet files to the staging prefix for the
   target table (e.g. `s3://<bucket>/staging/orders/`).
2. A scheduled Oban job or S3-triggered event detects new files and enqueues an
   ingest job on the `ingest` queue.
3. The DuckDB ingestion worker reads the staged files, validates schema
   conformance and row limits, then promotes them to the landing database —
   applying partition layout (e.g. `year=2026/month=06/day=15/`) based on
   partition columns in the data.
4. In one Postgres transaction, the landing catalog is updated to publish a new
   snapshot referencing the promoted files.
5. The job records success, cleans up the staging files, and broadcasts an event
   over PubSub; any LiveView watching the dataset updates live.

Until step 4 commits, readers see the previous snapshot. Ingestion is never
observed half-applied. Files that fail validation stay in staging for inspection.

## Query

**Interactive (small, bounded):**

1. A request hits the API or a LiveView action.
2. Phoenix authorizes it and scopes it to the tables the caller may read.
3. Phoenix calls the DuckDB service synchronously.
4. DuckDB reads the current snapshot's file list from the catalog, prunes
   partitions, scans only the needed Parquet from S3, and streams rows back.
5. Phoenix forwards the stream to the client or renders it in LiveView.

**Expensive (unbounded):**

- Same start, but at step 3 Phoenix enqueues an Oban job instead of calling
  synchronously, and returns a handle. Results are delivered via PubSub/polling
  when ready. This is the guard that keeps a heavy query off the web path.

## Transformation

All transformations go through dbt. Users write models that read from landing,
transform, and write to refining or reporting. Each dbt run is an Oban job on
  the `transform` queue: DuckDB executes the model SQL, writes Parquet, and
publishes a new DuckLake snapshot in one transaction.

dbt runs are triggered by:

- Git push or webhook (on code change)
- Cron schedule (for recurring materializations)
- Manual trigger via the Phoenix UI

The invariant holds across all writes: **write immutable Parquet first, then
publish via a Postgres transaction.** Readers always see a consistent snapshot
and never a partial write. Concurrency reduces to "one writer per table at a
time, unlimited readers" — enforced by the control plane, not by DuckDB.
