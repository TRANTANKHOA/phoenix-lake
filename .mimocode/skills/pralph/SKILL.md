---
name: pralph
description: Use pralph for multi-phase AI development workflow — plan, stories, implement, justloop, compound learning, and project querying
---

# Pralph — Multi-Phase AI Development Workflow

**Pralph** (Planned Ralph) orchestrates Claude Code externally to automate the full software development lifecycle — from design to implementation.

## Installation

Prerequisites: Python 3.10+, Claude Code CLI installed and authenticated.

```bash
cd /Users/khoa.tran/plutusoft/pralph
./install.sh
```

This creates a virtualenv, installs dependencies (DuckDB, click, tenacity), and adds `pralph` to your PATH.

## Script Location

```bash
python3 .claude/skills/pralph/pralph.py <command> [args...]
```

Or use the installed `pralph` command directly after installation.

## Core Workflow

The standard pralph workflow follows these phases:

`plan` → `stories` → `webgen` (optional) → `implement`

### Phase 1: Plan

Create a comprehensive design document through interactive conversation with Claude.

```bash
# Create design document (--name sets project identity)
pralph plan --name <project-name> --prompt "Build a task management app with auth"

# Via skill wrapper
python3 .claude/skills/pralph/pralph.py plan --name <project-name> "Build a task management app"
```

Output: `.pralph/design-doc.md`, `.pralph/guardrails.md`

### Phase 2: Stories

Extract user stories from the design document.

```bash
pralph stories

# Via skill wrapper
python3 .claude/skills/pralph/pralph.py stories
```

Stories are stored in DuckDB with acceptance criteria, priority, complexity, and dependencies.

### Phase 2b: Add / Ideate / Refine

Manage stories on the fly:

```bash
# Add a single story as an idea
pralph add --prompt "add dark mode support" --next

# Break a high-level idea into multiple stories
pralph ideate "add internationalization support"

# Refine existing stories (split, merge, rewrite)
pralph refine -s AUTH-001 "split into login and registration"
```

### Phase 3: Implement

Autonomously implement stories from the backlog.

```bash
# Implement with review and compound learning
pralph implement --compound --max-iterations 30

# Via skill wrapper
python3 .claude/skills/pralph/pralph.py implement --compound
```

## Justloop

A simple loop for running any prompt to completion without the full workflow:

```bash
# Task as positional argument
pralph justloop "refactor the auth module to use JWT tokens"

# Multi-word prompts work naturally
pralph justloop fix all linting errors and update deprecated API calls

# Via skill wrapper
python3 .claude/skills/pralph/pralph.py justloop "fix all linting errors"
```

## Compound Learning

Capture non-trivial solutions as structured documentation:

```bash
# Auto-capture after each successful story
pralph implement --compound

# Ad-hoc capture from recent work
pralph compound --prompt "Fixed CORS issue by adding middleware"
pralph compound --story-id AUTH-001
```

Solutions are stored in `.pralph/solutions/` and automatically recalled during future phases.

## Query and Monitor

Query project data stored in DuckDB:

```bash
# Built-in shortcuts
pralph query --progress        # story counts by status
pralph query --cost            # cost breakdown by phase
pralph query --cost-per-story  # cost per story
pralph query --stories         # list all stories with status
pralph query --errors          # recent errors
pralph query --timeline        # implementation timeline
pralph query --report          # full progress report
pralph query --report --watch 10  # auto-refresh every 10 seconds

# Custom SQL
pralph query "SELECT id, title, status FROM stories WHERE priority = 1"
```

## Story Viewer

Browse and manage stories in a web UI:

```bash
pralph viewer            # opens http://localhost:8411
pralph viewer --port 9000 --no-open
```

## Global Options

| Option | Default | Description |
|--------|---------|-------------|
| `--model` | `opus` | Model alias or full Claude model name |
| `--max-iterations` | `50` | Max loop iterations per phase |
| `--max-budget-usd` | — | Cost limit per Claude invocation |
| `--cooldown` | `5` | Seconds between iterations |
| `--verbose` | — | Show full Claude output |
| `--project-dir` | `.` | Target project directory |

## Command Options Summary

### `plan`
- `--name` — Project name (required on first run)
- `--prompt` — Guidance for design doc creation
- `--reset` — Reset phase state and start fresh

### `stories`
- `--extract-weight` (default: `80`) — Extract vs research weight (0-100)
- `--reset` — Reset phase state

### `webgen`
- `--reset` — Reset phase state

### `add`
- `--prompt` — Brief idea to turn into a story
- `--next` — Priority 1 — implement next
- `--anytime` — Let Claude pick priority

### `ideate`
- `--ideas-file` — Path to ideas file (default: `.pralph/ideas.md`)
- `--prompt` — Ideas as inline text

### `refine`
- `-s`, `--story` — Story ID(s) to refine (repeatable)
- `-p`, `--pattern` — Glob pattern to match story IDs
- `--prompt` — Refinement instruction

### `implement`
- `--story-id` — Implement a specific story
- `--phase1` / `--no-phase1` (default: on) — Architecture-first grouping
- `--review` / `--no-review` (default: on) — Run reviewer after each implementation
- `--compound` / `--no-compound` (default: off) — Capture learnings after each story
- `--prompt` — Guidance for implementation
- `--parallel` — Max concurrent stories (default: 1)

### `justloop`
- `--prompt` — Task prompt
- `--reset` — Reset phase state

### `compound`
- `--story-id` — Story ID to capture learnings from
- `--prompt` — Description of what was done

### `query`
- `--progress` — Story progress by status
- `--cost` — Cost breakdown
- `--stories` — List all stories
- `--errors` — Recent errors
- `--report` — Full progress report
- `--watch SECONDS` — Auto-refresh

## Configuration

Config is resolved in order: project `.pralph/config.json` > user `~/.pralph/config.json` > defaults.

```json
// ~/.pralph/config.json
{
  "global_compound": true  // Save learnings globally by domain
}
```

## Project State

Local files (in `.pralph/`):
- `project.json` — Project identity
- `config.json` — Project-level config overrides
- `domains.txt` — Override auto-detected domains
- `design-doc.md` — Design document
- `guardrails.md` — Coding standards
- `review-feedback/` — Per-story review notes
- `solutions/` — Compound learning knowledge base

DuckDB tables (in `~/.pralph/pralph.duckdb`):
- `projects` — Registered projects
- `stories` — Story backlog
- `status_log` — Status change history
- `run_log` — Per-iteration log with costs
- `phase_state` — Current phase progress
- `solutions_index` — Searchable solution index

## Token Usage Warning

pralph orchestrates multiple Claude Code sessions in a loop. A single `implement` run can use significant tokens. Use `--max-budget-usd` and `--max-iterations` to set limits, and monitor usage with `pralph query --cost`.

## Quick Reference

```bash
# Full workflow
pralph plan --name myapp "Build a task manager"
pralph stories
pralph implement --compound
pralph query --report

# Add story mid-workflow
pralph add --prompt "add dark mode" --next

# Quick task loop
pralph justloop "fix all linting errors"

# Check progress
pralph query --report --watch 10
```
