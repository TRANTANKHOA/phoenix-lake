---
name: review-html
description: The single skill for Phoenix Lake HTML docs. REVIEW every page in a folder for visual rendering defects, content/correctness issues (consistency, duplication/overlap, source-vs-markdown drift, technical claims) and lossless enhancement suggestions, writing <folder>/html-review.yml; AND ALIGN the HTML to the markdown source of truth after source changes. Use for any HTML review, audit, or markdown↔HTML alignment.
---

# Review & Align HTML

One skill for the HTML docs, two modes sharing one source-of-truth model:

- **Review** (read-only) — audit every page for defects + lossless enhancements → `<folder>/html-review.yml`.
- **Align** (mutating) — update the HTML to match the markdown after source changes.

Choose by intent: "review / audit / check the HTML" → **Review**; "align / update / sync / fix the HTML to match markdown" → **Align**. (This skill absorbs the former `align-html`.)

## Source of truth (both modes)

The markdown is authoritative; the HTML is a rendering of it. Cross-check / align against:

| Source | Covers |
|--------|--------|
| `architecture/ducklake-control-plane.md` | Overview, business logic, application architecture, infrastructure |
| `architecture/ducklake-control-plane/README.md` | Shape, data flows, dbt integration summary, document index |
| `architecture/ducklake-control-plane/01-architecture.md` | Two planes, responsibilities, boundaries |
| `architecture/ducklake-control-plane/06-data-flows.md` | Ingestion, query, transformation paths |
| `architecture/ducklake-control-plane/09-dbt-integration.md` | Git-synced workflow, template YAML, conventions |
| `architecture/**/*.md` | also `AUTH_MODULE.md`, `UI_DESIGN.md`, `IMPLEMENTATION_HIERARCHY.md`, `PROJECT_STRUCTURE.md`, `02`–`10` |
| `docs/openapi.yaml` | the API contract mirrored into `docs/api.html` |

---

## Mode 1 — Review

Audit every `*.html` in a folder visually and for content/correctness, then propose lossless enhancements, and write `<folder>/html-review.yml`. **Fix nothing — only report.**

### Process

1. **Render** — `bash .mimocode/skills/review-html/render.sh <folder>` (default `docs`). Prints a manifest (rel-path → PNG files) and a final `# outdir:` line.
2. **Visual review** — `Read` every PNG page. Flag: duplicated/jumbled sections, restarting counters, identical cards or headers twice; broken glyphs (literal codes like `"90"` for `←`); overflow/overlap/cut-off/horizontal scroll; broken images/empty containers/leftover placeholder text; dead links visible (nav `href="#"`); low contrast/tiny font/wall-of-text; inconsistent header/footer/nav across pages.
3. **Content review** — read the HTML source **and** the markdown source of truth. Flag:
   - **consistency** — the same fact disagrees across pages or vs markdown (queues, timeouts, limits, counts, naming, "enforced" vs "plain", catalog vs database)
   - **duplication** — repeated/overlapping segments: identical/near-duplicate sections, cards, or headers within a page; the same content restated across pages; HTML↔HTML or MD↔MD redundancy that should be a cross-reference, not a copy
   - **drift** — facts that exist only in HTML, dropped/added sections, stale external URLs vs markdown
   - **correctness** — invented/non-public APIs (e.g. `duckdb_query_metrics()`), broken code samples, self-contradictory adapter/protocol/topology claims
   - **gap** — implied but never specified (ports, env vars + defaults, versions)
   - **nit** — typos, dead `href="#"`, stale links

   > **Duplication vs conciseness:** a literal/near-duplicate segment (the same block twice) is a `duplication` **issue**; tightening wordy-but-unique prose is a `conciseness` **enhancement**.

4. **Cite precisely** — every issue carries `location:` (`file:line`) + a quoted `evidence:` snippet (AUDIT.md style); cross-refs in `related:`. For duplication, cite **both** occurrences.
5. **Enhancements (lossless)** — per page, concrete, reversible ways to boost visual impact / scannability / readability / conciseness **without dropping any insight or detail**:

   | Dimension | Look for |
   |-----------|----------|
   | `visual-impact` | stronger hierarchy/contrast/emphasis, whitespace, diagrams or cards so key facts stand out |
   | `scannability` | headers, TL;DR/summary boxes, comparison tables, bold key terms, TOC + anchors, progressive disclosure |
   | `readability` | shorter sentences, tighter structure, font size / line-height, chunking |
   | `conciseness` | trim redundancy/wordiness, dedupe — **state exactly what detail is preserved** |

   Every enhancement MUST include a non-empty `preserves:` field proving no insight/detail was lost.

6. **Compile & write** `<folder>/html-review.yml` per the schema below; print the summary counts.

### Issue model (two axes)
- `severity`: `critical` | `major` | `minor`
- `category`: `visual` | `consistency` | `duplication` | `drift` | `correctness` | `gap` | `nit`

### YAML schema

```yaml
folder: docs/
generated_at: 2026-06-25T22:58:00Z      # date -u +"%Y-%m-%dT%H:%M:%SZ"
reviewer:
  mode: full            # visual + content
  source_of_truth: ["architecture/**/*.md", "docs/openapi.yaml"]
files_reviewed: 14
pages_reviewed: 27
summary:
  total_issues: 20
  by_severity: { critical: 2, major: 8, minor: 10 }
  by_category: { visual: 4, consistency: 5, duplication: 2, drift: 4, correctness: 2, gap: 1, nit: 2 }
  total_enhancements: 8
  by_dimension: { visual-impact: 2, scannability: 3, readability: 1, conciseness: 2 }
issues:
  - id: V1
    file: docs/api.html
    page: 1                       # null for source-only findings
    severity: major
    category: visual
    title: Back-nav arrow renders the literal string "90"
    description: >
      The back-nav link shows "90 Back to Documentation" instead of a left
      arrow; the CSS content uses unescaped "90" rather than the U+2190 codepoint.
    location: docs/api.html:28
    evidence: '.back-nav a::before { content: "90"; }'
    suggestion: 'Set content: "\2190"; (← arrow).'
  - id: DU1
    file: docs/postgres.html
    page: 2
    severity: major
    category: duplication
    title: '"Ownership Rules" section is duplicated on the same page'
    description: >
      Two "Ownership Rules" headers and two identical "Advantages" cards appear;
      the section counter restarts. No counterpart in 04-postgres-ducklake.md.
    location: docs/postgres.html:390
    evidence: 'duplicate "Ownership Rules" header also at docs/postgres.html:408'
    related: ["docs/postgres.html:408"]
    suggestion: "Remove the duplicate block; regenerate from 04-postgres-ducklake.md."
  - id: C1
    file: docs/api.html
    page: null
    severity: critical
    category: correctness
    title: OpenAPI mirrored in the page declares no security on any endpoint
    location: docs/api.html:802
    evidence: 'security: []'
    related: ["architecture/AUTH_MODULE.md:427"]
    suggestion: "Default to bearerAuth; exempt only /health and /auth/*."
enhancements:
  - id: E1
    file: docs/duckdb-service.html
    page: 2
    dimension: scannability       # visual-impact | scannability | readability | conciseness
    title: Turn the 6-step ingestion paragraph into a numbered step table
    current: "Steps are a dense paragraph; the queue / concurrency / uniqueness facts are buried mid-sentence."
    suggestion: "3-column table (Step | Queue | Concurrency / Uniqueness) — same facts, scannable in seconds."
    preserves: "All 6 steps, queue names, and the per-table uniqueness rule remain intact."
```

### YAML hygiene
- Quote any value containing `:`, `#`, `{`, `}`, quotes, or leading/trailing spaces — when a value contains double quotes, wrap the **whole** value in single quotes (e.g. `title: '"Ownership Rules" is duplicated'`).
- Use block scalars (`>` folded / `|` literal) for long descriptions.
- `id` prefixes by type, sequential: `V` visual, `S` consistency, `DU` duplication, `D` drift, `C` correctness, `G` gap, `N` nit, `E` enhancement.

### Caveats
- **JS-rendered pages** (e.g. `docs/api.html` via swagger-ui) may render blank/partial via headless Chrome. If a page looks empty, record `category: visual, title: "page did not fully render (JS); reviewed from source"` and review from the HTML source.
- Visual review sees only what is on-screen; pair with content review for source-level defects.
- See memory `docs-html-visual-review` for the poppler / Claude-restart gotcha.

---

## Mode 2 — Align

Update the HTML to match the markdown after the source changes. Markdown is the source of truth; HTML is a rendering. **Mutating** — this mode edits HTML.

### When to use
- After editing any markdown source → re-align the rendered HTML.
- When a Review report flags `drift` / `consistency` / `duplication` issues → fix them here.

### Alignment checklist
When markdown changes, update the HTML to match:
1. **Component descriptions** — cards under "The shape" match the component list in README + `01-architecture`.
2. **Data flows** — ingestion/query/transformation steps match `06-data-flows`.
3. **Application architecture** — Phoenix and DuckDB service bullet lists match `01-architecture` + overview.
4. **Infrastructure** — spec-rows match the overview + `04-postgres-ducklake`.
5. **dbt section** — matches `09-dbt-integration` (template YAML, validation rules, execution flow).
6. **Design validation** — cards match `08-validation`.
7. **Stat grid** — numbers accurate (4 components, 3 databases, 0 catalog servers, 1 writer per table).
8. **Footer links** — paths resolve to existing files; source links are page-specific.

### Common drift patterns
- Queue names change (e.g. adding `materialize`) → update the Phoenix bullet list.
- New design docs added → add the corresponding section/card to the HTML.
- Staging / database naming conventions change → update data-flow steps and the stat grid.
- dbt validation rules change → update template YAML + validation bullets.

### Process
1. Read the changed markdown source.
2. Locate the corresponding HTML section.
3. Update text, steps, or data to match (don't clobber HTML-only content — see memory `docs-html-md-drift`).
4. Verify all internal links resolve.
5. Render with `render.sh` and visually confirm (Review mode, steps 1–2).
