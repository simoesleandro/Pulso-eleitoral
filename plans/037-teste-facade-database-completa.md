# Plan 037: Teste de fumaça garantindo que a façade `database.py` cobre tudo em `db/*`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 0992d23..HEAD -- database.py db/`
> If `database.py` or anything under `db/` changed since this plan was
> written, compare the "Current state" excerpt below against the live code
> before proceeding; on a mismatch, treat it as a STOP condition (a
> genuinely new public function needing a facade export is expected drift —
> add it to the exports list rather than treating it as a blocker).

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `0992d23`, 2026-07-17

## Why this matters

Plan 029 split the former `database.py` god-module into 7 submodules under
`db/` (`core.py`, `candidatos.py`, `eventos.py`, `pesquisas.py`, `kpis.py`,
`monte_carlo.py`, `usuarios.py`). `database.py` is now a hand-maintained
façade that re-exports ~35 names via explicit `from db.X import a, b, c`
statements, so the 19 existing call sites (`app.py`, `coletar.py`,
`collectors/*`, `cronos/tasks/monitor_pesquisas.py`,
`scripts/rodar_parana.py`, and 13 test files) that used to `import database`
keep working unchanged. This audit manually cross-checked every current
call site against every current `db/*` export and confirmed the façade is
complete today — but that completeness is **entirely incidental**: nothing
in the test suite actually asserts it. A future change that adds a new
public function to a `db/*.py` module (or renames one) without remembering
to update the corresponding `from db.X import ...` line in `database.py`
would silently make that function unreachable via `import database` — and
nothing would fail until some code path tried to use it, likely in
production. A single smoke test that walks each `db/*` module's public
names and asserts each is reachable as `database.<name>` turns that future
mistake into an immediate, obvious CI failure.

## Current state

- `database.py:23-72` — the façade's full export list (read the live file
  for exact current line numbers, this is the shape as of this plan's
  writing):

```python
from db.core import get_conn, get_db, init_db, limpar_cache_analises, salvar_log_scheduler, buscar_ultimo_log

_cache_candidatos = None

from db.candidatos import (
    _popular_candidatos, _invalidar_cache_candidatos, _carregar_candidatos_cache,
    get_mapa_apelidos, get_cores_candidatos, get_candidatos_por_espectro,
    get_nomes_presidenciais, get_presidenciais_canonicos, get_candidatos_ignorar,
)

from db.eventos import listar_eventos, criar_evento, remover_evento

from db.pesquisas import (
    get_comparativo_candidato, get_pesquisas_mais_recentes, detectar_variacoes_bruscas,
    get_media_agregada, get_house_effects, get_historico_multi, get_historico_candidato,
    get_top_candidatos, get_institutos_com_totais, get_dados_regionais, _e_candidato,
)

from db.kpis import get_kpis_avancados, get_visao_geral, _media_intervalo

from db.monte_carlo import (
    fator_volatilidade, _redistribuir_indecisos, prob_vitoria_primeiro_turno,
    _margens_por_candidato, _pct_mudar_voto_recente, _pct_indecisos_medio,
    _simular_cenario, simular_monte_carlo_cenarios, _contagem_pesquisas_por_candidato,
    _aviso_amostra_limitada, simular_prob_vitoria_1_turno,
    simular_monte_carlo_cargo, get_simulacao_monte_carlo,
    get_confronto_2turno_real, get_simulacao_segundo_turno,
)

from db.usuarios import criar_usuario, verificar_usuario, listar_usuarios, remover_usuario, toggle_usuario
```

- The mapping this test needs to encode: `database.py` imports from 7
  specific submodules (`db.core`, `db.candidatos`, `db.eventos`,
  `db.pesquisas`, `db.kpis`, `db.monte_carlo`, `db.usuarios`) — **not**
  every name defined in every `db/*.py` file needs to be exported (some are
  genuinely module-private helpers only used within their own module, e.g.
  functions never imported anywhere else). The test's job is not "assert
  100% of `db/*` is re-exported" (that would be too strict and would break
  on legitimate internal refactoring) — it's "assert every name the façade
  currently claims to export actually resolves," **plus** a looser check
  that would have caught the actual historical incidents this codebase has
  had: names that exist in a `db/*` module, are used by at least one
  non-`db/`, non-`database.py` caller via `from database import X`, but are
  missing from the façade. See Step 2 for the precise, achievable version
  of this check.

- Existing test file to extend: `tests/test_database.py` (already imports
  `from database import get_conn, init_db, DB_PATH` and tests
  `db/core.py`/façade behavior — this is the natural home for a
  façade-completeness test, not a new file).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Tests | `python -m pytest -q tests/test_database.py` | all pass |
| Full suite | `python -m pytest -q` | all pass |

## Scope

**In scope** (the only file you should modify):
- `tests/test_database.py` — add one new test function.

**Out of scope**:
- `database.py` itself — do not add or remove any export as part of this plan; the façade is confirmed complete today, this plan only adds the guard-rail test.
- Any `db/*.py` file.
- A fully general "every db/* public name is exported" test — as explained in Current State, that's the wrong bar (it would flag legitimate internal-only helpers). Build the narrower, precise check described in Step 2.

## Git workflow

- Branch: `advisor/037-teste-facade-database-completa`
- Commit message style: `test(db): garante que database.py re-exporta o que db/* expõe hoje`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Write a test that pins today's known-good export list

Add a test to `tests/test_database.py` that hardcodes the current list of
names each `db/*` submodule is expected to export via the façade (copy the
exact list from "Current state" above, grouped by submodule) and asserts
every one of them is an attribute of the `database` module:

```python
def test_facade_reexporta_todo_o_db_conhecido():
    """Regressão: database.py é uma façade mantida à mão sobre db/*.py
    (plano 029). Se um nome sair da lista de re-exports sem que ninguém
    perceba, ele fica inacessível via `import database` em silêncio — só
    quebra quando algum caller tentar usá-lo em produção. Este teste fixa
    a lista conhecida-boa de hoje; ao adicionar uma função nova e pública
    num submódulo de db/*, adicione o nome aqui também (e no import
    correspondente em database.py)."""
    import database

    esperado = {
        # db/core.py
        "get_conn", "get_db", "init_db", "limpar_cache_analises",
        "salvar_log_scheduler", "buscar_ultimo_log",
        # db/candidatos.py
        "_popular_candidatos", "_invalidar_cache_candidatos",
        "_carregar_candidatos_cache", "get_mapa_apelidos",
        "get_cores_candidatos", "get_candidatos_por_espectro",
        "get_nomes_presidenciais", "get_presidenciais_canonicos",
        "get_candidatos_ignorar",
        # db/eventos.py
        "listar_eventos", "criar_evento", "remover_evento",
        # db/pesquisas.py
        "get_comparativo_candidato", "get_pesquisas_mais_recentes",
        "detectar_variacoes_bruscas", "get_media_agregada",
        "get_house_effects", "get_historico_multi", "get_historico_candidato",
        "get_top_candidatos", "get_institutos_com_totais",
        "get_dados_regionais", "_e_candidato",
        # db/kpis.py
        "get_kpis_avancados", "get_visao_geral", "_media_intervalo",
        # db/monte_carlo.py
        "fator_volatilidade", "_redistribuir_indecisos",
        "prob_vitoria_primeiro_turno", "_margens_por_candidato",
        "_pct_mudar_voto_recente", "_pct_indecisos_medio",
        "_simular_cenario", "simular_monte_carlo_cenarios",
        "_contagem_pesquisas_por_candidato", "_aviso_amostra_limitada",
        "simular_prob_vitoria_1_turno", "simular_monte_carlo_cargo",
        "get_simulacao_monte_carlo", "get_confronto_2turno_real",
        "get_simulacao_segundo_turno",
        # db/usuarios.py
        "criar_usuario", "verificar_usuario", "listar_usuarios",
        "remover_usuario", "toggle_usuario",
    }

    faltando = [nome for nome in esperado if not hasattr(database, nome)]
    assert not faltando, f"database.py não re-exporta: {faltando}"
```

If plan 033 (dead code removal in `db/pesquisas.py`) has already landed
when you write this test, the list above is unaffected — `_media_intervalo`
stays listed under `db/kpis.py` only, which is already correct in the list
above.

**Verify**: `python -m pytest -q tests/test_database.py -k test_facade_reexporta_todo_o_db_conhecido` → 1 passed.

### Step 2: Write a second test catching the actual historical failure mode

The more valuable check is forward-looking: catch the case where a *caller*
(any file outside `db/` and `database.py`) does `from database import X` for
some `X` that doesn't actually exist on the `database` module. This is
exactly the class of bug plan 019 found and fixed for a different reason
(an unrelated `NameError` swallowed by a broad `except Exception`) — a
missing attribute on `database` should fail loudly. Add:

```python
def test_todos_os_imports_de_database_resolvem():
    """Varre app.py, coletar.py, collectors/*.py, cronos/**/*.py,
    scripts/*.py e tests/*.py por `from database import X, Y` e confirma
    que cada nome importado existe de fato em `database`. Import-time
    já garante isso indiretamente (um ImportError pararia a suíte), mas
    este teste torna a garantia explícita e documenta a superfície real
    da façade."""
    import ast
    import glob
    import database

    arquivos = (
        glob.glob("app.py") + glob.glob("coletar.py") +
        glob.glob("collectors/*.py") + glob.glob("cronos/**/*.py", recursive=True) +
        glob.glob("scripts/*.py") + glob.glob("tests/*.py")
    )

    problemas = []
    for caminho in arquivos:
        with open(caminho, "r", encoding="utf-8") as f:
            arvore = ast.parse(f.read(), filename=caminho)
        for node in ast.walk(arvore):
            if isinstance(node, ast.ImportFrom) and node.module == "database":
                for alias in node.names:
                    if not hasattr(database, alias.name):
                        problemas.append(f"{caminho}: from database import {alias.name}")

    assert not problemas, "Imports de `database` que não resolvem:\n" + "\n".join(problemas)
```

**Verify**: `python -m pytest -q tests/test_database.py -k test_todos_os_imports_de_database_resolvem` → 1 passed.

### Step 3: Run the full test suite

**Verify**: `python -m pytest -q` → all pass, baseline count + 2.

## Test plan

- New tests: `tests/test_database.py::test_facade_reexporta_todo_o_db_conhecido` and `tests/test_database.py::test_todos_os_imports_de_database_resolvem` (both described fully in Steps 1–2 above).
- Structural pattern followed: existing tests in `tests/test_database.py` already import `database` directly and assert on its attributes/behavior (e.g. `test_get_conn`), so these fit the file's existing style.
- Verification: `python -m pytest -q` → all pass, baseline + 2 new passing tests.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `tests/test_database.py::test_facade_reexporta_todo_o_db_conhecido` exists and passes
- [ ] `tests/test_database.py::test_todos_os_imports_de_database_resolvem` exists and passes
- [ ] `python -m pytest -q` exits 0, baseline pass count + 2 (modulo known Windows Monte Carlo flakiness)
- [ ] No files outside `tests/test_database.py` are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The hardcoded "esperado" set in Step 1 doesn't match what `database.py` currently imports (the façade has drifted since this plan was written) — update the set to match the live `database.py` file's actual import list rather than the list in this plan, since the live code is ground truth; note the discrepancy when you report back.
- Step 2's test finds a real problem (a caller importing a name from `database` that doesn't exist) — this would be a genuine pre-existing bug this test surfaced; do NOT silently fix it by adding the missing export to `database.py` as part of this plan (that's a different, riskier change requiring its own review) — report it and let the operator decide whether to fold the fix into this plan or file a separate one.
- `ast.walk`-based static analysis in Step 2 produces false positives from dynamic imports (e.g. `importlib.import_module`) that this AST-based check can't see — if you find any, note them in the test's docstring as a known limitation rather than trying to handle every possible dynamic-import pattern.

## Maintenance notes

- When a new function is added to any `db/*.py` module and needs to be
  reachable via `import database`, two things must happen together: add
  the `from db.X import new_name` line to `database.py`, and add
  `"new_name"` to the `esperado` set in
  `test_facade_reexporta_todo_o_db_conhecido`. This test's failure message
  will name exactly which name is missing when someone forgets the first
  step; the second step (updating the test) is on the person making the
  future change, same as any other test that pins a known-good state.
- This test intentionally does not use dynamic introspection (e.g.
  `inspect.getmembers` diffing against every `db/*` module) to determine
  the "expected" set automatically, because that would flag legitimate
  module-private helpers as missing exports. If a future maintainer wants
  that stricter check, it needs an explicit allowlist of intentionally-
  private names per module — out of scope here.
