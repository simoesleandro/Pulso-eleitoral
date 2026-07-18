# Plan 036: Ativa WAL + busy_timeout no SQLite para reduzir "database is locked"

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 0992d23..HEAD -- db/core.py collectors/base.py collectors/quaest_regional.py`
> If any of these files changed since this plan was written, compare the
> "Current state" excerpts below against the live code before proceeding;
> on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `0992d23`, 2026-07-17

## Why this matters

`db/core.py:get_conn()` opens every SQLite connection in this app (used by
Flask request handlers via `get_db()`, and directly by the scheduler) with
SQLite's default journal mode and default 5-second busy timeout — no
`PRAGMA journal_mode=WAL` or `PRAGMA busy_timeout` override. Two raw
`sqlite3.connect()` calls elsewhere (`collectors/base.py:91` and
`collectors/quaest_regional.py:86`) open independent connections to the
same file with the same unconfigured defaults. This app runs a
`BackgroundScheduler` (`app.py`) that writes collector data while
simultaneously serving read requests through `get_db()` on the same file —
without WAL mode, SQLite readers and writers block each other more
aggressively than necessary. During this audit, running two concurrent
`pytest` invocations against the same SQLite test DB reproduced
`sqlite3.OperationalError: database is locked` inside `db/core.py:init_db`
and `scripts/migrate_candidatos_status.py`. In production, a scheduler run
overlapping with a request (or an admin-triggered `/admin/coletar-url` run
overlapping with the daily scheduled job) can hit the same contention and
surface as a user-facing 500. `PRAGMA journal_mode=WAL` allows one writer
and many concurrent readers without blocking each other, and a longer
`busy_timeout` makes SQLite retry-and-wait instead of immediately raising
when a writer *is* briefly holding the file lock.

## Current state

- `db/core.py:25-35` — the single most important connection factory, used
  by everything that goes through `get_conn()`/`get_db()`:

```python
def get_conn():
    """Retorna uma conexão aberta com o SQLite, configurando a row_factory."""
    # Garante que a pasta 'data' exista
    if not os.path.exists(database.DATA_DIR):
        os.makedirs(database.DATA_DIR, exist_ok=True)

    conn = sqlite3.connect(database.DB_PATH)
    conn.row_factory = sqlite3.Row
    # Habilita chaves estrangeiras
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn
```

- `collectors/base.py:91` — a second, independent raw connection inside
  `BaseCollector` (the exact surrounding function name may differ slightly;
  confirm with `grep -n -B5 "conn = sqlite3.connect(self.db_path)" collectors/base.py`
  before editing — there are two occurrences in this file, at lines 91 and
  405; **only** the one at line 91 is in scope here — line 405 is inside
  `_salvar_regional`, already addressed by plan 032, and adding a `finally`
  there is out of scope for this plan; only add the PRAGMA lines to it, not
  restructure its try/finally).

- `collectors/quaest_regional.py:86` — a third independent raw connection.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Tests | `python -m pytest -q` | all pass |
| Reproduce the lock (optional, before your fix) | run `python -m pytest -q` in two terminals simultaneously against the same test DB | may show `database is locked` before the fix; should be more resilient after |

## Scope

**In scope** (the only files you should modify):
- `db/core.py` — add `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout` to `get_conn()`.
- `collectors/base.py` — add the same two `PRAGMA` calls to the connection opened at line 91 only.
- `collectors/quaest_regional.py` — add the same two `PRAGMA` calls to the connection opened at line 86.

**Out of scope**:
- `collectors/base.py:405` (`_salvar_regional`'s connection) — plan 032 already restructures this method's try/finally; adding the PRAGMA calls there is fine but do NOT re-touch the try/finally structure plan 032 established. If plan 032 has not landed yet when you execute this plan, add the two PRAGMA lines to the `conn = sqlite3.connect(self.db_path)` call at line 405 as well, matching whatever try/except shape exists at that point — but do not restructure error handling as part of this plan.
- `app.py:1003` (the `/admin/apply-db` connection, used only transiently to validate an incoming SQLite file before swapping it in) — this connection is short-lived and not part of the concurrent read/write contention pattern this plan addresses; do not modify it.
- Any schema change, migration, or `.db` file — WAL mode is a runtime PRAGMA, not a schema change, and takes effect per-connection (it does create a `-wal` and `-shm` sidecar file next to the `.db` file at runtime — this is expected SQLite behavior, not a bug).
- Changing `conn.row_factory` or the `foreign_keys` PRAGMA already present in `get_conn()` — leave those lines exactly as they are, just add the two new PRAGMA lines alongside them.

## Git workflow

- Branch: `advisor/036-sqlite-wal-busy-timeout`
- Commit message style: `fix(banco): ativa WAL e busy_timeout para reduzir contenção sqlite`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add WAL + busy_timeout to `db/core.py:get_conn()`

Add two `conn.execute(...)` calls immediately after `conn.row_factory =
sqlite3.Row` and before the existing `conn.execute("PRAGMA foreign_keys =
ON;")` line (order doesn't matter functionally, but keep all three PRAGMA
calls grouped together for readability):

```python
    conn = sqlite3.connect(database.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=10000;")
    # Habilita chaves estrangeiras
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn
```

(10000 = 10 seconds, double the SQLite default of 5s — long enough to
absorb a brief scheduler write, short enough not to make a genuinely stuck
request hang indefinitely.)

**Verify**: `grep -n "PRAGMA journal_mode\|PRAGMA busy_timeout" db/core.py` → 2 matches, both inside `get_conn`.

### Step 2: Add the same PRAGMAs to `collectors/base.py:91`

Locate the connection at `collectors/base.py:91` (confirm with `grep -n -B5 -A2 "conn = sqlite3.connect(self.db_path)" collectors/base.py` and pick the first occurrence). Add the same two lines immediately after that connection is opened, before it's used:

```python
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=10000;")
```

**Verify**: `grep -n "PRAGMA journal_mode\|PRAGMA busy_timeout" collectors/base.py` → at least 2 matches near line 91 (plus 2 more near line 405 if you also chose to apply it there per the Scope note).

### Step 3: Add the same PRAGMAs to `collectors/quaest_regional.py:86`

Same pattern, at the connection opened at `collectors/quaest_regional.py:86`.

**Verify**: `grep -n "PRAGMA journal_mode\|PRAGMA busy_timeout" collectors/quaest_regional.py` → 2 matches.

### Step 4: Run the full test suite

**Verify**: `python -m pytest -q` → all pass. Note: WAL mode creates `pulso_test.db-wal` and `pulso_test.db-shm` sidecar files during test runs — this is normal SQLite behavior, not a leak; confirm `tests/` still passes with `TESTING=True`'s isolated test DB path.

## Test plan

No new test is required to prove PRAGMA values were set correctly at the
unit level, but you should verify the setting took effect:

- Add one small test in `tests/test_database.py` (model after
  `test_get_conn` at `tests/test_database.py:37`) that opens a connection
  via `get_conn()` and asserts the journal mode:

```python
def test_get_conn_ativa_wal_e_busy_timeout():
    """Regressão: get_conn() deve configurar WAL + busy_timeout para reduzir
    contenção entre o scheduler e requests concorrentes."""
    conn = get_conn()
    try:
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
        assert journal_mode.lower() == "wal"
        assert busy_timeout == 10000
    finally:
        conn.close()
```

- Verification: `python -m pytest -q tests/test_database.py -k test_get_conn_ativa_wal_e_busy_timeout` → 1 passed. Then `python -m pytest -q` → all pass.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `db/core.py:get_conn()` sets both `PRAGMA journal_mode=WAL;` and `PRAGMA busy_timeout=10000;`
- [ ] `collectors/base.py`'s connection at (former) line 91 sets both PRAGMAs
- [ ] `collectors/quaest_regional.py`'s connection at (former) line 86 sets both PRAGMAs
- [ ] New test `test_get_conn_ativa_wal_e_busy_timeout` passes
- [ ] `python -m pytest -q` exits 0, same pass count as baseline plus 1 (modulo known Windows Monte Carlo flakiness)
- [ ] No files outside `db/core.py`, `collectors/base.py`, `collectors/quaest_regional.py`, `tests/test_database.py` are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Any of the three target connection sites don't match the "Current state" excerpts (drifted since this plan was written).
- WAL mode causes any test failure related to file locking or the `-wal`/`-shm` sidecar files not being cleaned up between test runs — this would be a real regression on Windows (this repo has documented Windows-specific SQLite file-lock flakiness already, see `plans/README.md`'s note on Monte Carlo tests); if failures increase (not just the known ~5 flaky ones), stop and report rather than trying multiple busy_timeout values blindly.
- `database.DB_PATH` or the test DB setup assumes a specific journal-mode file layout that WAL breaks (e.g. any code that copies or deletes the `.db` file directly without accounting for `-wal`/`-shm` siblings — check `scripts/sync_db.py` and `/admin/apply-db` in `app.py` for this pattern, though neither is in scope to modify, just to check they still work).

## Maintenance notes

- WAL mode creates `<dbname>-wal` and `<dbname>-shm` sidecar files next to
  the main `.db` file. `scripts/sync_db.py` (uploads the local SQLite file
  to Fly.io) and `/admin/apply-db` (receives it) should be checked by a
  future maintainer to confirm they either checkpoint WAL into the main
  file before transfer (`PRAGMA wal_checkpoint(TRUNCATE);`) or transfer all
  three files together — otherwise a sync could miss recently-committed-but-
  not-yet-checkpointed data still sitting in the `-wal` file. This plan
  does not modify `sync_db.py`/`apply-db`; flag this as a fast-follow if
  sync behavior looks wrong after this change lands.
- 10-second busy_timeout is a starting value; if production still shows
  lock contention after this lands, the next lever is investigating why a
  write is taking that long (likely a large collector batch commit), not
  raising the timeout further.
