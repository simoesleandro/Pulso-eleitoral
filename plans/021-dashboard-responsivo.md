# Plan 021: Dashboard responsivo — grids fixos e tabelas sem scroll quebram em mobile

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 8d3827f..HEAD -- templates/dashboard.html static/css/base.css`
> If either file changed since this plan was written, re-run the `grep`
> commands in "Current state" to confirm the line numbers and content still
> match before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug (UX)
- **Planned at**: commit `8d3827f`, 2026-07-16

## Why this matters

The dashboard's design system already has a working responsive pattern
(`.pe-kpi-grid` collapses from 4 to 2 columns under 768px — see
`static/css/base.css:297-304`), but several grids inside
`templates/dashboard.html` were written with **inline** `grid-template-
columns` styles that bypass that system entirely and never collapse on
small screens. Four wide `<table>` elements also have no horizontal-scroll
container, so on a narrow viewport their columns get squeezed or the table
overflows the page. This is a real, visible breakage for any mobile visitor
— and the fix is almost entirely mechanical: replace ad-hoc inline styles
with classes that follow the pattern already proven correct elsewhere in
the same file.

## Current state

- The working reference pattern — `static/css/base.css:297-304`:

```css
.pe-kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
@media (max-width: 768px) {
  .pe-kpi-grid { grid-template-columns: repeat(2, 1fr); }
}
```

- The non-responsive grids in `templates/dashboard.html` (line numbers as of
  commit `8d3827f` — re-confirm with `grep -n "grid-template-columns"
  templates/dashboard.html` before editing, since earlier changes this
  session may have shifted a couple of lines):

  - `:62` — `<div class="pe-kpi-grid" style="grid-template-columns: repeat(3,1fr); gap:16px; margin-top:16px;" id="kpis-avancados-grid">` — Visão Geral analytics grid (margem/turno/concentração).
  - `:205` — `<div style="display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-bottom:24px;" id="kpis-analise-grid">` — RJ analysis grid (campo minado/volatilidade/aceleração).
  - `:119` and `:185` — `<div style="display:grid; grid-template-columns:1fr 1fr; gap:16px;">` — two-column layout blocks inside the presidente/governador sections (confirm exact surrounding context before editing; these may be candidate-info side-by-side blocks).
  - `:833` and `:871` — `<div style="display:grid; grid-template-columns:1fr 1fr; gap:16px;">` — two 2nd-round simulation cards.

- The four wide tables with no scroll wrapper — `grep -n "<table"
  templates/dashboard.html`:

  - `:693` — comparativo entre institutos
  - `:992` — regional por estado
  - `:1128` and `:1174` — house-effects / rejeição (confirm which is which
    by reading the surrounding `<div id="...">` before editing)

  Current shape (example, `:693`):

```html
<table style="width:100%; border-collapse:collapse;">
```

  None of these four tables are wrapped in a scrollable container.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Run tests | `TESTING=True python -m pytest -q` | all pass (this is a template-only change; confirm nothing HTML-snapshot-tests these exact strings) |
| Visual check | run the app locally and resize the browser to ~375px width (iPhone SE) for each of the 6 grids and 4 tables | no column squeezing, no page-level horizontal scroll; tables scroll internally instead |

## Scope

**In scope**:
- `templates/dashboard.html` — the 6 grid `style="..."` attributes and 4
  `<table>` elements listed above
- `static/css/base.css` — add 1-2 new utility classes (see Step 1) if you
  choose the class-based approach instead of repeating inline media-query
  workarounds

**Out of scope**:
- Any visual redesign beyond making existing layouts collapse correctly
  (no new columns, no reordering of cards).
- The `.pe-kpi-grid` class itself (`base.css:297-304`) — already correct,
  do not touch.
- JS logic that populates these grids/tables (`carregarKpisAvancados()`,
  `carregarKpisAnaliseRJ()`, etc.) — only the surrounding HTML/CSS changes.

## Git workflow

- Branch: `advisor/021-dashboard-responsivo`
- Commit message style: conventional commits in Portuguese, e.g.
  `fix(dashboard): grids e tabelas responsivos em telas pequenas`
- Do NOT push or open a PR unless explicitly instructed.

## Steps

### Step 1: Add a reusable 3-column responsive class

In `static/css/base.css`, add a new class next to `.pe-kpi-grid`
(`base.css:297-304`) for the 3-column grids, following the exact same
shape:

```css
.pe-kpi-grid-3 {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
@media (max-width: 768px) {
  .pe-kpi-grid-3 { grid-template-columns: 1fr; }
}
```

(Collapsing 3→1 column on mobile, not 3→2, since 2 columns of a 3-column
KPI card layout tends to look uneven — use your judgment here only if the
existing `.pe-kpi-grid` 4→2 pattern suggests otherwise; if in doubt, match
`.pe-kpi-grid`'s ratio convention instead of inventing a new one.)

**Verify**: `grep -n "pe-kpi-grid-3" static/css/base.css` shows the new
rule with its media query.

### Step 2: Apply the new class to the two 3-column grids

Replace the inline `style="grid-template-columns: repeat(3,1fr); ..."` at
`dashboard.html:62` and `:205` with `class="pe-kpi-grid pe-kpi-grid-3"` (or
just `class="pe-kpi-grid-3"` if `.pe-kpi-grid` provides no shared
properties beyond `display:grid`/`gap` that this new class doesn't already
have — check for conflicts before combining both classes on one element).
Keep any other inline styles on those elements that aren't
`grid-template-columns`/`gap` (e.g. `margin-top`, `margin-bottom`) as
inline styles — this plan only moves the responsive-breaking property.

**Verify**: reload the dashboard at ≤768px width — both grids stack to 1
column; at ≥769px they show 3 columns side by side as before.

### Step 3: Fix the four `1fr 1fr` grids

For `dashboard.html:119`, `:185`, `:833`, `:871`, add a media query. Since
these are one-off inline blocks (not reused elsewhere), the simplest
correct fix is a shared class rather than 4 separate inline-style
edits — add to `base.css`:

```css
.pe-grid-2col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
@media (max-width: 768px) {
  .pe-grid-2col { grid-template-columns: 1fr; }
}
```

then replace each of the four `style="display:grid; grid-template-
columns:1fr 1fr; gap:16px;"` attributes with `class="pe-grid-2col"`.

**Verify**: at ≤768px, each of the 4 blocks stacks to 1 column; content
inside them (2nd-round simulation cards, presidente/governador side-by-side
blocks) remains readable, not overlapping.

### Step 4: Wrap the 4 wide tables in a scroll container

For each of the 4 `<table>` elements found via `grep -n "<table"
templates/dashboard.html`, wrap it in a div:

```html
<div style="overflow-x:auto;">
  <table style="width:100%; border-collapse:collapse; ...">
    ...
  </table>
</div>
```

Do this by editing the opening `<table ...>` line to insert the wrapper
`<div>` immediately before it, and find that table's matching closing
`</table>` tag to insert the closing `</div>` immediately after — read
enough surrounding context for each table to locate its correct closing
tag (they are not adjacent lines; each table body has multiple rows).

**Verify**: at ≤375px width, each table scrolls horizontally within its own
container instead of causing the whole page to scroll sideways or squeezing
column text unreadably.

## Test plan

- This is a template/CSS-only change with no new server-side logic, so no
  new Python test is required. If the repo has any HTML-snapshot or
  Selenium/Playwright UI test that asserts exact `style` attribute strings
  on these elements (check `tests/test_templates_refactor.py` and
  `tests/test_dashboard.py` for any string-matching on `grid-template-
  columns` or the affected `id`s), update those assertions to match the new
  class-based markup instead of the old inline styles.
- Verification: `TESTING=True python -m pytest -q` → all pass (confirms no
  existing test asserts on the removed inline styles) — if any test fails
  because it string-matches an inline style, note it in your report as a
  file you needed to update.

## Done criteria

- [ ] `TESTING=True python -m pytest -q` exits 0
- [ ] `grep -n "grid-template-columns: repeat(3,1fr)\|grid-template-columns:repeat(3,1fr)" templates/dashboard.html` returns no matches (both migrated to the new class)
- [ ] `grep -n "grid-template-columns:1fr 1fr" templates/dashboard.html` returns no matches (all 4 migrated)
- [ ] `grep -c "overflow-x:auto" templates/dashboard.html` is at least 4 (one per wrapped table)
- [ ] Manual check at 375px width: no page-level horizontal scrollbar, all 4 tables scroll internally, all 6 grids collapse to fewer columns
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row for 021 updated

## STOP conditions

- Any of the 6 grid locations or 4 table locations don't match the excerpts
  above (file has drifted) — re-grep and re-read before editing.
- Combining `.pe-kpi-grid` and the new `.pe-kpi-grid-3` class on the same
  element produces a CSS conflict (e.g. both define
  `grid-template-columns`, and cascade order matters) — in that case, use
  `.pe-kpi-grid-3` alone without `.pe-kpi-grid`, and note the decision.
- An existing test asserts on the literal inline `style` string you're
  removing and you can't tell from the test name/context whether updating
  it is safe — stop and report rather than guessing at intent.

## Maintenance notes

- Any future card grid added to `dashboard.html` should use
  `.pe-kpi-grid`/`.pe-kpi-grid-3`/`.pe-grid-2col` (or a new equally-
  responsive class) instead of inline `grid-template-columns` — this plan
  fixes the existing instances but doesn't prevent a future PR from
  reintroducing the same mistake; a lint/review note may be worth adding to
  `CLAUDE.md`'s conventions section.
- This plan does not address the broader inline-style sprawl noted in the
  UX audit (font-sizes, spacing scattered as `style="..."` throughout the
  file) — that's a larger tech-debt item, tracked separately, not bundled
  here.
