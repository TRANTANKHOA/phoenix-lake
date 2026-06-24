# Phoenix Lake

Greenfield "minimum viable lakehouse" — Elixir/Phoenix as control plane, DuckDB as compute engine, one Postgres for app metadata + three DuckLake catalogs (landing, refining, reporting), Parquet on pluggable storage.

**Design proposal, not a deployed service.**

[Live Documentation](https://trantankhoa.github.io/phoenix-lake/)

## Architecture

| Component | Role | Language |
|-----------|------|----------|
| **Phoenix** | Control plane — API, LiveView, Oban, Auth | Elixir |
| **DuckDB service** | Compute engine — queries, ingestion, dbt, Parquet | Rust (Axum + duckdb-rs) |
| **Postgres** | App metadata + DuckLake catalogs | Postgres 16 |
| **Storage** | Parquet files — S3, local disk, or Azure Blob (pluggable) | adapter pattern |

## Key Design Decisions

- **Single DuckDB service** handles both reads and writes via PostgreSQL wire protocol
- **Oban** is the scheduler; DuckDB is the engine; Phoenix is the control plane
- **Ingestion is append-only** — data cleaning happens in dbt, not during ingest
- **Writes serialized** via Oban (per-project) + DuckDB service (per-table)
- **dbt Core v2 (Fusion)** — Rust binary, no Python runtime needed
- **Three-tier caching** — DuckDB process memory (hot) → Postgres (warm) → S3 (cold)

## Project Structure

```
├── app/                        # Phoenix control plane (Elixir)
├── duckdb-service/             # Compute engine (Rust)
├── architecture/               # Design docs (source of truth)
├── docs/                       # HTML documentation site
├── tests/                      # Python integration tests
├── Dockerfile                  # Phoenix app container
├── docker-compose.yml          # Local development
└── .github/workflows/          # CI/CD
```

## Documentation

| Page | Description |
|------|-------------|
| [Architecture](https://trantankhoa.github.io/phoenix-lake/architecture.html) | System overview, components, boundaries |
| [DuckDB Service](https://trantankhoa.github.io/phoenix-lake/duckdb-service.html) | Compute engine, queries, ingestion, threading |
| [Auth](https://trantankhoa.github.io/phoenix-lake/auth.html) | Tokens, IdP, grants, roles |
| [Data Flows](https://trantankhoa.github.io/phoenix-lake/data-flows.html) | Ingestion, query, transformation |
| [API Reference](https://trantankhoa.github.io/phoenix-lake/api.html) | OpenAPI spec, Swagger UI |
| [Scaling](https://trantankhoa.github.io/phoenix-lake/scaling.html) | Reads, writes, boundaries |
| [dbt](https://trantankhoa.github.io/phoenix-lake/dbt.html) | Git-synced transformations |
| [Deployment](https://trantankhoa.github.io/phoenix-lake/deployment.html) | Docker, K8s, AWS |

## Local Development

```bash
docker compose up
```

Services:
- Phoenix: http://localhost:4000
- MinIO Console: http://localhost:9001
- DuckDB service: localhost:5432

## License

Proprietary — design phase.
