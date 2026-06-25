# Phoenix Lake Documentation Audit

**Scope:** `architecture/*.md`, `architecture/ducklake-control-plane/*.md` (incl. `README.md`), and `docs/` (`openapi.yaml` + rendered HTML pages).
**Date:** 2026-06-25
**Mode:** Read-only. No source document was modified; this run only produces this report.

Every finding cites `file:line` and, where it changes the meaning, an exact quoted snippet so the citation can be re-checked. Citations were verified against the files on disk (not just inferred). Where a technical claim depends on a third-party product's current behaviour (DuckDB/DuckLake/dbt/Postgres/S3), the finding says "verify against current docs" rather than asserting.

---

## Summary

**Overall health: mixed.** The architecture markdown is internally coherent at the narrative level — the control-plane / data-plane split, the write-then-publish invariant, and the landing/refining/reporting layer model are stated consistently across documents. However, the documentation set has three systemic problems that would mislead a real implementation:

1. **The Phoenix↔DuckDB integration is the single most load-bearing fact in the system, and four documents describe it four different ways.** It is unclear what protocol Phoenix uses to reach DuckDB, where `dbt run` executes, and whether write-serialization is even enforceable.
2. **The OpenAPI contract contradicts the security design.** It declares no authentication on any endpoint and labels the token format as JWT, while every other document describes opaque bcrypt-hashed `pk_live_` tokens.
3. **The rendered HTML has drifted ahead of (and occasionally diverged from) the markdown source of truth**, and several HTML pages contain rendering defects (duplicate sections, a dropped response schema, a stale external URL) with no counterpart in the markdown.

**Counts** (deduplicated across the four concern areas):

| Severity | Count |
|----------|------:|
| Critical | 8 |
| Consistency (cross-document contradictions) | 14 |
| Drift (markdown↔HTML, openapi↔api/auth/data-flow) | 13 |
| Coverage gaps | 19 |
| Minor / nits | 13 |

The critical issues are concentrated in three clusters: **auth/API contract**, **the DuckDB service + dbt execution topology**, and **rendered HTML fidelity**. Most are individually cheap to fix; their collective effect is that a builder cannot currently derive one consistent, buildable spec from the docs.

---

## Critical Issues

### C1. OpenAPI declares no security on any endpoint
`docs/openapi.yaml:802` — `security: []` — overrides the `bearerAuth` scheme defined at `openapi.yaml:796-800` globally, so per the contract **every** endpoint (`/query`, `/ingest`, `/databases`, `/table`, `/job`) is unauthenticated.
- **Contradicts:** `architecture/AUTH_MODULE.md:427` ("Validates and authorizes every request") and `architecture/ducklake-control-plane/02-phoenix-app.md:66-74` ("Authenticates users and service clients at the edge").
- **Impact:** An implementer deriving the contract from OpenAPI would build an open API. The `/health` exception is plausible, but the global `[]` makes *everything* open.
- **Fix:** Set a global default of `security: [bearerAuth: []]` and mark only `/health` and the `/auth/*` browser flows as exceptions (or apply `bearerAuth` per-operation).

### C2. Token format mismatch: OpenAPI says JWT, all other docs say opaque `pk_live_` bcrypt tokens
`docs/openapi.yaml:800` — `bearerFormat: JWT` — vs `architecture/AUTH_MODULE.md:35` (`Authorization: Bearer pk_live_...`), `AUTH_MODULE.md:91` (`pk_live_<48 random chars>`), `AUTH_MODULE.md:80` (`# bcrypt hash`).
- The Phoenix tokens are random opaque strings looked up by 8-char prefix and verified with bcrypt. They are **not** JWTs. (`jose` at `AUTH_MODULE.md:309` is only an IdP JWT adapter, not the local token format.)
- **Fix:** Drop `bearerFormat: JWT` (or change the scheme to `type: apiKey`), and document the `pk_live_` opaque-token format in the OpenAPI description.

### C3. The Phoenix↔DuckDB integration and dbt execution topology is described four incompatible ways
This is the most under-specified, load-bearing fact in the system. Four documents give four different models:

| Source | Claim | Lines |
|--------|-------|-------|
| `02-phoenix-app.md` | Phoenix "calls the DuckDB service synchronously" — no protocol given | `02-phoenix-app.md:11-12` |
| `ducklake-control-plane.md` | DuckDB runs as "a dedicated query service (Rust wrapping DuckDB, or a thin DuckDB server)" **and** "worker-embedded DuckDB inside Oban workers" | `ducklake-control-plane.md:91-93` |
| `03-duckdb-service.md` | An Axum **HTTP** server owns a persistent DuckDB connection; Phoenix/Oban call it over HTTP; writes go through a per-table writer queue | `03-duckdb-service.md:53,196-226` |
| `09-dbt-integration.md` | The Oban worker runs `dbt run`; dbt connects to the DuckDB service **directly over the PostgreSQL wire protocol** through a load balancer | `09-dbt-integration.md:125-127,141-143,151-153` |
| `docs/duckdb-service.html` | "dbt connects via dbt-postgres adapter through load balancer … SQL via Postgres wire protocol" | `duckdb-service.html:151-153,720` |

- These are materially different architectures with different auth boundaries, pooling, and write-serialization points. "Worker-embedded DuckDB inside Oban workers" (Elixir) is not technically possible without a binding (DuckDB has no native Elixir NIF); the Rust/Axum story in `03` implies the opposite. If dbt connects direct over the Postgres wire (`09`, HTML), the per-table writer queue in `03` cannot enforce write serialization. No markdown states the host, port, or transport; the only port (`8080`) and the `DUCKDB_HOST`/`DUCKDB_PORT` vars exist solely in `docs/deployment.html:82,294-300`.
- **Fix:** Pick one topology, state the wire protocol + port + inter-service auth in `03-duckdb-service.md` (and reflect it in `02` and `09`), and reconcile whether dbt goes through the Axum service or direct.

### C4. DuckDB service code sample uses `open_in_memory`, contradicting the "persistent warm-cached connection" design
`architecture/ducklake-control-plane/03-duckdb-service.md:207` — `Connection::open_in_memory_with_flags(...)` (read path) and `:223` — `Connection::open_in_memory()` (write path), while the prose says the read connection is "read-only, **persistent**" (`:201`) and the service is "a long-running process" with a warm cache (`:53`, `:323` D4).
- An in-memory DuckDB has no persistence and no on-disk catalog; it cannot be the warm-cached process the latency story depends on, and it cannot meaningfully "ATTACH a Postgres-backed DuckLake catalog" as a persistent store.
- **Fix:** Use `Connection::open(<file>)` (or document that the local file is scratch and the catalog is ATTACHed over the `postgres` extension), and align the code with the prose.

### C5. `validate_token` hashes then does an equality lookup — can never match (broken auth)
`architecture/AUTH_MODULE.md:407-409`:
```
hash = Bcrypt.hash_pwd_salt(key)
case PhoenixLake.Repo.get_by(Token, key_prefix: prefix, key_hash: hash) do
```
- `Bcrypt.hash_pwd_salt/1` generates a fresh random salt on every call, so the computed `hash` will never equal the stored `key_hash`. Token validation is broken as written. This directly contradicts design decision D1 at `AUTH_MODULE.md:744` ("use `Bcrypt.verify_pass`") and `docs/auth.html:194`, which correctly use prefix-lookup + `verify`.
- **Fix:** Replace the body with prefix-lookup (`get_by(Token, key_prefix: prefix)`) then `Bcrypt.verify_pass(key, token.key_hash)`, as D1 describes.

### C6. Invented / non-public DuckDB APIs in the rendered HTML
- `docs/duckdb-service.html:443` — `SELECT * FROM ducklake_snapshots WHERE version = 42`
- `docs/duckdb-service.html:445` — `SELECT * FROM ducklake_data_files WHERE snapshot_id = ...`
- `docs/postgres.html:486` — `SELECT * FROM duckdb_query_metrics()`

DuckLake snapshot/file metadata is **not** exposed for arbitrary client `SELECT` under those names; the documented public interface is DuckDB's table-versioning syntax (e.g. `my_ducklake.at_version('events', 42)` / `AT VERSION`). `duckdb_query_metrics()` is not a documented DuckDB function. These read as fabricated APIs and would mislead an implementer. (Note: `10-partitioning-strategy.md:139-140` also queries `ducklake_data_files` / `ducklake_table` as if stable public tables; the catalog DDL is never specified — see G6.)
- **Fix:** Replace the snapshot reads with the real `AT VERSION` syntax; remove or correct `duckdb_query_metrics()` (DuckDB exposes profiling via `EXPLAIN`/`pragma_database_size`/settings, not a query-metrics function). Verify the internal catalog table names before quoting them.

### C7. Ingestion diagram shows Hive-style directory partitioning that contradicts the partitioning strategy
`docs/duckdb-service.html:407` — `promote files to landing/orders/year=.../` (Hive-style path) vs `architecture/ducklake-control-plane/10-partitioning-strategy.md:115` — "Partition keys are stored in **catalog metadata**, not in file paths" (the Iceberg-like model DuckLake uses).
- These are two different physical layouts. If keys live in catalog metadata (per the strategy doc), the path should not encode `year=`.
- **Fix:** Make the ingestion diagram consistent with the catalog-metadata model (drop the `year=` path), or change the strategy doc.

### C8. dbt adapter story is self-contradictory and technically unsound
`architecture/ducklake-control-plane/09-dbt-integration.md:85` says `profiles.yml` is generated "with the correct **`attach` entries**" (a DuckDB-adapter concept), but `:131` shows the profile as `type: postgres` connecting over the "Postgres wire protocol" (`:125-127`) to a single `dbname: landing`. A `postgres`-type dbt profile cannot use DuckDB `ATTACH` semantics; the two halves describe different adapters. Separately, treating DuckDB's Postgres-wire-compatibility layer as a drop-in Postgres server is unsound — dbt's `postgres` adapter makes assumptions (system catalogs, `information_schema` shapes, transaction semantics) that DuckDB does not guarantee. The real path is the `dbt-duckdb` adapter (which has native DuckLake support), which no document references.
- **Fix:** Pick one adapter — `dbt-duckdb` with a DuckLake catalog (recommended), or a documented Postgres-wire implementation — and make the `profiles.yml` example match the prose.

---

## Consistency Problems (cross-document contradictions)

### S1. Oban queue set disagrees across at least four documents
- `02-phoenix-app.md:60-62`, `ducklake-control-plane.md:74-75`, `IMPLEMENTATION_HIERARCHY.md:81`: three queues — `interactive`, `ingest`, `transform`.
- `03-duckdb-service.md:118-130`: three queues — `ingest`, `transform`, `maintenance` (no `interactive`).
- `docs/phoenix.html:176-180`: four queues — `interactive`, `ingest`, `transform`, `maintenance`.
- `architecture/UI_DESIGN.md:138`: `interactive, ingest, transform, maint` (abbreviated `maint`).
- **Fix:** Standardise on one set (likely `interactive`, `ingest`, `transform`, `maintenance`) and the full word `maintenance` everywhere.

### S2. Oban `transform` concurrency limit: 3 vs 2
`03-duckdb-service.md:122` — `limit: 3` vs `docs/duckdb-service.html:673,704,791` — "Oban limit: 2" / "Oban transform limit" = 2. **Fix:** pick one.

### S3. Query timeout default: 5 s vs 30 s
`docs/openapi.yaml:514` — `timeout_ms` `default: 5000` vs `02-phoenix-app.md:24` — "hard timeout (default: 30 seconds)" and `docs/data-flows.html:165,197` — "timeout: 30s". The contract's documented default is 6× smaller than the architecture's. **Fix:** align, or clarify 5 s client deadline vs 30 s server fallback.

### S4. Ingestion uniqueness key: table vs table+filename
`03-duckdb-service.md:120,133` — unique by `[:table_name]` ("only one ingest per table at a time") vs `docs/duckdb-service.html:398` — "unique by table + filename". Different dedup semantics. **Fix:** pick one and apply it to both.

### S5. Staging prefix: "enforced" vs "plain"
`ducklake-control-plane.md:29` and `docs/architecture.html:201` say "enforced staging prefix"; `01-architecture.md:43` and `ducklake-control-plane.md:36` say "plain S3 prefix". (The root design doc is also internally inconsistent — "enforced" at :29 vs "plain" at :36.) Whether staging is policy-enforced or convention matters for ingestion security. **Fix:** pick one term.

### S6. Scaling model: single-node thesis vs horizontal read-replica pool
`07-scaling-boundaries.md:3` — "a deliberate bet that one machine is enough for the data plane"; `:9` — "DuckDB runs one query in one process on one machine." vs `docs/scaling.html:57,139,175` — an auto-scaled pool of read-only DuckDB containers "Min 2, max 10", "DuckDB x2-10 (HPA)". These are two different architectures; the markdown never mentions horizontal read replicas. **Fix:** reconcile — single-node or replica pool — and make both docs agree. (See also G5: how each read-only container attaches the catalog is unspecified.)

### S7. Deployment posture: "not yet built / sketch" vs fully specified infra
`ducklake-control-plane.md:16,113-118` — "not a deployed service"; "Not yet built … would fit the existing CodePipeline model." vs `docs/deployment.html:46-61,209` — Docker Compose, Kubernetes/Helm, and AWS ECS Fargate-or-EKS with concrete task definitions, HPA, and Terraform (`deployment.html:129-131,229-231`). The HTML has materially outrun the markdown's "design sketch" framing. **Fix:** reconcile — either soften the HTML or commit the specifics into the markdown.

### S8. Reporting layer: "materialized views" vs dbt external Parquet materialization
`docs/glossary.html:94-95,155-156` — reporting "uses materialized views for dashboards … refreshed via Oban jobs" vs `09-dbt-integration.md:104-106,181-196` — reporting models use dbt **`external`** materialization writing Parquet to `s3://<bucket>/reporting/`. DuckLake/DuckDB materialized views are a different mechanism than external Parquet tables. **Fix:** align the glossary to the dbt design.

### S9. "README + 9 docs" but the directory has 10 numbered docs
`ducklake-control-plane.md:133` — "Full design set: … (README + 9 docs)." The directory actually contains `README.md` plus `01`…`10` (10 numbered docs). **Fix:** "README + 10 docs."

### S10. Component / role counts in HTML hero stats disagree with the source
- `docs/phoenix.html:47` — "4 Core roles" vs `AUTH_MODULE.md:58` and `docs/auth.html:49` ("3 Roles": admin/editor/viewer). The "4" likely counts `default_role`, which is a fallback, not a role.
- `docs/phoenix.html:49` — "∞ Concurrent users" vs `07-scaling-boundaries.md:31-34` ("bounded concurrency … tens of dashboards, a team of analysts").
- **Fix:** change 4→3 (or relabel), and replace ∞ with a bounded figure.

### S11. Job status enum `succeed` (verb-as-state)
`docs/openapi.yaml:391` — `enum: [queued, running, succeed, failed]` (repeated `:539,571,603`; mirrored in `api.html`). `succeed` is a verb; unusual and likely a typo for `succeeded`/`success`. Stable across both specs but suspect. **Fix:** confirm intent and, if wrong, rename everywhere.

### S12. "Catalog" vs "database" used interchangeably for landing/refining/reporting
`01-architecture.md:36-37` ("Three DuckLake catalogs") vs `ducklake-control-plane.md:29` ("three enforced DuckLake **databases**") vs `ducklake-control-plane.md:33-34` ("three DuckLake catalogs"). DuckLake distinguishes a catalog from a database within it; conflating them misleads. **Fix:** standardise and clarify catalog-vs-database.

### S13. `last_used_at` referenced but absent from the Token schema and migration
`docs/auth.html:196,422` and `architecture/AUTH_MODULE.md:748` (D5: "Add `last_used_at`") reference it, but the Token schema (`AUTH_MODULE.md:76-88`) and migration (`AUTH_MODULE.md:692-699`) define no such column. The audit-trail guarantee (`AUTH_MODULE.md:729`) depends on a column that does not exist. **Fix:** add `last_used_at :utc_datetime` to schema + migration.

### S14. PROJECT_STRUCTURE root name and listed directories do not match the repo
`PROJECT_STRUCTURE.md:6` draws the tree under a root named `ducklake/`; the real repo root is `phoenix-lake`. The claimed tree also includes directories that do not yet exist (`dbt/`, `helm/`, `terraform/`, the full `app/lib/...` LiveView tree at `PROJECT_STRUCTURE.md:48-104`) and lists only 4 LiveView modules (`:77-81`) where `UI_DESIGN.md:212-219` requires 6 (`TableLive`, `IngestLive` missing). Given the repo is scaffolding, this is acceptable as an *intended* layout, but the doc presents it as the current layout. **Fix:** label it as planned/target structure, fix the root name, and align the LiveView module list with `UI_DESIGN.md`.

---

## Drift (markdown↔HTML, and openapi↔api/auth/data-flow docs)

### D1. `api.html` drops the `POST /query` 202 response schema that `openapi.yaml` defines
`docs/api.html:277-279` — `202` has only a `description`, no `content`/`schema` vs `docs/openapi.yaml:149-154` — `202` → `QueryJobResult`. The two "rendered" specs disagree on the response body of the same operation. (Aside from this, `api.html` matches `openapi.yaml` byte-for-byte.) **Fix:** re-render `api.html` from `openapi.yaml`.

### D2. `postgres.html` has duplicated / jumbled sections (rendering defect)
`docs/postgres.html` shows two "Ownership Rules" headers (`:390` and `:408`), two identical "Advantages" cards (`:361` and `:396`), and the section counter restarts. The markdown (`04-postgres-ducklake.md`) has no such duplication. **Fix:** regenerate `postgres.html` from `04-postgres-ducklake.md`.

### D3. `dbt.html` omits several sections present in `09-dbt-integration.md`
`docs/dbt.html` drops the `profiles.yml` block (`09:125-137`), the template-validation rules (`09:87-112`), the incremental-models section (`09:236-241`), and the `dbt_project.yml` convention (`09:168-179`). The HTML reader therefore never sees the dbt adapter/connection story. **Fix:** re-render `dbt.html`.

### D4. Engine/DB versions and settings appear only in HTML, never in markdown
- DuckDB engine `v1.5.2` (`architecture.html:212`) — silent in every markdown file.
- `PostgreSQL 16 · single instance` (`postgres.html:81`) — silent in `04-postgres-ducklake.md`.
- DuckDB settings `memory_limit=4-8GB`, `threads=CPU`, `access_mode=READ_ONLY` (`duckdb-service.html:601-604`) — silent in `03-duckdb-service.md`.
- *(Note: the "DuckLake 1.0 client list" / "0.3 added Iceberg interop" references at `architecture.html:213` do appear in markdown at `04-postgres-ducklake.md:79` and `07-scaling-boundaries.md:43`, so DuckLake versioning is consistent; only the **DuckDB engine** version is HTML-only.)*
- **Fix:** record versions in the markdown (which is the source of truth) and regenerate HTML.

### D5. `STORAGE_PATH` env var and the "S3 = default" label are HTML-only
`docs/duckdb-service.html:271,256` and `docs/s3.html:125,128` introduce `STORAGE_PATH=...` and label S3 as `default`; `03-duckdb-service.md:41-45` defines neither (it requires `STORAGE_BACKEND=s3` explicitly). **Fix:** add to the markdown or remove from the HTML.

### D6. The full application Postgres schema is HTML-only
`docs/postgres.html:169-268` enumerates `users, tokens, grants, datasets, tables, query_history, query_results, oban_jobs`. `04-postgres-ducklake.md` lists only roles (`:9-15`); the app schema is silent. **Fix:** move the app-schema list into the markdown.

### D7. DuckLake connector maturity text differs
`04-postgres-ducklake.md:79` lists "Spark, Trino, DataFusion, **and Pandas**" and notes "0.3 added Iceberg read/write interop"; `docs/postgres.html:427` drops Pandas and the 0.3 detail ("emerging but most are work-in-progress"). **Fix:** re-render.

### D8. Stale DuckLake reference URL in three HTML pages
`docs/duckdb-service.html:1004`, `docs/postgres.html:555`, `docs/s3.html:301` all link `https://duckdb.org/docs/extensions/ducklake.html`, while the markdown source list uses the current official site `https://ducklake.select/` (`08-validation.md:50-52`). The `duckdb.org` path is the old extension page and likely redirects/404s. **Fix:** update the HTML links to `ducklake.select`.

### D9. Overstated "Zero JavaScript" LiveView claim (HTML-only)
`docs/phoenix.html:164-167` — "LiveView eliminates the need for a separate JavaScript frontend … zero JavaScript." LiveView requires a small JS client (`phoenix_live_view.js`) for the WebSocket. `02-phoenix-app.md:38-47` phrases it correctly. **Fix:** "minimal JavaScript," matching the markdown.

### D10. `api.html` back-nav arrow renders the literal string `90`
`docs/api.html:28` — `.back-nav a::before { content: "90"; }`. The link displays `90 Back to Documentation` instead of a ← arrow. **Fix:** `content: "\2190";` (←).

### D11. UI navigation links are dead (`href="#"`)
`docs/ui.html:141-145,167,258,296` — Dashboard/Query/Datasets/Jobs/Ingest nav and "View all"/"Export" anchors all use `href="#"`. Acceptable only if `ui.html` is a static mockup; otherwise link to the in-page section anchors. **Fix:** point to section anchors or document as mockup-only.

### D12. Glossary "Materialize"/"Reporting" contradict the dbt external-materialization design
(Same root issue as S8, listed under Drift because the glossary is the rendered term reference.) `glossary.html:94-95,156` says reporting uses "materialized views … refreshed via Oban jobs"; `09-dbt-integration.md:104-106` says dbt `external` Parquet materialization. **Fix:** align the glossary definition.

### D13. Footer "Design spec" link is generic across pages
`docs/dbt.html:156`, `glossary.html:189`, `index.html:123` (and others) footer-link to `architecture/ducklake-control-plane.md` regardless of page source. For `dbt.html` the real source is `09-dbt-integration.md` (correctly linked in the body at `dbt.html:150`). **Fix:** make footer source links page-specific.

---

## Gaps (implied but never fully specified)

| # | Gap | Where implied | Why it matters |
|---|-----|---------------|----------------|
| G1 | Phoenix→DuckDB wire protocol / port / auth | `01-architecture.md:26`, `02-phoenix-app.md:11-12` | Defines system shape; only `deployment.html:82` gives port 8080. (See C3.) |
| G2 | DuckDB read-replica catalog attach model | `scaling.html:65-75,175` | Multiple read-only DuckDB containers each must ATTACH the Postgres catalog; write contention / freshness unspecified. |
| G3 | Phoenix / Elixir version | every markdown file | Build pinning; silent everywhere. (See D4.) |
| G4 | API token TTL / expiry default | `AUTH_MODULE.md:84,745`; `auth.html:249` | `expires_at` is `virtual: true` (not persisted), so D2's "reject if past" cannot work; no TTL value anywhere. **Fix:** persist the column + state a default TTL. |
| G5 | Token CRUD + `/auth/*` + `/logout` endpoints | `AUTH_MODULE.md:75-91,631-637` | No way to create/rotate/revoke tokens or perform browser login exists in `openapi.yaml`. |
| G6 | DuckLake catalog physical schema | `10-partitioning-strategy.md:139-140`; `duckdb-service.html:443-445` | Example queries assume stable catalog table names that are never specified; catalog DDL absent. |
| G7 | Retention mechanism + default + owner | `05-s3-storage.md:65-72` | "a retention policy expires old snapshots" — by what (DuckLake `snapshot_retention`? a Phoenix job?), default, configurability all unstated. |
| G8 | S3/MinIO/R2 credential + endpoint env vars | `03-duckdb-service.md:47` | `AWS_ACCESS_KEY_ID`, `AWS_ENDPOINT_URL_S3`, `AWS_REGION`, `AWS_ALLOW_HTTP`, path-style vs virtual-host — none enumerated; MinIO path-style is a common setup failure. |
| G9 | Postgres app-DB vs catalog-DB boundary | `04-postgres-ducklake.md:66-74` | Same Postgres *database* (schema-qualified) or separate? RLS never mentioned. |
| G10 | Postgres connection pooling | `03-duckdb-service.md:83`; `duckdb-service.html:240` | Pooler choice (PgBouncer?), pool size, DuckLake `postgres`-extension pooling — unspecified. |
| G11 | DuckDB extension INSTALL vs LOAD; offline behaviour | `03-duckdb-service.md:211` | `INSTALL …;` with no `LOAD`; air-gapped/offline `INSTALL` not addressed. |
| G12 | Phoenix↔DuckDB inter-service auth | `02-phoenix-app.md:70-71` | "DuckDB trusts the control plane" — but `deployment.html:213` gives DuckDB its own IAM task role; nothing documents how Phoenix authenticates to the DuckDB endpoint (port 8080). Real security gap. |
| G13 | PubSub adapter (multi-pod) | `02-phoenix-app.md:30,44`; `deployment.html:131` | With >1 Phoenix pod the PubSub backend is load-bearing (PG2/Postgres/Redis) and unspecified. |
| G14 | Two config mechanisms coexist | `ducklake-control-plane.md:110-111` vs `deployment.html:89-96` | `config/{env}.yml` vs environment variables — unexplained. |
| G15 | Per-query memory limit vs container memory | `deployment.html:309` vs `:130` | `DUCKDB_MEMORY_LIMIT` default 4 GB equals the container 4 Gi — one query could exhaust a pod. |
| G16 | `TableLive` page | `UI_DESIGN.md:217` | Routed (`/datasets/:database/:table`) but never designed (no mock/components). |
| G17 | dbt scheduling UI + test-result surfacing | `09-dbt-integration.md:116,141` | Runs trigger on "cron schedule"; no UI to edit cron; no doc on surfacing `dbt build` test results. |
| G18 | Local (email/password) accounts | `AUTH_MODULE.md:70` | "local accounts (email/password …)" claimed, but no password field on User, no hashing lib (Argon2/bcrypt/comeonin), no login flow. |
| G19 | CSRF protection | `AUTH_MODULE.md:621-624` | Browser pipeline issues session cookies but neither AUTH_MODULE nor auth.html mention CSRF tokens. |

---

## Minor / Nits

- **N1.** `architecture/AUTH_MODULE.md:300` — link `https://hexdeps.pm/assent` is a typo for `hexdocs.pm/assent` (used correctly elsewhere, e.g. `:8,734`).
- **N2.** `docs/*.html` footers (30 occurrences) — "Design spec: https://github.com/**TRANTANKHOA**/phoenix-lake". The committing git user is `khoa.tran`; confirm the canonical GitHub owner and update if stale.
- **N3.** `docs/openapi.yaml:431-457` — `/job/{job_id}/cancel` and `/retry` omit `404`, unlike sibling cancel endpoints (`:189,255`) and `/job/{job_id}` GET (`:428`). Add `404` for consistency.
- **N4.** `docs/openapi.yaml:572-573` — Job schema `worker` field is stale for an Oban-only design (Oban 2.x jobs have no user-facing `worker` column in the way modelled). Verify against the real `oban_jobs` columns.
- **N5.** `architecture/AUTH_MODULE.md:331-332` — `WORKOS_API_KEY` is read as an OAuth `client_secret`; WorkOS uses it as the server API key, not a client secret. Document exact semantics.
- **N6.** `architecture/ducklake-control-plane/08-validation.md:20-21` — "snapshots can reference parts of a Parquet file, so millions can coexist" overstates granularity; DuckLake tracks files (and append/delete islands), not arbitrary sub-file byte ranges. Soften.
- **N7.** `docs/glossary.html:66` — DuckDB "can't shuffle across machines" is true but phrased to imply no parallelism (DuckDB is multi-threaded single-node). Optional wording.
- **N8.** `04-postgres-ducklake.md:79` and `08-validation.md:38` — "DuckLake 1.0 client list" / "0.3 added Iceberg interop" are uncited to any release note (the only URL, `08:50`, is the 0.1 launch post). Add a citation or mark as illustrative.
- **N9.** `08-validation.md:55` — `https://duckdb.org/docs/current/connect/concurrency` may have rotted (DuckDB periodically reorganises docs). Verify.
- **N10.** `PROJECT_STRUCTURE.md:150-155` — the canonical project tree includes an internal tooling dir (`.mimocode/skills/…`). Out of place in an architecture doc; remove.
- **N11.** `IMPLEMENTATION_HIERARCHY.md:93-101` — Phase 7 (dbt) omits `external` materialization, `ducklake.yml` provisioning, and retention that `09-dbt-integration.md` makes first-class. Add them.
- **N12.** `architecture/ducklake-control-plane.md:127` — "S3 (or GCS/Azure Blob)" multi-cloud option appears only in the root design doc; all architecture/UI docs assume S3. Commit to S3-only or propagate the abstraction.
- **N13.** `docs/scaling.html:86,137` — autoscale metric "P95 > SLA → add" but no SLA value is defined anywhere. State a target P95.

---

## Recommendations

1. **Resolve the Phoenix↔DuckDB topology first (C3, C8).** It is the highest-leverage fix: one decision (HTTP service vs Postgres-wire; dbt in-worker vs in-service; the wire protocol + port + inter-service auth) unblocks C3, C4, the write-serialization question, and G1/G2/G12. Record it in `03-duckdb-service.md` and cascade to `02`, `09`, and the HTML.
2. **Fix the API contract (C1, C2, S3, G5).** Remove the global `security: []` and the `bearerFormat: JWT`; align the timeout default; add token CRUD + `/auth/*` + `/logout`. These are small edits that remove the most misleading contract claims.
3. **Fix the broken auth code (C5, S13, G4).** Correct `validate_token`; persist `expires_at`; add `last_used_at`. These are correctness bugs, not just doc drift.
4. **Treat the architecture markdown as the single source of truth and regenerate the HTML (D1–D13).** Several drift items (D1 `api.html`, D2 `postgres.html`, D3 `dbt.html`, D8 stale URL) are mechanical re-render fixes. A single regeneration pass from the corrected markdown would close most drift findings. (The repo already has an `align-html` workflow for exactly this.)
5. **Standardise the small facts (S1–S14).** Queue names, transform limit, timeout, uniqueness key, staging "enforced" vs "plain", catalog-vs-database, "9 docs", role/concurrency counts. A short "canonical facts" appendix (ports, env vars + defaults, queue set, table names, versions) in `architecture/ducklake-control-plane.md` would prevent recurrence.
6. **Back-fill the build-critical gaps (G1–G19).** Prioritise G1 (connectivity), G4/G5 (auth lifecycle), G6 (catalog schema), G8 (S3 env vars), G9/G10 (Postgres boundary + pooling), G12/G13/G19 (inter-service auth, PubSub, CSRF). Each is a concrete item a builder needs and currently cannot find.
7. **De-risk technical-accuracy claims (C6, C7, N6, N8, N9).** Replace invented DuckDB APIs with real DuckLake syntax; cite (or mark illustrative) version/interop claims; verify the concurrency-doc URL.

**Sequencing:** items 1–3 are correctness-critical and should precede any build work; items 4–5 are a single doc-render + standardisation pass; items 6–7 can follow as the build plan firms up.
