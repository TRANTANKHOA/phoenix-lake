# 04 — Postgres & DuckLake catalog

One Postgres instance — **PostgreSQL 16, single instance** — serves two roles:
the application database and the DuckLake catalog. Every project gets three
DuckLake catalogs (landing, refining, reporting). Keeping them together is a
deliberate simplification. (16 is the pinned major version; a single instance is
the locked deployment shape — see [07 — Scaling boundaries](07-scaling-boundaries.md).)

## App metadata

The control-plane state described in [02](02-phoenix-app.md). Phoenix owns these
tables; DuckLake's catalog tables (snapshots, data files, …) are managed
internally by the extension and are never read or written by Phoenix — clean
separation, no overlap. This is read and written by Phoenix on every request and
job.

**Users & Auth** (canonical schema in [AUTH_MODULE](../AUTH_MODULE.md))

- `users` — `email` (unique, indexed), `name` (from IdP or admin), `role`
  (admin | editor | viewer), `provider` (google | workos | okta | local),
  `provider_uid` (IdP's unique user ID), `active` (default: true).
- `tokens` — `key_hash` (bcrypt, never plaintext), `key_prefix` (first 8 chars
  for prefix lookup), `name` ("CI pipeline", "dbt runner"), `scopes`
  (["read", "write"]), `expires_at` (default TTL 90 days; nil = no expiry),
  `last_used_at` (updated on each validation), `user_id` → `users`.
- `grants` — `database` ("landing" | "refining" | "reporting" | "*"), `table`
  (table name or "*" for all), `permission` (read | write | admin),
  `user_id` → `users`.

**Dataset & Table registry**

- `datasets` — `name` (unique display name), `description` (optional),
  `database` (landing | refining | reporting), `created_by` → `users`.
- `tables` — `dataset_id` → `datasets`, `table_name` (unique per dataset),
  `schema_json` (jsonb column definitions), `row_count`, `size_bytes`,
  `updated_at`.

**Query & Results metadata**

- `query_history` — `user_id` → `users`, `sql` (submitted SQL), `database`
  (target database), `status` (pending | running | completed | failed),
  `duration_ms`, `row_count`, `started_at`, `completed_at`.
- `query_results` — `query_id` → `query_history`, `result_url` (S3 presigned URL
  to Parquet), `column_types` (jsonb column-type info), `row_count`,
  `size_bytes`. Actual data lives in S3, not Postgres.

**Oban (built-in)**

- `oban_jobs` — `queue` (interactive | ingest | transform | maintenance),
  `state` (available | executing | completed | retryable), `args` (jsonb job
  arguments), `errors` (jsonb error history), `attempts`, `scheduled_at`.
  Managed by the Oban library; unique constraint on `project_id` for the
  transform queue (one dbt run per project at a time — see
  [03](03-duckdb-service.md)).

## DuckLake catalog

DuckLake stores lakehouse metadata in a SQL database (the *catalog database*)
rather than in object-store manifest files. In this design the catalog database
is the same Postgres that holds app metadata. Every project gets three DuckLake
catalogs with a fixed naming convention — landing, refining, reporting — created
automatically by the platform. Each is a separate `ATTACH`:

```sql
-- ⚠ verify exact ATTACH parameters against the current DuckLake (v1.x) syntax.
-- Each catalog stores its metadata in a distinct Postgres schema (METADATA_SCHEMA)
-- so the three catalogs share one Postgres instance without colliding.
ATTACH 'ducklake:postgres:dbname=phoenix_lake' AS landing
  (DATA_PATH 's3://<bucket>/landing/',   METADATA_SCHEMA 'ducklake_landing');
ATTACH 'ducklake:postgres:dbname=phoenix_lake' AS refining
  (DATA_PATH 's3://<bucket>/refining/',  METADATA_SCHEMA 'ducklake_refining');
ATTACH 'ducklake:postgres:dbname=phoenix_lake' AS reporting
  (DATA_PATH 's3://<bucket>/reporting/', METADATA_SCHEMA 'ducklake_reporting');
```

Each catalog holds:

- Table definitions and their schema, including schema-evolution history.
- Snapshots — each a consistent version of a table at a point in time.
- The list of Parquet files (and their statistics) that make up each snapshot.
- Partition information used for pruning.

A query resolves a table to its current snapshot by reading the appropriate
catalog, which tells DuckDB exactly which S3 files to scan.

### Catalog physical schema (proposed — ⚠ verify against DuckLake version)

DuckLake **owns and auto-provisions** its catalog schema — Phoenix never
hand-writes or directly reads/writes the `ducklake_*` catalog tables. When a
catalog is first created, DuckLake materializes its standard set of metadata
tables **inside the configured `METADATA_SCHEMA`** in Postgres. The only DDL
the platform issues against a catalog is the provisioning statement below plus
ordinary lake DDL (`CREATE TABLE`, `INSERT`, `DELETE`, `DROP TABLE`) routed
**through DuckDB**, which in turn updates the catalog tables transactionally.

```sql
-- ⚠ verify exact syntax against the current DuckLake (0.4) docs.
-- CREATE DATA CATALOG provisions the 28 metadata tables inside METADATA_SCHEMA.
-- On subsequent process starts the same catalog is re-opened with ATTACH (above).
CREATE DATA CATALOG 'ducklake:postgres:dbname=phoenix_lake' AS landing
  (DATA_PATH 's3://<bucket>/landing/', METADATA_SCHEMA 'ducklake_landing');
```

**Physical layout in Postgres** — one schema per catalog, each holding the same
standard set of catalog tables (DuckLake 0.4 = 28 tables):

| Postgres schema | Catalog | Holds metadata for |
|-----------------|---------|---------------------|
| `ducklake_landing` | landing | `s3://<bucket>/landing/` tables/snapshots |
| `ducklake_refining` | refining | `s3://<bucket>/refining/` tables/snapshots |
| `ducklake_reporting` | reporting | `s3://<bucket>/reporting/` tables/snapshots |

**Key catalog tables DuckLake creates** (full 28-table spec:
<https://ducklake.select/docs/stable/specification/tables/overview.html>):

- `ducklake_table` / `ducklake_column` — table + column definitions and schema-evolution history.
- `ducklake_snapshot` / `ducklake_snapshot_changes` — one row per table version, with author + commit message.
- `ducklake_data_file` — the Parquet file manifest (path, `record_count`, `file_size_bytes`, partition id) for each snapshot.
- `ducklake_file_column_stats` — per-file min/max/null counts used for pruning.
- `ducklake_partition_info` / `ducklake_file_partition_value` — partition layout for pruning.
- `ducklake_table_stats` — rolled-up table-level row count and size.
- `ducklake_files_scheduled_for_deletion` — files staged for physical removal (the input to the two-phase retention job defined in [§05 — Retention](05-s3-storage.md#retention--mechanism-defaults-and-owner)).

> **Proposed, not yet built.** The catalog schema is owned by the DuckLake
> extension and is whatever DuckLake 0.4 (or the version pinned at build) emits;
> the table list above is the reference shape for the example catalog queries
> elsewhere in these docs, and must be re-verified against the installed
> DuckLake version before any code depends on a specific column name.

> **Terminology — catalog vs database.** In DuckLake, a *catalog* is what you
> `ATTACH` (here `landing`, `refining`, `reporting`) — the attached lake with its
> tables and snapshots. A *catalog database* is the SQL backend that stores that
> metadata (this Postgres). The HTTP API and grant model expose the three catalogs
> under the `database` resource and `database` field name (e.g.
> `database: "landing"`); there, "database" means "a DuckLake catalog," not a
> Postgres database.

### App vs catalog database boundary (proposed)

App metadata and the DuckLake catalog live in the **same logical Postgres
database** (`phoenix_lake`) — one database, not two. Separation is
**schema-qualified**, not database-qualified:

| Postgres schema | Owner | What lives here |
|-----------------|-------|-----------------|
| `public` | Phoenix | `users`, `tokens`, `grants`, `datasets`, `tables`, `query_history`, `query_results`, `oban_jobs` |
| `ducklake_landing` | DuckLake extension (via DuckDB) | landing catalog tables (snapshots, data files, …) |
| `ducklake_refining` | DuckLake extension (via DuckDB) | refining catalog tables |
| `ducklake_reporting` | DuckLake extension (via DuckDB) | reporting catalog tables |

**Role separation (proposed — ⚠ confirm at build time).** Two Postgres roles
enforce the boundary at the DB so a credential leak on one side cannot cross to
the other:

- `phoenix_app` — used only by Phoenix (Ecto). Granted on `public`; **no
  privileges** on the `ducklake_*` schemas. Phoenix never reads or writes the
  catalog tables directly.
- `duckdb_catalog` — used only by the DuckDB service's `postgres` extension when
  it attaches the catalogs. Granted on the three `ducklake_*` schemas; **no
  privileges** on `public`.

**Row-Level Security — deliberately not used.** Authorization is enforced in the
Phoenix application layer (the `grants` table + the role check in
`validate_token`, see [AUTH_MODULE](../AUTH_MODULE.md)), consistent with the
locked "control plane is trusted" model: Phoenix authenticates the caller and
checks grants before issuing any SQL, so every catalog/data access has already
been authorized by the time it reaches the DB. RLS is omitted as a deliberate
simplicity trade-off rather than forgotten; it can be layered in later as
defense-in-depth if a multi-tenant or shared-DB deployment ever needs it.

> **Proposed, not yet built.** The two-role split and the no-RLS posture are the
> reference boundary; the exact role names and grant scripts are finalized when
> the `phoenix_lake` database is provisioned.

### Connection pooling (proposed)

The app database is reached through Phoenix's standard **Ecto + DBConnection +
postgrex** pool, under the `phoenix_app` role. It is a low-TPS metadata workload
(auth + grant checks, dataset/table rows, `query_history`, Oban jobs), so the
pool is small and Oban shares the same repo pool:

| Concern | Default | Why |
|---------|---------|-----|
| Pool size | `DB_POOL_SIZE` (default `10`). Size 10–20 per pod. | Control-plane metadata ops are cheap and bursty; 10–20 covers API + LiveView + Oban from one pod. |
| PgBouncer | **Off by default.** Optional, **transaction mode**, in front of the `phoenix_app` role only. | A single Postgres instance absorbs the control plane at the locked scale. Add PgBouncer only when many Phoenix pods (each holding a 10–20 pool) would exceed Postgres `max_connections`. |
| Prepared statements under PgBouncer | If PgBouncer is enabled, run Ecto with **prepared statements disabled** (`prepare: :unnamed`). | Transaction-mode PgBouncer is incompatible with named prepared statements — Ecto will fail without this. |
| PgBouncer in front of the **catalog** path | **Never.** | The DuckDB→catalog path uses session-level protocol features and is direct-only — see [03 → Postgres connection pooling](03-duckdb-service.md#postgres-connection-pooling-proposed--verify-at-build). |

The DuckDB→catalog pool lives on the `duckdb_catalog` role and is sized in
[03](03-duckdb-service.md#postgres-connection-pooling-proposed--verify-at-build);
the two pools are independent and never share a pooler.

> **Proposed, not yet built.** Pool defaults and the PgBouncer posture are the
> reference configuration; finalize `DB_POOL_SIZE` and Postgres `max_connections`
> against the real pod count and Oban concurrency at scaffold time.

## Why one Postgres

The decisive advantage is **transactional consistency between data and catalog**.

When an ingestion or materialization job writes new Parquet to S3 and then
publishes it, the catalog update is an ordinary Postgres transaction. Either the
new snapshot becomes visible or it doesn't — there is never a state where the
files exist but no snapshot references them, or a snapshot references files that
aren't there yet.

Separate catalogs give isolation at the catalog boundary:

- A bad dbt run in one catalog cannot corrupt another.
- Each catalog can have independent snapshot retention and compaction policies.
- Access control is per-catalog: analysts can be granted read on certain
  catalogs while others stay restricted.

It also removes a whole service. There is no separate catalog system (no Glue, no
standalone metastore) to deploy, secure, back up, and keep consistent with the
app. Backups, point-in-time recovery, and access control are solved once, for
all roles, by Postgres.

## Practical separation

Though physically one Postgres, the concerns stay logically separate:

- Landing, refining, and reporting are distinct DuckLake catalogs, each with its
  own catalog tables, snapshots, and data path.
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
