# Plan 022: Padronizar erro/loading no dashboard e acabar com o fallback mockado silencioso

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 8d3827f..HEAD -- templates/dashboard.html`
> If the file changed since this plan was written, re-run the `grep`
> commands in "Current state" to confirm line numbers before proceeding; on
> a mismatch, treat it as a STOP condition.
>
> **Recommended order**: run this plan after `plans/021-dashboard-responsivo.md`
> if both are being executed — they touch the same file
> (`templates/dashboard.html`) and doing 021 first avoids a merge conflict
> on unrelated lines. Not a hard dependency; either order works if executed
> separately with a rebase in between.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none (recommended after 021 — see note above)
- **Category**: bug (UX)
- **Planned at**: commit `8d3827f`, 2026-07-16

## Why this matters

`carregarPresidente()` and `carregarGovernador()` silently fall back to
hardcoded mock data (`fallbackPres`/`fallbackGov`, dated June 2026) when
their fetch fails, with **no visual indicator** that the numbers on screen
are fake. A user has no way to know they're looking at stale example data
instead of a real poll — this is actively misleading for a product whose
entire value proposition is "these are the real, current numbers." Several
other loading functions (`carregarVisaoGeral`, `carregarHistoricoMulti`,
`carregarRegional`, `inicializarComparativo`, `carregarSimulacao`) have no
`try/catch` at all, so a network hiccup on any of them can leave a whole
section blank with zero feedback, while sibling functions
(`carregarRejeicao`, `carregarHouseEffects`, `carregarCenarioVitoriaRJ`)
already do this correctly — the fix is to make every loader follow the
pattern that's already proven to work in this same file.

## Current state

- The mock fallback data — `templates/dashboard.html:280-294`:

```js
const fallbackPres = {
  candidatos: ["Lula", "Flávio Bolsonaro", "Ciro Gomes", "Simone Tebet"],
  percentuais: [44.2, 37.5, 4.8, 3.5],
  data_coleta: "2026-06-08",
  instituto: "Atlas (Fallback)",
  margem_erro: 2.0
};

const fallbackGov = {
  candidatos: ["Eduardo Paes", "Cláudio Castro", "Marcelo Freixo", "Rodrigo Neves"],
  percentuais: [37.2, 23.8, 12.0, 10.2],
  data_coleta: "2026-06-05",
  instituto: "Quaest (Fallback)",
  margem_erro: 2.5
};
```

- Where it's consumed silently — `templates/dashboard.html:324-332`
  (`carregarPresidente`) and `:379-387` (`carregarGovernador`, same shape):

```js
async function carregarPresidente() {
  let data = fallbackPres;
  try {
    const res = await fetch('/api/pesquisas/presidente?tipo=' + tipoPres);
    if (res.ok) {
      const json = await res.json();
      if (json.candidatos && json.candidatos.length > 0) data = json;
    }
  } catch (err) { console.warn('Erro presidente:', err); }

  document.getElementById('pres-instituto').textContent = data.instituto;
  ...
```

  Note `data.instituto` already gets rendered as `"Atlas (Fallback)"` /
  `"Quaest (Fallback)"` into `#pres-instituto` — the word "(Fallback)" is
  technically present in the DOM today, but as plain instituto-name text
  with no visual distinction (no color, no banner, no icon) — easy to miss
  entirely. This plan makes it unmissable instead of merely technically-present.

- Functions with NO try/catch around their fetch (confirmed by direct
  read) — `templates/dashboard.html:623-624` (`carregarVisaoGeral`):

```js
async function carregarVisaoGeral() {
  const res = await fetch('/api/visao-geral');
  const data = await res.json();
  ...
```

  Same pattern (no try/catch on the primary fetch) applies to
  `carregarHistoricoMulti` (`:483`), `carregarRegional` (`:978`),
  `inicializarComparativo` (`:722`), and `carregarSimulacao` (`:792`) —
  confirm each by reading the function before editing, since exact line
  numbers may have shifted slightly if plan 021 landed first.

- The correct existing pattern to copy — `carregarRejeicao`
  (`:1101` onward) already wraps its fetch in `try/catch` and shows a
  visible error message in its container on failure; use that function's
  catch-block shape as the template for the others.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Run tests | `TESTING=True python -m pytest -q` | all pass |
| Manual check (fallback banner) | temporarily point `fetch('/api/pesquisas/presidente...')` at a nonexistent path, reload, confirm a visible "dados de exemplo" indicator appears, then revert | banner visible, distinct styling |
| Manual check (error states) | temporarily break one of the newly-wrapped fetches (e.g. typo the URL), reload, confirm a visible error message appears instead of a blank section | error message visible in that section only |

## Scope

**In scope**:
- `templates/dashboard.html` — `carregarPresidente`, `carregarGovernador`
  (add visible fallback indicator), and `carregarVisaoGeral`,
  `carregarHistoricoMulti`, `carregarRegional`, `inicializarComparativo`,
  `carregarSimulacao` (add try/catch + visible error state, matching
  `carregarRejeicao`'s existing pattern)

**Out of scope**:
- Removing the fallback data entirely (a reasonable alternative design,
  but a bigger product decision than this plan — this plan makes the
  fallback visually honest, it doesn't remove it).
- Adding loading skeletons/spinners to containers that currently show
  nothing while waiting (a separate, lower-priority polish item noted in
  the UX audit — not bundled here to keep this plan's diff focused on
  error-path correctness).
- Any change to `carregarRejeicao`, `carregarHouseEffects`,
  `carregarCenarioVitoriaRJ` themselves — they're already correct, used
  only as the reference pattern.

## Git workflow

- Branch: `advisor/022-padronizar-erro-loading`
- Commit message style: conventional commits in Portuguese, e.g.
  `fix(dashboard): sinaliza dado de fallback e padroniza tratamento de erro`
- Do NOT push or open a PR unless explicitly instructed.

## Steps

### Step 1: Read the reference pattern

Read `carregarRejeicao` in full (`templates/dashboard.html`, starting
around line 1101) to see exactly how it structures its `try/catch` and
what it renders into its container on failure. Every function touched in
this plan should follow that same shape (a visible, styled message
replacing the section's content on error — not a silent `console.warn`
alone).

### Step 2: Add a visible fallback indicator to `carregarPresidente`/`carregarGovernador`

In both functions, after the existing `try/catch` (`:324-332` and
`:379-387`), track whether the fallback was used:

```js
async function carregarPresidente() {
  let data = fallbackPres;
  let usouFallback = true;
  try {
    const res = await fetch('/api/pesquisas/presidente?tipo=' + tipoPres);
    if (res.ok) {
      const json = await res.json();
      if (json.candidatos && json.candidatos.length > 0) { data = json; usouFallback = false; }
    }
  } catch (err) { console.warn('Erro presidente:', err); }

  // ... existing rendering ...

  const fallbackWarn = document.getElementById('pres-fallback-aviso'); // add this element near #pres-fonte in the HTML
  if (fallbackWarn) fallbackWarn.style.display = usouFallback ? 'block' : 'none';
```

Add a corresponding hidden-by-default element in the HTML near
`#pres-fonte` (find that `id` in the static markup, not the JS template
string, and add a sibling element), styled distinctly (e.g. warning color,
matching the existing `#aviso-defasagem` banner's visual language at
`templates/dashboard.html:50-56` for consistency — reuse that same
warning color token rather than inventing a new one):

```html
<div id="pres-fallback-aviso" style="display:none; ...">
  ⚠️ Dados de exemplo — falha ao carregar a pesquisa real. Recarregue a página.
</div>
```

Repeat identically for `carregarGovernador` with a `#gov-fallback-aviso`
element and Portuguese copy adjusted for "governador".

**Verify**: manually break the presidente fetch (temporarily point it at a
404 path), reload, confirm the warning banner appears; revert the temporary
break, reload, confirm the banner stays hidden.

### Step 3: Add try/catch + visible error state to the 5 unguarded loaders

For each of `carregarVisaoGeral`, `carregarHistoricoMulti`,
`carregarRegional`, `inicializarComparativo`, `carregarSimulacao`: wrap the
fetch + rendering body in `try { ... } catch (err) { ... }`, and in the
`catch` block, set the function's target container's `innerHTML` to a
visible error message, following `carregarRejeicao`'s exact wording/style
pattern (read its catch block from Step 1 and reuse the same phrasing
convention, adapted per section — e.g. "Erro ao carregar house effects."
becomes "Erro ao carregar visão geral.", etc.).

Do this one function at a time, verifying each independently before moving
to the next (5 sub-steps, same shape):

3a. `carregarVisaoGeral` (`:623`) → wrap in try/catch, error state targets
`#kpi-grid` (or the first container it populates).
3b. `carregarHistoricoMulti` (`:483`) → error state targets the chart's
container/card.
3c. `carregarRegional` (`:978`) → error state targets the regional table
container.
3d. `inicializarComparativo` (`:722`) → error state targets the comparativo
container.
3e. `carregarSimulacao` (`:792`) → error state targets the simulação
container.

**Verify** (per sub-step): temporarily break that one function's fetch URL,
reload, confirm a visible error message appears in that section only (not a
blank area, not a JS console-only warning); revert and confirm normal
rendering resumes.

## Test plan

- This is a frontend-only change; no new Python test is strictly required.
  If `tests/test_templates_refactor.py` or `tests/test_dashboard.py` assert
  on the exact structure of the sections touched here (e.g. checking that
  certain `id`s exist in the rendered HTML), confirm the new
  `#pres-fallback-aviso`/`#gov-fallback-aviso` elements don't break those
  assertions — they're additive, so existing assertions should still pass
  unless a test does an exact full-HTML-string comparison (unlikely, but
  check).
- Verification: `TESTING=True python -m pytest -q` → all pass, unaffected
  by an HTML-only change.
- Manual verification (per Steps 2 and 3) is the real test plan here, since
  the affected behavior only manifests client-side under network failure
  conditions that server-side pytest doesn't simulate.

## Done criteria

- [ ] `TESTING=True python -m pytest -q` exits 0
- [ ] `grep -n "usouFallback" templates/dashboard.html` shows it used in
      both `carregarPresidente` and `carregarGovernador`
- [ ] `grep -c "catch (err)" templates/dashboard.html` increased by at
      least 5 compared to `git show 8d3827f:templates/dashboard.html | grep -c "catch (err)"`
- [ ] Manual check: breaking each of the 7 functions' fetch individually
      and reloading shows a visible, section-scoped error/fallback message
      each time (not a blank area, not console-only)
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row for 022 updated

## STOP conditions

- Any of the 7 functions named above don't match the excerpts/line ranges
  given (file has drifted, possibly from plan 021 landing first) — re-read
  the current function body before editing.
- `carregarRejeicao`'s error-handling pattern (the reference to copy) has
  itself changed shape since this plan was written — re-read it fresh
  before using it as a template.
- Adding the try/catch to `carregarVisaoGeral` reveals that other code
  depends on it throwing/not-catching (e.g. `Promise.all` in
  `inicializar()` expecting a rejection to short-circuit something) —
  re-read `inicializar()` (`templates/dashboard.html`, search
  `async function inicializar`) before assuming it's safe to swallow the
  error silently inside each loader.

## Maintenance notes

- Any new `carregar*` function added to this dashboard in the future
  should follow this same try/catch + visible-error-state pattern from the
  start — worth a one-line mention in `CLAUDE.md`'s conventions section if
  the maintainer wants to prevent regression.
- This plan does not add loading skeletons for the initial "blank until
  populated" state noted in the UX audit — that's a separate, lower-
  priority polish item, deliberately deferred.
