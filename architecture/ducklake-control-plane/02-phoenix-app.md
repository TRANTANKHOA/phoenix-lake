# 02 — Phoenix application

Phoenix is the control plane. It does no heavy data work; it coordinates.

> **Target runtime: Phoenix 1.8 on Elixir 1.18 / Erlang OTP 27** (current as of
> mid-2026). The major versions are the target; patch levels track upstream and
> are pinned by the release build's lockfile. This is a *proposed* pin — confirm
> against the real `mix.lock` once the `app/` scaffold is generated. (OTP 27 over
> 28: OTP 28 has a known `mix release` regex issue at the time of writing.) See
> D4 for the matching DuckDB / PostgreSQL version pins.

## API

The API is the programmatic entry point for clients and integrations.

- Accepts query requests, ingestion submissions, and job-control calls.
- Validates and authorizes every request before any work is scheduled.
- For fast, interactive queries it calls the DuckDB service over HTTP
  synchronously and streams rows back.
- For anything expensive or long-running it enqueues an Oban job and returns a
  job handle the client can poll or subscribe to.

The key rule: the API never blocks a web process on a large scan. Either the
query is small and bounded, or it becomes a job.

## Query routing

The API decides per-request whether to run a query synchronously or enqueue it.
The routing uses a timeout-based fallback:

1. Phoenix calls the DuckDB service synchronously with a hard timeout (default:
   30 seconds).
2. If the query completes within the timeout, results stream back directly.
3. If the timeout fires, Phoenix kills the DuckDB connection, enqueues the query
   as an Oban job on the `interactive` queue, and returns a job handle to the
   client.
4. The client receives a 202 with the handle, then polls or subscribes to PubSub
   for results.

This avoids estimating query cost upfront. The DuckDB service enforces
per-query memory and row limits so a runaway query fails fast rather than
consuming unbounded resources. The timeout is configurable per-project.

## LiveView

LiveView is the interactive UI: dashboards, query builders, job monitors, dataset
browsers.

- Renders results pushed from the server, so the UI updates in real time as a
  job progresses or a query returns.
- Subscribes to job and query events over PubSub, so a running transformation
  or ingestion reflects live in the browser without polling.
- Keeps per-session UI state on the server, which suits exploratory analytics
  where each user drives a sequence of queries.

## PubSub (multi-pod adapter)

LiveView and the API rely on PubSub for real-time job/query/ingest events
(`job:<id>`, `query:<id>`, `ingest:<id>` topics — see [UI](UI_DESIGN.md) and
[06](06-data-flows.md)). On a single pod any adapter works trivially; the
choice only becomes load-bearing once `phoenix.replicas > 1`, because a job
running on pod A must broadcast its progress to a LiveView socket connected to
pod B.

**Default (proposed): `Phoenix.PubSub.PG2` over a clustered BEAM.** PG2 (Erlang
process groups) is the Phoenix default and broadcasts across the cluster with no
extra infrastructure. Multi-pod only needs the pods clustered — a shared
distribution cookie and node discovery (libcluster with the Kubernetes DNS /
EPMD strategy, or DNS-based `inet_tcp`). Latency is in-process-fast and it adds
no dependency, which fits the "single Postgres, no extra stateful services"
posture.

| Concern | Default | Why |
|---------|---------|-----|
| Adapter | `Phoenix.PubSub.PG2` | Phoenix default; zero infra, in-cluster broadcast; works on one pod or N. |
| Cluster wiring | libcluster (Kubernetes DNS / EPMD strategy), shared cookie | Required *only* at `phoenix.replicas > 1` so nodes form a BEAM cluster. |
| Fallback (no clustering) | `Phoenix.PubSub.Postgres` (LISTEN/NOTIFY over the shared Postgres) | When the BEAM can't be clustered (e.g. no EPMD reachability), reuses the existing Postgres — no Redis — at the cost of slightly higher latency and a little catalog-DB load. |
| Extra infra (Redis) | **Not added by default.** | Only if a Redis is already operated; the design avoids a second stateful service. |

> **Proposed, not yet built.** Confirm the discovery strategy against the
> deployment target (libcluster's `Kubernetes.DNS` vs `Kubernetes.EPMD` vs
> ECS/gossip) at scaffold time. With one Phoenix pod the default just works;
> PG2 + clustering is the multi-pod promotion path, and Postgres-backed PubSub
> is the no-extra-infra fallback.

## Oban

Oban is the job engine, backed by the same Postgres instance.

- Runs ingestion, dbt transformations, compaction, and scheduled
  reports as background jobs.
- Provides retries, uniqueness, scheduling (cron-style), and rate limiting per
  queue — so heavy data work is throttled independently of web traffic.
- Each job invokes the DuckDB service over HTTP to do the actual data work,
  then records the outcome and the resulting catalog snapshot in Postgres. For
  dbt, the worker runs `dbt` whose thin custom adapter submits compiled SQL to
  the service — the worker itself runs no DuckDB.

Queues are separated by cost profile — `interactive` (low-latency reads that
time out of the synchronous path), `ingest`, `transform`, and `maintenance`
(compaction, retention, file cleanup) — so a backlog of heavy jobs never
starves quick ones.

## Auth

Authentication and authorization live entirely in the control plane.

- Authenticates users and service clients at the edge.
- Authorizes access at the dataset/table level before any query reaches DuckDB.
- The DuckDB service trusts the control plane: it only ever receives requests
  that have already been authorized, scoped to the tables the caller may read.
  "Trusts" means *authorization* is delegated — the service still authenticates
  that the caller is Phoenix (network-isolated port 8080 + a shared-secret
  bearer token on every request); see [03 — inter-service auth](03-duckdb-service.md#phoenixduckdb-inter-service-authentication-proposed--verify-at-build).

This keeps the data plane simple — DuckDB does not implement multi-tenant
access control; Phoenix does, once, at the boundary.

## State Phoenix owns in Postgres

- Users, sessions, roles, and grants.
- Dataset and table registrations (the user-facing catalog of what exists).
- Query history and results metadata.
- Oban job rows and their state.

This is *app* metadata, kept separate from — but in the same database as — the
DuckLake catalog described in [04](04-postgres-ducklake.md).
