# Plan 028: Acessibilidade básica do dashboard (headings, aria, gráficos)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat f53d533..HEAD -- templates/dashboard.html static/css/tokens.css`
> If either file changed since this plan was written, re-run the `grep`
> commands in "Current state" to confirm line numbers before proceeding; on
> a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug (UX/accessibility)
- **Planned at**: commit `f53d533`, 2026-07-16

## Why this matters

The dashboard has **zero** `aria-*`, `role`, or `alt` attributes anywhere
in the file (`grep -c "aria-\|role=" templates/dashboard.html` → 0) despite
being a data-dense public page. Three concrete, fixable gaps: (1) the
"Visão Geral" section is the only top-level section without an `<h2>`,
breaking the heading outline a screen-reader user relies on to navigate;
(2) the three `<canvas>` chart elements have no accessible name or
fallback text — a chart is invisible to a screen reader with nothing to
announce; (3) the estimulada/espontânea toggle buttons rely purely on a
CSS class (`pe-tipo-btn--active`) to convey which option is selected, with
no `aria-pressed` for assistive tech. These are additive, low-risk fixes
that don't change any visual layout.

## Current state

- `templates/dashboard.html:47` — the one top-level section without a
  heading (compare to `:84`, `:176`, `:220`, `:241`, which all have
  `<h2 class="pe-section__title">`):

```html
    <section id="secao-visao-geral" class="pe-section">

      <!-- Aviso de defasagem (ativado por JS quando a última pesquisa passa do limiar) -->
      <div id="aviso-defasagem" ...>
```

- `templates/dashboard.html:109,159,180` — the three `<canvas>` elements,
  none with an accessible name:

```html
<div class="pe-chart-container"><canvas id="chart-presidente"></canvas></div>
...
<div class="pe-chart-container" style="height:380px;"><canvas id="chart-historico-multi"></canvas></div>
...
<div class="pe-chart-container"><canvas id="chart-governador"></canvas></div>
```

- `templates/dashboard.html:102-103` — the toggle buttons with no
  `aria-pressed`:

```html
<button type="button" class="pe-tipo-btn pe-tipo-btn--active" data-tipo="estimulada" onclick="setTipoPres('estimulada')">Estimulada</button>
<button type="button" class="pe-tipo-btn" data-tipo="espontanea" onclick="setTipoPres('espontanea')">Espontânea</button>
```

  and the JS that toggles the active class — `templates/dashboard.html:291-292`:

```js
document.querySelectorAll('#pres-tipo-toggle .pe-tipo-btn').forEach(b =>
  b.classList.toggle('pe-tipo-btn--active', b.dataset.tipo === tipo)
```

  (there is also a `#gov-tipo-toggle` or equivalent for the governador
  section, if one exists — `grep -n "pe-tipo-toggle" templates/dashboard.html`
  to find every toggle-button group in the file, not just the presidente
  one shown above.)

- `static/css/tokens.css:20` — `--pe-text-muted: #5a7184`, used
  extensively for secondary text (labels, dates, "Fonte:" lines). A
  contrast check against the two backgrounds it's typically shown on
  (`--pe-bg: #F7F9FB` and `--pe-surface-2: #FFFFFF`) is close to the WCAG
  AA threshold for normal text (4.5:1) — **verify with an actual contrast
  tool before changing anything** (a hand calculation during this plan's
  authoring landed around 4.8:1 against white, which would pass; don't
  trust that number blindly, re-derive it in Step 4 with a real tool or
  library, since it's borderline and easy to get wrong by hand).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Run tests | `TESTING=True python -m pytest -q` | all pass (template-only change) |
| Contrast check | see Step 4 — use a real contrast-ratio tool/library, not a guess | ratio ≥ 4.5:1 for normal-size text, or a documented decision to accept a lower ratio for large/bold text (≥3:1 threshold applies there) |

## Scope

**In scope**:
- `templates/dashboard.html` — add the missing `<h2>` to
  `secao-visao-geral`, add accessible names to the 3 `<canvas>` elements,
  add `aria-pressed` to the tipo-toggle buttons (both presidente and
  governador groups, and any other `pe-tipo-btn` group found via grep)

**Out of scope**:
- Full WCAG AA/AAA audit of the entire site (this plan targets the 3
  concrete gaps above, not an exhaustive accessibility rewrite).
- Changing `--pe-text-muted`'s color value — Step 4 only *verifies*
  contrast; only change the token if the verification confirms a real
  failure, and if so treat that as a separate, deliberate design decision
  (it affects visual identity site-wide) rather than a mechanical fix —
  STOP and report the measured ratio instead of unilaterally picking a new
  color.
- Full keyboard-navigation audit (tab order, focus rings) — not covered by
  this plan's identified gaps.

## Git workflow

- Branch: `advisor/028-acessibilidade-dashboard`
- Commit message style: conventional commits in Portuguese, e.g.
  `fix(a11y): heading da visão geral, nome acessível dos gráficos, aria-pressed nos toggles`
- Do NOT push or open a PR unless explicitly instructed.

## Steps

### Step 1: Add the missing `<h2>` to Visão Geral

At `templates/dashboard.html:47`, add a heading matching the visual/markup
style of the other sections (compare `:84`'s `<h2 class="pe-section__title">Presidente</h2>`):

```html
    <section id="secao-visao-geral" class="pe-section">
      <h2 class="pe-section__title">Visão Geral</h2>

      <!-- Aviso de defasagem (ativado por JS quando a última pesquisa passa do limiar) -->
```

Check the nav link text for this section (`grep -n "nav-visao-geral\|#secao-visao-geral" templates/dashboard.html` — likely in `templates/base.html` or the topbar) to make sure "Visão Geral" matches the label already used elsewhere, so the new heading doesn't introduce an inconsistent name for the same section.

**Verify**: `grep -n 'pe-section__title">Visão Geral' templates/dashboard.html` shows the new heading; reload the dashboard and confirm no visual regression (heading style matches other sections).

### Step 2: Accessible names for the 3 charts

For each `<canvas>`, add an `aria-label` describing what the chart shows,
and wrap it (or its container) with `role="img"` so assistive tech treats
it as a single described image rather than an empty interactive element:

```html
<div class="pe-chart-container"><canvas id="chart-presidente" role="img" aria-label="Gráfico de barras com a intenção de voto para presidente por candidato"></canvas></div>
...
<div class="pe-chart-container" style="height:380px;"><canvas id="chart-historico-multi" role="img" aria-label="Gráfico de linha com a evolução das pesquisas ao longo do tempo por candidato"></canvas></div>
...
<div class="pe-chart-container"><canvas id="chart-governador" role="img" aria-label="Gráfico de barras com a intenção de voto para governador do Rio de Janeiro por candidato"></canvas></div>
```

This is a static label (doesn't update per-candidate/per-value dynamically)
— that's an intentional, acceptable simplification for this plan: it tells
a screen-reader user *what kind of chart this is and what it shows in
general*, which is far better than nothing, without requiring the JS
rendering code to be touched. A fully dynamic, value-specific description
is a larger feature, out of scope here.

**Verify**: `grep -c 'role="img"' templates/dashboard.html` → at least 3.

### Step 3: `aria-pressed` on toggle buttons

Run `grep -n "pe-tipo-btn\"" templates/dashboard.html` and
`grep -n "pe-tipo-toggle" templates/dashboard.html` to enumerate every
toggle-button group in the file (presidente's `#pres-tipo-toggle` is
confirmed to exist; check whether governador has an equivalent — the UX
audit from the previous session's report noted governador's chart doesn't
currently have a tipo toggle, so there may be only one group, or the
governador section may have gained one since — verify against the live
file, don't assume).

For each toggle button found, add `aria-pressed="true"`/`"false"` matching
its initial active state in the static HTML:

```html
<button type="button" class="pe-tipo-btn pe-tipo-btn--active" data-tipo="estimulada" aria-pressed="true" onclick="setTipoPres('estimulada')">Estimulada</button>
<button type="button" class="pe-tipo-btn" data-tipo="espontanea" aria-pressed="false" onclick="setTipoPres('espontanea')">Espontânea</button>
```

Then update the JS that toggles `.pe-tipo-btn--active` (`templates/dashboard.html:291-292`
for the presidente group — locate any sibling toggle function similarly)
to also toggle the `aria-pressed` attribute in the same place:

```js
document.querySelectorAll('#pres-tipo-toggle .pe-tipo-btn').forEach(b => {
  const ativo = b.dataset.tipo === tipo;
  b.classList.toggle('pe-tipo-btn--active', ativo);
  b.setAttribute('aria-pressed', ativo ? 'true' : 'false');
});
```

**Verify**: `grep -n "aria-pressed" templates/dashboard.html` shows both
the static initial values and the JS toggle logic present.

### Step 4: Verify (don't assume) the `--pe-text-muted` contrast ratio

Compute the actual WCAG contrast ratio of `#5a7184` against `#FFFFFF`
(`--pe-surface-2`) and against `#F7F9FB` (`--pe-bg`) using a real
tool/library — e.g. `python -c "import colorsys; ..."` with the WCAG
relative-luminance formula, or any contrast-checker CLI/library available
in this environment. Do not eyeball it or reuse a number from this plan's
"Current state" section without re-deriving it yourself.

- If both ratios are **≥ 4.5:1**: no code change needed here — record the
  measured ratios in your final report and move on.
- If either ratio is **below 4.5:1**: STOP and report the measured
  ratio(s) rather than picking a replacement color yourself — this token
  is used site-wide and a color change is a design decision for the
  maintainer, not something to make unilaterally inside an accessibility
  bugfix plan.

**Verify**: your report states the exact measured ratio(s) for both
background pairings, with the method/tool used to compute them.

## Test plan

- This is a template/CSS-adjacent change with no new server-side logic;
  no new Python test is required beyond confirming the full suite still
  passes.
- Verification: `TESTING=True python -m pytest -q` → all pass, unaffected.
- Manual verification: reload the dashboard, confirm the new `<h2>` renders
  with consistent styling, and (if you have access to any accessibility
  inspection tool — browser devtools' Accessibility panel, `axe`, etc.)
  confirm the canvases now report an accessible name and the toggle
  buttons report a pressed state. If no such tool is available in this
  environment, code-level verification (the grep checks in each step) is
  an acceptable substitute — state clearly in your report whether a live
  accessibility-tree check was performed or only the static markup was
  verified.

## Done criteria

- [ ] `TESTING=True python -m pytest -q` exits 0
- [ ] `grep -n 'pe-section__title">Visão Geral' templates/dashboard.html` shows the new heading
- [ ] `grep -c 'role="img"' templates/dashboard.html` is at least 3
- [ ] `grep -n "aria-pressed" templates/dashboard.html` shows both static
      attributes and JS toggle logic
- [ ] Report includes the measured `--pe-text-muted` contrast ratio(s)
      against both `--pe-bg` and `--pe-surface-2`, with method used
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row for 028 updated

## STOP conditions

- Any of the cited line numbers/excerpts don't match the live file (drift)
  — re-grep and re-read before editing.
- The contrast check (Step 4) comes back below 4.5:1 for either background
  — stop and report the number rather than changing the color yourself.
- A second (or third) tipo-toggle group is found that doesn't match the
  `#pres-tipo-toggle` structure assumed here (different container id,
  different JS function) — adapt Step 3 to that group's actual structure
  rather than skipping it silently.

## Maintenance notes

- If the maintainer decides to darken `--pe-text-muted` based on this
  plan's contrast measurement, that change ripples through every use of
  the token site-wide (labels, dates, muted metadata across all pages,
  not just the dashboard) — treat it as its own follow-up plan with a
  broader review, not a one-line tweak bundled here.
- Any new chart added to this dashboard in the future should get the same
  `role="img"` + `aria-label` treatment from the start.
