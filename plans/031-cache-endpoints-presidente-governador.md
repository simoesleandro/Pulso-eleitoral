# Plan 031: Cache `/api/pesquisas/presidente` e `/api/pesquisas/governador-rj`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 0992d23..HEAD -- app.py`
> If `app.py` changed since this plan was written, compare the "Current
> state" excerpt below against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `0992d23`, 2026-07-17

## Why this matters

`app.py` has 15 public read-only `/api/*` endpoints, and 13 of them carry
`@cache.cached(timeout=300)`. Two do not: `/api/pesquisas/presidente` and
`/api/pesquisas/governador-rj`. Both call `get_pesquisas_mais_recentes()`
(`db/pesquisas.py`), which runs a `LEFT JOIN candidatos` with a per-row
`ORDER BY` — not free. `templates/dashboard.html` calls both unconditionally
on every single dashboard page load (`carregarPresidente()` and
`carregarGovernador()` inside `inicializar()`). On a public, link-shared,
mobile-heavy dashboard (see `PRODUCT.md`'s stated usage context), this means
every visitor re-executes an uncached query that all its sibling endpoints
already avoid. This looks like an oversight from when these two routes were
first written, not a deliberate freshness requirement — nothing about "most
recent poll" needs sub-5-minute freshness, and `/admin/apply-db` already
calls `cache.clear()` on every data refresh so cached responses can never go
stale beyond a fresh collection.

## Current state

- `app.py` — the two uncached routes, back to back:

```python
@app.route('/api/pesquisas/presidente')
def api_pesquisas_presidente():
    """Retorna dados consolidados da pesquisa mais recente para Presidente."""
    ...

@app.route('/api/pesquisas/governador-rj')
def api_pesquisas_governador_rj():
    """Retorna dados consolidados da pesquisa mais recente para Governador RJ."""
    ...
```

  (exact line numbers: `api_pesquisas_presidente` at `app.py:598`,
  `api_pesquisas_governador_rj` at `app.py:627` — confirm with
  `grep -n "def api_pesquisas_presidente\|def api_pesquisas_governador_rj" app.py`
  since the drift check may have shifted them slightly.)

- The pattern to match — a sibling endpoint with the same "no query-string
  params" shape, already cached (`app.py:757` area, `/api/institutos`):

```python
@cache.cached(timeout=300)
def api_institutos():
    ...
```

  Neither `/api/pesquisas/presidente` nor `/api/pesquisas/governador-rj`
  takes any query-string parameters, so use the plain
  `@cache.cached(timeout=300)` form — the same one used by
  `/api/visao-geral` (`app.py:500`), not the `query_string=True` variant
  used by endpoints like `/api/regional/presidente` (`app.py:731`) which
  vary by request args.

- Cache invalidation is already handled globally: `/admin/apply-db` calls
  `cache.clear()` after swapping the database, and under `TESTING=True` the
  cache is a `NullCache` (see `CLAUDE.md`, "Cache" section) — no test will
  see stale data from this change.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Tests | `python -m pytest -q` | all tests pass, no new failures |
| Manual check | `python -m pytest -q tests/test_dashboard.py tests/test_cache_key.py` | all pass |

## Scope

**In scope** (the only file you should modify):
- `app.py` — add `@cache.cached(timeout=300)` above `api_pesquisas_presidente` and `api_pesquisas_governador_rj`.

**Out of scope**:
- Any other route's caching (all others are already correctly configured).
- `db/pesquisas.py` — no query logic changes needed; this is purely a caching-layer fix.
- `templates/dashboard.html` — no frontend changes needed.

## Git workflow

- Branch: `advisor/031-cache-endpoints-presidente-governador`
- Commit message style (conventional commits, Portuguese — see `git log --oneline`):
  `fix(perf): cacheia /api/pesquisas/presidente e /governador-rj`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add caching to `/api/pesquisas/presidente`

Add `@cache.cached(timeout=300)` immediately above `def api_pesquisas_presidente():`
in `app.py`, matching the exact decorator style used on `/api/visao-geral`
(`app.py:500`) and `/api/institutos`.

**Verify**: `grep -n -B1 "def api_pesquisas_presidente" app.py` → shows
`@cache.cached(timeout=300)` on the line immediately above.

### Step 2: Add caching to `/api/pesquisas/governador-rj`

Same as Step 1, for `def api_pesquisas_governador_rj():`.

**Verify**: `grep -n -B1 "def api_pesquisas_governador_rj" app.py` → shows
`@cache.cached(timeout=300)` on the line immediately above.

### Step 3: Run the full test suite

**Verify**: `python -m pytest -q` → all tests pass (same pass/fail count as
before this change, modulo the flaky Monte Carlo tests noted below).

## Test plan

No new tests are needed — this is a pure decorator addition following an
existing, already-tested pattern (13 other endpoints use the identical
decorator and are covered by `tests/test_dashboard.py`). Do not write a new
test file for this; if you want extra confidence, confirm
`tests/test_cache_key.py` still passes (it exercises the caching layer
generically).

- Verification: `python -m pytest -q` → all pass.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n -B1 "def api_pesquisas_presidente" app.py` shows `@cache.cached(timeout=300)` directly above
- [ ] `grep -n -B1 "def api_pesquisas_governador_rj" app.py` shows `@cache.cached(timeout=300)` directly above
- [ ] `python -m pytest -q` exits 0 (or has the exact same failures as a clean baseline run before your change — see STOP conditions)
- [ ] No files outside `app.py` are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `api_pesquisas_presidente` or `api_pesquisas_governador_rj` no longer
  exist at those names in `app.py` (the codebase has drifted since this
  plan was written).
- Either route already has a `@cache.cached` decorator (someone beat you to
  it) — report and stop, don't stack a second decorator.
- The test suite has pre-existing failures unrelated to this change. Note:
  this repo has a known flakiness where ~5 `test_monte_carlo.py` tests fail
  on a fresh/zeroed local database on Windows due to a file-lock timing
  issue, and pass on rerun or in CI — if you see only those specific
  failures, they are not caused by your change; do not attempt to fix them.

## Maintenance notes

- If either endpoint ever needs to accept a query parameter (e.g. a
  `cargo=` filter, mirroring how other endpoints vary responses), switch to
  `@cache.cached(timeout=300, query_string=True)` and use the normalized
  cache-key helper pattern already established in `app.py` (see
  `_chave_cache_alertas` and its siblings) rather than the raw
  `query_string=True` flag, per the fix from plan 026.
- No other follow-up expected — this is a self-contained, low-risk fix.
