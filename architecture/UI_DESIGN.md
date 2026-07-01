# UI Design

LiveView-based interactive dashboard. Server-rendered, real-time over WebSocket. No separate JavaScript frontend.

## Pages

### 1. Dashboard (home)

Default landing page. At-a-glance system status.

```
┌─────────────────────────────────────────────────────────────────┐
│  Phoenix Lake                                    [user] [logout]│
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ 3        │ │ 12       │ │ 847      │ │ 2.4 GB   │          │
│  │ databases│ │ tables   │ │ queries   │ │ storage  │          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
│                                                                 │
│  ┌─────────────────────────────┐ ┌─────────────────────────┐   │
│  │  Active Jobs                │ │  System Health           │   │
│  │  ─────────────              │ │  ──────────────          │   │
│  │  🟢 ingest/orders    2m ago │ │  DuckDB    ● connected  │   │
│  │  🟡 transform/models running│ │  Postgres  ● connected  │   │
│  │  ⚪ compact/landing  queued │ │  S3        ● connected  │   │
│  │                             │ │  Oban      ● healthy    │   │
│  │  View all →                 │ │                          │   │
│  └─────────────────────────────┘ └─────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Recent Queries                                         │   │
│  │  ─────────────                                          │   │
│  │  SELECT count(*) FROM landing.orders  succeed  120ms   │   │
│  │  SELECT * FROM refining.users LIMIT 10 succeed  45ms   │   │
│  │  SELECT sum(revenue) FROM reporting…  succeed  890ms   │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

**LiveView:** `DashboardLive`
- PubSub subscribes to job events, query completions
- Stats update in real-time as jobs complete
- Auto-refresh every 5s for health checks

### 2. Query Builder

Interactive SQL editor with results viewer.

```
┌─────────────────────────────────────────────────────────────────┐
│  Query Builder                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Database: [landing ▾]    Timeout: [30s]                        │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  SELECT o.id, o.total, u.email                          │   │
│  │  FROM landing.orders o                                  │   │
│  │  JOIN landing.users u ON o.user_id = u.id               │   │
│  │  WHERE o.created_at > '2026-01-01'                      │   │
│  │  ORDER BY o.total DESC                                  │   │
│  │  LIMIT 100                                              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  [▶ Run Query]  [Save]  [History]                               │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Results (100 rows, 120ms)                    [Export ▾]│   │
│  │  ─────────────────────────────────────────────────────  │   │
│  │  │ id    │ total  │ email              │                │   │
│  │  ├───────┼────────┼────────────────────┤                │   │
│  │  │ 12401 │ 9,847  │ alice@acme.com     │                │   │
│  │  │ 11892 │ 8,234  │ bob@startup.io     │                │   │
│  │  │ 10345 │ 7,891  │ carol@bigco.com    │                │   │
│  │  │ ...   │ ...    │ ...                │                │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

**LiveView:** `QueryLive`
- Run query → synchronous if fast, 202 + polling if async
- Results table with sort, pagination
- Export to CSV/Parquet
- Query history sidebar

### 3. Dataset Browser

Explore databases, tables, schemas.

```
┌─────────────────────────────────────────────────────────────────┐
│  Datasets                                                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐           │
│  │ 🟢 landing   │ │ 🟢 refining  │ │ 🟢 reporting │           │
│  │ 12 tables    │ │ 8 tables     │ │ 5 tables     │           │
│  │ 1.2 GB       │ │ 890 MB       │ │ 340 MB       │           │
│  │ [Browse →]   │ │ [Browse →]   │ │ [Browse →]   │           │
│  └──────────────┘ └──────────────┘ └──────────────┘           │
│                                                                 │
│  ── landing/orders ──────────────────────────────────────────  │
│                                                                 │
│  Schema:                                                        │
│  ┌────────────┬──────────┬────────┬──────────┐                 │
│  │ Column     │ Type     │ Nullable│ Partition │                │
│  ├────────────┼──────────┼────────┼──────────┤                 │
│  │ id         │ BIGINT   │ no     │          │                 │
│  │ user_id    │ BIGINT   │ no     │          │                 │
│  │ total      │ DECIMAL  │ no     │          │                 │
│  │ status     │ VARCHAR  │ yes    │          │                 │
│  │ created_at │ TIMESTAMP│ no     │ ✓        │                 │
│  └────────────┴──────────┴────────┴──────────┘                 │
│                                                                 │
│  Stats: 847,293 rows · 234 files · 1.2 GB · Snapshot #1,847  │
│                                                                 │
│  [Query this table]  [Ingest data]  [View snapshots]            │
└─────────────────────────────────────────────────────────────────┘
```

**LiveView:** `DatasetsLive`
- Click database → list tables
- Click table → route to `/datasets/:database/:table` (TableLive, below)
- Schema viewer with column types and descriptions
- Snapshot history (time travel)

### 3b. Table Detail (TableLive)

Routed single-table deep-dive — the page a table name links to from the
Dataset Browser, Query results, and Jobs. This is the "time travel" surface:
pick a snapshot and the schema/stats/query actions all reflect that version.

```
┌─────────────────────────────────────────────────────────────────┐
│  Datasets › landing › orders                    [user]          │
├─────────────────────────────────────────────────────────────────┤
│  orders   (last ingested 2m ago · snapshot #1,847)              │
│                                                                 │
│  Snapshot: [1,847 (current) ▾]   ⬚ Time travel                 │
│                                                                 │
│  [Query at #1,847]  [Ingest data]  [Export Parquet/CSV]        │
│                                                                 │
│  ── Schema ─────────────────────────────────────────────────── │
│  ┌────────────┬───────────┬────────┬──────────┬──────────────┐ │
│  │ Column     │ Type      │ Null   │ Partition │ Description │ │
│  ├────────────┼───────────┼────────┼──────────┼──────────────┤ │
│  │ id         │ BIGINT    │ no     │          │ Order id     │ │
│  │ user_id    │ BIGINT    │ no     │          │ FK → users   │ │
│  │ total      │ DECIMAL   │ no     │          │ Order total  │ │
│  │ status     │ VARCHAR   │ yes    │          │ order state  │ │
│  │ created_at │ TIMESTAMP │ no     │ ✓ y/m/d  │ partition key│ │
│  └────────────┴───────────┴────────┴──────────┴──────────────┘ │
│                                                                 │
│  ── Stats (#1,847) ────────────────────────────────────────── │
│  847,293 rows · 234 files · 1.2 GB · 12 partitions             │
│  storage: s3://phoenix-lake/landing/orders/                    │
│                                                                 │
│  ── Snapshot history ──────────────────────────────────────── │
│  ┌────────┬─────────────────┬────────┬────────┬──────────────┐ │
│  │ Snap   │ Written         │ Rows   │ Files  │ Change       │ │
│  ├────────┼─────────────────┼────────┼────────┼──────────────┤ │
│  │ #1,847 │ 2026-06-28 14:02│ 847,293│ 234    │ +1,204 (app) │ │
│  │ #1,846 │ 2026-06-28 09:15│ 846,089│ 232    │ +880 (app)   │ │
│  │ #1,845 │ 2026-06-27 21:30│ 845,209│ 231    │ compact (×4) │ │
│  │ #1,840 │ 2026-06-26 03:00│ 842,011│ 240    │ retention ✓  │ │
│  └────────┴─────────────────┴────────┴────────┴──────────────┘ │
│                                                                 │
│  ── Recent ingestions ───────────────────────────────────────  │
│  abc.parquet  ✅ done  12,847 rows  2m ago   [Job #847]       │
│  def.parquet  🟢 run   —          running   [Job #849]       │
└─────────────────────────────────────────────────────────────────┘
```

**LiveView:** `TableLive` (`/datasets/:database/:table`, session + grant)
- **Snapshot selector** drives the whole page — schema, stats, and the
  "Query at #N" action are all re-resolved against the chosen DuckLake
  snapshot (`AT (VERSION => N)`), enabling read-only time travel without
  mutating the table's current state.
- Schema viewer uses the `SchemaViewer` component (column type + partition
  marker, same as the Dataset Browser).
- Stats row reads from the DuckLake catalog (`ducklake_table`,
  `ducklake_data_file` aggregates — see `10-partitioning-strategy.md`);
  rows/size reflect the selected snapshot, not just `current`.
- Snapshot history lists recent snapshots with row/file delta and the
  mutation kind (append / compact / retention sweep — refs G7); selecting
  a row updates the selector.
- **Recent ingestions** filters `query_history`/Oban jobs to this table
  and links into the Job Monitor.
- Actions are **grant-gated**: viewers get read-only (query/time-travel);
  editors also see Ingest / Export. A 403 surfaces as the `--color-error`
  banner, consistent with the global authz model.

### 4. Job Monitor

Real-time job status with live updates.

```
┌─────────────────────────────────────────────────────────────────┐
│  Jobs                                           [Filter ▾]     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Status: [All] [Running] [Queued] [Succeed] [Failed]           │
│  Queue:  [All] [interactive] [ingest] [transform] [maintenance]│
│                                                                 │
│  ┌──────┬───────────┬──────────┬────────┬────────┬──────────┐ │
│  │ ID   │ Queue     │ Status   │ Worker │ Started│ Duration │ │
│  ├──────┼───────────┼──────────┼────────┼────────┼──────────┤ │
│  │ #847 │ ingest    │ 🟢 run   │ Ingest │ 2m ago │ 2m 14s   │ │
│  │ #846 │ transform │ 🟡 queue │ Transf │ 5m ago │ —        │ │
│  │ #845 │ ingest    │ ✅ done  │ Ingest │ 8m ago │ 1m 02s   │ │
│  │ #844 │ interact  │ ✅ done  │ Query  │ 12m ago│ 3.2s     │ │
│  │ #843 │ maint     │ ❌ fail  │ Compa… │ 15m ago│ 45s      │ │
│  └──────┴───────────┴──────────┴────────┴────────┴──────────┘ │
│                                                                 │
│  ── Job #847 ────────────────────────────────────────────────  │
│  Worker: PhoenixLake.Jobs.IngestWorker                          │
│  Args: {"table": "orders", "file": "20260619_120000_abc.par"}  │
│  Result: {"rows_inserted": 12847, "snapshot_id": 1848}         │
│  Attempts: 1/3                                                  │
│                                                                 │
│  [Cancel]  [Retry]                                              │
└─────────────────────────────────────────────────────────────────┘
```

**LiveView:** `JobsLive`
- PubSub subscribes to Oban job events
- Rows update in real-time (no page refresh)
- Click row → expand details
- Cancel/retry actions

### 5. Ingestion Tracker

Upload and monitor file ingestion.

```
┌─────────────────────────────────────────────────────────────────┐
│  Ingestion                                                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Drop files here or [Browse files]                       │   │
│  │  Target table: [orders ▾]                                │   │
│  │                                                          │   │
│  │  📄 20260619_120000_abc.parquet  2.3 MB  [Upload]       │   │
│  │  📄 20260619_120001_def.parquet  1.8 MB  [Upload]       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ── Recent Ingestions ───────────────────────────────────────  │
│                                                                 │
│  ┌────────────┬────────┬──────────┬──────────┬──────────┐      │
│  │ File       │ Table  │ Status   │ Rows     │ Time     │      │
│  ├────────────┼────────┼──────────┼──────────┼──────────┤      │
│  │ abc.par    │ orders │ ✅ done  │ 12,847   │ 2m 14s   │      │
│  │ def.par    │ users  │ 🟢 run   │ —        │ running  │      │
│  │ ghi.par    │ items  │ ❌ fail  │ —        │ 45s      │      │
│  └────────────┴────────┴──────────┴──────────┴──────────┘      │
│                                                                 │
│  Error: ghi.par — Schema mismatch: column 'price' expected      │
│  DECIMAL(10,2), got VARCHAR                                      │
└─────────────────────────────────────────────────────────────────┘
```

**LiveView:** `IngestLive`
- Drag-and-drop file upload
- Progress bar via PubSub
- Error details with schema mismatch info

## Navigation

```
┌─────────────────────────────────────────────────────────────────┐
│  🦆 Phoenix Lake    Dashboard  Query  Datasets  Jobs  Ingest   │
│                                                          [user] │
└─────────────────────────────────────────────────────────────────┘
```

| Route | LiveView | Auth |
|-------|----------|------|
| `/` | `DashboardLive` | session |
| `/query` | `QueryLive` | session |
| `/datasets` | `DatasetsLive` | session |
| `/datasets/:database/:table` | `TableLive` | session + grant |
| `/jobs` | `JobsLive` | session |
| `/ingest` | `IngestLive` | session + grant |

## Components

### Shared

- `NavbarComponent` — top nav with active state
- `StatsGrid` — stat cards with numbers
- `StatusBadge` — colored status indicators (running, queued, succeeded, failed)
- `DataTable` — sortable, paginated table
- `SchemaViewer` — column list with types and partition markers
- `JobRow` — expandable job details
- `FileUpload` — drag-and-drop with progress

### Real-time

- PubSub topics: `job:<id>`, `query:<id>`, `ingest:<id>`
- LiveView subscriptions auto-reconnect on disconnect
- Optimistic UI updates for cancel/retry actions

## Design Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--color-phoenix` | `#7c3aed` | Primary actions, links |
| `--color-success` | `#22c55e` | Succeed status, health |
| `--color-warning` | `#f59e0b` | Running, queued |
| `--color-error` | `#ef4444` | Failed, 403 |
| `--color-info` | `#3b82f6` | Query, schema |
| `--color-muted` | `#64748b` | Secondary text |
| `--radius` | `8px` | Card, button corners |
| `--shadow` | `0 2px 8px rgba(0,0,0,0.06)` | Card hover |
