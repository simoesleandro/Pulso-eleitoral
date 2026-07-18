# Plan 029: Divide o god-module `database.py` em `db/` com façade de re-export

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat f53d533..HEAD -- database.py`
> If `database.py` changed since this plan was written, re-run
> `grep -n "^def \|^class " database.py` and compare against this plan's
> function inventory before proceeding; on a mismatch (functions
> added/removed/renamed), treat it as a STOP condition and re-derive the
> module boundaries from the live file rather than this plan's list.
>
> **This is the highest-risk, highest-effort plan in this batch.** It is a
> pure refactor — zero behavior change is the entire point. If you find
> yourself "improving" a function while moving it, stop; that's a
> different, separate change.

## Status

- **Priority**: P4 (lowest priority in this batch — pure maintainability,
  no user-facing or security impact; do this when there's slack, not under
  time pressure)
- **Effort**: L
- **Risk**: MED (mechanical but wide-reaching — 19 files import from
  `database.py` today; a facade done wrong breaks all of them at once)
- **Depends on**: none, but strongly recommend running it in isolation —
  don't combine with any other plan touching `database.py` in the same
  work session, to keep the diff reviewable
- **Category**: tech-debt
- **Planned at**: commit `f53d533`, 2026-07-16

## Why this matters

`database.py` is 1943 lines covering at least 7 distinct responsibilities
(connection/schema management, candidate-name normalization, poll
aggregation & KPIs, Monte Carlo simulation, events CRUD, scheduler
logging, user auth) in one file. This makes the file hard to navigate,
creates merge-conflict hotspots (multiple unrelated plans in this same
audit round — 018 and 023 — both needed to touch code near each other in
`database.py`/`collectors/base.py`), and obscures which functions are
actually related. Splitting it into a `db/` package by responsibility,
behind a `database.py` façade that re-exports everything under its
original name, gets the maintainability benefit with **zero call-site
changes** — all 19 existing `from database import X` / `import database`
usages across `app.py`, `collectors/*.py`, `coletar.py`,
`cronos/tasks/monitor_pesquisas.py`, `scripts/rodar_parana.py`, and 13
test files keep working unmodified.

## Current state

- `database.py` is 1943 lines. Full function/class inventory (via
  `grep -n "^def \|^class " database.py`, re-run this yourself before
  starting — do not trust this list if the drift check flagged changes):

```
get_conn, _popular_candidatos, _invalidar_cache_candidatos,
_carregar_candidatos_cache, get_mapa_apelidos, get_cores_candidatos,
get_candidatos_por_espectro, get_nomes_presidenciais,
get_presidenciais_canonicos, get_candidatos_ignorar, init_db, get_db,
get_comparativo_candidato, limpar_cache_analises, salvar_log_scheduler,
buscar_ultimo_log, get_pesquisas_mais_recentes, detectar_variacoes_bruscas,
listar_eventos, criar_evento, remover_evento, get_media_agregada,
get_house_effects, get_confronto_2turno_real, get_simulacao_segundo_turno,
fator_volatilidade, _redistribuir_indecisos, prob_vitoria_primeiro_turno,
_margens_por_candidato, _pct_mudar_voto_recente, _pct_indecisos_medio,
_simular_cenario, simular_monte_carlo_cenarios,
_contagem_pesquisas_por_candidato, _aviso_amostra_limitada,
simular_prob_vitoria_1_turno, simular_monte_carlo_cargo,
get_simulacao_monte_carlo, get_dados_regionais, _media_intervalo,
get_kpis_avancados, _e_candidato, get_top_candidatos, get_historico_multi,
get_historico_candidato, get_institutos_com_totais, get_visao_geral,
criar_usuario, verificar_usuario, listar_usuarios, remover_usuario,
toggle_usuario
```

- 19 files currently import from `database` (confirmed via
  `grep -rln "from database import\|import database" --include="*.py" .`):
  `app.py`, `coletar.py`, `collectors/base.py`,
  `collectors/gemini_extractor.py`, `cronos/tasks/monitor_pesquisas.py`,
  `scripts/rodar_parana.py`, and 13 files under `tests/`.

- `DB_PATH`, `DATA_DIR`, `TESTING`-driven path selection (`database.py`
  top-of-file, before `get_conn`) are module-level **state**, not
  functions — these must live in exactly one place (the new
  `db/core.py`) and be re-exported by the façade, since tests monkeypatch
  `database.DB_PATH` directly (confirmed in `tests/test_collectors.py`'s
  `test_save_recoleta_atualiza_metadados`, which does
  `database.DB_PATH = str(db_file)` then restores it) — the façade must
  expose the **same mutable module attribute**, not a copy, or that
  monkeypatching pattern silently breaks (mutating `database.DB_PATH`
  would no longer affect what `db.core` actually uses internally unless
  the façade re-exports by reference correctly — see Step 2's specific
  warning about this).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Run tests | `TESTING=True python -m pytest -q` | all pass, exit 0 — run this after EVERY step below, not just at the end |
| Check for stale imports | `grep -rn "from database import\|^import database" --include="*.py" .` | still shows the same 19 files, all importing from the top-level `database` module (the façade), never directly from `db.*` |

## Scope

**In scope**:
- Create a new `db/` package (`db/__init__.py`, `db/core.py`,
  `db/candidatos.py`, `db/pesquisas.py`, `db/eventos.py`,
  `db/monte_carlo.py`, `db/kpis.py`, `db/usuarios.py`, `db/scheduler.py` —
  see Step 1 for the exact function-to-module mapping)
- Rewrite `database.py` itself into a thin façade: `from db.core import
  *`, `from db.candidatos import *`, etc., re-exporting every public name
  the old module exposed, so `import database; database.get_media_agregada(...)`
  and `from database import get_media_agregada` both still work

**Out of scope**:
- Changing any function's logic, signature, return shape, or SQL — this
  is a pure move. If you notice a bug while moving a function (there are
  several already known, tracked as separate plans/backlog items), do NOT
  fix it here — note it in your report instead.
- Changing any of the 19 call sites — they must not need to change at all.
  If you find yourself wanting to update an import in `app.py` or a test
  file to import from `db.kpis` directly instead of `database`, that's
  out of scope for this plan (a possible *future* cleanup once the façade
  has proven stable, not part of this move).
- Splitting `tests/` — test files stay as they are, importing from
  `database` same as always.

## Git workflow

- Branch: `advisor/029-split-god-module-database`
- Commit style: conventional commits in Portuguese. Recommend **one
  commit per module extracted** (not one giant commit) so the diff is
  reviewable step by step — e.g. `refactor(db): extrai db/usuarios.py de database.py`,
  then `refactor(db): extrai db/eventos.py de database.py`, etc., ending
  with a final commit that reduces `database.py` to the façade.
- Do NOT push or open a PR unless explicitly instructed.

## Steps

Work through the modules in this order — **smallest and most isolated
first**, so you build confidence in the facade pattern before touching the
larger, more interconnected modules. Run the full test suite after every
single step, not just at the end — this is the only way to catch a broken
import immediately, while you still remember what you just moved.

### Step 0: Create the package skeleton

```
db/__init__.py       # empty, just makes `db` a package
db/core.py           # get_conn, get_db, init_db, DB_PATH/DATA_DIR module state, limpar_cache_analises, salvar_log_scheduler, buscar_ultimo_log
db/candidatos.py     # _popular_candidatos, _invalidar_cache_candidatos, _carregar_candidatos_cache, get_mapa_apelidos, get_cores_candidatos, get_candidatos_por_espectro, get_nomes_presidenciais, get_presidenciais_canonicos, get_candidatos_ignorar, _e_candidato
db/eventos.py        # listar_eventos, criar_evento, remover_evento
db/usuarios.py       # criar_usuario, verificar_usuario, listar_usuarios, remover_usuario, toggle_usuario
db/pesquisas.py      # get_comparativo_candidato, get_pesquisas_mais_recentes, detectar_variacoes_bruscas, get_media_agregada, get_house_effects, get_historico_multi, get_historico_candidato, get_top_candidatos, get_institutos_com_totais, get_dados_regionais, _media_intervalo
db/monte_carlo.py    # fator_volatilidade, _redistribuir_indecisos, prob_vitoria_primeiro_turno, _margens_por_candidato, _pct_mudar_voto_recente, _pct_indecisos_medio, _simular_cenario, simular_monte_carlo_cenarios, _contagem_pesquisas_por_candidato, _aviso_amostra_limitada, simular_prob_vitoria_1_turno, simular_monte_carlo_cargo, get_simulacao_monte_carlo, get_confronto_2turno_real, get_simulacao_segundo_turno
db/kpis.py            # get_kpis_avancados, get_visao_geral
```

This grouping follows the domain sections already implied by the
comments/ordering in the current `database.py` (candidatos normalization
is explicitly called out in `CLAUDE.md` as its own concern; Monte
Carlo/2nd-round simulation is already a dense, self-referential cluster of
`_`-prefixed helpers feeding a few public functions; users/auth is fully
independent of everything else). If, once you're actually looking at the
real function bodies, a function's true dependencies point to a different
module than listed here, move it to the module it actually belongs with
and note the deviation in your report — this list is a starting hypothesis
from reading function names, not a verified dependency graph.

**Verify**: `find db/ -name "*.py"` (or `dir` on Windows) shows the 8
skeleton files (all empty except `__init__.py` which stays empty
permanently).

### Step 1: Extract `db/usuarios.py` first (most isolated)

This module has no dependencies on any other database.py function beyond
`get_db()`/`get_conn()` — the safest possible starting point. Move
`criar_usuario`, `verificar_usuario`, `listar_usuarios`, `remover_usuario`,
`toggle_usuario` (read each function's current body directly from
`database.py` — do not guess at their contents) into `db/usuarios.py`,
importing `get_db`/`get_conn` from `db.core` (which doesn't exist as real
code yet — see Step 2 for why `db/core.py` must be extracted *before* this
step actually works end-to-end; do Step 2 first if you hit a circular
problem, adjusting this plan's stated order doesn't need permission, use
judgment on sequencing as long as the end state matches Step 8's target).

In `database.py`, replace the moved function bodies with:
```python
from db.usuarios import criar_usuario, verificar_usuario, listar_usuarios, remover_usuario, toggle_usuario
```//
(placed near the top of the file, or wherever the façade imports are
being collected — see Step 8 for the final shape; during the incremental
steps it's fine for `database.py` to be a hybrid of real code and façade
imports).

**Verify**: `TESTING=True python -m pytest -q tests/test_usuarios.py` →
all pass. Then `TESTING=True python -m pytest -q` (full suite) → all pass.

### Step 2: Extract `db/core.py`

Move `get_conn`, `get_db`, `init_db`, `limpar_cache_analises`,
`salvar_log_scheduler`, `buscar_ultimo_log`, and the module-level
`DB_PATH`/`DATA_DIR`/`TESTING`-driven path-selection logic (whatever
precedes `get_conn` at the top of the current file) into `db/core.py`.

**Critical**: `database.py`'s façade must re-export `DB_PATH` such that
`database.DB_PATH = <new value>` (the monkeypatch pattern used in
`tests/test_collectors.py`) actually changes what `db.core`'s functions
read. A plain `from db.core import DB_PATH` in `database.py` creates a
**second, independent binding** — reassigning `database.DB_PATH` would
NOT change `db.core.DB_PATH`, silently breaking that test's monkeypatch
pattern (the test would appear to pass because it resets the value
correctly, but the actual `save()`/`init_db()` calls in between would
still be hitting the *original* `DB_PATH`, defeating the isolation the
test relies on — this is the single most dangerous silent-breakage risk
in this entire plan). To avoid this, either:
(a) keep `DB_PATH` as a genuine module-level variable in `database.py`
    itself (not moved into `db/core.py`), and have `db/core.py`'s
    functions accept it as a parameter or read it via
    `import database; database.DB_PATH` (a live attribute lookup, not a
    one-time import-time snapshot), or
(b) have `db/core.py` expose a mutable holder object/function
    (`get_db_path()`) instead of a bare module attribute, and update
    `database.py`'s façade to proxy reads/writes through it.
Pick whichever is simpler once you're looking at the real code — the
constraint is: **mutating `database.DB_PATH` after this refactor must
still change what every DB-touching function actually connects to,
exactly as it does today.** Write a throwaway manual check before moving
on (see Verify below) — don't just trust the test suite passing, since
the existing test might not exercise the exact failure mode described
here as rigorously as you'd want.

**Verify**: `TESTING=True python -c "
import database
old = database.DB_PATH
database.DB_PATH = '/tmp/test_probe.db'
import db.core
assert db.core.DB_PATH == '/tmp/test_probe.db' or True  # adapt this assertion to whichever approach (a)/(b) you took — the real check is functional, see next line
database.DB_PATH = old
print('DB_PATH monkeypatch still propagates correctly')
"` — adapt this probe script to actually prove the propagation works for
whichever mechanism you chose; don't skip this check. Then
`TESTING=True python -m pytest -q tests/test_collectors.py -k recoleta_atualiza_metadados` →
must still pass (this is the test that depends on this exact behavior).
Then full suite.

### Step 3: Extract `db/candidatos.py`

Move the candidate-normalization cluster (`_popular_candidatos`,
`_invalidar_cache_candidatos`, `_carregar_candidatos_cache`,
`get_mapa_apelidos`, `get_cores_candidatos`, `get_candidatos_por_espectro`,
`get_nomes_presidenciais`, `get_presidenciais_canonicos`,
`get_candidatos_ignorar`, `_e_candidato`). Per `CLAUDE.md`, this cache "a
falha transitória na carga não é memoizada" and `apply-db` invalidates it
— re-read `app.py`'s `/admin/apply-db` route to confirm exactly how it
calls the invalidation function today, and make sure the façade re-export
keeps that call site working unchanged.

**Verify**: `TESTING=True python -m pytest -q tests/test_migrate_candidatos_status.py`
(or wherever candidatos-cache tests live — grep for
`_carregar_candidatos_cache\|_invalidar_cache_candidatos` in `tests/` to
find them) → all pass. Then `TESTING=True python -m pytest -q -k apply_db`
→ all pass (confirms the cache-invalidation call site in `/admin/apply-db`
still works). Then full suite.

### Step 4: Extract `db/eventos.py`

Move `listar_eventos`, `criar_evento`, `remover_evento`.

**Verify**: `TESTING=True python -m pytest -q -k evento` → all pass. Full
suite.

### Step 5: Extract `db/pesquisas.py`

Move `get_comparativo_candidato`, `get_pesquisas_mais_recentes`,
`detectar_variacoes_bruscas`, `get_media_agregada`, `get_house_effects`,
`get_historico_multi`, `get_historico_candidato`, `get_top_candidatos`,
`get_institutos_com_totais`, `get_dados_regionais`, `_media_intervalo`.
This is the largest and most test-critical module — `get_media_agregada`
has a fixed numeric contract in `tests/test_agregacao.py` per `CLAUDE.md`
("O contrato numérico dessa lógica está fixado... qualquer mudança na
fórmula exige atualizar os dois"). You are NOT changing the formula, only
its file location — but run this module's tests with extra care.

**Verify**: `TESTING=True python -m pytest -q tests/test_agregacao.py
tests/test_variacoes.py` → all pass, identical results to before the
move (if you have the pre-move test output saved, diff it; if not, at
minimum confirm 0 failures). Full suite.

### Step 6: Extract `db/kpis.py`

Move `get_kpis_avancados`, `get_visao_geral` — both depend on
`get_media_agregada` (now in `db/pesquisas.py`) and candidate helpers (now
in `db/candidatos.py`); import from those modules rather than duplicating
logic.

**Verify**: `TESTING=True python -m pytest -q -k kpis_avancados` → all
pass. Full suite.

### Step 7: Extract `db/monte_carlo.py`

Move the Monte Carlo/2nd-round cluster (`fator_volatilidade`,
`_redistribuir_indecisos`, `prob_vitoria_primeiro_turno`,
`_margens_por_candidato`, `_pct_mudar_voto_recente`,
`_pct_indecisos_medio`, `_simular_cenario`, `simular_monte_carlo_cenarios`,
`_contagem_pesquisas_por_candidato`, `_aviso_amostra_limitada`,
`simular_prob_vitoria_1_turno`, `simular_monte_carlo_cargo`,
`get_simulacao_monte_carlo`, `get_confronto_2turno_real`,
`get_simulacao_segundo_turno`). This is the second-largest and most
internally-interdependent cluster — move it as one atomic step (don't
split it further) since its `_`-prefixed helpers call each other
extensively.

**Verify**: `TESTING=True python -m pytest -q tests/test_monte_carlo.py
tests/test_confronto_2turno.py` → all pass. Full suite.

### Step 8: Reduce `database.py` to a pure façade

By this point every function has moved to a `db/*` module and
`database.py` should already be mostly façade imports accumulated across
Steps 1–7. Do a final pass: confirm `database.py` contains **no function
bodies at all** anymore (only imports + whatever module-level state Step 2
required to stay in `database.py` per its resolution of the `DB_PATH`
propagation problem), and that every name the old file used to export is
still importable from `database` with the exact same name.

```python
# database.py (final shape, illustrative — adapt based on Step 2's resolution)
from db.core import get_conn, get_db, init_db, limpar_cache_analises, salvar_log_scheduler, buscar_ultimo_log  # + DB_PATH/DATA_DIR per Step 2
from db.candidatos import (
    get_mapa_apelidos, get_cores_candidatos, get_candidatos_por_espectro,
    get_nomes_presidenciais, get_presidenciais_canonicos, get_candidatos_ignorar,
)
from db.eventos import listar_eventos, criar_evento, remover_evento
from db.usuarios import criar_usuario, verificar_usuario, listar_usuarios, remover_usuario, toggle_usuario
from db.pesquisas import (
    get_comparativo_candidato, get_pesquisas_mais_recentes, detectar_variacoes_bruscas,
    get_media_agregada, get_house_effects, get_historico_multi, get_historico_candidato,
    get_top_candidatos, get_institutos_com_totais, get_dados_regionais,
)
from db.kpis import get_kpis_avancados, get_visao_geral
from db.monte_carlo import (
    simular_monte_carlo_cenarios, simular_prob_vitoria_1_turno, simular_monte_carlo_cargo,
    get_simulacao_monte_carlo, get_confronto_2turno_real, get_simulacao_segundo_turno,
)
```

(Underscore-prefixed "private" helpers like `_carregar_candidatos_cache`
are used directly by tests in some cases — `grep -rn
"database\._[a-z]" tests/` to find every such usage and make sure the
façade re-exports those too, even though they're conventionally private;
breaking a test's ability to reach `database._carregar_candidatos_cache`
would be an unnecessary regression.)

**Verify**: `TESTING=True python -m pytest -q` (full suite) → all pass.
`python -c "import database; print(len([n for n in dir(database) if not n.startswith('__')]))"`
→ compare the count against the same command run on the pre-refactor
`database.py` (check out the old version in a scratch location, or just
compare against the function-inventory list in "Current state" above —
same names should all resolve).

## Test plan

- No new tests are needed — this plan's entire test plan is "the existing
  1943-line-module's existing test suite must pass identically after
  every single step," since this is a pure refactor with an explicit
  zero-behavior-change goal.
- The one exception: Step 2's `DB_PATH` propagation check is a new,
  temporary manual verification (not meant to become a permanent test
  file) — but if you find a clean way to turn it into a permanent regression
  test protecting the façade's `DB_PATH` proxying behavior, that's a
  reasonable, in-scope addition (add it to `tests/test_database.py`).

## Done criteria

- [ ] `TESTING=True python -m pytest -q` exits 0 after the final step (and
      after every intermediate step, per your own incremental commits)
- [ ] `database.py` contains no function/class bodies — pure imports
      (verify by eye, or `grep -c "^def \|^class " database.py` → `0`)
- [ ] Every name in the original function inventory (see "Current state")
      is still importable from `database` (`python -c "import database;
      [getattr(database, n) for n in [...]]"` with the full list — no
      `AttributeError`)
- [ ] `grep -rn "from db\." app.py collectors/ coletar.py cronos/ scripts/ tests/` returns no matches — none of the 19 original call sites were changed to import from `db.*` directly; they all still go through `database`
- [ ] The `DB_PATH` monkeypatch propagation check from Step 2 passes
- [ ] `plans/README.md` status row for 029 updated

## STOP conditions

- The live `database.py` function inventory doesn't match the list in
  "Current state" (drift) — re-derive the module boundaries from what's
  actually there instead of blindly following this plan's grouping.
- Any full-suite run fails after a step — do not proceed to the next
  module extraction with a red suite; fix the current step first (likely
  a missed import or the `DB_PATH` propagation issue from Step 2).
- You discover a genuine circular import between two proposed `db/*`
  modules (e.g. `db.kpis` needs something from `db.monte_carlo` which
  needs something from `db.kpis`) that can't be resolved by adjusting
  which module a function lives in — stop and report the specific cycle
  rather than working around it with a local/deferred import hack.
- You find yourself wanting to fix a bug in a function while moving it —
  don't. Note the bug in your report; this plan is a pure move.

## Maintenance notes

- Once this façade has been stable for a while, a natural follow-up (NOT
  part of this plan) is migrating the 19 call sites to import from
  `db.pesquisas`/`db.kpis`/etc. directly instead of the `database` façade
  — that's a bigger, separate, purely-optional cleanup that removes the
  façade layer entirely. Don't do it as part of this plan; the façade's
  entire value here is *not* touching those 19 files.
- Any new database function added after this split should go directly
  into the appropriate `db/*` module, not back into `database.py` — the
  façade should only ever gain new re-export lines, never new logic.
