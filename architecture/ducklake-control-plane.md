---
name: phoenix-lake
kind: design
owner: data-platform
description: Greenfield "minimum viable lakehouse" design — Elixir/Phoenix as the control plane, DuckDB as the analytical engine, Postgres holding both app metadata and the DuckLake catalog, and Parquet on S3.
---

# Phoenix Lake

A greenfield design sketch for a small-to-mid analytical lakehouse with far fewer
moving parts than a Spark / Glue / Athena / Airflow stack. Elixir is the control
plane; DuckDB is the data plane; one Postgres holds both app metadata and the
DuckLake catalog; Parquet data lives on S3. Full design lives under
`architecture/ducklake-control-plane/`.

> This is a design proposal, not a deployed service. It does **not** replace the
> existing Iceberg + Athena + Glue platform — it targets workloads where the
> largest query intermediate fits in one machine's RAM and concurrency is bounded.

## Overview

The system splits cleanly into a **control plane** and a **data plane**.

Elixir/Phoenix is the control plane: it terminates HTTP and the LiveView UI,
authenticates and authorizes every request, schedules background work through
Oban, and records what work exists and what state it is in. It holds decisions
about data, not data itself.

DuckDB is the data plane: it does the CPU- and memory-heavy work — scanning
Parquet, joining, aggregating, writing new Parquet — in a long-running DuckDB
service (a Rust/Axum process with a warm, persistent read connection),
deliberately kept off the BEAM scheduler.

One Postgres instance underpins both: app metadata for Phoenix, and three
DuckLake catalogs (landing, refining, reporting) for the lake. S3 holds the
only large durable copy of the data, as immutable Parquet, across the three
enforced DuckLake catalogs. Staging is a plain S3 prefix for incoming files.

Intended users: internal analytics, operational BI, embedded reporting, and
small-to-mid data marts on a new product where fewer services matter more than
distributed scale.

## Business logic

Three flows exercise the whole system:

- **Ingestion** — Parquet files are dropped into a staging S3 prefix, validated
  and authorized, promoted to the landing DuckLake catalog, and published as a
  new snapshot in one Postgres transaction.
- **Query** — small interactive queries run synchronously against DuckDB and
  stream rows back; expensive queries become Oban jobs and return a handle. Either
  way DuckDB reads the current snapshot's file list, prunes partitions, and scans
  only what it needs.
- **Transformation** — dbt models read from landing, transform data, and write
  to refining or reporting. Each run is an Oban job that publishes a new
  DuckLake snapshot atomically.

The invariant across all three: **write immutable Parquet first, then publish via
a Postgres transaction.** Readers always see a consistent snapshot; concurrency
reduces to "one writer per table, unlimited readers", enforced by the control
plane.

Consumers: dashboards and the API surface results; downstream products read
published snapshots.

## Application architecture

**Phoenix (control plane)**

1. Terminate HTTP/WebSocket; serve API and LiveView UI.
2. Authenticate and authorize every request at the table level before any work
   reaches DuckDB.
3. Route small bounded queries to a synchronous DuckDB call; route anything
   expensive to an Oban job and return a handle.
4. Supervise jobs via Oban queues separated by cost profile (`interactive`,
   `ingest`, `transform`, `maintenance`) so heavy work never starves quick work.
5. Read/write app metadata in Postgres; broadcast job and query events over
   PubSub so LiveView updates live.

**DuckDB service (data plane)**

1. Run as a long-running service holding a warm, persistent read-only
   connection; open a temporary connection per write and serialize writes
   through a per-table writer queue so one writer owns a table at a time.
2. Resolve a table to its current snapshot via the DuckLake catalog, prune
   partitions, and scan only the needed Parquet from S3.
3. On ingestion/transformation, write Parquet then publish the new snapshot in a
   Postgres transaction — visible all-or-nothing.
4. Manage Parquet: right-size files, run data-file compaction, expire old
   snapshots, and delete now-unreferenced files (catalog-driven).
5. Enforce per-query memory/row/time limits so a runaway query fails fast.

One deployment form: a dedicated DuckDB service (a Rust/Axum process wrapping
DuckDB) handles both interactive reads and batch writes. Phoenix and its Oban
workers call it over HTTP; for dbt, a thin custom dbt adapter submits compiled
SQL to this same service. DuckDB is never embedded in the BEAM or the Oban
workers.

## Infrastructure

Proposed components, grouped by role:

- **Compute** — a Phoenix/Elixir cluster (web + Oban workers) and a DuckDB query
  service. The two scale on independent axes: web concurrency vs. query CPU/RAM.
- **Postgres** — one managed instance serving two logical roles in separate
  schemas: app metadata (owned by Phoenix) and the DuckLake catalog (written by
  the DuckDB data plane, read by Phoenix). DuckLake supports Postgres as a
  first-class catalog database.
- **S3** — Parquet data files only; no authoritative metadata. File layout is an
  optimisation concern (partition on filtered columns, right-size files), never a
  correctness one — the catalog defines table contents.

Per-environment differences would follow the repo convention of a
`config/{env}.yml` per environment (dev, prod, produs, prodae, prodbr), sizing the
Postgres instance, the DuckDB service, and S3 buckets per region.

## Build and deploy

Not yet built. A deployment would fit the existing CodePipeline model: source →
build (Elixir release + DuckDB service image) → multi-account deploy per
environment. Postgres provisioned as managed infrastructure; S3 buckets per env;
the DuckDB service shipped as a container alongside the Phoenix release.

## External dependencies

- **DuckDB** — embedded analytical engine; one-writer/many-readers, single-process
  model. Multi-writer via the beta Quack remote protocol is not relied on.
- **DuckLake** — lakehouse table format storing metadata in SQL and data in
  Parquet; provides snapshots, ACID with snapshot isolation, and schema evolution.
- **Postgres** — app database, Oban backend, and DuckLake catalog.
- **S3 (or GCS/Azure Blob)** — Parquet object storage.
- **Oban** — Postgres-backed job engine for ingestion, transformation, and
  compaction.

## References

- Full design set: `architecture/ducklake-control-plane/` (README + 10 docs).
- Design validation with sources: `architecture/ducklake-control-plane/08-validation.md`.
- dbt integration: `architecture/ducklake-control-plane/09-dbt-integration.md`.
- [DuckLake — SQL as a Lakehouse Format](https://ducklake.select/2025/05/27/ducklake-01/)
- [DuckDB Concurrency docs](https://duckdb.org/docs/current/connect/concurrency)
- [The Essential Guide to DuckLake — MotherDuck](https://motherduck.com/learn/ducklake-guide/)
