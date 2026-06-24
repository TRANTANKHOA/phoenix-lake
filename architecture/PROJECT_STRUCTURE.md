# Project Structure

Multi-component layout for Phoenix Lake. Each directory maps to an architecture component.

```
ducklake/
│
├── architecture/                    # Design docs (source of truth)
│   ├── IMPLEMENTATION_HIERARCHY.md  # Phased build plan
│   ├── ducklake-control-plane.md    # Overview doc
│   └── ducklake-control-plane/      # 10 design documents
│       ├── 01-architecture.md
│       ├── 02-phoenix-app.md
│       ├── 03-duckdb-service.md
│       ├── 04-postgres-ducklake.md
│       ├── 05-s3-storage.md
│       ├── 06-data-flows.md
│       ├── 07-scaling-boundaries.md
│       ├── 08-validation.md
│       ├── 09-dbt-integration.md
│       └── 10-partitioning-strategy.md
│
├── docs/                            # HTML documentation site
│   ├── index.html
│   ├── architecture.html
│   ├── phoenix.html
│   ├── duckdb-service.html
│   ├── postgres.html
│   ├── s3.html
│   ├── data-flows.html
│   ├── scaling.html
│   ├── dbt.html
│   ├── deployment.html
│   ├── glossary.html
│   ├── api.html                     # Swagger UI
│   ├── openapi.yaml                 # OpenAPI 3.0 spec
│   └── styles.css
│
├── app/                             # Phoenix control plane (Elixir)
│   ├── mix.exs
│   ├── mix.lock
│   ├── config/
│   │   ├── config.exs
│   │   ├── dev.exs
│   │   ├── test.exs
│   │   ├── prod.exs
│   │   └── runtime.exs
│   ├── lib/
│   │   ├── phoenix_lake/
│   │   │   ├── application.ex       # OTP app + supervision tree
│   │   │   ├── repo.ex              # Ecto repo (app metadata)
│   │   │   ├── ducklake/            # DuckLake catalog schemas
│   │   │   │   ├── database.ex
│   │   │   │   ├── table.ex
│   │   │   │   ├── snapshot.ex
│   │   │   │   └── column.ex
│   │   │   ├── accounts/            # Auth + user management
│   │   │   │   ├── user.ex
│   │   │   │   ├── token.ex
│   │   │   │   └── grants.ex
│   │   │   └── jobs/                # Oban workers
│   │   │       ├── ingest_worker.ex
│   │   │       ├── query_worker.ex
│   │   │       ├── transform_worker.ex
│   │   │       └── compact_worker.ex
│   │   └── phoenix_lake_web/
│   │       ├── endpoint.ex
│   │       ├── router.ex
│   │       ├── telemetry.ex
│   │       ├── controllers/
│   │       │   ├── health_controller.ex
│   │       │   ├── database_controller.ex
│   │       │   ├── table_controller.ex
│   │       │   ├── query_controller.ex
│   │       │   ├── ingest_controller.ex
│   │       │   └── job_controller.ex
│   │       ├── live/                # LiveView components
│   │       │   ├── dashboard_live.ex
│   │       │   ├── query_live.ex
│   │       │   ├── datasets_live.ex
│   │       │   └── jobs_live.ex
│   │       ├── components/          # Shared UI components
│   │       │   ├── layouts.ex
│   │       │   └── core_components.ex
│   │       └── plugs/
│   │           ├── auth.ex
│   │           └── authorize.ex
│   ├── priv/
│   │   └── repo/
│   │       ├── migrations/          # App metadata migrations
│   │       └── seeds.exs
│   └── test/
│       ├── test_helper.exs
│       ├── support/
│       │   ├── conn_case.ex
│       │   └── data_case.ex
│       └── phoenix_lake_web/
│           └── controllers/
│               ├── health_controller_test.exs
│               ├── database_controller_test.exs
│               ├── table_controller_test.exs
│               ├── query_controller_test.exs
│               ├── ingest_controller_test.exs
│               └── job_controller_test.exs
│
├── duckdb-service/                  # Compute engine (Rust)
│   ├── Cargo.toml                   # If Rust
│   ├── src/
│   │   ├── main.rs
│   │   ├── config.rs
│   │   ├── query.rs                 # Read path
│   │   ├── ingest.rs                # Write path
│   │   ├── catalog.rs               # Postgres DuckLake connection
│   │   ├── storage.rs               # S3 client
│   │   └── limits.rs                # Per-query memory/time limits
│   └── Dockerfile
│
├── dbt/                             # dbt project template
│   ├── dbt_project.yml
│   ├── ducklake.yml                 # Platform config (layers, retention)
│   ├── profiles.yml                 # Generated by platform
│   ├── models/
│   │   ├── staging/                 # source() → landing
│   │   │   └── _staging__sources.yml
│   │   ├── refining/                # ref() → refining
│   │   └── reporting/               # ref() → reporting
│   └── macros/
│
├── tests/                           # Python integration tests
│   └── test_api.py
│
├── helm/                            # Kubernetes deployment
│   ├── app/                         # Phoenix app
│   ├── duckdb-service/              # DuckDB service
│   └── values.yaml
│
├── terraform/                       # AWS infrastructure
│   ├── main.tf
│   ├── rds.tf                       # Postgres
│   ├── s3.tf                        # Bucket
│   ├── ecs.tf                       # Containers
│   └── variables.tf
│
├── docker-compose.yml               # Local dev (Postgres + MinIO + services)
├── .github/
│   └── workflows/
│       ├── deploy-pages.yml         # GitHub Pages (docs)
│       ├── ci.yml                   # Lint + test
│       └── release.yml              # Build + push images
├── .mimocode/
│   └── skills/
│       ├── align-html/SKILL.md
│       └── git/
│           ├── SKILL.md
│           └── git.py
├── .gitignore
├── validate_openapi.py
└── README.md
```

## Component Boundaries

```
┌─────────────────────────────────────────────────────┐
│  app/                   Phoenix control plane       │
│  - API, auth, UI, job scheduling                    │
│  - Calls duckdb-service for compute                 │
│  - Owns app metadata in Postgres                    │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP
                       ▼
┌─────────────────────────────────────────────────────┐
│  duckdb-service/        Compute engine              │
│  - SQL execution, ingestion, dbt                    │
│  - Reads/writes Parquet on S3                       │
│  - Catalog queries to Postgres                      │
└──────────┬──────────────────────┬───────────────────┘
           │                      │
           ▼                      ▼
┌──────────────────┐   ┌──────────────────┐
│  Postgres        │   │  S3 / MinIO      │
│  - App metadata  │   │  - staging/      │
│  - DuckLake      │   │  - landing/      │
│    catalogs      │   │  - refining/     │
└──────────────────┘   │  - reporting/    │
                       └──────────────────┘
```

## Naming Conventions

| Component | Prefix | Example |
|-----------|--------|---------|
| Phoenix controllers | `*_controller.ex` | `query_controller.ex` |
| Phoenix LiveView | `*_live.ex` | `dashboard_live.ex` |
| Oban workers | `*_worker.ex` | `ingest_worker.ex` |
| Ecto schemas | `*.ex` | `database.ex`, `table.ex` |
| Ecto migrations | `*_create_*.exs` | `20260619_create_users.exs` |
| DuckDB service | `*.rs` | `query.rs`, `ingest.rs` |
| Tests | `*_test.exs` / `test_*.py` | `query_controller_test.exs` |
