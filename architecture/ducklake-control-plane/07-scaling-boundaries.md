# 07 — Scaling boundaries

This design is a deliberate bet that one machine is enough for the data plane.
That bet is correct far more often than people assume, but it has real edges.
Knowing where they are is the difference between "elegantly simple" and "painted
into a corner".

## The single real limit: query intermediate size

DuckDB runs one query in one process on one machine. Scans stream and don't
accumulate, so scan *size* is rarely the problem — partition pruning means a
query over a 10 TB table may touch only a few GB.

The wall appears when a query must **materialise state larger than one machine's
RAM**: a wide high-cardinality `GROUP BY`, a hash join with a huge build side, a
global sort, a high-cardinality `DISTINCT`. DuckDB spills to local disk and slows
down; it cannot spill across machines the way a distributed engine shuffles.

So the predictor of "will this fit" is not table size — it is the size of the
largest intermediate result a query must hold.

## The limit you hit first: concurrency

Before data size bites, concurrency usually does. DuckDB is single-writer per
database and is not a multi-tenant query server. This design handles that by:

- Running readers in a long-running DuckDB service, each query bounded by
  per-query memory/time limits (no shared mutable state across queries).
- Serialising writers to one-per-table through Oban.
- Throttling heavy work via separate Oban queues.
- Target interactive-query **P95 < 5 s** (the synchronous deadline in
  [02](02-phoenix-app.md)); slower queries are demoted to Oban jobs.

That scales to bounded concurrency — tens of dashboards, a team of analysts. It
does **not** scale to hundreds or thousands of simultaneous interactive tenants
hammering shared tables. That is a job for Snowflake / BigQuery / Trino.

## Signals you've crossed the line

- Queries routinely spill to disk and run for minutes despite good partitioning.
- A single materialization no longer fits in the largest affordable machine's RAM.
- Concurrent interactive users number in the hundreds-plus.
- You need mature, native multi-engine reads (Athena / Snowflake / BigQuery) over
  the same tables. DuckLake connectors for Spark, Trino, and DataFusion exist but
  are work-in-progress; Iceberg interop landed in DuckLake 0.3. For hardened
  cross-engine interop, Iceberg is still ahead.
- Strict enterprise governance/catalog requirements that DuckLake's young
  ecosystem doesn't yet meet.

## Where to go when you cross it

- **Scale up first.** Bigger machine, better partitioning, more aggressive
  materialization. This buys a surprising amount of room and keeps the simple
  architecture.
- **Scale reads horizontally.** Before leaving DuckDB, add read-only containers
  behind a load balancer (the pool model in [03](03-duckdb-service.md)). Each
  independently attaches the same DuckLake catalog and reads the same S3 Parquet,
  so interactive read concurrency rises without giving up single-node-per-query
  simplicity. Writers stay serialized — this scales reads, not writes.
- **Offload the heavy minority.** Keep DuckDB for the 90% of workloads that fit,
  and route the few genuinely distributed queries to an existing Spark/Trino/
  Athena platform. Most teams never need more than this hybrid.
- **Scale out the engine.** If distributed execution becomes the norm rather than
  the exception, a DataFusion + Ballista style engine (or a managed warehouse)
  replaces the single-node data plane — while the Elixir control plane,
  Postgres-as-catalog, and S3 storage can largely stay.

## The honest decision rule

- Largest intermediate fits in one machine's RAM **and** concurrency is bounded
  **and** no cross-engine interop required → this design is not just viable, it's
  simpler than the alternatives.
- Cross-machine shuffle, hundreds of concurrent tenants, or multi-engine interop
  → keep a distributed engine in the picture.

For the existing platform-data-lake (Iceberg + Athena + Glue, multi-region, PII
governance) the second branch holds. The interesting wedge for *this* design is
the small workloads currently paying the distributed-engine tax — single-partition
transforms, modest refine models, embedded reporting — where one box is genuinely
plenty.
