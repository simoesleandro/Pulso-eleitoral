# Plan 032: Fecha a conexão sqlite3 vazada em `_salvar_regional` sob exceção

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 0992d23..HEAD -- collectors/base.py`
> If `collectors/base.py` changed since this plan was written, compare the
> "Current state" excerpt below against the live code before proceeding; on
> a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `0992d23`, 2026-07-17

## Why this matters

`BaseCollector._salvar_regional` (`collectors/base.py`) opens a raw
`sqlite3.connect()` outside any `try/finally`. `conn.close()` is only
reached on the success path, after `conn.commit()`. If any exception occurs
mid-loop — a constraint violation, a disk error, or lock contention from a
concurrent writer (see plan 036, the related WAL/busy_timeout finding) —
the `except Exception` block logs and returns without ever closing `conn`.
This method is called daily by `GazetaDoPovoColetor` and `CnnBrasilColetor`
via the scheduler (`app.py`'s `BackgroundScheduler` job), so a leaked
connection accumulates as an open OS-level handle in the long-running
scheduler process every time a regional save fails partway through — a slow
resource leak that compounds over the life of the process.

## Current state

- `collectors/base.py:395-423` — the full method as it exists today:

```python
    def _salvar_regional(self, dados: list[dict], uf: str) -> None:
        """Filtra para candidatos presidenciais e persiste em pesquisas_regionais
        (uma linha por candidato/UF). Compartilhado pelos coletores que recortam
        intenção presidencial por estado (GazetaDoPovo, CNN Brasil). O filtro
        impede que matérias de eleição estadual (governador) contaminem a visão
        presidencial por estado."""
        dados = self._filtrar_presidenciais(dados)
        if not dados:
            return
        try:
            conn = sqlite3.connect(self.db_path)
            inseridos = 0
            for d in dados:
                conn.execute(
                    "INSERT OR REPLACE INTO pesquisas_regionais "
                    "(instituto_id, data_pesquisa, uf, candidato, percentual) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (d.get('instituto_id', self.instituto_id),
                     d.get('data_pesquisa', ''),
                     uf,
                     d['candidato'],
                     d['percentual'])
                )
                inseridos += 1
            conn.commit()
            conn.close()
            self.logger.info("[%s] Regional %s: %d intenções salvas", self.name, uf, inseridos)
        except Exception as e:
            self.logger.error("[%s] Erro ao salvar regional %s: %s", self.name, uf, e)
```

- The `try/finally` pattern already used elsewhere in this same file for
  the analogous risk — `db/core.py`'s `salvar_log_scheduler` and
  `buscar_ultimo_log` both open a connection, wrap the DB work in
  `try/except`, and close it in a `finally`:

```python
def salvar_log_scheduler(resultado: list) -> None:
    conn = get_conn()
    try:
        ...
        conn.commit()
    except Exception as e:
        raise e
    finally:
        conn.close()
```

  Match this shape: move `conn = sqlite3.connect(self.db_path)` before the
  `try`, and add a `finally: conn.close()` so the connection is always
  closed regardless of success or failure. Keep the existing
  `except Exception as e:` logging behavior unchanged (this repo's
  established convention for collector-level errors is to log and continue,
  not raise — see `CLAUDE.md`, "Coleta" section: "uma falha num release não
  derruba as demais do mesmo lote").

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Tests | `python -m pytest -q tests/test_collectors.py tests/test_gazetadopovo.py tests/test_cnn_brasil.py` | all pass |
| Full suite | `python -m pytest -q` | all pass |

## Scope

**In scope** (the only files you should modify):
- `collectors/base.py` — `_salvar_regional` method only.
- `tests/test_collectors.py` — add one new regression test (see Test plan).

**Out of scope**:
- `collectors/quaest_regional.py`'s own `_salvar_regionais` (note the
  slightly different name, plural) — it was already consolidated to call
  the shared `BaseCollector._salvar_regional` per plan 013's cleanup; only
  touch it if `grep -n "_salvar_regional" collectors/quaest_regional.py`
  shows it still has its own duplicate raw-connection implementation. If it
  does, STOP and report — that's outside this plan's scope, but worth
  flagging since it would have the identical leak.
- Any other method in `collectors/base.py`.
- The WAL/busy_timeout change (plan 036) — do not combine the two changes
  in one commit even though they touch related risk; keep this plan's diff
  minimal and reviewable on its own.

## Git workflow

- Branch: `advisor/032-fix-conn-leak-salvar-regional`
- Commit message style: `fix(coleta): fecha conexão sqlite3 vazada em _salvar_regional sob exceção`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Wrap the connection lifecycle in try/finally

Rewrite `_salvar_regional` so `conn = sqlite3.connect(self.db_path)` happens
before the `try` block, and add a `finally: conn.close()` clause. Remove the
now-redundant `conn.close()` call from inside the `try` block's success
path (the `finally` covers it). The `conn.commit()` and the
`self.logger.info(...)` success log stay inside `try`, before the implicit
fall-through to `finally`. The result should look like:

```python
    def _salvar_regional(self, dados: list[dict], uf: str) -> None:
        """..."""
        dados = self._filtrar_presidenciais(dados)
        if not dados:
            return
        conn = sqlite3.connect(self.db_path)
        try:
            inseridos = 0
            for d in dados:
                conn.execute(
                    "INSERT OR REPLACE INTO pesquisas_regionais "
                    "(instituto_id, data_pesquisa, uf, candidato, percentual) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (d.get('instituto_id', self.instituto_id),
                     d.get('data_pesquisa', ''),
                     uf,
                     d['candidato'],
                     d['percentual'])
                )
                inseridos += 1
            conn.commit()
            self.logger.info("[%s] Regional %s: %d intenções salvas", self.name, uf, inseridos)
        except Exception as e:
            self.logger.error("[%s] Erro ao salvar regional %s: %s", self.name, uf, e)
        finally:
            conn.close()
```

**Verify**: `python -c "import ast; ast.parse(open('collectors/base.py').read())"` → no output (valid syntax).

### Step 2: Add a regression test proving the connection closes even on failure

In `tests/test_collectors.py`, add a test that forces an exception mid-loop
(e.g. missing `'candidato'` key in one of the dicts, which raises `KeyError`
inside the loop before `conn.commit()`) and then verifies the connection is
closed — e.g. by opening a second, exclusive connection to the same
`tmp_path` DB file immediately afterward and confirming it doesn't hang or
raise `database is locked` (Windows/SQLite will raise or block if the first
handle is still open with a lock). Model the test structure after
`test_save_empty_list_does_not_error` (`tests/test_collectors.py:82`) for
the `tmp_path` + schema-init pattern:

```python
def test_salvar_regional_fecha_conexao_mesmo_com_erro(tmp_path):
    """Regressão: _salvar_regional vazava a conexão sqlite3 quando uma
    exceção ocorria antes do conn.close() no caminho de sucesso."""
    db_file = tmp_path / "test_regional_leak.db"
    conn = sqlite3.connect(db_file)
    schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.close()

    from collectors.gazetadopovo import GazetaDoPovoColetor
    collector = GazetaDoPovoColetor(str(db_file))
    # dict sem a chave 'candidato' força KeyError dentro do loop, antes do commit
    dados_invalidos = [{"instituto_id": 1, "data_pesquisa": "2026-01-01", "percentual": 40.0}]
    collector._salvar_regional(dados_invalidos, "SP")  # não deve levantar

    # Se a conexão anterior não foi fechada, esta abertura exclusiva falha/trava.
    conn2 = sqlite3.connect(db_file, timeout=1)
    conn2.execute("SELECT 1")
    conn2.close()
```

Adjust the collector class used (`GazetaDoPovoColetor`) if it doesn't
directly expose `_salvar_regional` with this signature — check
`collectors/gazetadopovo.py` first with
`grep -n "_salvar_regional\|_filtrar_presidenciais" collectors/gazetadopovo.py collectors/cnn_brasil.py`
and pick whichever concrete collector calls the shared base method most
directly.

**Verify**: `python -m pytest -q tests/test_collectors.py -k test_salvar_regional_fecha_conexao_mesmo_com_erro` → 1 passed.

### Step 3: Run the full test suite

**Verify**: `python -m pytest -q` → all pass (same baseline as before your change, see STOP conditions for the known Windows flakiness caveat).

## Test plan

- New test: `tests/test_collectors.py::test_salvar_regional_fecha_conexao_mesmo_com_erro` — forces a `KeyError` mid-loop and confirms the connection was closed (see Step 2 for the exact test body).
- Structural pattern to follow: `test_save_empty_list_does_not_error` (`tests/test_collectors.py:82`) for the `tmp_path` + schema-init boilerplate.
- Verification: `python -m pytest -q tests/test_collectors.py` → all pass, including the 1 new test.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `_salvar_regional` in `collectors/base.py` has `conn.close()` in a `finally` block, not only on the success path
- [ ] `python -m pytest -q tests/test_collectors.py -k test_salvar_regional_fecha_conexao_mesmo_com_erro` passes
- [ ] `python -m pytest -q` exits 0 (modulo the known Windows Monte Carlo flakiness, see STOP conditions)
- [ ] No files outside `collectors/base.py` and `tests/test_collectors.py` are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `_salvar_regional`'s code doesn't match the "Current state" excerpt (drifted since this plan was written).
- `collectors/quaest_regional.py` turns out to still have its own duplicate raw-connection `_salvar_regional`/`_salvar_regionais` implementation (see Scope) — report it, don't fix it here.
- The regression test in Step 2 can't reliably reproduce a mid-loop exception with the chosen collector class — try a different concrete collector before giving up, but if none work after two attempts, stop and report what you tried.
- Pre-existing test failures appear that aren't the known Windows Monte Carlo flakiness (5 tests in `test_monte_carlo.py` failing only on a fresh local DB, passing on rerun/CI).

## Maintenance notes

- This same "raw `sqlite3.connect()` without a context manager" pattern
  also exists in `app.py:933` (`/admin/apply-db`) and
  `collectors/quaest_regional.py` — already tracked in `plans/README.md`'s
  backlog as "convergir os 3 padrões de acesso a DB." This plan does not
  attempt that broader convergence; it only closes the specific leak found
  in `_salvar_regional`.
- If a future refactor moves collector DB writes onto `db.core.get_db()`'s
  context-manager pattern (used elsewhere in the codebase), this fix
  becomes redundant but harmless.
