# 10 — Partitioning strategy

Partitioning in DuckLake is defined per-table via `ALTER TABLE ... SET
PARTITIONED BY` and affects only new data written after the partition is set.
Existing data keeps its original layout.

## Supported transforms

| Transform | Expression | Use case |
|-----------|------------|----------|
| identity | `col_name` | Low-cardinality columns (region, status, tenant) |
| bucket | `bucket(N, col_name)` | Hash distribution for even spread |
| year | `year(ts)` | Annual partitioning |
| month | `month(ts)` | Monthly partitioning |
| day | `day(ts)` | Daily partitioning |
| hour | `hour(ts)` | Hourly partitioning (high-volume streams) |

## Partitioning by table type

### Fact tables (events, transactions, logs)

Partition by time. Most queries filter by time range, and high-cardinality fact
data benefits most from time pruning.

```sql
ALTER TABLE events SET PARTITIONED BY (year(event_ts), month(event_ts));
```

When to use daily vs monthly:
- **Daily** — tables with 100M+ rows/month; queries typically hit a single day
- **Monthly** — tables with 10M–100M rows/month; daily creates too many small files
- **Hourly** — streaming ingestion with 1B+ rows/day; rare in practice

### Entity tables (users, products, orders)

Partition by a low-cardinality business dimension. Queries typically scope to a
single business unit, tenant, or region.

```sql
ALTER TABLE orders SET PARTITIONED BY (region, month(ordered_at));
ALTER TABLE users SET PARTITIONED BY (tenant_id);
```

When to use composite partitioning:
- When queries always filter by **both** dimensions (e.g., tenant + time)
- When one dimension alone produces partitions that are too large

### Dimension tables (lookup, reference)

Do not partition small dimension tables. The overhead of partition management
exceeds the pruning benefit when the entire table fits in memory.

```sql
-- Don't partition: < 1GB, < 10M rows
ALTER TABLE countries RESET PARTITIONED BY;
ALTER TABLE status_codes RESET PARTITIONED BY;
```

When to partition a dimension:
- Large dimension (10M+ rows, >1GB) with time-based queries
- Slowly changing dimensions where historical snapshots matter

### Large dimensions (slowly changing, high-cardinality)

Use bucket partitioning for even distribution when the partition key has
skewed cardinality (e.g., user IDs where some users have disproportionate
activity).

```sql
ALTER TABLE user_profiles SET PARTITIONED BY (bucket(16, user_id));
ALTER TABLE user_profiles SET PARTITIONED BY (bucket(16, user_id), month(updated_at));
```

Bucketing ensures uniform file sizes regardless of data distribution.

### Time-series aggregates (materialized reports)

Partition by the time grain that matches the query pattern. Dashboard queries
typically hit a single month or week.

```sql
ALTER TABLE daily_revenue SET PARTITIONED BY (year(day), month(day));
ALTER TABLE hourly_metrics SET PARTITIONED BY (day(metric_ts));
```

### Multi-tenant SaaS

Partition by tenant first, then time. This gives row-level isolation by tenant
and time pruning within each tenant.

```sql
ALTER TABLE tenant_events SET PARTITIONED BY (tenant_id, month(event_ts));
```

When to skip tenant partitioning:
- Tenant count is low (<100) and queries rarely scope to a single tenant
- Tables are small enough that tenant filtering via WHERE is sufficient

## Rules of thumb

1. **Partition on columns queries filter on**, not columns they select
2. **Target 100MB–1GB per partition** — small enough to prune, large enough to
   scan efficiently
3. **Avoid high-cardinality partition keys** (e.g., `user_id` without bucketing)
   — creates millions of tiny files
4. **Dimension tables under 1GB rarely need partitioning**
5. **If a partition has <1000 rows**, it's probably too granular
6. **Composite partitions** (tenant + time) work when queries always filter by
   both dimensions

## DuckLake-specific behavior

- Partitioning affects **only new data** — existing data keeps its original
  layout
- Partition keys are stored in **catalog metadata**, not in file paths
- Partition layout can **evolve over time** — change keys without rewriting
  existing data
- DuckLake uses **file-level zone maps** (min/max stats) for automatic pruning

## Choosing the right grain

| Rows/month | Recommended grain | Example |
|------------|-------------------|---------|
| < 1M | No partitioning or monthly | Small lookup, slow-changing dimension |
| 1M–100M | Monthly | Standard fact table, most entity tables |
| 100M–1B | Daily | High-volume events, clickstream |
| 1B+ | Hourly or bucket | Real-time streams, IoT sensor data |

## Monitoring partition health

Check for partitions that are too small or too large:

```sql
-- List partition sizes
SELECT
  partition_value,
  COUNT(*) as file_count,
  SUM(size_bytes) / 1024 / 1024 as size_mb
FROM ducklake_data_files
WHERE table_id = (SELECT id FROM ducklake_table WHERE table_name = 'events')
GROUP BY partition_value
ORDER BY size_mb DESC;
```

Signs of bad partitioning:
- Partitions with <1000 rows → too granular, merge or remove partition key
- Partitions with >10GB → too coarse, add a finer time grain
- Many empty partitions → data doesn't match the partition expression
