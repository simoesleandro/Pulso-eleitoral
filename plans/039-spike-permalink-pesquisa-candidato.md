# Plan 039 (spike): Investigar um permalink citável por pesquisa/candidato

> **Executor instructions**: This is a **design/spike plan**, not a
> build-everything plan — the goal is a short written recommendation plus a
> working prototype of the riskiest part, not a shipped feature. Follow the
> steps in order. If anything in the "STOP conditions" section occurs,
> stop and report — do not improvise past it. When done, update the status
> row for this plan in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 0992d23..HEAD -- app.py db/pesquisas.py templates/dashboard.html`
> If any of these changed since this plan was written, re-read the current
> versions before proceeding — the specific route names, function
> signatures, and template structure below may have shifted.

## Status

- **Priority**: P3
- **Effort**: M (coarse — spike/design work, not a full build)
- **Risk**: LOW (prototype only; no production route is being finalized by this plan)
- **Depends on**: none
- **Category**: direction
- **Planned at**: commit `0992d23`, 2026-07-17

## Why this matters

`PRODUCT.md` (this repo's product brief) names three personas sharing the
public dashboard, and one of them — "Jornalista/imprensa" — is described as
needing to "citar números em matéria" and "navega direto para dado
específico (instituto, data, candidato)." The doc's stated Product Purpose
section names the actual success metric: **"Sucesso = ser citável e
confiável."** Today, `templates/dashboard.html` exposes exactly four
section-level anchors (`#secao-visao-geral`, `#secao-presidente`,
`#secao-governador`, `#secao-dados`) — nothing addresses an individual poll,
institute result, or candidate comparison. A journalist today can link to
"the dashboard" or "the presidente section," not to "this specific Quaest
poll from this date" or "the full historical comparison for this
candidate." This is a direct gap against the product's own named persona
and stated success metric — not a speculative feature, but something
`PRODUCT.md` itself points at. This plan is scoped as a spike because the
right shape (a per-poll detail page? a per-candidate comparison view? a
shareable query-string state on the existing dashboard?) is a design
decision the maintainer should make with a prototype in hand, not something
to build unreviewed.

## Current state

- `db/pesquisas.py:25-58` — `get_comparativo_candidato(candidato, cargo)`
  already returns exactly the shape a "candidate detail" view would need:
  one row per institute with `percentual`, `data`, `margem_erro`. This
  function already exists and is already called by
  `app.py`'s `/api/comparativo` route — no new query logic is needed for a
  candidate-level view; only new route(s)/template(s).
- `db/pesquisas.py:60+` — `get_pesquisas_mais_recentes(cargo, tipo)` returns
  the most recent poll per cargo with its full set of candidate
  intentions — the shape a "poll detail" view would need, though it
  currently only returns the *most recent* poll, not an arbitrary
  historical one by ID; a poll-detail permalink would need a new query
  (`SELECT ... FROM pesquisas WHERE id = ?`) joined with `intencoes` and
  `institutos`, which does not exist as a function today — confirm with
  `grep -n "def get_pesquisa_por_id\|WHERE p.id = ?" db/pesquisas.py`
  (expected: no matches, confirming this is new).
- `templates/dashboard.html:46,80,183,257` — the four existing section
  anchors, for reference on the current permalink granularity.
- `PRODUCT.md` — read the full file before starting; the "Users" and
  "Product Purpose" sections are the direct grounding for this spike, and
  the "Design Principles" section (methodology always visible, one office
  at a time) constrains what a detail view must show (source, institute,
  date, type — not just the raw number).

## What this spike must produce

Not shippable code — a short written recommendation (a markdown doc, e.g.
`docs/spike-permalink-pesquisa.md`, or inline in your final report if the
operator prefers) covering:

1. **Which shape to build**, with a one-paragraph case for each option
   considered:
   - A. Per-poll detail page/route (e.g. `/pesquisa/<id>`) using a new
     `get_pesquisa_por_id(id)` query function.
   - B. Per-candidate comparison anchor/route (e.g.
     `/comparativo/<candidato>` or a query-string-addressable state on the
     existing dashboard, e.g. `/dashboard?candidato=Lula`) built on the
     already-existing `get_comparativo_candidato`.
   - C. Both, in sequence, and which order.
   - D. Neither — an honest "not worth it yet" verdict is acceptable if the
     spike surfaces a reason (e.g. traffic data showing nobody deep-links
     today, or a simpler fix like better `<meta>` tags on section anchors
     covers most of the citability need).
2. **A working prototype of the riskiest/most novel piece only** — for
   whichever option you recommend, build the minimum needed to prove it
   works end-to-end: one new route, one new (or reused) query function, and
   a bare-bones template render (does not need dashboard.html's full visual
   polish — a plain HTML table showing institute/date/percentual/margem_erro
   is sufficient to prove the concept). This proves the query and routing
   work; it does not need to be production-styled.
3. **Open questions for the maintainer** — things this spike cannot resolve
   alone: URL scheme preference, whether detail pages should be indexable
   by search engines (SEO angle — `PRODUCT.md` doesn't mention this,
   explicitly flag it as unaddressed), whether social-share meta tags
   (Open Graph) matter for the "shared via WhatsApp/Twitter" usage context
   `PRODUCT.md` describes, and rough effort for the full (non-prototype)
   build once a direction is chosen.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Tests | `python -m pytest -q` | all pass — prototype code should not break existing tests |
| Manual check | `python app.py`, visit prototype route in a browser | renders without error |

## Scope

**In scope**:
- Reading `PRODUCT.md`, `db/pesquisas.py`, `app.py`'s existing route
  patterns, and `templates/dashboard.html`'s existing template structure to
  ground the recommendation.
- One new prototype route in `app.py` (or a new small template file) for
  whichever option you recommend, minimal styling.
- One new query function in `db/pesquisas.py` if needed (e.g.
  `get_pesquisa_por_id`), following the existing query style in that file
  (parameterized SQL, `get_db()` context manager — see
  `get_comparativo_candidato` for the pattern to match).
- The written recommendation doc.

**Out of scope**:
- Wiring the prototype into `templates/dashboard.html`'s real navigation or
  making it visually match the site's design system — this is a spike, not
  the final feature.
- Any decision about SEO/Open Graph implementation — surface it as an open
  question, do not implement it.
- Modifying any existing route or query function — only add new ones.
- Committing to a specific URL scheme as final — the prototype's URL is a
  working example, not a commitment; say so in the recommendation doc.

## Git workflow

- Branch: `advisor/039-spike-permalink-pesquisa-candidato`
- Commit message style: `spike(produto): protótipo de permalink por pesquisa/candidato`
- Do NOT push or open a PR unless the operator instructed it. Given this is
  a spike, consider explicitly flagging in your final report that this
  branch is exploratory and not intended to merge as-is — the maintainer
  should treat it as a reference, then decide whether to turn the
  recommendation into a real numbered plan.

## Steps

### Step 1: Read the grounding docs and existing query surface

Read `PRODUCT.md` in full. Read `db/pesquisas.py`'s existing query
functions (`get_comparativo_candidato`, `get_pesquisas_mais_recentes`) to
confirm what data shape is already available versus what would need a new
query.

**Verify**: you can state, in your own words, which of the two options
(A/B from "What this spike must produce") needs zero new backend query
logic and which needs one new function — this should be obvious from
reading the two existing functions above.

### Step 2: Prototype the recommended option end-to-end

Build the minimum route + query (if needed) + bare template to prove the
concept renders real data from the local dev database. Use `app.py`'s
existing route style as the pattern (see any simple `@app.route(...)` GET
handler that queries and renders, e.g. `/metodologia`'s route for the
render-a-template shape, or `/api/comparativo`'s route for the
query-and-jsonify shape if you're prototyping a JSON-first approach
instead).

**Verify**: `python app.py`, visit the prototype route in a browser, confirm it renders real poll/candidate data without a server error.

### Step 3: Run the test suite to confirm nothing broke

**Verify**: `python -m pytest -q` → all pass, same baseline count (the prototype adds code but should not need new required tests at spike stage — see Test plan).

### Step 4: Write the recommendation doc

Write the recommendation covering the three points in "What this spike must
produce." Keep it under ~1 page — this is a decision aid, not a spec.

**Verify**: the doc exists (wherever you and the operator agree it should live) and explicitly answers: which option, why, and what's still open.

## Test plan

No required new automated tests at spike stage — this is exploratory code
whose purpose is to inform a decision, not to ship. If your prototype adds
a new query function to `db/pesquisas.py`, a single smoke test confirming
it doesn't crash on the seeded test database is reasonable (model after any
existing simple test in `tests/test_dashboard.py` or `tests/test_database.py`
for a `client.get(...)` pattern), but do not build a full test suite around
throwaway spike code.

- Verification: `python -m pytest -q` → all pass, baseline + at most 1 smoke test.

## Done criteria

Machine-checkable + a written deliverable. ALL must hold:

- [ ] A working prototype route exists and renders real data when the app is run locally
- [ ] `python -m pytest -q` exits 0, no regression from baseline
- [ ] A written recommendation exists covering: which option, one-paragraph case for each option considered, and the open-questions list from "What this spike must produce"
- [ ] The recommendation explicitly states this branch/prototype is not intended to merge as-is
- [ ] `plans/README.md` status row updated, noting this was a spike (not a shipped feature) and pointing to the recommendation doc's location

## STOP conditions

Stop and report back (do not improvise) if:

- The grounding read of `PRODUCT.md` and the current dashboard suggests
  this gap has already been addressed by other work since this plan was
  written (e.g. a permalink feature landed via a different plan) — report
  and stop rather than duplicating it.
- Building even the minimal prototype requires touching more than one
  existing file beyond adding new routes/functions (e.g. if it turns out
  the existing template system requires deep changes to render even a
  bare-bones detail page) — that's a signal the "minimal prototype" scope
  was underestimated; report what you found instead of expanding scope
  unilaterally.

## Maintenance notes

- If the maintainer picks a direction from this spike's recommendation,
  the next step is a full numbered plan (following the standard template,
  not this spike template) scoped to the actual build: real styling
  matching the design system, proper route naming, SEO/OG decision applied,
  and full test coverage — this spike's prototype code should likely be
  discarded and rebuilt cleanly rather than incrementally polished, since
  spike code deliberately skips the rigor a shipped feature needs.
- This spike does not investigate the CSV/JSON export/API direction item
  already tracked in `plans/README.md`'s backlog (roadmap #9) — that's a
  related but separate direction, addressable independently.
