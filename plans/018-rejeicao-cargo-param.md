# Plan 018: `/api/rejeicao` aceita `cargo` (governador_rj deixa de ser invisível)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 8d3827f..HEAD -- app.py templates/dashboard.html`
> If `app.py` or `templates/dashboard.html` changed since this plan was
> written, compare the "Current state" excerpts below against the live code
> before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `8d3827f`, 2026-07-16

## Why this matters

`/api/rejeicao` is the only endpoint in the app that ignores the `cargo`
query-string convention every sibling endpoint follows. It hardcodes
`cargo = 'presidente'` directly in the SQL, so any rejection data collected
for the RJ governor race (`cargo='governador_rj'`) is permanently invisible
in the product — not a missing feature, just data that can exist in the
`rejeicoes` table and never surface anywhere. Fixing this is a small,
low-risk change that follows an existing, well-established pattern in the
same file.

## Current state

- `app.py:970-994` — `api_rejeicao()`, the only handler in the file that does
  not read `cargo` from `request.args`:

```python
@app.route('/api/rejeicao')
@cache.cached(timeout=300)
def api_rejeicao():
    """Retorna média de rejeição por candidato nos últimos 30 dias."""
    resultado = []
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT r.candidato, AVG(r.percentual) AS media, COUNT(*) AS n_pesquisas
                FROM rejeicoes r
                JOIN pesquisas p ON p.id = r.pesquisa_id
                WHERE p.data_pesquisa >= date('now', '-30 days')
                  AND p.cargo = 'presidente'
                GROUP BY r.candidato
                ORDER BY media DESC
            """)
            rows = cursor.fetchall()
            resultado = [
                {"candidato": row["candidato"], "media": round(row["media"], 1), "n_pesquisas": row["n_pesquisas"]}
                for row in rows
            ]
    except Exception as e:
        app.logger.error(f"Erro em /api/rejeicao: {e}")
    return jsonify({"rejeicoes": resultado})
```

- The repo convention this must match — `app.py:626-634`, `/api/alertas`,
  reads `cargo` with a `presidente` default and passes it as a bind
  parameter, and is decorated with `@cache.cached(timeout=300,
  query_string=True)` (note the `query_string=True` — without it, every
  `?cargo=` variant would hit the same cache entry):

```python
@app.route('/api/alertas')
@cache.cached(timeout=300, query_string=True)
def api_alertas():
    """Retorna alertas de variações bruscas de percentual."""
    from database import detectar_variacoes_bruscas
    cargo = request.args.get('cargo', 'presidente')
    limiar = _parse_num(request.args.get('limiar'), float, 3.0)
    janela = _parse_num(request.args.get('janela'), int, 7)
    return jsonify({"alertas": detectar_variacoes_bruscas(cargo, limiar, janela)})
```

- Frontend call site — `templates/dashboard.html`, function `carregarRejeicao()`
  (around line 1095-1120 in the current file; search for
  `fetch('/api/rejeicao')` to confirm the exact line — it currently has no
  `cargo` param):

```js
async function carregarRejeicao() {
  try {
    const res = await fetch('/api/rejeicao');
    const data = await res.json();
    const container = document.getElementById('rejeicao-container');
    ...
```

- The rejection card lives in `secao-analise` today (single card, no cargo
  selector). This plan does NOT redesign the card — it only makes the cargo
  parametrizable and adds the RJ fetch alongside the existing presidential
  one, matching how `carregarKpisAnaliseRJ()` (added this session) fetches
  `governador_rj` data into its own grid.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Run tests | `TESTING=True python -m pytest -q` | all pass, exit 0 |
| Run a single test file | `TESTING=True python -m pytest -q tests/test_dashboard.py` | all pass |
| Manual smoke check | `TESTING=True python -c "import app; c=app.app.test_client(); print(c.get('/api/rejeicao?cargo=governador_rj').get_json())"` | valid JSON, no traceback |

## Scope

**In scope**:
- `app.py` — `api_rejeicao()` (lines 970-994)
- `templates/dashboard.html` — `carregarRejeicao()` and the rejeição card
  markup (add a second container/card for `governador_rj`, or a cargo
  toggle — see Step 3 for the minimal option)
- `tests/test_dashboard.py` (or wherever existing `/api/rejeicao` tests live
  — `grep -rn "api_rejeicao\|/api/rejeicao" tests/` to find them) — add
  coverage for the new param

**Out of scope**:
- Any change to how rejection data is collected/extracted (Gemini prompt,
  `collectors/*.py`) — this plan only exposes what's already in the DB.
- Redesigning the rejeição card's visual layout beyond adding the RJ variant.

## Git workflow

- Branch: `advisor/018-rejeicao-cargo-param` (or match whatever branch
  convention is active in the repo at execution time)
- Commit message style: conventional commits in Portuguese, e.g.
  `fix(rejeicao): aceita cargo=governador_rj em vez de hardcode presidente`
  (see `git log --oneline -10` for examples)
- Do NOT push or open a PR unless explicitly instructed.

## Steps

### Step 1: Parametrize `api_rejeicao()` by cargo

Edit `app.py:970-994`. Add `cargo = request.args.get('cargo', 'presidente')`
at the top of the function body (matching the pattern at `app.py:631`), bind
it into the SQL in place of the hardcoded string literal, and add
`query_string=True` to the `@cache.cached(...)` decorator (matching
`app.py:627`) so `?cargo=governador_rj` and no-param requests get separate
cache entries.

```python
@app.route('/api/rejeicao')
@cache.cached(timeout=300, query_string=True)
def api_rejeicao():
    """Retorna média de rejeição por candidato nos últimos 30 dias. ?cargo= opcional (default presidente)."""
    from flask import request
    cargo = request.args.get('cargo', 'presidente')
    resultado = []
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT r.candidato, AVG(r.percentual) AS media, COUNT(*) AS n_pesquisas
                FROM rejeicoes r
                JOIN pesquisas p ON p.id = r.pesquisa_id
                WHERE p.data_pesquisa >= date('now', '-30 days')
                  AND p.cargo = ?
                GROUP BY r.candidato
                ORDER BY media DESC
            """, (cargo,))
            ...
```

(`request` is already imported at module level in `app.py` in every other
handler — check `from flask import ... request` near the top of the file
before adding a duplicate import; if it's already imported globally, don't
re-import it inside the function.)

**Verify**:
`TESTING=True python -c "import app; c=app.app.test_client(); r=c.get('/api/rejeicao?cargo=governador_rj'); print(r.status_code, r.get_json())"`
→ status 200, JSON with a `"rejeicoes"` key (list may be empty if no RJ
rejection data exists yet in the test DB — that's fine, an empty list is a
valid result, not a failure).

### Step 2: Add the RJ fetch on the dashboard

In `templates/dashboard.html`, find `carregarRejeicao()`. Add a second call
(or refactor into a parametrized helper called twice) that fetches
`/api/rejeicao?cargo=governador_rj` and renders into a new container inside
`secao-governador` (the RJ section — match the placement pattern used for
`carregarKpisAnaliseRJ()`'s `#kpis-analise-grid`, which lives inside
`secao-governador` in the HTML, not `secao-analise`). Add the new container
`<div id="rejeicao-rj-container">` near the existing governor charts, with
a `<div class="pe-kpi__label">Rejeição — Governador RJ</div>` heading
matching the style of nearby cards.

Call the new loader function from `inicializar()` alongside the existing
`carregarRejeicao()` call.

**Verify**: start the app locally (`python app.py` or however the repo's
`run` skill launches it) and confirm in the browser that the RJ section
shows a rejection card without JS console errors. If no RJ rejection data
exists in the local DB, the card should show its existing empty-state
message (check how `carregarRejeicao()` already handles an empty
`rejeicoes` list — reuse that same empty-state branch, don't invent a new
one).

### Step 3: Add/extend a test for the cargo param

Find the existing test(s) covering `/api/rejeicao` (`grep -rn
"api_rejeicao\|/api/rejeicao" tests/`). Add a case that seeds a
`governador_rj` pesquisa with a `rejeicoes` row, calls
`/api/rejeicao?cargo=governador_rj`, and asserts the response includes that
candidate — and a second case confirming `/api/rejeicao` with no param still
defaults to `presidente` (regression guard for the default-preserving
change).

**Verify**: `TESTING=True python -m pytest -q tests/test_dashboard.py` (or
wherever the test landed) → all pass.

## Test plan

- New test: `/api/rejeicao?cargo=governador_rj` returns RJ rejection data
  when present in the DB.
- New test (or extend existing): `/api/rejeicao` with no query param still
  defaults to `presidente` (backward compatibility).
- Pattern to follow: look at how `test_agregacao.py` or `test_variacoes.py`
  seed a `pesquisas`/`intencoes`/`rejeicoes` row for a given `cargo` — reuse
  that seeding helper rather than writing raw INSERTs from scratch.
- Verification: `TESTING=True python -m pytest -q` → all pass, including the
  new test(s).

## Done criteria

- [ ] `TESTING=True python -m pytest -q` exits 0
- [ ] `grep -n "cargo = request.args.get" app.py` includes a line inside
      `api_rejeicao` (confirms the hardcode is gone)
- [ ] `grep -n "p.cargo = 'presidente'" app.py` returns no match inside
      `api_rejeicao` specifically (the literal string is gone from that
      function's SQL)
- [ ] Dashboard shows a rejection card for governador_rj (manually verified
      in browser, or via the test added in Step 3)
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row for 018 updated

## STOP conditions

- The code at `app.py:970-994` doesn't match the excerpt above (file has
  drifted — re-read it and compare before proceeding).
- `carregarRejeicao()` in `dashboard.html` doesn't exist under that name
  anymore, or the rejeição card markup has been restructured — re-locate it
  before assuming the plan's Step 2 instructions still apply verbatim.
- Adding `query_string=True` to the cache decorator causes a test failure
  unrelated to this endpoint (would indicate a shared caching assumption
  elsewhere in the test suite) — stop and report rather than removing the
  flag to make tests pass.

## Maintenance notes

- If a third cargo is ever added to the app (the domain currently supports
  only `presidente` and `governador_rj` per `CLAUDE.md`), this same pattern
  (parametrized `cargo`, `query_string=True` cache) should be followed
  rather than hardcoding a third literal.
- The RJ rejection card may show an empty state for a long time if no
  collector currently extracts rejection data for governor-race releases —
  that's expected and not a bug in this plan; it's a data-availability
  question, not a code question.
