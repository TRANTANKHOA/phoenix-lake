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
implementation is swappable via environment variable. **S3 is the production
default**; local disk and Azure Blob are the alternatives.

| Backend | Config | Role | Use case |
|---------|--------|------|----------|
| S3 | `STORAGE_BACKEND=s3` | default | Production (AWS S3, MinIO, GCS, R2) |
| Local disk | `STORAGE_BACKEND=local` | dev / edge | Dev, edge, single-node deployments |
| Azure Blob | `STORAGE_BACKEND=azure` | Azure | Teams on Azure cloud |

Two env vars drive storage:

- `STORAGE_BACKEND` — selects the adapter: `s3` | `local` | `azure`.
- `STORAGE_PATH` — the location data is written to: an S3 URI/prefix
  (`s3://<bucket>/<prefix>`) for S3-compatible backends, or a local directory
  path for local disk. The adapter resolves paths under `STORAGE_PATH`; DuckDB's
  `httpfs` extension then performs the actual S3 I/O (or direct file reads for
  local disk).

DuckDB's `httpfs` extension handles S3 I/O natively. For local disk, DuckDB
reads Parquet files directly — no extension needed. The adapter pattern is at
the path resolution layer, not the I/O layer.

### S3-compatible credentials &amp; endpoints

When `STORAGE_BACKEND=s3`, DuckDB's `httpfs` extension authenticates and
addresses the object store with the standard AWS SDK environment variables, so
the same bucket env works for AWS S3, MinIO, Cloudflare R2, GCS, and
LocalStack. The service surfaces them; it does not bake credentials in.

| Variable | Purpose | Required for |
|----------|---------|--------------|
| `AWS_ACCESS_KEY_ID` | Access key for the S3 API. | Static-key deployments (MinIO, R2, LocalStack). Optional on AWS if an IAM task role / instance profile is attached. |
| `AWS_SECRET_ACCESS_KEY` | Secret key paired with the access key. | Same as above. |
| `AWS_SESSION_TOKEN` | Temporary-credential token (STS / role chain). | Only when credentials are short-lived. |
| `AWS_REGION` / `AWS_DEFAULT_REGION` | Bucket region. | AWS S3; ignored by some S3-compatible stores but harmless to set. |
| `AWS_ENDPOINT_URL_S3` | Custom S3 endpoint (overrides the AWS default). | **MinIO, R2, LocalStack, on-prem.** e.g. `http://minio:9000`. (`AWS_ENDPOINT_URL` applies to *all* AWS services; `_S3` is the scoped form.) |
| `AWS_ALLOW_HTTP` | Set to `"true"` to permit `http://` (non-TLS) endpoints. | **MinIO / LocalStack over plain HTTP** — DuckDB refuses plaintext endpoints unless this is set. |
| `s3_url_style` | DuckDB address style: `auto` \| `vhost` \| `path`. | **MinIO requires `path`** (`vhost` style assumes `<bucket>.<host>` DNS that MinIO does not serve). Set as a DuckDB `SET s3_url_style='path';` after `LOAD httpfs;`, or via config. |

**Common setup failures (these are what G8 exists to flag):**

- **MinIO path-style.** MinIO does not serve virtual-host-style addresses, so
  `s3_url_style='path'` must be set or bucket addressing fails. AWS S3 and R2
  work with the default `auto`/`vhost`.
- **Plain-HTTP endpoint.** A `http://minio:9000` endpoint is rejected until
  `AWS_ALLOW_HTTP="true"` is set. Production stays on TLS (`https://`) with this
  unset.
- **Endpoint scope.** Use `AWS_ENDPOINT_URL_S3` (S3-scoped), not
  `AWS_ENDPOINT_URL` (all services), unless you intentionally want every AWS
  client redirected.

**Credential source (proposed — confirm at build).** Default: static keys from
the env vars above, read once at service start and passed to DuckDB's `s3_*`
settings. On AWS specifically, prefer the IAM task role / instance profile and
omit the static-key vars — DuckDB's `httpfs` resolves role credentials the same
way the SDK does. Token rotation is the credential source's responsibility
(STS for roles; manual or CI-managed rotation for static keys), not the
service's.

> **Verify against the installed DuckDB version.** `AWS_ENDPOINT_URL_S3` and the
> `s3_url_style` setting are current `httpfs` behavior; re-confirm the exact
> names against the pinned DuckDB version before code depends on them.

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

### Runtime settings

The persistent read connection is opened with these DuckDB settings (PRAGMAs),
sized to the deployment's `8GB RAM / 4 CPU` budget (see [Deployment](#deployment)):

| Setting | Value | Why |
|---------|-------|-----|
| `memory_limit` | 6 GB (default; ~75% of the 8 Gi container) | Process-global cap; leaves off-heap headroom; spills to disk on overflow — see [Per-query vs container memory](#per-query-vs-container-memory-g15). |
| `threads` | CPU count | Parallel scan + query execution (the 4-thread budget the transform limit is sized to). |
| `access_mode` | `READ_ONLY` | The read connection never writes; writes go through temporary connections. |
| `enable_progress_bar` | `false` | Disabled in production. |

`access_mode` is set via `Config::default().access_mode(...)` at open (above);
`memory_limit` and `threads` are the equivalent `PRAGMA memory_limit` /
`PRAGMA threads` on the same connection. The value flows from the
`DUCKDB_MEMORY_LIMIT` env var.

### Per-query vs container memory (G15)

DuckDB's `memory_limit` is a **process-global** cap — the total memory the DuckDB
instance will use across *all* concurrent queries and intermediate results on the
connection, **not** a strict per-query limit. The deployment.html env var label
("Per-query memory limit") is a slight misnomer for this global cap. Two things
must hold so a single query cannot OOM the pod:

1. **The DuckDB cap must sit below the container limit, with headroom.** The read
   replica pod is sized at **8 Gi / 4 CPU** (the canonical budget the diagrams and
   the Deployment section use). `DUCKDB_MEMORY_LIMIT` defaults to **6 GB** (~75% of
   the container), leaving ~2 Gi for the OS, the Rust/Axum service process, and
   DuckDB's own off-heap structures (Parquet read buffers, the cached catalog
   metadata, per-thread stacks). When DuckDB reaches its `memory_limit` it
   **spills to its temp directory on ephemeral disk** rather than allocating
   further — it does not OOM-kill the pod. The pod is only at risk if those
   off-heap structures exhaust the headroom, which is why the ~2 Gi margin exists.

2. **Concurrency bounds how the global budget is shared.** DuckDB has no dedicated
   per-query memory pragma, so the budget is protected structurally: the read pool
   serves interactive reads (bounded fan-out), and the memory-heavy work is dbt
   transforms on the `transform` queue, hard-limited to **2 concurrent** (see
   [Concurrency handling](#concurrency-handling)). Worst case a single query
   claims the full 6 GB before spilling — slow, not fatal.

| Knob | Default | Why |
|------|---------|-----|
| Container memory (`duckdb.memory`) | 8 Gi | Canonical read-replica budget; room for DuckDB + headroom. |
| `DUCKDB_MEMORY_LIMIT` (DuckDB `memory_limit`) | 6 GB (~75% of container) | Process-global cap; ~2 Gi off-heap headroom; spills to disk on overflow. |
| Transform concurrency | 2 | Bounds how many heavy queries share the 6 GB. |
| Temp dir | ephemeral disk (`emptyDir`) | Spill target so overflow degrades to slow, not OOM. |

> **Proposed defaults — confirm at build.** The 8 Gi pod / 6 GB cap split assumes a
> `4 CPU` node; raise both proportionally on larger nodes, keeping the ~25%
> off-heap margin.

> **Target engine: DuckDB v1.5.2** (current as of mid-2026). The Quack
> multi-writer remote protocol exists at this version but is still beta, which
> is why this design serialises writers itself rather than relying on it — see
> [08 — Design validation](08-validation.md).

### Postgres connection pooling (proposed — ⚠ verify at build)

The DuckDB service reaches the DuckLake catalog through DuckDB's `postgres`
extension, which maintains a **small pool of backend Postgres connections per
ATTACHed catalog** and multiplexes the service's concurrent catalog reads across
them. Catalog traffic is metadata-light (snapshot pointers, file references,
partition maps), and DuckDB caches catalog metadata in process memory, so this
pool stays small — it does **not** grow with query fan-out.

**Defaults (proposed):**

| Concern | Default | Why |
|---------|---------|-----|
| Catalog connections per replica | Low — a few per ATTACHed catalog (3 catalogs → low single-digit dozens total). Cap so `catalogs × conn-per-catalog × replicas` stays under Postgres `max_connections`. | Metadata-only traffic; in-process caching means few live catalog round-trips. |
| Connection source | DuckDB `postgres` extension pool (re-used across requests on the persistent connection). | The persistent read connection is warm; catalog connections are pooled inside it, not opened per query. |
| PgBouncer in front of this path | **No.** Direct connection only. | The `postgres` extension uses session-level protocol features (prepared statements / `SET`) that transaction-mode PgBouncer breaks, and catalog transactions are short commits that gain nothing from a pooler. |

The same single Postgres also holds the app database; the Phoenix-side pool
(Ecto/DBConnection) and the multi-pod PgBouncer posture are spec'd in
[04 — App vs catalog database boundary → Connection pooling](04-postgres-ducklake.md#connection-pooling-proposed).

> **Proposed, not yet built.** The exact setting name that caps the `postgres`
> extension's backend pool (e.g. a per-attach connection limit) is whatever the
> installed `postgres` extension version exposes; re-confirm it against the pinned
> DuckDB version before code depends on a specific knob.

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

**Connectivity (wire protocol, host, port):** The service is a plain HTTP
server (Axum). Phoenix and its Oban workers reach it over HTTP at
`http://${DUCKDB_HOST}:${DUCKDB_PORT}` and nothing else — there is no
Postgres-wire listener and no in-process binding (DuckDB has no native Elixir
NIF). `DUCKDB_HOST` is the service hostname (`localhost` under compose, the
in-cluster service DNS name on Kubernetes) and `DUCKDB_PORT` defaults to
`8080`. The only client is the control plane; this single HTTP transport is the
topology decision recorded under C3.

### Phoenix↔DuckDB inter-service authentication (proposed — ⚠ verify at build)

The service **trusts the control plane for *authorization*** — Phoenix has
already scoped each request to the tables the caller may read before it reaches
DuckDB (see [02 — Auth](02-phoenix-app.md#auth), and "What the service does not
do" below). But trust is not blind: plain HTTP carries no caller identity, so the
service must still verify that *the caller is the control plane*, in two layers:

1. **Network isolation (primary boundary).** Port 8080 is never exposed publicly.
   In production the service is reachable only from the Phoenix pods — a
   Kubernetes `NetworkPolicy` (or ECS security group / compose internal network)
   restricts ingress to the Phoenix service account / security group. Anything
   outside that policy cannot reach the endpoint at all.

2. **Shared-secret caller authentication.** Every request from Phoenix carries a
   pre-shared token in an `Authorization: Bearer ${DUCKDB_SERVICE_TOKEN}` header;
   the service compares it constant-time and rejects with `401` on mismatch or
   absence. The token is a single deployment-scoped secret shared only between
   Phoenix and the DuckDB service — it proves "this request came from the control
   plane" and nothing more. The service does **not** re-authorize the *contents*
   (which tables the end-user may read); it trusts Phoenix's scope.

**Defaults (proposed):**

| Concern | Default | Why |
|---------|---------|-----|
| Transport | Plain HTTP **restricted to the private network** (no public ingress). TLS optional inside the mesh; terminate at the ALB/LB if a request crosses a non-private hop. | Single-tenant to its control plane; network policy is the real boundary, in-mesh TLS is belt-and-suspenders. |
| Caller identity | Shared-secret bearer token (`DUCKDB_SERVICE_TOKEN`), compared constant-time; `401` on failure. | Simplest mechanism that defeats a non-Phoenix caller on a shared network; keeps per-user identity out of the data plane. |
| Stricter alternative | mTLS between Phoenix and the DuckDB service (mutual client+server certs), or a service-mesh workload identity (SPIFFE / Istio). | For deployments where the network is not fully trusted, or where zero long-lived secret-at-rest is required. |
| Data-plane authorization | **Not re-checked** — Phoenix's scope is trusted. | Keeps DuckDB simple; the control plane owns multi-tenant access control once, at the boundary. |

> **The IAM task role is a different identity.** The DuckDB service's own IAM task
> role (deployment.html — "DuckDB: RDS read-only + S3") is its *outbound*
> identity for reaching the Postgres catalog and S3 data. That is unrelated to how
> Phoenix authenticates *to* the service. The two identities are independent: the
> role talks to S3/RDS; the shared secret talks to the control plane.

> **Proposed, not yet built.** A single shared secret is the pragmatic default for
> a private single-tenant link; rotate it through the secret store (not by hand).
> Promote to mTLS where the threat model needs mutual cryptographic identity, and
> re-confirm the chosen mechanism at scaffold time against the deployment target
> (mesh vs. flat network).

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

### Read replicas and catalog freshness

When the read pool runs more than one container (see [Scaling reads](#deployment)),
each replica is a fully independent DuckDB service that **read-only ATTACHes the
same DuckLake catalog** stored in Postgres. There is nothing to replicate between
replicas:

- **Catalog is shared, not copied.** All replicas ATTACH the one DuckLake catalog
  in Postgres, so a new snapshot is visible to every replica the moment the
  writer's Postgres transaction commits. Readers get snapshot isolation — a query
  pins the snapshot version it started with.
- **Data is shared.** Parquet lives on S3; every replica scans the same immutable
  files.
- **Cache freshness.** Each replica caches catalog metadata and zone maps in
  process memory. On a configurable refresh interval (or when a query's pinned
  snapshot is older than that interval), the replica re-reads the catalog from
  Postgres. Staleness is bounded by that interval — never by cross-replica
  propagation, because there is none.
- **Writes still serialize.** Replicas only read. All writes go through the
  single-writer queue in one writer-capable instance; replicas never accept writes.

This is why the pool scales reads (stateless containers over a shared catalog and
S3) but not writes.

## What the service does not do

- No *data-plane* access control — trusts the control plane's authorization
  (which tables an end-user may read is Phoenix's decision, not DuckDB's). It
  does authenticate that the *caller* is the control plane — see
  [Phoenix↔DuckDB inter-service auth](#phoenixduckdb-inter-service-authentication-proposed--verify-at-build).
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
