# Plan 034: Loga exceções antes de retornar sentinelas silenciosos em `db/usuarios.py` e `db/core.py`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 0992d23..HEAD -- db/usuarios.py db/core.py`
> If either file changed since this plan was written, compare the "Current
> state" excerpts below against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `0992d23`, 2026-07-17

## Why this matters

Four functions catch `except Exception` and return a plain sentinel value
(`[]`, `False`, or `None`) with no logging: `listar_usuarios`,
`remover_usuario`, and `toggle_usuario` in `db/usuarios.py`, plus
`buscar_ultimo_log` in `db/core.py`. This makes a transient infrastructure
error (a locked database, a disk I/O error) indistinguishable from a normal
"not found" / "no-op" result. `remover_usuario`/`toggle_usuario` back the
admin user-management UI — a security-sensitive surface — so an operator
trying to deactivate a compromised account and silently failing due to a
DB error would see the exact same "False" result as trying to toggle a
nonexistent user ID, with zero signal in the logs that anything went wrong.
Adding a log line before each `return` preserves the existing function
contract (same return values, same call sites unaffected) while making
these failures visible in production logs.

## Current state

- `db/usuarios.py:74-87` — `listar_usuarios`:

```python
def listar_usuarios() -> list[dict]:
    """Retorna todos os usuários cadastrados sem a hash da senha."""
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, nome, ativo, criado_em, ultimo_login FROM usuarios ORDER BY username ASC"
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []
    finally:
        conn.close()
```

- `db/usuarios.py:90-101` — `remover_usuario`:

```python
def remover_usuario(user_id: int) -> bool:
    """Exclui o usuário do banco por ID. Retorna True se excluiu com sucesso."""
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        return False
    finally:
        conn.close()
```

- `db/usuarios.py:104-120` — `toggle_usuario`:

```python
def toggle_usuario(user_id: int) -> bool:
    """Inverte o status 'ativo' (0 para 1, ou 1 para 0) do usuário por ID."""
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ativo FROM usuarios WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if row is None:
            return False
        novo_status = 0 if row['ativo'] == 1 else 1
        cursor.execute("UPDATE usuarios SET ativo = ? WHERE id = ?", (novo_status, user_id))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()
```

- `db/core.py:149-166` — `buscar_ultimo_log`:

```python
def buscar_ultimo_log() -> dict | None:
    """Busca o log de execução do scheduler mais recente."""
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT job, executado_em, resultado FROM scheduler_log ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            return {
                "job": row["job"],
                "executado_em": row["executado_em"],
                "resultado": json.loads(row["resultado"]) if row["resultado"] else []
            }
        return None
    except Exception:
        return None
    finally:
        conn.close()
```

- The logging convention already used elsewhere in these same files —
  `db/core.py` already has a module-level `logger = logging.getLogger(__name__)`
  (line 22) and uses it in `init_db` (`logger.warning(...)`, line 110). Match
  that style: `logger.exception(...)` inside the `except` block (use
  `.exception()`, not `.error()`, so the traceback is captured — this repo
  doesn't currently use `.exception()` anywhere, but it's the standard
  Python logging method for exactly this situation and is a strict
  improvement with the same call signature as `.error()`).
- `db/usuarios.py` currently has **no** module-level logger — you must add
  one (`import logging` + `logger = logging.getLogger(__name__)`), matching
  the exact pattern already in `db/core.py:14,22`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Tests | `python -m pytest -q tests/test_usuarios.py` | all pass |
| Full suite | `python -m pytest -q` | all pass |

## Scope

**In scope** (the only files you should modify):
- `db/usuarios.py` — add module-level logger; add `logger.exception(...)` calls in the 3 functions listed above.
- `db/core.py` — add `logger.exception(...)` call in `buscar_ultimo_log`.

**Out of scope**:
- `criar_usuario` and `verificar_usuario` in `db/usuarios.py` — these already `raise e` in their `except` blocks (a different, already-correct pattern that propagates instead of swallowing) — do not change their behavior.
- `salvar_log_scheduler` in `db/core.py` — also already `raise e`, already correct.
- Changing return types or the function contracts — callers (`app.py`'s admin routes) must keep working exactly as before; only the logging changes.
- Any other `except Exception` in the codebase not listed above — this plan is scoped to these 4 specific sites.

## Git workflow

- Branch: `advisor/034-log-excecoes-silenciosas-usuarios-core`
- Commit message style: `fix(observabilidade): loga exceções antes de retornar sentinela em usuarios/core`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add a module-level logger to `db/usuarios.py`

At the top of `db/usuarios.py`, add `import logging` to the imports and
`logger = logging.getLogger(__name__)` after the imports, matching
`db/core.py:14,22`'s exact placement (imports, then a blank line, then the
logger assignment, then a blank line before the first function).

**Verify**: `grep -n "^import logging\|^logger = " db/usuarios.py` → both lines present.

### Step 2: Log in `listar_usuarios`, `remover_usuario`, `toggle_usuario`

In each of the three functions, change `except Exception:` to
`except Exception:` followed by a `logger.exception(...)` call before the
`return`. Example for `listar_usuarios`:

```python
    except Exception:
        logger.exception("Erro ao listar usuários")
        return []
```

Apply the analogous change to `remover_usuario` (`logger.exception("Erro ao
remover usuário id=%s", user_id)`) and `toggle_usuario`
(`logger.exception("Erro ao alternar status do usuário id=%s", user_id)`).
Keep the return values (`[]`, `False`, `False`) exactly as they are today.

**Verify**: `grep -n "logger.exception" db/usuarios.py` → 3 matches.

### Step 3: Log in `buscar_ultimo_log`

In `db/core.py`, change the `except Exception:` in `buscar_ultimo_log` to
log before returning `None`:

```python
    except Exception:
        logger.exception("Erro ao buscar último log do scheduler")
        return None
```

**Verify**: `grep -n "logger.exception" db/core.py` → 1 match, inside `buscar_ultimo_log`.

### Step 4: Run the affected and full test suites

**Verify**: `python -m pytest -q tests/test_usuarios.py` → all pass. Then `python -m pytest -q` → all pass.

## Test plan

No new tests are strictly required — this change is additive logging with
no change to return values or control flow, and the existing
`tests/test_usuarios.py` (covers `remover_usuario`, `toggle_usuario`,
`listar_usuarios` indirectly via admin routes) already exercises the happy
paths that must remain unchanged. If you want extra confidence, you may add
one test using `caplog` (pytest's built-in log-capture fixture) that forces
an exception (e.g. by closing the connection early or monkeypatching
`get_conn` to return a broken connection) and asserts a log record was
emitted — model it after any existing test in `tests/test_usuarios.py` for
the `tmp_path`/monkeypatch setup pattern. This is optional; do not spend
more than one attempt on it before moving on if it proves fiddly to set up.

- Verification: `python -m pytest -q` → all pass, same pass count as baseline (plus 1 if you added the optional `caplog` test).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `db/usuarios.py` has a module-level `logger = logging.getLogger(__name__)`
- [ ] `grep -n "logger.exception" db/usuarios.py` shows 3 matches (one per function: `listar_usuarios`, `remover_usuario`, `toggle_usuario`)
- [ ] `grep -n "logger.exception" db/core.py` shows 1 match, inside `buscar_ultimo_log`
- [ ] `criar_usuario` and `verificar_usuario` in `db/usuarios.py` are unchanged (`git diff db/usuarios.py` shows no hunks touching them)
- [ ] `salvar_log_scheduler` in `db/core.py` is unchanged
- [ ] `python -m pytest -q` exits 0, same pass count as baseline (modulo known Windows Monte Carlo flakiness)
- [ ] No files outside `db/usuarios.py` and `db/core.py` are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Any of the 4 target functions' code doesn't match the "Current state" excerpts (drifted since this plan was written).
- Adding the logger import to `db/usuarios.py` creates a circular import (it shouldn't — `db/usuarios.py` only imports `from db.core import get_conn`, and `logging` is stdlib — but if `python -m pytest -q` fails with an `ImportError` immediately after this change, stop and report).
- The test suite shows failures that reference these functions after your change — revert and report.

## Maintenance notes

- This plan intentionally does not change the WAL/busy_timeout behavior of
  the underlying connections (see plan 036, a separate related finding) —
  once that lands, the exceptions these functions now log will occur less
  often in practice, but the logging itself remains valuable for whatever
  residual failure modes exist.
- If this codebase later adopts structured logging (correlation IDs,
  JSON logs — noted as a DX gap in the broader backlog), these
  `logger.exception(...)` calls are natural upgrade points.
