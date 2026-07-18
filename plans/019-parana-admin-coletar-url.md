# Plan 019: Corrige `_detectar_coletor` (urlparse não importado) e registra Paraná Pesquisas em `/admin/coletar-url`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 8d3827f..HEAD -- app.py`
> If `app.py` changed since this plan was written, compare the "Current
> state" excerpt below against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.
>
> **Revision note (2026-07-16, 2nd attempt)**: a first executor run on this
> plan stopped after discovering that Step 2's own verification command
> fails — not because of anything wrong with this plan's edits, but because
> of an **unrelated, pre-existing bug** in `_detectar_coletor` itself (see
> "Why this matters" and Step 0 below, both added in this revision). The
> plan's scope now explicitly includes fixing that bug, since without it
> Step 2's registration has no real effect at request time — the two are
> the same user-facing gap ("pasting a known institute's URL routes to the
> wrong collector"), just with two independent causes.

## Status

- **Priority**: P1 (raised from P2 — this blocks domain routing for every
  institute, not just Paraná)
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `8d3827f`, 2026-07-16 (revised same day after 1st
  executor run on top of `d4b62e8`)

## Why this matters

Two independent bugs combine into one user-facing symptom: pasting a known
institute's URL into `/admin/coletar-url` silently routes to the wrong
collector.

1. **`_detectar_coletor` never worked, for any institute.** It calls
   `urlparse(url)` as a bare global name, but `urlparse` is never imported
   at module scope in `app.py` — it's only imported *locally* inside a
   different function, `_url_segura` (`from urllib.parse import urlparse`
   around line 811), which doesn't make it visible to `_detectar_coletor`.
   Every call raises `NameError`, which the function's own
   `try/except Exception` swallows, leaving `host = ''`, so every URL —
   `gazetadopovo.com.br`, `cnnbrasil.com.br`, `datafolha.folha.uol.com.br`,
   all of them — falls through to `_COLETOR_FALLBACK` (`'gazetadopovo'`).
   Verified live: `TESTING=True python -c "from app import
   _detectar_coletor; print(_detectar_coletor('https://cnnbrasil.com.br/algo'))"`
   prints `gazetadopovo`, not `cnn_brasil`. This has presumably been silently
   broken since the function was written — no test exercises
   `_detectar_coletor` directly, only the higher-level contract test that
   doesn't go through URL routing.
2. **`coletar.py` (the automated daily pipeline) already runs
   `ParanaPesquisasCollector` in its rotation, but the admin's manual
   single-URL tool has no entry for it in either lookup dict** — so even
   after fixing bug #1, a `paranapesquisas.com.br` URL would still have
   nowhere correct to route to. `gazetadopovo`'s HTML parser doesn't know
   how to pull the PDF that Paraná Pesquisas actually publishes.

Fixing only #2 (the original scope of this plan) would leave `/admin/
coletar-url` still silently wrong for every other institute — Datafolha,
CNN Brasil, Verita, Quaest — because bug #1 means the correctly-registered
domain never gets matched at request time. Both are small, low-risk fixes;
bundling them here closes the actual gap instead of half of it.

## Current state

- `app.py:765-786` — the two lookup dicts the route uses, and the fallback:

```python
_COLETORES_DISPONIVEIS = {
    'datafolha':      ('collectors.datafolha',        'DatafolhaCollector'),
    'quaest':         ('collectors.quaest',            'QuaestCollector'),
    'gazetadopovo':   ('collectors.gazetadopovo',      'GazetaDoPovoColetor'),
    'cnn_brasil':     ('collectors.cnn_brasil',        'CnnBrasilColetor'),
    'verita':         ('collectors.verita',            'VeritaCollector'),
    'quaest_regional':('collectors.quaest_regional',   'QuaestRegionalColetor'),
}

# Mapeia domínio → coletor. A chave é casada por sufixo no hostname, então
# subdomínios (www., datafolha.folha.uol...) também batem.
_DOMINIO_COLETOR = {
    'gazetadopovo.com.br':          'gazetadopovo',
    'cnnbrasil.com.br':             'cnn_brasil',
    'datafolha.folha.uol.com.br':   'datafolha',
    'quaest.com.br':                'quaest_regional',
    'institutoverita.com.br':       'verita',
}

# Coletor genérico usado quando o domínio não é reconhecido (extrai via Gemini).
_COLETOR_FALLBACK = 'gazetadopovo'
```

- The collector class already exists and is exercised by the automated
  pipeline — `collectors/paraná_pesquisas.py:48`:

```python
class ParanaPesquisasCollector(PlaywrightCollector, BaseCollector):
```

  (note the file name has an accented `á` — `collectors/paraná_pesquisas.py`
  — the import path below must match exactly; do not rename the file as
  part of this plan, that's tracked separately)

- `coletar.py:45-64` already imports and registers this collector in the
  automated rotation — use that import statement as the reference for the
  exact module path to use in `_COLETORES_DISPONIVEIS`.

- The real-world URLs this collector handles look like
  `https://paranapesquisas.com.br/pesquisas/...` (seen in `data/pulso.db`
  `fonte_url` values collected by the automated pipeline) — the domain to
  key on is `paranapesquisas.com.br`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Run tests | `TESTING=True python -m pytest -q` | all pass, exit 0 |
| Run collector contract test | `TESTING=True python -m pytest -q tests/test_collectors.py -k contrato` | passes, now covering Paraná too |

## Scope

**In scope**:
- `app.py` — the missing `urlparse` import (module scope, near the other
  top-level imports), and the `_COLETORES_DISPONIVEIS`/`_DOMINIO_COLETOR`
  dicts (lines 765-782)
- `tests/test_collectors.py` — add explicit domain-detection tests (the
  existing `test_coletores_disponiveis_cumprem_contrato_get_page_parse_release`
  will automatically cover the new entry's `_get_page`/`_parse_release`
  contract once it's added to the dict, but domain routing needs its own
  assertions, including a regression test for bug #1 covering an
  *existing* institute, not just Paraná)

**Out of scope**:
- Renaming `collectors/paraná_pesquisas.py` to remove the accent (tracked
  as a separate, independent finding — do not bundle it here).
- Any change to `ParanaPesquisasCollector` itself, or to `coletar.py`'s
  automated rotation (already correct).
- Adding new domains for other institutes not currently broken.

## Git workflow

- Branch: `advisor/019-parana-admin-coletar-url`
- Commit message style: conventional commits in Portuguese, e.g.
  `fix(admin): registra ParanaPesquisasCollector em coletar-url`
- Do NOT push or open a PR unless explicitly instructed.

## Steps

### Step 0: Fix the missing `urlparse` import in `_detectar_coletor`

Run `grep -n "^from urllib\|^import urllib\|from urllib.parse import" app.py`
to confirm the only `urlparse` import in the file is the local one inside
`_url_segura` (around line 811: `from urllib.parse import urlparse`). Add a
top-level import near the other module-level imports at the top of
`app.py` (alongside the existing `from flask import ...` etc.):

```python
from urllib.parse import urlparse
```

Then, in `_url_segura`, the now-redundant local `from urllib.parse import
urlparse` line can stay (it's harmless — a local import shadowing the
module-level one is not a bug, just slightly redundant) or be removed for
cleanliness; either is fine, don't spend more than a glance deciding.

**Verify**: `TESTING=True python -c "from app import _detectar_coletor; print(_detectar_coletor('https://cnnbrasil.com.br/algo'))"`
→ prints `cnn_brasil` (not `gazetadopovo`). This confirms the pre-existing
bug is fixed for an institute that was already correctly registered in
`_DOMINIO_COLETOR` before this plan touched anything.

### Step 1: Add the collector entry

In `app.py`, add a `'parana'` key to `_COLETORES_DISPONIVEIS` pointing at
the same module path `coletar.py` uses to import `ParanaPesquisasCollector`
(confirm the exact string via `grep -n "ParanaPesquisasCollector"
coletar.py` — it will be something like `'collectors.paraná_pesquisas'`,
matching the accented filename):

```python
_COLETORES_DISPONIVEIS = {
    'datafolha':      ('collectors.datafolha',        'DatafolhaCollector'),
    'quaest':         ('collectors.quaest',            'QuaestCollector'),
    'gazetadopovo':   ('collectors.gazetadopovo',      'GazetaDoPovoColetor'),
    'cnn_brasil':     ('collectors.cnn_brasil',        'CnnBrasilColetor'),
    'verita':         ('collectors.verita',            'VeritaCollector'),
    'quaest_regional':('collectors.quaest_regional',   'QuaestRegionalColetor'),
    'parana':         ('collectors.paraná_pesquisas',  'ParanaPesquisasCollector'),
}
```

**Verify**: `TESTING=True python -c "import importlib; m=importlib.import_module('collectors.paraná_pesquisas'); print(m.ParanaPesquisasCollector)"`
→ prints the class, no `ImportError`/`ModuleNotFoundError`.

### Step 2: Add the domain mapping

Add the domain entry to `_DOMINIO_COLETOR`:

```python
_DOMINIO_COLETOR = {
    'gazetadopovo.com.br':          'gazetadopovo',
    'cnnbrasil.com.br':             'cnn_brasil',
    'datafolha.folha.uol.com.br':   'datafolha',
    'quaest.com.br':                'quaest_regional',
    'institutoverita.com.br':       'verita',
    'paranapesquisas.com.br':       'parana',
}
```

**Verify**:
`TESTING=True python -c "from app import _detectar_coletor; print(_detectar_coletor('https://paranapesquisas.com.br/pesquisas/algum-artigo'))"`
→ prints `parana`.

### Step 3: Add domain-detection tests (covering both bugs)

In `tests/test_collectors.py`, add tests asserting `_detectar_coletor`
works correctly — both for the new Paraná entry and, as a regression guard
for bug #1, for an institute that was already registered before this plan
(so a future accidental removal of the top-level `urlparse` import gets
caught immediately instead of silently reverting to the fallback for
everyone):

```python
def test_detectar_coletor_parana():
    from app import _detectar_coletor
    assert _detectar_coletor('https://paranapesquisas.com.br/pesquisas/x') == 'parana'
    assert _detectar_coletor('https://www.paranapesquisas.com.br/pesquisas/x') == 'parana'

def test_detectar_coletor_institutos_existentes():
    """Regressão do bug de urlparse não importado (NameError engolido pelo
    except Exception, tudo caindo no fallback gazetadopovo)."""
    from app import _detectar_coletor
    assert _detectar_coletor('https://cnnbrasil.com.br/algo') == 'cnn_brasil'
    assert _detectar_coletor('https://datafolha.folha.uol.com.br/algo') == 'datafolha'
    assert _detectar_coletor('https://institutoverita.com.br/algo') == 'verita'
```

**Verify**: `TESTING=True python -m pytest -q tests/test_collectors.py -k detectar_coletor` → 2 passed.

## Test plan

- New test `test_detectar_coletor_parana` in `tests/test_collectors.py`
  (Step 3 above), modeled directly on the existing
  `test_coletores_disponiveis_cumprem_contrato_get_page_parse_release`
  structure (same file, same import style).
- The existing `test_coletores_disponiveis_cumprem_contrato_get_page_parse_release`
  test (`tests/test_collectors.py:28-47`) iterates
  `_COLETORES_DISPONIVEIS.items()` and will automatically pick up the new
  `'parana'` entry once Step 1 lands — no changes needed to that test, but
  confirm it still passes (it instantiates every registered collector, so
  it will catch any import typo from Step 1).
- Verification: `TESTING=True python -m pytest -q` → all pass, including the
  new test.

## Done criteria

- [ ] `TESTING=True python -m pytest -q` exits 0
- [ ] `grep -n "^from urllib.parse import urlparse" app.py` shows the new
      top-level import
- [ ] `TESTING=True python -c "from app import _detectar_coletor; assert _detectar_coletor('https://cnnbrasil.com.br/x') == 'cnn_brasil'"` exits 0 (proves bug #1 is fixed for a pre-existing institute, not just Paraná)
- [ ] `python -c "from app import _COLETORES_DISPONIVEIS; assert 'parana' in _COLETORES_DISPONIVEIS"` exits 0
- [ ] `python -c "from app import _DOMINIO_COLETOR; assert _DOMINIO_COLETOR['paranapesquisas.com.br'] == 'parana'"` exits 0
- [ ] `TESTING=True python -c "from app import _detectar_coletor; assert _detectar_coletor('https://paranapesquisas.com.br/x') == 'parana'"` exits 0
- [ ] New tests `test_detectar_coletor_parana` and
      `test_detectar_coletor_institutos_existentes` exist and pass
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row for 019 updated

## STOP conditions

- `app.py:765-786` doesn't match the excerpt above (dicts have been
  restructured or renamed) — re-read and adapt before proceeding.
- `collectors/paraná_pesquisas.py` fails to import (e.g. dependency issue
  unrelated to this plan) — that's a pre-existing problem in the automated
  pipeline too; stop and report rather than trying to fix the collector
  itself, which is out of scope.
- The class name or module path found in `coletar.py` doesn't match
  `ParanaPesquisasCollector` / `collectors.paraná_pesquisas` as assumed
  here — use whatever `coletar.py` actually imports, and note the
  discrepancy in your report.
- After adding the top-level `urlparse` import, `_detectar_coletor` still
  doesn't correctly route a pre-existing institute's domain (i.e. bug #1
  turns out to have a second, different cause beyond the missing import) —
  stop and report the new finding rather than digging further into
  `_url_segura` or other functions, which are out of scope.

## Maintenance notes

- If `collectors/paraná_pesquisas.py` is ever renamed (tracked separately),
  this plan's Step 1 entry needs its module path updated in the same
  commit as the rename — otherwise `/admin/coletar-url` breaks again.
- This plan does not change what happens when Paraná Pesquisas publishes a
  release that isn't a PDF the collector can parse — that failure mode
  (collector runs, extracts nothing) is unchanged and out of scope here.
