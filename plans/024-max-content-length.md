# Plan 024: Configura `MAX_CONTENT_LENGTH` (corpo de request ilimitado em rota pública)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat f53d533..HEAD -- app.py`
> If `app.py` changed since this plan was written, compare the "Current
> state" excerpt below against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `f53d533`, 2026-07-16

## Why this matters

`app.py` never sets `app.config['MAX_CONTENT_LENGTH']`, so Flask/Werkzeug
will buffer and parse a request body of unbounded size before any route
handler gets a chance to reject it. `/login` (public, POST) and
`/admin/coletar-url` (`request.get_json()`) are the two routes that parse a
body without any size ceiling today. This is a cheap, low-effort hardening
step — a one-line config plus a regression test — that closes a memory/CPU
exhaustion vector against a single-process (Waitress, no multi-worker)
deployment.

## Current state

- `app.py:19-56` — the app's config block, where cross-cutting Flask config
  already lives (cache, cookies, CSRF, rate limiter — this plan adds one
  more line to the same block):

```python
app = Flask(__name__)

# Configurações do Flask
_secret = os.getenv('SECRET_KEY')
if not _secret:
    ...
app.secret_key = _secret

# NullCache em testes: ...
_cache_type = 'NullCache' if os.getenv('TESTING') == 'True' else 'SimpleCache'
cache = Cache(app, config={'CACHE_TYPE': _cache_type, 'CACHE_DEFAULT_TIMEOUT': 300})

# Rate limiting (Flask-Limiter). ...
_limiter_default = "10000 per minute" if os.getenv('TESTING') == 'True' else "60 per minute"
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=[_limiter_default],
    storage_uri="memory://",
)

# Flags de cookie de sessão (defesa contra XSS/MITM/CSRF).
_em_producao = bool(os.getenv('FLY_APP_NAME'))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=_em_producao,
)
```

- Confirmed absent: `grep -n "MAX_CONTENT_LENGTH" app.py` returns no match.
- No route in this app accepts file uploads over HTTP today (the `/admin/
  apply-db` DB swap happens via `flyctl sftp put` outside the request
  cycle, per `scripts/sync_db.py` — not a Flask route) — so a generous
  limit is safe; this is about bounding accidental/malicious oversized
  bodies on `/login` (form POST) and `/admin/coletar-url` (small JSON
  payload: a URL string and a collector key).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Run tests | `TESTING=True python -m pytest -q` | all pass, exit 0 |

## Scope

**In scope**:
- `app.py` — add `MAX_CONTENT_LENGTH` to the `app.config.update(...)` block
  (or a standalone `app.config['MAX_CONTENT_LENGTH'] = ...` line near it)
- `tests/` — one regression test confirming an oversized body is rejected

**Out of scope**:
- Any per-route override (no route in this app needs a different limit
  than the global one).
- Building an actual file-upload route (none exists over HTTP today).

## Git workflow

- Branch: `advisor/024-max-content-length`
- Commit message style: conventional commits in Portuguese, e.g.
  `fix(seguranca): configura MAX_CONTENT_LENGTH para limitar corpo de request`
- Do NOT push or open a PR unless explicitly instructed.

## Steps

### Step 1: Set the config

Add to the `app.config.update(...)` call at `app.py:46-50` (or as a
separate line right after it):

```python
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2 MB — generoso para form/JSON, sem upload de arquivo por HTTP hoje
```

2 MB is a deliberately generous ceiling — the largest legitimate payload in
this app is a small JSON body (`/admin/coletar-url`) or a login form; there
is no file-upload route to accommodate. Don't tighten below what's
comfortable for those.

**Verify**: `TESTING=True python -c "import app; print(app.app.config['MAX_CONTENT_LENGTH'])"` → prints `2097152`.

### Step 2: Add a regression test

Add a test that POSTs a body larger than the configured limit to a public
route (`/login` is the simplest target, already unauthenticated) and
asserts a `413` response:

```python
def test_login_rejeita_corpo_maior_que_max_content_length(client):
    corpo_grande = 'x' * (3 * 1024 * 1024)  # 3 MB, acima do limite de 2 MB
    resp = client.post('/login', data={'username': 'admin', 'password': corpo_grande})
    assert resp.status_code == 413
```

Place this in `tests/test_rate_limiting.py` (added by plan 020, already
covers `/login` security-adjacent behavior) or a new small test file — your
call, but don't duplicate the `client` fixture if one already exists in the
file you choose (check `tests/test_rate_limiting.py`'s fixtures first).

**Verify**: `TESTING=True python -m pytest -q -k max_content_length` → 1
passed.

## Test plan

- New test: oversized POST body → `413 Request Entity Too Large`.
- Verification: `TESTING=True python -m pytest -q` → all pass, including
  the new test, full suite unaffected.

## Done criteria

- [ ] `TESTING=True python -m pytest -q` exits 0
- [ ] `grep -n "MAX_CONTENT_LENGTH" app.py` shows the new config line
- [ ] New test exists and passes, demonstrating `413` on an oversized body
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row for 024 updated

## STOP conditions

- `app.py:19-56` doesn't match the excerpt above (config block
  restructured) — re-read before adding the new line.
- Setting `MAX_CONTENT_LENGTH` to 2 MB breaks an existing test that posts a
  legitimately large body (unlikely, but check `tests/test_admin_coletar_url.py`
  or similar if it exists) — if so, raise the limit rather than lowering
  test expectations, and note why in your report.

## Maintenance notes

- If a real file-upload route is ever added, revisit this limit — 2 MB
  would be too small for, say, a PDF upload. This plan's ceiling is sized
  for the current all-JSON/form app, not a future one.
