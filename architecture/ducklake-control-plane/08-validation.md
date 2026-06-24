# 08 — Design validation

The design was checked against current DuckLake and DuckDB documentation and
commentary (as of mid-2026). The core claims hold; three points needed nuance.

## Confirmed

- **Metadata in a SQL database, data as Parquet on object storage.** DuckLake
  stores schemas, file locations, version history, and transaction logs in a
  standard transactional SQL database, with data in Parquet on S3/GCS/Azure.
  Supported catalog databases include PostgreSQL, MySQL, SQLite, DuckDB, and
  MotherDuck — so the "Postgres-as-catalog" choice is first-class.
- **Catalog-in-SQL is the actual unlock.** A query hits the database once, gets a
  precise file list, and goes straight to Parquet — metadata latency drops from
  seconds to milliseconds, and there is no separate catalog server or metadata
  compaction to run. This is exactly the "one database, no extra services"
  benefit the design leans on.
- **Snapshots are cheap, transactional rows.** A DuckLake snapshot is a few rows
  in the metadata store; snapshots can reference parts of a Parquet file, so
  millions can coexist. This validates the "write Parquet, then publish via a
  Postgres transaction" invariant and the atomic, no-downtime swap for
  materialized tables.
- **ACID with snapshot isolation, including DDL.** All operations, including
  `CREATE TABLE` / `ALTER TABLE`, are fully transactional with all-or-nothing
  semantics. This backs the ingestion and materialization flows, which depend on
  publish-or-nothing visibility.
- **DuckDB is one-writer, many-readers, single-process.** Confirmed. The design's
  response — isolated short-lived reader processes plus control-plane-serialised
  writers — matches the documented model rather than fighting it.

## Nuanced after validation

- **Multi-writer is becoming possible, but isn't relied on.** The Quack remote
  protocol turns DuckDB into a client/server database with multiple writers, but
  it is beta as of DuckDB v1.5.2. The design deliberately serialises writers in
  the control plane instead — see [03](03-duckdb-service.md).
- **Multi-engine interop is improving, still behind Iceberg.** DuckLake's 1.0
  client list includes Spark, Trino, DataFusion, and Pandas, and 0.3 added Iceberg
  read/write interop — but most connectors are work-in-progress and native Athena
  / Snowflake / BigQuery reads aren't there yet. For hardened cross-engine interop,
  Iceberg remains ahead. See [04](04-postgres-ducklake.md) and
  [07](07-scaling-boundaries.md).
- **"No compaction" applies to metadata, not data files.** Eliminating catalog
  servers and metadata compaction is real. Data-file compaction (merging many
  small Parquet files for scan efficiency) is still worthwhile and remains a job
  the DuckDB service runs — see Parquet management in [03](03-duckdb-service.md).

## Sources

- [DuckLake — SQL as a Lakehouse Format (launch post)](https://ducklake.select/2025/05/27/ducklake-01/)
- [DuckLake official site](https://ducklake.select/)
- [DuckLake Transactions docs](https://ducklake.select/docs/stable/duckdb/advanced_features/transactions)
- [The Essential Guide to DuckLake — MotherDuck](https://motherduck.com/learn/ducklake-guide/)
- [duckdb/ducklake — GitHub](https://github.com/duckdb/ducklake)
- [DuckDB Concurrency docs](https://duckdb.org/docs/current/connect/concurrency)
- [Quack protocol — multiple writers](https://siddique-ahmad.medium.com/duckdb-just-changed-the-game-meet-quack-the-protocol-that-unlocks-multiple-writers-d339e92f0bda)
- [ducklake-spark connector — GitHub](https://github.com/motherduckdb/ducklake-spark)
- [trino-ducklake connector — GitHub](https://github.com/awitten1/trino-ducklake)
- [Is DuckLake a Step Backward? — pracdata.io](https://www.pracdata.io/p/is-ducklake-a-step-backward)
