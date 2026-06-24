# 02 — Phoenix application

Phoenix is the control plane. It does no heavy data work; it coordinates.

## API

The API is the programmatic entry point for clients and integrations.

- Accepts query requests, ingestion submissions, and job-control calls.
- Validates and authorizes every request before any work is scheduled.
- For fast, interactive queries it calls the DuckDB service synchronously and
  streams rows back.
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

## Oban

Oban is the job engine, backed by the same Postgres instance.

- Runs ingestion, dbt transformations, compaction, and scheduled
  reports as background jobs.
- Provides retries, uniqueness, scheduling (cron-style), and rate limiting per
  queue — so heavy data work is throttled independently of web traffic.
- Each job invokes the DuckDB service to do the actual data work, then records
  the outcome and the resulting catalog snapshot in Postgres.

Queues are separated by cost profile (for example: a low-latency `interactive`
queue, a `ingest` queue, and a `transform` queue) so a backlog of heavy jobs
never starves quick ones.

## Auth

Authentication and authorization live entirely in the control plane.

- Authenticates users and service clients at the edge.
- Authorizes access at the dataset/table level before any query reaches DuckDB.
- The DuckDB service trusts the control plane: it only ever receives requests
  that have already been authorized, scoped to the tables the caller may read.

This keeps the data plane simple — DuckDB does not implement multi-tenant
access control; Phoenix does, once, at the boundary.

## State Phoenix owns in Postgres

- Users, sessions, roles, and grants.
- Dataset and table registrations (the user-facing catalog of what exists).
- Query history and results metadata.
- Oban job rows and their state.

This is *app* metadata, kept separate from — but in the same database as — the
DuckLake catalog described in [04](04-postgres-ducklake.md).
