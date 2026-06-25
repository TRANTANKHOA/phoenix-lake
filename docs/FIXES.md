# Phoenix Lake Documentation Audit — Fix Tracker

Living progress tracker for `docs/AUDIT.md`. Updated as findings are resolved.
Legend: ✅ fixed · ⚠️ flagged-verify · ⏸️ skipped-needs-decision · ⬜ pending.
Already-done-this-session (C3, C4, C8, G11, S6) are re-verified and locked.

**Pending owner confirmation:**
- dbt adapter name (`dbt-duckdb` fork / `type: duckdb_service`) is a PLACEHOLDER — do not rename.
- GitHub owner `TRANTANKHOA` (N2) — committing git user is `khoa.tran`; awaiting canonical owner.

## Critical
- ✅ C3 — Phoenix↔DuckDB topology → HTTP service, dbt adapter over HTTP (locked)
- ✅ C4 — `open_in_memory` → persistent file (locked)
- ✅ C8 — dbt adapter → `dbt-duckdb` fork over HTTP (locked)
- ✅ C1 — openapi global `security: []` → `bearerAuth` default; /health + /auth/* exempt — `docs/openapi.yaml`, `docs/api.html`
- ✅ C2 — dropped `bearerFormat: JWT`; documented `pk_live_` opaque format in scheme description — `docs/openapi.yaml`, `docs/api.html`
- ✅ C5 — AUTH_MODULE `validate_token` → prefix-lookup + Bcrypt.verify_pass (+ expiry guard); auth.html already correct — `architecture/AUTH_MODULE.md`
- ⚠️ C6 — invented DuckDB APIs → real DuckLake `AT (VERSION=>)` syntax (duckdb-service.html), `duckdb_query_metrics()` → profiler (postgres.html), `ducklake_data_files`→`ducklake_file` (10-partitioning-strategy.md); all with ⚠ verify notes — `docs/duckdb-service.html`, `docs/postgres.html`, `architecture/ducklake-control-plane/10-partitioning-strategy.md`
- ✅ C7 — ingestion diagram Hive-style `year=` path → flat `<file_uuid>.parquet` + catalog-metadata partitioning — `docs/duckdb-service.html`

## Consistency (S1–S14)
- ✅ S6 — scaling model (locked)
- ✅ S1 — Oban queue set → `interactive`/`ingest`/`transform`/`maintenance` everywhere — `architecture/ducklake-control-plane/02-phoenix-app.md`, `architecture/ducklake-control-plane.md`, `architecture/IMPLEMENTATION_HIERARCHY.md`, `architecture/ducklake-control-plane/03-duckdb-service.md` (+interactive queue), `architecture/UI_DESIGN.md` (`maint`→`maintenance`), `docs/glossary.html`, `docs/postgres.html`
- ✅ S2 — transform concurrency limit → `2` everywhere (md `limit: 3`→`2` + rationale; HTML already `2` with coherent 2×2=4 threading budget, untouched) — `architecture/ducklake-control-plane/03-duckdb-service.md`
- ✅ S3 — query timeout reconciled (5s client sync deadline vs 30s server hard kill) — `docs/openapi.yaml`, `docs/api.html`
- ✅ S4 — ingest uniqueness key → `table_name` (markdown source of truth; code `keys: [:table_name]` + prose "one ingest per table at a time"); fixed divergent HTML diagram label `table + filename` → `table` — `docs/duckdb-service.html`
- ✅ S5 — staging prefix term → "plain S3 prefix" everywhere; "enforced" reserved for the three DuckLake databases — `architecture/ducklake-control-plane/README.md`, `docs/index.html`, `docs/architecture.html`, `docs/glossary.html` (md `05-s3-storage.md`, `ducklake-control-plane.md`, `01-architecture.md` already correct)
- ✅ S7 — deployment posture reconciled: added "Design proposal, not a deployed service … target / reference deployment — not yet built" callout (mirrors index.html) + softened subtitle "supports"→"targets"; root-doc markdown already frames it as "not yet built" (no dedicated deployment.md exists) — `docs/deployment.html`
- ✅ S8 — reporting: glossary "materialized views refreshed via Oban" → dbt `external` materialization writing Parquet to `s3://<bucket>/reporting/`, triggered on the `transform` queue (aligned "Materialize" + "Reporting" entries) — `docs/glossary.html`
- ⬜ S9 — "README + 9 docs" → "README + 10 docs"
- ⬜ S10 — role/concurrency hero counts
- ⬜ S11 — job status `succeed` enum
- ⬜ S12 — catalog vs database wording
- ⬜ S13 — `last_used_at` column in Token schema/migration
- ⬜ S14 — PROJECT_STRUCTURE root name + LiveView list

## Drift (D1–D13)
- ✅ D1 — api.html POST /query 202 schema restored (QueryJobResult) — `docs/api.html`
- ⬜ D2 — postgres.html duplicate sections
- ⬜ D3 — dbt.html missing sections
- ⬜ D4 — engine/version settings HTML→markdown
- ⬜ D5 — STORAGE_PATH / S3=default HTML→markdown
- ⬜ D6 — app schema HTML→markdown
- ⬜ D7 — DuckLake connector maturity text
- ⬜ D8 — stale duckdb.org → ducklake.select URLs
- ⬜ D9 — "Zero JavaScript" LiveView claim
- ✅ D10 — api.html back-arrow `content:"90"` → `\2190` — `docs/api.html`
- ⬜ D11 — ui.html dead `href="#"` links
- ✅ D12 — glossary Materialize/Reporting aligned to dbt `external` materialization (same root as S8) — `docs/glossary.html`
- ⬜ D13 — footer source links page-specific

## Gaps (G1–G19)
- ✅ G11 — DuckDB INSTALL vs LOAD (locked)
- ⬜ G1 — Phoenix→DuckDB wire protocol/port/auth (covered by C3; verify)
- ⬜ G2 — read-replica catalog ATTACH + freshness (spec in 03)
- ⬜ G3 — Phoenix/Elixir version
- ⬜ G4 — token TTL/expiry; persist expires_at
- ✅ G5 — token CRUD + /auth/* + /logout DRAFT stubs added (login/logout, GET+POST /auth/token, DELETE /auth/token/{id}) + Token/TokenCreated schemas — `docs/openapi.yaml`, `docs/api.html`
- ⬜ G6 — DuckLake catalog physical schema
- ⬜ G7 — retention mechanism/default/owner
- ⬜ G8 — S3/MinIO/R2 credential + endpoint env vars
- ⬜ G9 — Postgres app-DB vs catalog-DB boundary
- ⬜ G10 — Postgres connection pooling
- ⬜ G12 — Phoenix↔DuckDB inter-service auth
- ⬜ G13 — PubSub adapter (multi-pod)
- ⬜ G14 — config/{env}.yml vs env vars
- ⬜ G15 — per-query memory limit vs container memory
- ⬜ G16 — TableLive page
- ⬜ G17 — dbt scheduling UI + test surfacing
- ⬜ G18 — local email/password accounts
- ⬜ G19 — CSRF protection

## Minor (N1–N13)
- ⬜ N1 — hexdeps.pm → hexdocs.pm
- ⬜ N2 — GitHub owner TRANTANKHOA (flag: pending owner confirmation)
- ✅ N3 — added 404 to /job/{job_id}/cancel and /retry — `docs/openapi.yaml`, `docs/api.html`
- ⚠️ N4 — Job `worker` field kept (real oban_jobs column) + ⚠ verify note added — `docs/openapi.yaml`, `docs/api.html`
- ⬜ N5 — WORKOS_API_KEY semantics
- ⬜ N6 — snapshots granularity overstatement
- ⬜ N7 — glossary DuckDB parallelism wording
- ⬜ N8 — DuckLake version citations
- ⬜ N9 — concurrency doc URL rotted
- ⬜ N10 — PROJECT_STRUCTURE internal tooling dir
- ⬜ N11 — IMPLEMENTATION_HIERARCHY Phase 7 dbt gaps
- ⬜ N12 — multi-cloud S3 option
- ⬜ N13 — autoscale SLA target
