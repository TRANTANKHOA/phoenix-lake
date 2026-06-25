# 03 — DuckDB service

The DuckDB service is the compute engine. It handles all CPU- and memory-heavy
work: queries, ingestion, transformation, and maintenance. Phoenix is the
control plane; Oban is the scheduler; DuckDB is where the work happens.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Phoenix (control plane)                                        │
│  - API, auth, UI                                                │
│  - Routes requests to DuckDB service                            │
│  - Queues jobs in Oban                                          │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  DuckDB Service (compute engine)                                │
│  - Persistent Rust process                                     │
│  - Handles both reads and writes                                │
│  - Connects to Postgres (catalog) and storage (data)           │
│  - Enforces per-query memory/time limits                        │
└─────────────────────────────────────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            ↓               ↓               ↓
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Postgres    │  │  Storage     │  │  Storage     │
│  - Catalogs  │  │  (S3)        │  │  (local)     │
│  - Snapshots │  │  - Parquet   │  │  - Parquet   │
│  - Metadata  │  │  - Staging   │  │  - Staging   │
└──────────────┘  └──────────────┘  └──────────────┘
```

## Storage adapter

Storage is pluggable. The DuckDB service uses a storage interface — the
implementation is swappable via environment variable:

| Backend | Config | Use case |
|---------|--------|----------|
| S3 | `STORAGE_BACKEND=s3` | Production (AWS S3, MinIO, GCS, R2) |
| Local disk | `STORAGE_BACKEND=local` | Dev, edge, single-node deployments |
| Azure Blob | `STORAGE_BACKEND=azure` | Teams on Azure cloud |

DuckDB's `httpfs` extension handles S3 I/O natively. For local disk, DuckDB
reads Parquet files directly — no extension needed. The adapter pattern is at
the path resolution layer, not the I/O layer.

## Process model

The DuckDB service is a **long-running process** (not short-lived workers). It:

- Stays alive between requests (warm cache, no cold start)
- Handles multiple concurrent requests (read-only mode)
- Connects to Postgres for catalog metadata
- Reads/writes Parquet on S3

**Concurrency model:**
- Reads: multiple concurrent (DuckDB supports many readers)
- Writes: serialized via Oban (one write job per table at a time)
- The service itself handles both; Oban ensures write serialization

## Read path (queries)

```
API request → Phoenix → DuckDB service → Postgres (catalog) → S3 (Parquet) → response
```

1. Phoenix authorizes the request and scopes it to allowed tables
2. Phoenix calls DuckDB service with the SQL query
3. DuckDB reads current snapshot from Postgres catalog
4. DuckDB prunes partitions using zone maps
5. DuckDB scans only needed Parquet files from S3
6. DuckDB streams results back to Phoenix
7. Phoenix forwards to API/LiveView

**Latency optimization:**
- Persistent process = no cold start
- Catalog metadata cached in DuckDB process memory
- Partition zone maps cached for repeated queries
- Connection pool to Postgres and S3

## Write path (ingestion, transformation, compaction)

```
Oban job → DuckDB service → Postgres (catalog) → S3 (Parquet) → done
```

1. Oban picks a job from the queue
2. Oban calls DuckDB service with the write operation
3. DuckDB executes the operation (ingest, dbt run, compact, etc.)
4. DuckDB writes Parquet to S3
5. DuckDB commits catalog update in Postgres
6. Oban marks job complete

**Write serialization:**
- Oban queues enforce one write per table at a time
- No two writers can modify the same table simultaneously
- If conflict occurs, DuckLake retries automatically

## Concurrency handling

### Two levels of serialization

Concurrency is enforced at two levels:

| Level | Where | What it prevents |
|-------|-------|-----------------|
| Job-level | Oban queues | Duplicate dbt runs for the same project |
| Query-level | DuckDB service | Concurrent writes to the same table |

### Job-level: Oban unique constraints

Oban queues use per-project uniqueness for dbt transforms:

```elixir
queues: [
  interactive: [limit: 8],
  ingest: [limit: 5, unique: [keys: [:table_name]]],
  transform: [
    limit: 2,
    unique: [
      keys: [:project_id],
      states: [:available, :scheduled, :executing, :retryable],
      replace: [:args]
    ]
  ],
  maintenance: [limit: 2]
]
```

- **`interactive`** — low-latency reads that time out of the synchronous path
  ([02](02-phoenix-app.md#query-routing)); small, fast, high priority.
- **`ingest`** — file promotion and landing writes.
- **`transform`** — dbt model execution; CPU/memory intensive. The limit is `2`
  deliberately: 2 concurrent dbt runs × 2 dbt threads = 4 parallel model
  submissions, matching the single DuckDB service's 4-thread budget without
  oversubscribing it.
- **`maintenance`** — compaction, snapshot expiration, file cleanup.

- **Ingestion jobs**: unique by `table_name` — only one ingest per table at a time
- **Transform jobs**: unique by `project_id` — only one dbt run per project at a time
- `replace: [:args]` — if a job is already waiting or running for this project,
  replace its args with the new push. Latest push always wins.
- A dbt run executes ALL models in the DAG — you can't unique by table because
  the job doesn't know which tables it writes to until it runs

**Git push behavior:**

```
Push 1 → dbt run starts (executing)
Push 2 → job waiting, args replaced with push 2's commit
Push 3 → job waiting, args replaced with push 3's commit
Push 1 finishes → push 3 runs (latest wins)
```

Only one pending job at a time. No jobs are discarded.

### Query-level: DuckDB service write routing

The DuckDB service parses incoming SQL and detects write operations (INSERT,
COPY, CREATE TABLE AS, etc.). Writes are routed through a single-writer queue
per table:

```
SQL → DuckDB service
  ├─ SELECT → any container (concurrent reads)
  └─ INSERT/COPY → single-writer queue per table
       └─ only one write to table X at a time
```

Reads are free. Writes are serialized. Multiple dbt runs can read the same
table concurrently. Only writes need coordination.

### DuckLake retry mechanism

If two writers somehow hit the same table (safety net):

```sql
CALL my_ducklake.set_option('write_retry_count', 3);
CALL my_ducklake.set_option('write_retry_delay_ms', 100);
```

The second writer detects the conflict and retries after a short delay.

### Postgres atomic commit

Catalog updates are Postgres transactions:

```sql
BEGIN;
-- Write Parquet to S3
-- Update catalog (insert snapshot, file references)
COMMIT;
```

Only one transaction commits at a time. Others wait or retry.

## Implementation

### Recommended: Rust service

```rust
// Axum HTTP server + duckdb-rs
use duckdb::Connection;
use axum::{routing::post, Json, Router};

struct DuckDBService {
    read_conn: Connection,   // read-only, persistent
    // Write operations create temporary connections
}

impl DuckDBService {
    fn new() -> Self {
        // Persistent, read-only connection — warm cache across requests. The
        // local file is just DuckDB scratch; the DuckLake catalog is ATTACHed
        // from Postgres and data lives on S3, so durability comes from those,
        // not from this connection being in-memory.
        let conn = Connection::open_with_flags(
            "duckdb_read.db",
            Config::default().access_mode(AccessMode::ReadOnly),
        ).unwrap();
        
        conn.execute("INSTALL ducklake; INSTALL postgres; INSTALL httpfs;", []).unwrap();
        conn.execute("LOAD ducklake; LOAD postgres; LOAD httpfs;", []).unwrap();
        
        Self { read_conn: conn }
    }
    
    fn query(&self, sql: &str) -> Result<Value> {
        // Read path: use persistent read-only connection
        self.read_conn.execute(sql, [])?
    }
    
    fn write(&self, sql: &str) -> Result<Value> {
        // Write path: create temporary connection
        let write_conn = Connection::open_in_memory().unwrap();
        write_conn.execute(sql, [])?
    }
}
```

## Deployment

Single container deployment:

```
┌─────────────────────────────────────────┐
│  DuckDB Service Container               │
│  ┌───────────────────────────────────┐  │
│  │  HTTP server (Axum)               │  │
│  │  DuckDB read connection (warm)    │  │
│  │  DuckDB write connections (temp)  │  │
│  │  Postgres connection pool         │  │
│  │  S3 client                        │  │
│  └───────────────────────────────────┘  │
│  Resources: 8GB RAM, 4 CPU              │
└─────────────────────────────────────────┘
```

**Scaling reads:** The default deployment is a **single container**. For higher
read concurrency or high availability, add containers behind a load balancer —
each is independent (no shared state). Auto-scale based on:

- CPU utilization > 70% → add container
- CPU utilization < 30% → remove container
- P95 query latency > SLA → add container
- Request queue depth > threshold → add container

Kubernetes HPA example:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
spec:
  minReplicas: 1  # default; set 2+ for high availability
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

ECS example:

```json
{
  "ScalingPolicies": [{
    "PolicyType": "TargetTrackingScaling",
    "TargetTrackingScalingPolicyConfiguration": {
      "TargetValue": 70.0,
      "PredefinedMetricSpecification": {
        "PredefinedMetricType": "ECSServiceAverageCPUUtilization"
      }
    }
  }]
}
```

**Scaling writes:** Writes are serialized at two levels — Oban prevents
duplicate dbt runs (per-project), and the DuckDB service routes writes through
a single-writer queue per table. Adding more DuckDB containers increases read
throughput but not write throughput. Scale writes by:
- Reducing the number of models that write to the same table
- Optimizing write operations (faster Parquet writes, less data)
- Splitting large tables into smaller ones

Write bottleneck is per-table serialization in the DuckDB service, not DuckDB
capacity.

## What the service does not do

- No access control — trusts the control plane's authorization
- No job scheduling — Oban handles queuing, retries, uniqueness
- No API routing — Phoenix handles HTTP, auth, UI
- No long-lived mutable state — state lives in Postgres and S3

## Scaling summary

| Path | Scaling | Trigger | Bottleneck |
|------|---------|---------|------------|
| Reads | Auto (HPA/ECS) | CPU, latency, queue depth | DuckDB CPU/RAM |
| Writes | Manual | Optimize operations, split tables | Per-table serialization in DuckDB service |

Reads scale horizontally (add containers). Writes are serialized per-table
by the DuckDB service — adding more containers doesn't increase write throughput.

## Design Decisions

| # | Issue | Decision | Why |
|---|-------|----------|-----|
| D1 | Rust vs Python for DuckDB service | Rust (Axum + duckdb-rs) | No GIL, lower memory, smaller image. Long-running compute engine favors performance over dev speed. |
| D2 | Single process vs separate read/write workers | One long-running process handles both | Warm cache, no cold start. Writes serialized by Oban, not by process separation. |
| D3 | Write serialization: two-level model | Oban (per-project, replace args) + DuckDB service (per-table) | Oban replaces waiting job args on new push (latest wins). DuckDB service parses SQL, routes writes through single-writer queue per table. |
| D4 | Read connection: per-request vs persistent | Persistent read-only connection | Catalog metadata cached in process memory. No re-initialization per query. |
| D5 | Write connection: shared vs temporary | Temporary per write operation | No cross-operation state leakage. Clean separation between reads and writes. |
| D6 | Scaling reads vs writes | Reads: horizontal (HPA). Writes: vertical. | Reads are stateless containers. Writes bottleneck at Oban serialization, not DuckDB capacity. |
