---
name: align-html
description: Use when the Phoenix Lake HTML architecture document needs to match the markdown source documents, or after editing markdown docs to update the HTML visualization
---

# Align HTML Architecture Document

Keep `ducklake-control-plane-architecture.html` in sync with the markdown source documents.

## Source of Truth

The markdown documents are authoritative. The HTML is a visual rendering.

| Document | Purpose |
|----------|---------|
| `architecture/ducklake-control-plane.md` | Overview, business logic, application architecture, infrastructure |
| `architecture/ducklake-control-plane/README.md` | Shape, data flows, dbt integration summary, document index |
| `architecture/ducklake-control-plane/01-architecture.md` | Two planes, responsibilities, boundaries |
| `architecture/ducklake-control-plane/06-data-flows.md` | Ingestion, query, transformation paths |
| `architecture/ducklake-control-plane/09-dbt-integration.md` | Git-synced workflow, template YAML, conventions |

## Alignment Checklist

When markdown changes, update the HTML to match:

1. **Component descriptions** — cards under "The shape" must match the component list in README and 01-architecture
2. **Data flows** — ingestion/query/transformation steps must match 06-data-flows
3. **Application architecture** — Phoenix and DuckDB service bullet lists must match 01-architecture and overview
4. **Infrastructure** — spec-rows must match the overview and 04-postgres-ducklake
5. **dbt section** — must match 09-dbt-integration (template YAML, validation rules, execution flow)
6. **Design validation** — cards must match 08-validation
7. **Stat grid** — numbers must be accurate (4 components, 3 databases, 0 catalog servers, 1 writer per table)
8. **Footer links** — paths must resolve to existing files

## Common Drift Patterns

- Queue names change (e.g. adding `materialize` queue) — update Phoenix bullet list
- New design docs added — add corresponding section or card to HTML
- Staging/database naming conventions change — update data flow steps and stat grid
- dbt validation rules change — update template YAML and validation bullets

## Process

1. Read the relevant markdown source document
2. Locate the corresponding HTML section
3. Update text, steps, or data to match
4. Verify all internal links resolve
5. Open in Chrome to visually confirm
