# Plan 035: Evita chamadas Gemini concorrentes duplicadas em `/api/visao-geral/analise`

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

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `0992d23`, 2026-07-17

## Why this matters

`/api/visao-geral/analise` (`app.py`) is a public, unauthenticated endpoint
with a 6-hour SQLite-backed cache (`analises_ia` table). When the cache
window expires, the route calls the Gemini API inline
(`gerar_com_cascata`, up to 3 model attempts with retry/backoff on 503) and
writes the result back to `analises_ia`. There is no lock or in-flight
request de-duplication. Waitress (this app's production server, per
`CLAUDE.md`) serves with multiple worker threads. If two or more requests
land in the same brief window right after the 6h cache expires — plausible
right after a scheduled collection run, or simply a burst of concurrent
visitors — each one independently misses the cache and calls the Gemini API,
multiplying LLM cost/latency for what should be a single shared computation
per 6-hour window. A simple in-process lock closes the common case for the
single-process deployment this app currently runs as.

## Current state

- `app.py:506-585` — the full route as it exists today (abbreviated to the
  relevant control flow; read the file directly for the exact current
  lines before editing):

```python
@app.route('/api/visao-geral/analise')
def api_visao_geral_analise():
    """Retorna análise do cenário político com cache de 6 horas."""
    from database import get_db, get_visao_geral
    import json
    import datetime

    cargo = 'visao_geral'

    # 1. Verifica cache no SQLite
    cached_analise = None
    cached_data = None
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT texto, criado_em FROM analises_ia
                WHERE cargo = ? AND criado_em >= datetime('now', 'localtime', '-6 hours')
            """, (cargo,))
            row = cursor.fetchone()
            if row:
                cached_analise = row['texto']
                cached_data = row['criado_em']
    except Exception as e:
        app.logger.error(f"Erro ao ler cache de analise: {e}")

    if cached_analise:
        ...
        return jsonify({...})

    # 2. Se não estiver no cache, chama Gemini API
    dados = get_visao_geral()
    prompt = f"..."
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"analise": "Gemini API Key não configurada.", "gerado_em": ""}), 500

    try:
        from google import genai
        from collectors.gemini_extractor import gerar_com_cascata
        client = genai.Client(api_key=api_key)
        analise_texto, _ = gerar_com_cascata(
            client, prompt,
            modelos=["gemini-2.5-flash", "gemini-2.5-flash-8b", "gemini-2.5-pro"]
        )
        if not analise_texto:
            return jsonify({"analise": "Erro ao gerar análise de IA.", "gerado_em": ""}), 500

        # 3. Salva no banco analises_ia
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with get_db() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO analises_ia (cargo, texto, criado_em)
                    VALUES (?, ?, ?)
                """, (cargo, analise_texto, now_str))
                conn.commit()
        except Exception as e:
            app.logger.error(f"Erro ao salvar analise no banco: {e}")

        gerado_em = ...
        return jsonify({"analise": analise_texto, "gerado_em": gerado_em})
    except Exception as e:
        app.logger.error(f"Erro na geração do Gemini: {e}")
        return jsonify({"analise": "Serviço de análise de IA temporariamente indisponível.", "gerado_em": ""}), 500
```

- The fix: add a module-level `threading.Lock()` near the top of `app.py`
  (alongside the other module-level state like `app = Flask(__name__)`),
  and acquire it around the "cache miss → call Gemini → write cache" block
  (step 2 above), with a **double-checked cache read** immediately after
  acquiring the lock — so a request that waited on the lock while another
  request was generating the analysis re-reads the now-fresh cache instead
  of calling Gemini a second time.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Tests | `python -m pytest -q tests/test_dashboard.py` | all pass |
| Full suite | `python -m pytest -q` | all pass |

## Scope

**In scope** (the only file you should modify):
- `app.py` — add a module-level lock and wrap the cache-miss branch of `api_visao_geral_analise`.

**Out of scope**:
- The 6-hour cache TTL logic itself, the prompt text, or the cascade model list — unchanged.
- Any other route.
- A fully correct multi-process lock (e.g. a DB-backed advisory lock) — this app runs as a single Waitress process today per `CLAUDE.md`'s deploy description; an in-process `threading.Lock()` is the right-sized fix. Do not build a distributed-lock mechanism.

## Git workflow

- Branch: `advisor/035-lock-analise-gemini-race`
- Commit message style: `fix(perf): evita chamadas Gemini concorrentes em /api/visao-geral/analise`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add a module-level lock

Near the top of `app.py`, after the `import` block and before the
`app = Flask(__name__)` line (or immediately after it — match wherever
other simple module-level state like the CSRF/cache/limiter objects are
initialized), add:

```python
import threading
_analise_ia_lock = threading.Lock()
```

Add `import threading` to the top-of-file imports if not already present
(check with `grep -n "^import threading" app.py` first).

**Verify**: `grep -n "_analise_ia_lock" app.py` → at least 1 match (the definition).

### Step 2: Wrap the cache-miss branch with the lock and a double-checked cache read

Restructure `api_visao_geral_analise` so that after the first cache check
(step "1. Verifica cache no SQLite" in Current state) returns a miss, the
function acquires `_analise_ia_lock` with a `with` statement, and — while
holding the lock — re-reads the cache once more before calling Gemini. If
the second read now finds a fresh row (because another thread finished
generating it while this thread was waiting on the lock), return that
result instead of calling Gemini again. Only call `gerar_com_cascata` if
the second read still misses. The shape should be:

```python
    # 2. Cache miss — adquire lock para evitar chamadas Gemini concorrentes
    with _analise_ia_lock:
        # Double-check: outra thread pode ter gerado a análise enquanto
        # esperávamos o lock.
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT texto, criado_em FROM analises_ia
                    WHERE cargo = ? AND criado_em >= datetime('now', 'localtime', '-6 hours')
                """, (cargo,))
                row = cursor.fetchone()
                if row:
                    cached_analise = row['texto']
                    cached_data = row['criado_em']
        except Exception as e:
            app.logger.error(f"Erro ao ler cache de analise (double-check): {e}")

        if cached_analise:
            try:
                dt = datetime.datetime.strptime(cached_data, "%Y-%m-%d %H:%M:%S")
                gerado_em = dt.strftime("%d/%m/%Y %H:%M")
            except Exception:
                gerado_em = cached_data
            return jsonify({"analise": cached_analise, "gerado_em": gerado_em})

        dados = get_visao_geral()
        prompt = f"..."  # mesmo prompt de antes
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return jsonify({"analise": "Gemini API Key não configurada.", "gerado_em": ""}), 500

        try:
            from google import genai
            from collectors.gemini_extractor import gerar_com_cascata
            client = genai.Client(api_key=api_key)
            analise_texto, _ = gerar_com_cascata(
                client, prompt,
                modelos=["gemini-2.5-flash", "gemini-2.5-flash-8b", "gemini-2.5-pro"]
            )
            ...  # resto do bloco original (salvar no banco, retornar jsonify) inalterado, apenas mais indentado dentro do `with`
```

Keep every line of logic from the original "2. Se não estiver no cache" and
"3. Salva no banco" blocks exactly as they are — only their indentation
changes (one extra level, to sit inside the `with _analise_ia_lock:`
block), plus the new double-check read and early-return added at the top
of the `with` block. Do not change the prompt text, the model cascade list,
or the error-handling messages.

**Verify**: `python -c "import ast; ast.parse(open('app.py').read())"` → no output (valid syntax).

### Step 3: Run the affected and full test suites

**Verify**: `python -m pytest -q tests/test_dashboard.py` → all pass. Then `python -m pytest -q` → all pass.

## Test plan

Testing true thread concurrency reliably in pytest is fiddly and prone to
flakiness; do not attempt a timing-dependent concurrency test. Instead:

- Rely on the existing `tests/test_dashboard.py` coverage of
  `/api/visao-geral/analise`'s single-request behavior (cache hit, cache
  miss, Gemini failure) to confirm the refactor didn't change the route's
  observable behavior for a single caller — the mocked Gemini extractor
  from `tests/conftest.py` makes single-threaded assertions
  straightforward.
- If you want extra confidence the lock is exercised, add one test that
  monkeypatches `_analise_ia_lock` with a real `threading.Lock()` (it
  already is one), calls the route function directly twice in a row from
  the *same* thread (which will simply succeed sequentially since a
  non-reentrant lock released after the first call allows the second), and
  asserts the mocked `gerar_com_cascata` was called at most once if the
  first call already populated the cache. This is optional — do not spend
  more than one attempt on it.

- Verification: `python -m pytest -q` → all pass, same pass count as baseline (plus 1 if you added the optional test).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `app.py` defines `_analise_ia_lock = threading.Lock()` at module level
- [ ] `api_visao_geral_analise`'s cache-miss branch (the Gemini call + `INSERT OR REPLACE` into `analises_ia`) is wrapped in `with _analise_ia_lock:`
- [ ] The double-checked cache read exists inside the `with` block, before the Gemini call
- [ ] `python -m pytest -q tests/test_dashboard.py` passes
- [ ] `python -m pytest -q` exits 0, same pass count as baseline (modulo known Windows Monte Carlo flakiness)
- [ ] No files outside `app.py` are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `api_visao_geral_analise`'s code doesn't match the "Current state" excerpt (drifted since this plan was written) — check the exact prompt text and model list before reproducing them in your rewrite; do not paraphrase them.
- The route's structure has been refactored into multiple functions/helpers since this plan was written — adapt the lock placement to wrap whatever the "cache miss → call Gemini → write cache" code path has become, but if it's not a clear single contiguous block anymore, stop and report instead of guessing where to split it.
- Adding the lock introduces a deadlock risk you can't rule out (e.g. if `get_db()` or `gerar_com_cascata` is later found to also try to acquire `_analise_ia_lock` reentrantly) — there's no evidence of this today, but if you find such a call path, stop and report rather than switching to `threading.RLock()` silently.

## Maintenance notes

- If this app is ever deployed with multiple processes (e.g. Waitress with
  `--threads` replaced by a multi-worker WSGI server, or scaled
  horizontally on Fly.io), this in-process lock stops being sufficient —
  a future maintainer would need a DB-backed or Redis-backed lock instead.
  Leave a comment near `_analise_ia_lock`'s definition noting this
  single-process assumption.
- This is the same general pattern (cache-miss stampede) that could apply
  to other expensive-to-compute, rarely-changing endpoints in the future —
  no other endpoint currently calls an external LLM API on a cache miss, so
  no other route needs this treatment today.
