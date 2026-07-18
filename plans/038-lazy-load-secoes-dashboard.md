# Plan 038: Carrega governador RJ e Dados sob demanda (lazy) no dashboard público

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 0992d23..HEAD -- templates/dashboard.html`
> If `templates/dashboard.html` changed since this plan was written,
> compare the "Current state" excerpts below against the live code before
> proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/031-cache-endpoints-presidente-governador.md (recommended order, not a hard dependency — do 031 first so the eager-loaded requests in this plan are already cached)
- **Category**: perf
- **Planned at**: commit `0992d23`, 2026-07-17

## Why this matters

`templates/dashboard.html`'s `inicializar()` function fires **20 API
requests in parallel** on every single page load, unconditionally, before
the visitor has scrolled anywhere. This roughly doubled when plan 030 added
the full Governador RJ extension (8 of the 20 calls are the `...RJ`/second-
argument variants added by that plan). `PRODUCT.md` — the product brief for
this repo — names three personas sharing this dashboard and states as
**design principle 3**: "Escaneável antes de exaustivo. Um eleitor casual
deve entender o cenário em poucos segundos rolando a página; o analista que
quer profundidade navega para uma seção dedicada, não precisa que a home
carregue tudo." The current behavior does the opposite of that stated
principle: it loads Presidente, Governador RJ, and the Dados section's
comparativo/institutos/regional data all at once, for every visitor,
including the casual-voter persona `PRODUCT.md` explicitly prioritizes for
this page and who is, per the same doc, "majoritariamente mobile" on "sessões
curtas." Deferring the Governador RJ and Dados sections' data fetches until
the visitor actually scrolls to them (or clicks the corresponding nav link)
cuts the initial request count roughly in half, speeds up first paint on
slow mobile connections, and brings the code back in line with the
product's own stated principle — without changing what any section
ultimately shows once viewed.

## Current state

- `templates/dashboard.html:1400-1425` — the full `inicializar()` function as it exists today:

```javascript
    // ─── Inicialização ────────────────────────────────────────
    async function inicializar() {
      // Eventos antes dos gráficos para os marcadores já aparecerem no 1º render.
      await Promise.all([carregarEventos(), carregarEventosRJ()]);
      await Promise.all([
        carregarVisaoGeral(),
        carregarKpisAvancados(),
        carregarKpisAnaliseRJ(),
        carregarPresidente(),
        carregarGovernador(),
        carregarInstitutos(),
        carregarMediaAgregada(),
        inicializarComparativo(),
        carregarHistoricoMulti(),
        carregarHistoricoMultiRJ(),
        carregarAlertas(),
        carregarAlertas('governador_rj', 'alertas-rj-container'),
        carregarSimulacao(),
        carregarCenarioVitoriaRJ(),
        carregarRegional(),
        carregarRejeicao('presidente', 'rejeicao-container'),
        carregarRejeicao('governador_rj', 'rejeicao-rj-container'),
        carregarHouseEffects(),
        carregarHouseEffects('governador_rj', 'house-effects-rj-container'),
      ]);
    }

    document.addEventListener('DOMContentLoaded', inicializar);
```

- `templates/dashboard.html:1429-1461` — the existing scroll-spy
  `IntersectionObserver` (already present, watches nav highlighting, not
  data loading) — this plan adds a **second**, separate `IntersectionObserver`
  for lazy data loading, it does not repurpose this one:

```javascript
  <script>
    // Realça o item de nav correspondente à seção visível (scroll-spy).
    const sections = [
      { id: 'secao-visao-geral', nav: 'nav-visao-geral' },
      { id: 'secao-presidente',  nav: 'nav-presidente' },
      { id: 'secao-governador',  nav: 'nav-governador' },
      { id: 'secao-dados',       nav: 'nav-dados' },
    ];
    ...
    const observer = new IntersectionObserver((entries) => {
      ...
    }, { threshold: 0.3 });

    sections.forEach(s => { ... });
```

- The four section anchors this plan uses as lazy-load boundaries
  (`templates/dashboard.html:46,80,183,257`):
  - `#secao-visao-geral` — stays eager (first paint, casual-voter's whole
    need per `PRODUCT.md`).
  - `#secao-presidente` — stays eager (this is the default/primary race per
    `PRODUCT.md`'s framing; presidential race data should be visible
    immediately on scroll without a loading flash for the majority
    use case).
  - `#secao-governador` — becomes lazy.
  - `#secao-dados` — becomes lazy.

- The split of loaders by section (grouping based on which section's DOM
  elements each `carregarX` function populates — verify each one's target
  container ID with `grep -n "getElementById" templates/dashboard.html`
  before moving it, since this plan's grouping is based on function *name*
  patterns and must be double-checked against actual DOM targets):
  - **Eager** (unchanged, fire on `DOMContentLoaded` as today): `carregarEventos()`, `carregarVisaoGeral()`, `carregarKpisAvancados()`, `carregarPresidente()`, `carregarMediaAgregada()`, `carregarHistoricoMulti()`, `carregarAlertas()` (presidente variant), `carregarSimulacao()`, `carregarRejeicao('presidente', 'rejeicao-container')`, `carregarHouseEffects()` (presidente variant).
  - **Lazy — governador RJ section** (fire when `#secao-governador` intersects): `carregarEventosRJ()`, `carregarKpisAnaliseRJ()`, `carregarGovernador()`, `carregarHistoricoMultiRJ()`, `carregarAlertas('governador_rj', 'alertas-rj-container')`, `carregarCenarioVitoriaRJ()`, `carregarRejeicao('governador_rj', 'rejeicao-rj-container')`, `carregarHouseEffects('governador_rj', 'house-effects-rj-container')`.
  - **Lazy — dados section** (fire when `#secao-dados` intersects): `carregarInstitutos()`, `inicializarComparativo()`, `carregarRegional()`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Backend tests (unaffected) | `python -m pytest -q` | all pass — this plan is frontend-only, but confirm nothing broke |
| Manual browser verification | see "Suggested executor toolkit" below | dashboard loads, sections populate on scroll |

## Suggested executor toolkit

- This is a frontend-only, JavaScript behavior change with no automated
  test coverage in this repo's Python test suite (there's no JS test
  framework here — confirmed by `grep -rn "jest\|playwright\|vitest"
  package.json 2>/dev/null` returning nothing / no `package.json` at all).
  Use the `webapp-testing` skill (Playwright-based browser driving) if
  available in your environment to manually verify: (1) the dashboard loads
  and the Visão Geral + Presidente sections show data immediately without
  scrolling; (2) scrolling to the Governador RJ section triggers its data
  to load (visible network requests, then populated charts); (3) scrolling
  to the Dados section does the same; (4) the existing scroll-spy nav
  highlighting still works exactly as before (unrelated to this change, but
  a regression risk since it shares the same section IDs).
- If `webapp-testing` isn't available, at minimum run
  `python app.py` locally, open the dashboard in any browser, open devtools
  Network tab, and manually confirm the request-count drop and the
  scroll-triggered loading before considering this plan done.

## Scope

**In scope** (the only file you should modify):
- `templates/dashboard.html` — restructure `inicializar()` into eager + two lazy-loaded groups, add one new `IntersectionObserver` for triggering the lazy loads.

**Out of scope**:
- `app.py` / `db/*` — no backend changes; every `carregarX()` function keeps calling the exact same API endpoints it does today, just at a different time.
- The existing scroll-spy `IntersectionObserver` (`templates/dashboard.html:1429+`) — leave it exactly as is; add a second, independent observer rather than merging logic into it (mixing "highlight nav" concerns with "trigger data load" concerns in one observer callback makes future changes to either harder to reason about).
- Any loading-state/skeleton UI redesign — if a section's container doesn't already show *some* loading indicator while its lazy fetch is in flight, that's a pre-existing gap (or already handled per plan 022's "padronizar erro/loading" work) — do not add new loading UI as part of this plan; only change *when* the fetch fires, not what happens visually while it's pending. If you discover during testing that scrolling to a lazy section shows a jarring empty flash with zero loading indicator, note it and continue — do not scope-creep into fixing it here.
- Changing which section loads eagerly vs. lazily beyond the grouping specified in Current State — do not, for example, decide Governador RJ should also be eager because "it might be equally important"; the product principle this plan implements explicitly favors deferring secondary sections, and PRODUCT.md's principle 1 already establishes Presidente/Governador RJ as separate, not equal-priority-by-default, sections on this page.

## Git workflow

- Branch: `advisor/038-lazy-load-secoes-dashboard`
- Commit message style: `perf(dashboard): carrega governador RJ e dados sob demanda ao rolar`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Split `inicializar()` into an eager group and two lazy trigger functions

Replace the single `inicializar()` function with:

```javascript
    // ─── Inicialização ────────────────────────────────────────
    async function inicializar() {
      // Eager: Visão Geral + Presidente, para o eleitor casual ver algo
      // completo sem rolar (PRODUCT.md, princípio 3 — escaneável antes de
      // exaustivo).
      await Promise.all([carregarEventos()]);
      await Promise.all([
        carregarVisaoGeral(),
        carregarKpisAvancados(),
        carregarPresidente(),
        carregarMediaAgregada(),
        carregarHistoricoMulti(),
        carregarAlertas(),
        carregarSimulacao(),
        carregarRejeicao('presidente', 'rejeicao-container'),
        carregarHouseEffects(),
      ]);
    }

    let _governadorCarregado = false;
    async function carregarSecaoGovernadorRJ() {
      if (_governadorCarregado) return;
      _governadorCarregado = true;
      await Promise.all([carregarEventosRJ()]);
      await Promise.all([
        carregarKpisAnaliseRJ(),
        carregarGovernador(),
        carregarHistoricoMultiRJ(),
        carregarAlertas('governador_rj', 'alertas-rj-container'),
        carregarCenarioVitoriaRJ(),
        carregarRejeicao('governador_rj', 'rejeicao-rj-container'),
        carregarHouseEffects('governador_rj', 'house-effects-rj-container'),
      ]);
    }

    let _dadosCarregados = false;
    async function carregarSecaoDados() {
      if (_dadosCarregados) return;
      _dadosCarregados = true;
      await Promise.all([
        carregarInstitutos(),
        inicializarComparativo(),
        carregarRegional(),
      ]);
    }

    document.addEventListener('DOMContentLoaded', inicializar);
```

The `_governadorCarregado`/`_dadosCarregados` boolean guards prevent
re-fetching every time the visitor scrolls back into view (an
`IntersectionObserver` fires its callback on every intersection crossing,
not just the first).

**Verify**: `grep -n "async function inicializar\|async function carregarSecaoGovernadorRJ\|async function carregarSecaoDados" templates/dashboard.html` → 3 matches.

### Step 2: Add a second `IntersectionObserver` that triggers the lazy loads

Immediately after the existing scroll-spy observer block
(`templates/dashboard.html:1429-1461` in Current State), add a new,
separate observer:

```javascript
    // Observer separado (não o de scroll-spy acima) para disparar o
    // carregamento sob demanda das seções Governador RJ e Dados.
    const lazyLoadTriggers = {
      'secao-governador': carregarSecaoGovernadorRJ,
      'secao-dados': carregarSecaoDados,
    };
    const lazyLoadObserver = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const trigger = lazyLoadTriggers[entry.target.id];
          if (trigger) trigger();
        }
      });
    }, { rootMargin: '200px 0px', threshold: 0 });

    Object.keys(lazyLoadTriggers).forEach(id => {
      const el = document.getElementById(id);
      if (el) lazyLoadObserver.observe(el);
    });
```

The `rootMargin: '200px 0px'` starts the fetch slightly before the section
is actually on screen, so data is likely ready by the time the visitor
finishes scrolling to it (avoids a visible loading flash for a fast
scroller).

**Verify**: `grep -n "lazyLoadObserver\|lazyLoadTriggers" templates/dashboard.html` → present.

### Step 3: Confirm the observer registration doesn't clash with the existing scroll-spy observer's element lookups

Both observers call `document.getElementById('secao-governador')` and
`document.getElementById('secao-dados')` independently — this is fine
(each observer keeps its own independent watch list), but confirm the
element IDs match exactly what's already used by the scroll-spy `sections`
array (`templates/dashboard.html:1432-1437`) to avoid a typo causing silent
non-triggering.

**Verify**: `grep -n "id: 'secao-governador'\|id: 'secao-dados'" templates/dashboard.html` and `grep -n "'secao-governador':\|'secao-dados':" templates/dashboard.html` → IDs match exactly (`secao-governador`, `secao-dados`, no `-rj` suffix or other variation).

### Step 4: Manual browser verification

Follow the "Suggested executor toolkit" section above — start the app
locally (`python app.py`), open `/dashboard`, and confirm: (1) Visão Geral
and Presidente sections populate immediately; (2) Governador RJ populates
only after scrolling near it (watch the Network tab — request count on
initial load should be visibly lower than 20); (3) Dados section populates
only after scrolling near it; (4) scrolling back up and down again does not
re-fire the same requests (the boolean guards from Step 1 prevent this);
(5) the existing scroll-spy nav highlighting still works.

**Verify**: manual confirmation of all 5 points above; if using
`webapp-testing`, capture a screenshot or network log as evidence.

### Step 5: Run the backend test suite (sanity check, unrelated code path)

**Verify**: `python -m pytest -q` → all pass, unchanged from baseline (this plan touches no Python).

## Test plan

- No Python tests apply (frontend-only change, no JS test framework in
  this repo). Verification is manual browser testing per Step 4, ideally
  via the `webapp-testing` skill if available.
- Do not add a JS test framework (Jest/Playwright test runner, etc.) as
  part of this plan just to test this one change — that's a much larger
  DX investment out of scope here; if the operator wants that, it's a
  separate plan.
- Verification: `python -m pytest -q` → all pass (proves nothing broke on
  the backend), plus the manual checklist in Step 4.

## Done criteria

Machine-checkable + manual. ALL must hold:

- [ ] `inicializar()` in `templates/dashboard.html` no longer calls any of the 8 governador-RJ or 3 dados-section loaders listed in "Current state" directly
- [ ] `carregarSecaoGovernadorRJ()` and `carregarSecaoDados()` functions exist, each with a boolean re-fetch guard
- [ ] A new `IntersectionObserver` (distinct from the existing scroll-spy one) triggers these two functions when `#secao-governador`/`#secao-dados` intersect the viewport
- [ ] Manual verification (Step 4) confirms: eager sections populate immediately, lazy sections populate only on scroll, no duplicate fetches on repeated scroll, scroll-spy nav still works
- [ ] `python -m pytest -q` exits 0, unchanged from baseline
- [ ] No files outside `templates/dashboard.html` are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `inicializar()`'s code doesn't match the "Current state" excerpt (drifted since this plan was written) — re-derive the eager/lazy grouping from whatever the current loader list is, using the same grouping logic (which section's DOM each loader populates), rather than blindly pasting this plan's code over a changed function.
- Any `carregarX()` function turns out to populate DOM elements in **more than one** section (e.g. a shared summary card that pulls from both Presidente and Governador RJ data) — that would break this plan's clean eager/lazy split; if you find one, stop and report which function and which sections it touches, rather than guessing which group it belongs in.
- The manual browser verification in Step 4 shows the lazy sections never trigger (observer not firing) after one reasonable debugging attempt (check element IDs match, check the observer's `root`/`rootMargin` aren't misconfigured for the page's scroll container) — report what you tried rather than shipping a broken lazy-load.
- `webapp-testing` (or any other browser tool) isn't available and you have no way to visually confirm the behavior — report this limitation explicitly rather than marking the plan done on code-reading confidence alone; this is a case where "looks right" is not sufficient given the change affects real user-facing load behavior.

## Maintenance notes

- If a future plan adds a 5th top-level section to the dashboard, follow
  this same pattern: default to lazy unless there's a specific product
  reason (per `PRODUCT.md`) for it to be eager.
- If `PRODUCT.md`'s persona priorities change (e.g. Governador RJ becomes
  the primary race instead of a secondary one for some future election
  cycle), the eager/lazy assignment in this plan should be revisited —
  it's a product decision encoded in code, not a fixed architectural fact.
- The `rootMargin: '200px 0px'` prefetch distance is a reasonable default,
  not a measured/tuned value — a future maintainer with real analytics on
  scroll speed could tune it.
