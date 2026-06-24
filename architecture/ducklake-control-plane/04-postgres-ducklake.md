# 04 — Postgres & DuckLake catalog

One Postgres instance serves two roles: the application database and the
DuckLake catalog for multiple databases. Keeping them together is a deliberate
simplification.

## App metadata

The control-plane state described in [02](02-phoenix-app.md):

- Users, sessions, roles, grants.
- Dataset/table registrations (the user-facing list of what exists and who may
  see it).
- Query history and results metadata.
- Oban job rows.

This is read and written by Phoenix on every request and job.

## DuckLake catalog

DuckLake stores lakehouse metadata in a SQL database rather than in object-store
manifest files. In this design that database is the same Postgres. Every project
gets three databases with a fixed naming convention — landing, refining,
reporting — created automatically by the platform:

```sql
CREATE DATABASE landing   (TYPE ducklake, DATA_PATH 's3://<bucket>/landing/');
CREATE DATABASE refining  (TYPE ducklake, DATA_PATH 's3://<bucket>/refining/');
CREATE DATABASE reporting (TYPE ducklake, DATA_PATH 's3://<bucket>/reporting/');
```

Each catalog holds:

- Table definitions and their schema, including schema-evolution history.
- Snapshots — each a consistent version of a table at a point in time.
- The list of Parquet files (and their statistics) that make up each snapshot.
- Partition information used for pruning.

A query resolves a table to its current snapshot by reading the appropriate
catalog, which tells DuckDB exactly which S3 files to scan.

## Why one Postgres

The decisive advantage is **transactional consistency between data and catalog**.

When an ingestion or materialization job writes new Parquet to S3 and then
publishes it, the catalog update is an ordinary Postgres transaction. Either the
new snapshot becomes visible or it doesn't — there is never a state where the
files exist but no snapshot references them, or a snapshot references files that
aren't there yet.

Separate databases give catalog-level isolation:

- A bad dbt run in one database cannot corrupt another.
- Each database can have independent snapshot retention and compaction policies.
- Access control is per-database: analysts can be granted read on certain
  databases while others stay restricted.

It also removes a whole service. There is no separate catalog system (no Glue, no
standalone metastore) to deploy, secure, back up, and keep consistent with the
app. Backups, point-in-time recovery, and access control are solved once, for
all roles, by Postgres.

## Practical separation

Though physically one Postgres, the concerns stay logically separate:

- Landing, refining, and reporting are distinct DuckLake databases with their own
  catalog tables, snapshots, and data paths.
- The landing catalog is written only by the ingestion worker; Phoenix reads
  from it but treats it as owned by the data plane.
- The refining and reporting catalogs are written by dbt and materialization
  jobs; Phoenix reads from them for query results and UI display.
- App tables are owned by Phoenix and never touched by DuckDB.

## The maturity caveat

The DuckLake catalog format is young. Third-party connectors are emerging —
DuckLake's 1.0 client list includes Spark, Trino, DataFusion, and Pandas, and
DuckLake 0.3 added Iceberg read/write interop — but most are work-in-progress, and
native reads from Athena, Snowflake, and BigQuery are not there yet. For broad,
production multi-engine interop, Iceberg remains the more mature choice today. If
that interop is a hard requirement, this catalog choice is the wrong one — see
[07 — Scaling boundaries](07-scaling-boundaries.md).
