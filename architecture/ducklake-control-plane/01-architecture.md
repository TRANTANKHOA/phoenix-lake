# 01 — Architecture

## Two planes

The system separates a **control plane** from a **data plane**.

The control plane is Elixir. It owns everything that is concurrent, long-lived,
or user-facing: HTTP and the UI, authentication, the job scheduler, and the
record of what work exists and what state it is in. It holds almost no data — it
holds *decisions about* data.

The data plane is DuckDB. It owns everything that is CPU- and memory-heavy:
scanning Parquet, joining, aggregating, and writing new Parquet files. It runs
as a long-running DuckDB service (a Rust/Axum process) that Phoenix and its
Oban workers call over HTTP.

Postgres sits underneath both planes as the shared source of truth, and S3 holds
the bytes.

## Responsibilities by layer

**Phoenix (control plane)**
- Terminates HTTP/WebSocket traffic; serves the API and LiveView UI.
- Authenticates and authorizes every request.
- Enqueues, schedules, and supervises jobs through Oban.
- Reads and writes *app* metadata in Postgres (users, datasets, query history, job state).
- Calls the DuckDB service to run queries and ingestion, and streams results back to the user.

**DuckDB service (data plane)**
- Executes ad-hoc and scheduled SQL against Parquet in S3 via DuckLake.
- Ingests incoming flat files, validating and transforming them to Parquet.
- Builds and refreshes tables via dbt transformations.
- Manages Parquet files: writing new data, and triggering compaction/cleanup.

**Postgres**
- App metadata for the Phoenix side.
- Three DuckLake catalogs (landing, refining, reporting) holding table
  definitions, schema evolution, snapshots, and file lists. Created automatically
  by the platform for every project.

**S3**
- Immutable Parquet data files across three enforced databases: landing (raw),
  refining (transformed), reporting (materialized). Staging is a plain S3
  prefix managed by the ingestion worker.

## Why each boundary exists

**Why isolate DuckDB from the BEAM.** The BEAM is excellent at concurrency,
messaging, and I/O, and deliberately bad at letting one task monopolise the
machine. A large analytical scan is exactly that kind of task. Embedding DuckDB
directly in the Phoenix node would let one heavy query degrade the scheduler for
every connected user. Running DuckDB as a separate HTTP service keeps the web
tier responsive and lets the two scale on different axes.

**Why Postgres holds the catalogs.** DuckLake stores lakehouse metadata in a SQL
database. Putting the three catalogs (landing, refining, reporting) in the
*same* Postgres as the app metadata means a job that writes new Parquet and the
catalog update that publishes it can happen in one transaction. There is no
separate catalog service to keep consistent, and no window where the files exist
but the catalog doesn't (or vice versa).

**Why S3 is the only data store.** Storage is decoupled from compute. Any number
of DuckDB processes can read the same Parquet concurrently, and storage cost
scales independently of how much compute is running. Three separate DuckLake
databases (landing, refining, reporting) give catalog-level isolation while
sharing the same bucket and Postgres instance.

## What this design assumes

- The largest query intermediate (hash table, sort buffer, group-by state) fits
  in one machine's RAM. See [07 — Scaling boundaries](07-scaling-boundaries.md).
- Concurrency is bounded and managed by the control plane, not pushed onto a
  single shared DuckDB instance.
- Cross-engine interop (Athena/Trino/Spark reading the same tables) is **not**
  required. DuckLake's catalog is DuckDB-centric today.
