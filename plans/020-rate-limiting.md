# Plan 020: Rate limiting em `/login` e nos endpoints públicos `/api/*`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 8d3827f..HEAD -- app.py requirements.txt requirements.lock`
> If any of these changed since this plan was written, compare the "Current
> state" excerpts below against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S–M
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `8d3827f`, 2026-07-16

## Why this matters

`/login` accepts unlimited POST attempts with no lockout or per-IP
throttling — `bcrypt.checkpw` (used in `database.verificar_usuario`) makes
each individual attempt slow, but nothing caps the number of attempts, so
an attacker can still brute-force the admin password given enough time and
distributed IPs. Separately, the 13+ public `/api/*` endpoints (some of
which run non-trivial SQL aggregations — `get_kpis_avancados`,
`detectar_variacoes_bruscas`, `get_historico_multi`) have no request
throttling at all, making them cheap to hammer for scraping or as a denial-
of-service vector against the single-process SQLite backend. Adding
rate limiting closes both gaps with one small, additive dependency.

## Current state

- `app.py:19-55` — how the app currently configures cross-cutting concerns
  (cache, cookies, CSRF) — this is the pattern to extend, not replace:

```python
app = Flask(__name__)
...
_cache_type = 'NullCache' if os.getenv('TESTING') == 'True' else 'SimpleCache'
cache = Cache(app, config={'CACHE_TYPE': _cache_type, 'CACHE_DEFAULT_TIMEOUT': 300})
...
app.config['WTF_CSRF_ENABLED'] = os.getenv('TESTING') != 'True'
csrf = CSRFProtect(app)
```

  Note the recurring convention: security/cross-cutting features are
  **disabled or neutralized under `TESTING=True`** so the test suite (which
  calls routes directly via Flask's test client, often many times per test
  file, sometimes from the same simulated "IP") isn't broken by them. Rate
  limiting must follow the same convention — see Step 1.

- `app.py:181-199` — the login route to protect:

```python
@app.route('/login', methods=['GET', 'POST'])
def login():
    """Rota de controle de acesso (login)."""
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        from database import verificar_usuario
        user = verificar_usuario(username, password)
        if user:
            session['logged_in'] = True
            session['username'] = user['username']
            session['nome'] = user['nome']
            return redirect(url_for('index'))
        else:
            error = "Usuário ou senha incorretos."

    return render_template('login.html', error=error)
```

- `app.py:626-994` — the block of `/api/*` routes (roughly 13 endpoints:
  `/api/alertas`, `/api/pesquisas/historico-multi`, `/api/media-agregada`,
  `/api/kpis-avancados`, `/api/simulacao-segundo-turno`, `/api/house-effects`,
  `/api/rejeicao`, and others — run `grep -n "@app.route('/api/" app.py` to
  get the exact current list before writing the blueprint-wide limit in
  Step 3).

- `requirements.txt:1-13` currently lists `flask>=3.0.0`,
  `flask-caching>=2.3.0`, `flask-wtf>=1.2.0` among others — `flask-limiter`
  is not present (confirmed via `grep -n limiter requirements.txt` → no
  match).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Install new dep locally (dev only, not committed as an artifact) | `pip install flask-limiter` | installs cleanly |
| Regenerate lockfile | `pip-compile requirements.txt -o requirements.lock` | new `flask-limiter` line appears in `requirements.lock` |
| Run tests | `TESTING=True python -m pytest -q` | all pass, exit 0 |
| Manual smoke check (rate limit fires) | `TESTING=False ADMIN_PASS=x python -c "..."` (see Step 4) | 429 after N requests |

## Suggested executor toolkit

- This plan adds a new dependency. Follow the exact pip-compile invocation
  documented in `CLAUDE.md`'s "Playwright... requirements.lock (gerado via
  pip-compile, sob Python 3.12 local; produção/CI/Docker fixam 3.11)" note
  — regenerate the lock the same way this repo already does for other deps,
  don't hand-edit `requirements.lock`.

## Scope

**In scope**:
- `requirements.txt`, `requirements.lock` — add `flask-limiter`
- `app.py` — limiter initialization (near the `cache`/`csrf` setup, lines
  19-55) and per-route limit decorators on `/login` and the `/api/*` routes
- `tests/` — a new test file or addition to an existing one covering the
  429 behavior

**Out of scope**:
- Redis-backed storage for the limiter (start with the default in-memory
  storage — the app runs as a single Waitress process per
  `app.py:1017-1029`/`CLAUDE.md`, so in-memory is correct for now; note this
  as a Maintenance note, not something to build here).
- Rate limiting `/admin/*` routes beyond `/login` (they already require
  `login_required`, i.e. an authenticated session — brute force there isn't
  the threat model this plan addresses).
- Changing `bcrypt` cost factor or any other auth mechanism.

## Git workflow

- Branch: `advisor/020-rate-limiting`
- Commit message style: conventional commits in Portuguese, e.g.
  `feat(seguranca): rate limiting em /login e endpoints publicos /api/*`
- Do NOT push or open a PR unless explicitly instructed.

## Steps

### Step 1: Add the dependency and initialize the limiter

Add `flask-limiter` to `requirements.txt` (alongside the other `flask-*`
entries), then regenerate `requirements.lock` with the repo's documented
`pip-compile` invocation.

In `app.py`, initialize the limiter right after the `cache` setup
(`app.py:41`), following the same `TESTING`-aware pattern used for cache
and CSRF — under `TESTING=True`, set an effectively unlimited default so
the test suite (which calls routes repeatedly from the same test-client
"IP") isn't affected:

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

_limiter_default = "10000 per minute" if os.getenv('TESTING') == 'True' else "60 per minute"
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=[_limiter_default],
    storage_uri="memory://",
)
```

**Verify**: `TESTING=True python -c "import app"` → no import error.

### Step 2: Apply a strict limit to `/login`

Decorate the `/login` route (`app.py:181-199`) with a tighter limit than
the global default — this is the actual brute-force mitigation:

```python
@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    ...
```

**Verify**: with `TESTING=False` in a throwaway shell (do not run this
against production), start the app locally and confirm normal login still
works once; full automated 429 verification happens in Step 4's test.

### Step 3: Confirm the global default covers `/api/*`

The `default_limits` set in Step 1 applies to every route that doesn't
have its own explicit `@limiter.limit(...)`, which includes all `/api/*`
routes automatically — no per-route decorator needed unless a specific
endpoint needs a different number. Run `grep -n "@app.route('/api/"
app.py` and confirm none of them already have a competing
`@limiter.limit` (they won't, since the limiter didn't exist before this
plan) — this step is a confirmation, not a code change, unless you decide a
specific heavy endpoint (e.g. `/api/kpis-avancados`,
`/api/pesquisas/historico-multi`) needs a stricter limit than the global
60/min default, in which case add it explicitly and note why in the commit
message.

**Verify**: `grep -c "@app.route('/api/" app.py` matches the count of
endpoints you expect to be covered by the default limit (no explicit
override needed for most).

### Step 4: Add a test confirming 429 behavior

Rate-limit testing needs `TESTING` to NOT neutralize the limiter for this
one test, so isolate it: use `app.test_client()` with a monkeypatched
limiter default, or (simpler) instantiate a *second* limiter instance
scoped to the test with a tiny limit and hit the route N+1 times asserting
the last response is 429. Follow whatever pattern
`tests/test_apply_db.py` uses for testing security-sensitive routes in
isolation (read that file first for the repo's established style of
security route testing before writing this one).

**Verify**: `TESTING=True python -m pytest -q tests/test_rate_limiting.py`
(or wherever the test lands) → passes, confirming a request past the limit
returns HTTP 429.

## Test plan

- New test: hammer `/login` past its limit (whatever number Step 2 sets)
  and assert the response past the threshold is `429`.
- New test (optional but recommended): confirm a single request to
  `/api/status` (a cheap, always-public endpoint) still returns 200 under
  normal conditions — i.e. the limiter doesn't break legitimate single
  requests.
- Pattern to follow: `tests/test_apply_db.py` for how this repo tests
  auth/security-sensitive routes in isolation from the rest of the suite.
- Verification: `TESTING=True python -m pytest -q` → all pass, including
  the new rate-limiting test(s), and the full existing suite is
  unaffected (confirms the `TESTING`-aware default in Step 1 works).

## Done criteria

- [ ] `TESTING=True python -m pytest -q` exits 0 (full suite, unaffected by
      the new limiter)
- [ ] `grep -n flask-limiter requirements.txt requirements.lock` shows the
      dependency in both files
- [ ] `grep -n "@limiter.limit" app.py` shows at least the `/login` route
      decorated
- [ ] New rate-limiting test exists and passes, demonstrating a 429 past
      the configured threshold
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row for 020 updated

## STOP conditions

- Adding the limiter causes unrelated existing tests to fail even with the
  `TESTING`-aware high default — investigate whether some test suite
  fixture reuses the same Flask app instance across many requests in a way
  that still trips the limit; do not simply disable the limiter under
  `TESTING` entirely without confirming why the high default wasn't enough.
- `requirements.lock` regeneration produces unexpected changes to unrelated
  pinned versions (pip-compile sometimes bumps transitive deps) — if the
  diff includes anything beyond adding `flask-limiter` and its own direct
  dependencies, stop and report rather than committing an unreviewed dep
  bump bundled into a security fix.
- You find `/admin/coletar-url` or another admin route already has informal
  rate limiting or a comment about it — re-read before assuming this is a
  greenfield addition.

## Maintenance notes

- The limiter uses in-memory storage (`storage_uri="memory://"`), which is
  correct only because the app runs as a single process (Waitress, no
  multi-worker). If the deployment ever moves to multiple worker processes
  or instances, this needs to move to a shared backend (Redis) or the
  limit becomes per-process instead of global — flag this explicitly if
  `Dockerfile`/`fly.toml` changes to add worker concurrency.
- If a legitimate integration (e.g. a future public API consumer) needs a
  higher limit than 60/min, prefer an API-key-based limit override over
  raising the global default, to keep the anonymous/scraping ceiling low.
