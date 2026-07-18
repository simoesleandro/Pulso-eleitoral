# Plan 026: Cache dos endpoints públicos usa chave normalizada, não query-string bruta

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
- **Depends on**: none (complements plan 020's rate limiting, already
  merged — that plan mitigates volume, this one removes the cache-bypass
  amplification specifically)
- **Category**: security
- **Planned at**: commit `f53d533`, 2026-07-16

## Why this matters

Three public, `@cache.cached(timeout=300, query_string=True)` endpoints
build their Flask-Caching cache key from the **raw** query string, before
the handler's own parameter normalization (`_parse_num`, `tipo`
whitelisting, `candidatos` parsing) ever runs. A client can vary the query
string in ways that are semantically identical but textually different —
`?janela=7` vs `?janela=07` vs `?janela=7.0` vs `?candidatos=Lula,Ciro` vs
`?candidatos=Ciro,Lula` — and each variant is a **cache miss**, hitting the
underlying SQL aggregation (`detectar_variacoes_bruscas`,
`get_historico_multi`, `get_media_agregada`) fresh every time. Combined
with plan 020's rate limit (60 req/min per IP by default), this is a much
smaller problem than before, but it's still needless load on SQLite for
zero legitimate benefit — the cache is supposed to absorb repeated
requests, and right now trivial client-side variation defeats it entirely.

## Current state

- `app.py:643-677` — the three affected endpoints:

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

@app.route('/api/pesquisas/historico-multi')
@cache.cached(timeout=300, query_string=True)
def api_pesquisas_historico_multi():
    """Retorna séries históricas de múltiplos candidatos para um cargo."""
    from database import get_historico_multi, get_top_candidatos
    cargo = request.args.get('cargo', 'presidente')
    tipo = request.args.get('tipo', 'estimulada')
    if tipo not in ('estimulada', 'espontanea'):
        tipo = 'estimulada'
    candidatos_param = request.args.get('candidatos', '')
    if candidatos_param:
        candidatos = [c.strip() for c in candidatos_param.split(',') if c.strip()]
    else:
        candidatos = get_top_candidatos(cargo, n=3)
    series = get_historico_multi(candidatos, cargo, tipo)
    return jsonify({"cargo": cargo, "series": series})

@app.route('/api/media-agregada')
@cache.cached(timeout=300, query_string=True)
def api_media_agregada():
    """Retorna média agregada dos últimos 30 dias por candidato para um cargo."""
    from database import get_media_agregada
    cargo = request.args.get('cargo', 'presidente')
    dias = _parse_num(request.args.get('dias'), int, 30)
    return jsonify(get_media_agregada(cargo, dias))
```

- `app.py:85-89` — the existing `_parse_num` helper, already the right tool
  for normalizing numeric params:

```python
def _parse_num(valor, tipo, default):
    """Coage query param para int/float com fallback seguro — evita 500 em
    endpoints públicos quando o cliente manda um valor não-numérico."""
    try:
        return tipo(valor)
    except (TypeError, ValueError):
        return default
```

- Flask-Caching's `cached()` decorator accepts a `key_prefix` argument that
  can be a **callable** (invoked with no arguments per request, inside the
  request context) instead of a string — its return value becomes part of
  the cache key. This is the documented mechanism for exactly this
  situation: build the key from *normalized* request data instead of the
  raw query string. Replacing `query_string=True` with a `key_prefix=`
  callable per endpoint is this plan's approach.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Run tests | `TESTING=True python -m pytest -q` | all pass, exit 0 |

## Scope

**In scope**:
- `app.py` — the three endpoints listed above: replace
  `query_string=True` with a `key_prefix=<callable>` that builds a
  canonical key from the already-normalized parameter values
- `tests/` — a test per endpoint confirming two semantically-equivalent
  but textually-different query strings produce the same cached result
  (i.e. the second call doesn't re-hit the DB — see Step 4 for how to
  observe this without mocking internals)

**Out of scope**:
- Any other `@cache.cached` endpoint not listed above (they either don't
  take free-form numeric/list params, or aren't flagged in the audit).
- Changing the cache timeout (300s) or backend (`SimpleCache`/`NullCache`).
- Plan 020's rate limiting — already done, this plan is independent and
  complementary.

## Git workflow

- Branch: `advisor/026-cache-chave-normalizada`
- Commit message style: conventional commits in Portuguese, e.g.
  `fix(cache): normaliza chave de cache antes de aplicar query_string`
- Do NOT push or open a PR unless explicitly instructed.

## Steps

### Step 1: `/api/alertas`

Replace the decorator and extract the normalization above the cache
lookup by defining a small key-prefix function:

```python
def _chave_cache_alertas():
    cargo = request.args.get('cargo', 'presidente')
    limiar = _parse_num(request.args.get('limiar'), float, 3.0)
    janela = _parse_num(request.args.get('janela'), int, 7)
    return f"alertas:{cargo}:{limiar}:{janela}"

@app.route('/api/alertas')
@cache.cached(timeout=300, key_prefix=_chave_cache_alertas)
def api_alertas():
    """Retorna alertas de variações bruscas de percentual."""
    from database import detectar_variacoes_bruscas
    cargo = request.args.get('cargo', 'presidente')
    limiar = _parse_num(request.args.get('limiar'), float, 3.0)
    janela = _parse_num(request.args.get('janela'), int, 7)
    return jsonify({"alertas": detectar_variacoes_bruscas(cargo, limiar, janela)})
```

(The normalization logic is duplicated between the key function and the
handler — this is intentional and unavoidable with this Flask-Caching
mechanism, since the key function runs before the handler body. Keep both
copies in sync if `_parse_num`'s defaults ever change.)

**Verify**: `TESTING=True python -c "
import app
c = app.app.test_client()
r1 = c.get('/api/alertas?janela=7')
r2 = c.get('/api/alertas?janela=07')
print(r1.status_code, r2.status_code)
"` → both `200` (functional smoke check; cache-hit behavior is verified in Step 4's test, not here).

### Step 2: `/api/pesquisas/historico-multi`

Same pattern, reusing the existing `candidatos`/`tipo` normalization
(including sorting `candidatos` so `Lula,Ciro` and `Ciro,Lula` collapse to
the same key — order doesn't change the *set* of series requested):

```python
def _chave_cache_historico_multi():
    from database import get_top_candidatos
    cargo = request.args.get('cargo', 'presidente')
    tipo = request.args.get('tipo', 'estimulada')
    if tipo not in ('estimulada', 'espontanea'):
        tipo = 'estimulada'
    candidatos_param = request.args.get('candidatos', '')
    if candidatos_param:
        candidatos = sorted(c.strip() for c in candidatos_param.split(',') if c.strip())
    else:
        candidatos = sorted(get_top_candidatos(cargo, n=3))
    return f"historico-multi:{cargo}:{tipo}:{','.join(candidatos)}"

@app.route('/api/pesquisas/historico-multi')
@cache.cached(timeout=300, key_prefix=_chave_cache_historico_multi)
def api_pesquisas_historico_multi():
    """Retorna séries históricas de múltiplos candidatos para um cargo."""
    from database import get_historico_multi, get_top_candidatos
    cargo = request.args.get('cargo', 'presidente')
    tipo = request.args.get('tipo', 'estimulada')
    if tipo not in ('estimulada', 'espontanea'):
        tipo = 'estimulada'
    candidatos_param = request.args.get('candidatos', '')
    if candidatos_param:
        candidatos = [c.strip() for c in candidatos_param.split(',') if c.strip()]
    else:
        candidatos = get_top_candidatos(cargo, n=3)
    series = get_historico_multi(candidatos, cargo, tipo)
    return jsonify({"cargo": cargo, "series": series})
```

Note: the handler's own `candidatos` list is deliberately left
**unsorted** (order may matter for how `get_historico_multi` orders its
response `series` — don't change response ordering behavior, only the
cache key). Only the key-function's copy is sorted.

**Verify**: `TESTING=True python -c "
import app
c = app.app.test_client()
r1 = c.get('/api/pesquisas/historico-multi?candidatos=Lula,Ciro Gomes')
r2 = c.get('/api/pesquisas/historico-multi?candidatos=Ciro Gomes,Lula')
print(r1.status_code, r2.status_code)
"` → both `200`.

### Step 3: `/api/media-agregada`

Same pattern:

```python
def _chave_cache_media_agregada():
    cargo = request.args.get('cargo', 'presidente')
    dias = _parse_num(request.args.get('dias'), int, 30)
    return f"media-agregada:{cargo}:{dias}"

@app.route('/api/media-agregada')
@cache.cached(timeout=300, key_prefix=_chave_cache_media_agregada)
def api_media_agregada():
    """Retorna média agregada dos últimos 30 dias por candidato para um cargo."""
    from database import get_media_agregada
    cargo = request.args.get('cargo', 'presidente')
    dias = _parse_num(request.args.get('dias'), int, 30)
    return jsonify(get_media_agregada(cargo, dias))
```

**Verify**: `TESTING=True python -c "
import app
c = app.app.test_client()
r1 = c.get('/api/media-agregada?dias=30')
r2 = c.get('/api/media-agregada?dias=30.0')
print(r1.status_code, r2.status_code)
"` → both `200`.

### Step 4: Add a cache-collapse regression test

Under `TESTING=True` the cache backend is `NullCache` (`app.py:41`,
`_cache_type = 'NullCache' if os.getenv('TESTING') == 'True' else
'SimpleCache'`), which never actually caches anything — so a test running
under `TESTING=True` cannot observe a real cache hit/miss. To test the key
function's *normalization logic* itself without depending on the live
cache backend, test the key-prefix functions directly as plain Python
functions inside a request context, rather than through two live HTTP
calls:

```python
def test_chave_cache_normaliza_parametros_equivalentes(client):
    """Duas variações textuais do mesmo pedido (janela=7 vs janela=07)
    devem produzir a mesma chave de cache — evita bypass de cache por
    variação trivial de query string."""
    with app.app.test_request_context('/api/alertas?janela=7'):
        chave1 = app._chave_cache_alertas()
    with app.app.test_request_context('/api/alertas?janela=07'):
        chave2 = app._chave_cache_alertas()
    assert chave1 == chave2

    with app.app.test_request_context('/api/pesquisas/historico-multi?candidatos=Lula,Ciro Gomes'):
        chave3 = app._chave_cache_historico_multi()
    with app.app.test_request_context('/api/pesquisas/historico-multi?candidatos=Ciro Gomes,Lula'):
        chave4 = app._chave_cache_historico_multi()
    assert chave3 == chave4
```

Adjust the exact module/attribute access (`app._chave_cache_alertas` vs an
import) to match how this repo's other tests import from `app` — check an
existing test file for the pattern (e.g. `from app import
_detectar_coletor` style used in `tests/test_collectors.py`) rather than
assuming `app.app` module-attribute access is idiomatic here.

**Verify**: `TESTING=True python -m pytest -q -k chave_cache` → passes.

## Test plan

- New test: for each of the 3 endpoints, two textually-different but
  semantically-equivalent query strings produce identical cache keys
  (tested by calling the key-prefix function directly in a request
  context, since `NullCache` under `TESTING=True` prevents observing a
  real cache hit).
- Verification: `TESTING=True python -m pytest -q` → all pass, including
  the new test.

## Done criteria

- [ ] `TESTING=True python -m pytest -q` exits 0
- [ ] `grep -n "query_string=True" app.py` no longer includes
      `/api/alertas`, `/api/pesquisas/historico-multi`, or
      `/api/media-agregada` (only other, unrelated endpoints if any)
- [ ] `grep -n "key_prefix=_chave_cache" app.py` shows all 3 endpoints
      updated
- [ ] New test(s) exist and pass, confirming key normalization
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row for 026 updated

## STOP conditions

- Any of the 3 endpoints don't match the excerpt above (handler logic
  restructured) — re-read and re-derive the key function from the live
  handler, don't copy this plan's snippet blindly.
- Flask-Caching's installed version doesn't support a callable
  `key_prefix` (check `flask-caching` version in `requirements.lock` — if
  the API differs from what's assumed here, stop and report rather than
  guessing at an alternate mechanism).
- The duplication between key-function and handler-body normalization
  logic bothers you enough to want to refactor into one shared helper —
  that's a reasonable instinct but is a larger change than this plan
  scopes; if you see a clean one-line way to share the logic without
  restructuring the route decorators, fine, otherwise leave the
  duplication as specified and note it as a follow-up idea in your report.

## Maintenance notes

- If any of these 3 endpoints gains a new query parameter in the future,
  the corresponding `_chave_cache_*` function must be updated in the same
  change — otherwise the new parameter would be silently ignored by the
  cache key while still being honored by the handler, causing wrong cached
  responses to be served for different inputs. This is the main risk this
  pattern introduces; a comment at each `_chave_cache_*` function should
  make this obligation obvious to the next editor.
