# Plan 030: Estende Governador RJ com histórico/eventos, alertas e house-effects

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat f53d533..HEAD -- templates/dashboard.html app.py database.py`
> If any of these changed since this plan was written, compare the
> "Current state" excerpts below against the live code before proceeding;
> on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3 (direction/feature — not a bug, a product gap; sequence
  after the bug/security plans in this batch, but ahead of the pure
  tech-debt plan 029 if the maintainer wants user-visible value first)
- **Effort**: M (turned out smaller than initially estimated — see "Why
  this matters")
- **Risk**: LOW — this plan makes **zero backend changes**; every endpoint
  it uses already accepts `?cargo=governador_rj`
- **Depends on**: none
- **Category**: direction (feature)
- **Planned at**: commit `f53d533`, 2026-07-16

## Why this matters

Governador RJ has no historical-trend chart with event markers, no
variação/alerta feed, and no house-effects table — all four exist today
only for presidente, even though the RJ governor race is half of this
product's stated scope (`CLAUDE.md`: "Radar de pesquisas eleitorais
brasileiras (presidente + governador RJ)"). The good news, confirmed by
reading the live code: **every backend function/endpoint these four
features need already accepts a `cargo` parameter and already works
correctly for `governador_rj`** — `detectar_variacoes_bruscas(cargo)`,
`get_house_effects(cargo)`, `get_historico_multi(candidatos, cargo, tipo)`,
and `listar_eventos(cargo)` (via `/api/alertas`, `/api/house-effects`,
`/api/pesquisas/historico-multi`, `/api/eventos`, all confirmed reading
`app.py:643-695`) were all built cargo-aware from the start. This plan is
therefore a **frontend-only** addition: four new loader functions and
their HTML containers inside `secao-governador`, each modeled directly on
its existing presidente equivalent with `cargo=governador_rj` substituted
in the fetch URL.

## Current state

- The four existing presidente-only pieces to model each new addition on
  (re-confirm exact line numbers with `grep -n "async function
  carregar(Alertas|HouseEffects|Eventos|HistoricoMulti)"
  templates/dashboard.html` before editing, since prior plans in this
  batch may have shifted lines slightly):

  1. **Alertas** — `carregarAlertas()` around line 777, renders into
     `#alertas-container` inside `secao-visao-geral`, fetches `/api/alertas`
     (no explicit `cargo=` today — defaults to presidente server-side).
  2. **House effects** — `carregarHouseEffects()` around line 1203,
     renders into a container inside `secao-dados`
     (`grep -n "secao-dados" templates/dashboard.html` to confirm the
     section id), fetches `/api/house-effects?cargo=presidente` explicitly
     — already shows you the exact URL shape to copy for governador_rj.
  3. **Eventos + marcadores** — `carregarEventos()` (line ~463) fetches
     `/api/eventos?cargo=presidente` into `window.eventosTimeline`, and
     `eventosMarkerPlugin` (line ~476) is a Chart.js plugin drawing
     vertical dashed lines + labels on `chart-historico-multi` at each
     event's nearest plotted date. The plugin is registered via
     `plugins: [eventosMarkerPlugin]` in the `new Chart({...})` call
     inside `renderizarHistoricoMulti` (line ~530-568).
  4. **Histórico multi-candidato** — `carregarHistoricoMulti()` (line
     ~509) + `renderizarHistoricoMulti(series)` (line ~529), fetches
     `/api/pesquisas/historico-multi?cargo=presidente&candidatos=Lula,Flávio%20Bolsonaro&tipo=...`,
     renders into `#chart-historico-multi` inside `#historico-multi-card`.

- Backend confirmation (already correct, no changes needed — read to
  confirm, don't modify):
  - `app.py:643-651` (`/api/alertas`) — `cargo = request.args.get('cargo',
    'presidente')`, already parametrized.
  - `app.py:679-685` (`/api/eventos`) — `cargo = request.args.get('cargo')`
    (no default — `None` cargo means "no cargo filter" per
    `listar_eventos(cargo: str | None = None)`; passing
    `cargo=governador_rj` explicitly works today).
  - `app.py:688-695` (`/api/house-effects`) — `cargo =
    request.args.get('cargo', 'presidente')`, already parametrized.
  - `app.py:653-668` (`/api/pesquisas/historico-multi`) — `cargo =
    request.args.get('cargo', 'presidente')`, `candidatos` param accepted
    as comma-separated names, already parametrized.
  - `database.get_top_candidatos(cargo, n=3)` — used as the default
    candidate list when `candidatos` isn't passed; already cargo-aware, so
    you likely don't even need to hardcode governador RJ candidate names
    the way `carregarHistoricoMulti` hardcodes `Lula,Flávio Bolsonaro` for
    presidente (that hardcoding exists to guarantee the *initial* two
    candidates shown match the two front-runners without waiting on a
    round-trip — replicate the same convenience if you know the current
    front-runners, or omit `candidatos=` entirely and let
    `get_top_candidatos` pick automatically; either is fine, note your
    choice in the report).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Run tests | `TESTING=True python -m pytest -q` | all pass |
| Manual smoke check per endpoint | `TESTING=True python -c "import app; c=app.app.test_client(); print(c.get('/api/house-effects?cargo=governador_rj').status_code)"` (repeat for alertas/eventos/historico-multi) | 200 for all four |

## Scope

**In scope**:
- `templates/dashboard.html` — four new loader functions
  (`carregarAlertasRJ`, `carregarHouseEffectsRJ`, `carregarEventosRJ`,
  `carregarHistoricoMultiRJ` or equivalent naming — match whatever
  convention `carregarKpisAnaliseRJ`/`carregarRejeicao(cargo,
  containerId)` from this same batch's plans 018 established), their HTML
  containers inside `secao-governador`, a second Chart.js instance for the
  RJ historical chart (`chart-historico-multi-rj` or similar — Chart.js
  requires a distinct canvas per chart instance, you cannot reuse
  `chart-historico-multi`), and registration of all four in `inicializar()`

**Out of scope**:
- Any backend change — `app.py`/`database.py` are read-only references in
  this plan, not edit targets. If you find a case where the RJ cargo
  genuinely doesn't work end-to-end (e.g. `get_historico_multi` returns
  empty because there's insufficient RJ polling history, or `listar_eventos`
  has no `governador_rj`/`geral` events seeded yet), that's a **data
  availability gap, not a code bug** — implement the feature correctly and
  let it render its existing empty-state message; don't fabricate data or
  change the query logic to compensate.
- Redesigning any of the four presidente equivalents.
- A shared toggle/selector UI unifying presidente and governador views —
  this plan adds parallel, separate sections, matching how presidente vs.
  governador are already two fully separate sections in this dashboard,
  not a unified switchable view.

## Git workflow

- Branch: `advisor/030-estender-analises-governador-rj`
- Commit style: conventional commits in Portuguese, e.g.
  `feat(governador-rj): adiciona histórico, eventos, alertas e house-effects`
  — consider one commit per feature (4 commits) for reviewability, given
  the size of this plan.
- Do NOT push or open a PR unless explicitly instructed.

## Steps

### Step 1: Alertas para governador RJ

Read `carregarAlertas()` in full. Add a parallel function (or parametrize
the existing one, following the `carregarRejeicao(cargo, containerId)`
pattern already established by plan 018 in this same file — check that
function's current shape as your template for how this codebase now
prefers to handle "same loader, different cargo") that fetches
`/api/alertas?cargo=governador_rj` and renders into a new container inside
`secao-governador`. Add the container HTML near the existing governador
charts, with a heading matching the visual style of nearby cards (compare
`carregarRejeicao`'s RJ card from plan 018, `<h3 class="pe-section__title"
style="font-size:13px; margin-top:24px;">...</h3>` + `<div class="pe-card"
id="...">`).

**Verify**: reload the dashboard, confirm the RJ section shows an alertas
card (empty-state message if no RJ alert data exists yet, matching how the
presidente version handles zero alerts).

### Step 2: House effects para governador RJ

Same pattern: read `carregarHouseEffects()`, add a parallel RJ version
fetching `/api/house-effects?cargo=governador_rj`, new container inside
`secao-governador`.

**Verify**: same as Step 1, for the house-effects card.

### Step 3: Eventos + marcadores para governador RJ

This is the most involved of the four, since it interacts with a chart
plugin. Two parts:

3a. Add a `carregarEventosRJ()` fetching `/api/eventos?cargo=governador_rj`
into a **separate** global, e.g. `window.eventosTimelineRJ` (do not reuse
`window.eventosTimeline` — that's read by `eventosMarkerPlugin` for the
presidente chart specifically; a shared variable would make the RJ
chart draw presidente's event markers, reintroducing exactly the kind of
cross-cargo data leak this whole audit round started by finding and
fixing).

3b. The `eventosMarkerPlugin` object (line ~476) reads `window.eventosTimeline`
directly inside its `afterDatasetsDraw` — this makes it presidente-specific
by construction. Either (a) parametrize the plugin to accept which
timeline global to read (e.g. wrap it in a factory function
`criarEventosMarkerPlugin(timelineGlobalName)` returning a plugin object),
or (b) create a second, near-duplicate plugin object
`eventosMarkerPluginRJ` reading `window.eventosTimelineRJ`. Prefer (a) if
it's a clean, small change; fall back to (b) if factoring it out proves
fiddly — either is acceptable, note which you chose and why.

**Verify**: reload the dashboard, confirm RJ's historical chart (added in
Step 4, needed before this step can be fully verified visually — do Step 4
first if you prefer, order between 3 and 4 doesn't matter functionally)
shows its own event markers, independent of and not duplicating
presidente's.

### Step 4: Histórico multi-candidato para governador RJ

Add a new `<canvas id="chart-historico-multi-rj">` inside `secao-governador`
(Chart.js instances are 1:1 with canvas elements — you cannot render two
different chart configs into the same canvas id). Add
`carregarHistoricoMultiRJ()` + `renderizarHistoricoMultiRJ(series)`
modeled on `carregarHistoricoMulti()`/`renderizarHistoricoMulti()`,
fetching `/api/pesquisas/historico-multi?cargo=governador_rj&tipo=...`
(decide whether to hardcode initial `candidatos=` for RJ's current
front-runners the way presidente does, or omit it and rely on
`get_top_candidatos('governador_rj', n=3)` — see the note in "Current
state"). Use the plugin variant from Step 3b for this chart's `plugins:
[...]` array.

**Verify**: reload the dashboard, confirm the RJ historical chart renders
with its own candidate toggle checkboxes (mirroring
`#candidatos-toggle`'s pattern — needs its own container id, e.g.
`#candidatos-toggle-rj`, don't reuse the presidente one).

### Step 5: Register everything in `inicializar()`

Add all four new loader calls to the `Promise.all([...])` array in
`inicializar()`, alongside the existing loaders.

**Verify**: `grep -n "carregarAlertasRJ\|carregarHouseEffectsRJ\|carregarEventosRJ\|carregarHistoricoMultiRJ" templates/dashboard.html`
shows each function both defined and called from `inicializar()`.

## Test plan

- This is a frontend-only feature addition against already-correct,
  already-tested backend endpoints — no new Python test is strictly
  required for backend behavior (it's already covered).
- If you want extra confidence, a lightweight test rendering `/dashboard`
  via the Flask test client and asserting the new container ids/function
  names appear in the HTML (same technique used to verify plan 018's RJ
  rejeição card) is a reasonable, in-scope addition — not mandatory.
- Verification: `TESTING=True python -m pytest -q` → all pass, unaffected.
- Manual verification (each step's own Verify) is the primary test plan
  here, since the value being added is entirely visual/interactive.

## Done criteria

- [ ] `TESTING=True python -m pytest -q` exits 0
- [ ] Four new containers + loader functions exist, confirmed via grep
      (see Step 5's verify command)
- [ ] Manual check: RJ section shows alertas, house-effects, eventos
      markers, and historical multi-candidato chart, each independent of
      the presidente equivalents (no shared global state between the two
      cargos' event timelines)
- [ ] No backend file (`app.py`, `database.py`) was modified
      (`git diff --stat` shows only `templates/dashboard.html`, or
      possibly `static/css/base.css` if new layout needed a shared class)
- [ ] `plans/README.md` status row for 030 updated

## STOP conditions

- Any of the four presidente-equivalent functions cited above don't match
  their described shape (file drifted) — re-read the live function before
  modeling the RJ version on it.
- `get_historico_multi('governador_rj', ...)` or any of the other three
  backend calls returns an unexpected shape or raises when called with
  `governador_rj` (i.e. the "already cargo-aware" premise turns out false
  for some function) — stop and report exactly which function/endpoint
  failed and how, rather than patching the backend yourself (that would be
  a different, separate bug-fix plan, not this feature-addition plan).
- You find `window.eventosTimeline` is read from more than just
  `eventosMarkerPlugin` (i.e. it has other consumers this plan's "Current
  state" didn't account for) — re-derive the safe way to add an RJ-scoped
  parallel variable without breaking those other consumers.

## Maintenance notes

- Any future third cargo (none exists today, but the pattern established
  here — parallel loader function + parallel timeline global + parallel
  canvas id — is exactly what to replicate again) should follow this same
  shape rather than trying to retrofit a "generic cargo" abstraction after
  the fact; two cargos' worth of duplication is normal and fine, a third
  might be the right time to actually factor out the shared pattern into
  a proper parametrized helper (candidate for a future refactor, not
  needed now).
- If `eventosMarkerPlugin` was refactored into a factory function (option
  3a in Step 3), document that pattern briefly in a code comment so a
  future editor adding a third cargo's chart knows to call the factory
  again rather than copy-pasting the plugin object.
