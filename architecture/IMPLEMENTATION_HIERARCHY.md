# Implementation Hierarchy

Long-term implementation plan derived from the architecture docs. Each phase depends on the previous ones.

## Dependency Graph

```
Phase 1 ──→ Phase 2 ──→ Phase 4 ──→ Phase 6
                ↓           ↑
            Phase 3 ────────┘
                ↓
            Phase 5 ──→ Phase 7
                            ↓
                        Phase 8
```

## Phases

### Phase 1: Foundation (no external dependencies)

Infrastructure that everything else runs on.

- **Postgres schema**
  - App metadata tables (users, sessions, grants)
  - Oban jobs table
  - DuckLake catalog init (landing, refining, reporting)
- **S3 bucket setup**
  - `staging/`
  - `landing/`
  - `refining/`
  - `reporting/`
- **docker-compose.yml** (Postgres + MinIO)

### Phase 2: Phoenix Core (control plane skeleton)

The Elixir/Phoenix app that coordinates everything.

- Phoenix app scaffolding
- Router + JSON API pipeline
- **Auth**
  - Token-based API auth (bcrypt hash, prefix lookup)
  - IdP integration via [Assent](https://hexdocs.pm/assent) (Google, WorkOS, Okta)
  - Session-based auth for browser login
  - User provisioning from IdP groups → role mapping
  - Grant system (database/table-level permissions)
  - Auth + Authorize plugs
- Health endpoint
- Ecto repos (app metadata)

### Phase 3: DuckDB Service (compute engine)

The highest-complexity component. Long-running process that executes all CPU/memory-heavy work.

- HTTP server (Rust/Axum)
- Read path (query → Parquet scan → response)
- Write path (ingest → Parquet write → catalog commit)
- Per-query memory/time limits
- Postgres catalog connection

### Phase 4: API Layer (wire Phoenix ↔ DuckDB)

Connects the control plane to the data plane. All OpenAPI endpoints.

- `POST /query` (sync + async routing)
- `GET /query/:job_id` (poll results)
- `POST /ingest` (file upload → staging)
- `GET /ingest/:job_id` (poll status)
- Database CRUD (list, create, get, update, delete)
- Table CRUD (list, create, get, update, delete)
- Job management (list, get, cancel, retry)

### Phase 5: Background Jobs (Oban)

Async execution engine backed by Postgres.

- Ingestion worker (staging → landing)
- Query worker (async execution)
- dbt transformation worker
- Compaction worker
- Queue isolation (interactive, ingest, transform, maintenance)

### Phase 6: LiveView UI

Interactive browser-based interface.

- Dashboard (job status, system health)
- Query builder + results viewer
- Dataset browser (databases, tables, schemas)
- Job monitor (live updates via PubSub)
- Ingestion status tracker

### Phase 7: dbt Integration

User-provided dbt models executed by the platform.

- Git repo sync (GitHub/GitLab webhooks)
- `profiles.yml` generation
- dbt run orchestration
- Model validation (`source()` → landing, `ref()` → refining/reporting)
- Snapshot management

### Phase 8: Production Hardening

Operational readiness.

- Observability (Telemetry, Prometheus, Grafana)
- Rate limiting + circuit breaker
- Backup/restore for Postgres
- S3 lifecycle policies
- HPA/ECS auto-scaling for DuckDB reads
- Load testing + capacity planning

## Critical Path

The fastest path to a working system:

```
Phase 1 → Phase 2 → Phase 3 → Phase 4
```

Once the API layer works end-to-end, everything else (UI, jobs, dbt, hardening) builds on top. Phase 3 (DuckDB Service) is the highest complexity and longest pole.

## Components by Complexity

| Component | Complexity | Language | Rationale |
|-----------|-----------|----------|-----------|
| Postgres schema | Low | SQL | Standard migrations |
| S3 setup | Low | Config | Bucket + lifecycle policies |
| Phoenix app | Medium | Elixir | Standard Phoenix scaffolding |
| DuckDB service | **High** | Rust | DuckDB integration, concurrency, memory management |
| API layer | Medium | Elixir | Phoenix controllers, query routing |
| Oban jobs | Medium | Elixir | Workers, queues, retry logic |
| LiveView UI | Medium | Elixir | Components, PubSub, real-time updates |
| dbt integration | Medium | Elixir + SQL | Git sync, execution, validation |
| Production hardening | Low-Medium | Mixed | Monitoring, scaling, ops |
