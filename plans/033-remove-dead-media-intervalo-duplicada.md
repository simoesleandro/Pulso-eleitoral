# Plan 033: Remove a cópia morta de `_media_intervalo` em `db/pesquisas.py`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 0992d23..HEAD -- db/pesquisas.py db/kpis.py`
> If either file changed since this plan was written, compare the "Current
> state" excerpts below against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `0992d23`, 2026-07-17

## Why this matters

Plan 029 split the former `database.py` god-module into `db/*.py`
submodules. During that split, the helper function `_media_intervalo` ended
up copied byte-for-byte into two different files — `db/pesquisas.py` and
`db/kpis.py` — instead of being defined once and imported. The copy in
`db/pesquisas.py` has zero call sites anywhere in the repo (confirmed by
`grep -rn "_media_intervalo" .` — only `db/kpis.py`'s own local copy is ever
called, from within `db/kpis.py:get_kpis_avancados`). This is dead code that
creates a maintenance trap: a future bug fix to the interval-averaging logic
has even odds of landing in the dead copy, silently having zero effect,
with no test to catch the mistake (since the dead copy is never exercised).

## Current state

- `db/pesquisas.py:426-434` — the dead, unused copy:

```python
def _media_intervalo(pontos: list[tuple[str, float]], inicio: str, fim: str = None):
    """Média dos percentuais com data_pesquisa em [inicio, fim) — ou
    [inicio, ...] se fim for None. Retorna None se não houver pontos no
    intervalo (equivalente a um AVG(...) SQL retornando NULL)."""
    if fim:
        vals = [pct for dt, pct in pontos if inicio <= dt < fim]
    else:
        vals = [pct for dt, pct in pontos if dt >= inicio]
    return mean(vals) if vals else None
```

- `db/kpis.py:9-17` — the live copy, the one actually used by
  `get_kpis_avancados` in the same file:

```python
def _media_intervalo(pontos: list[tuple[str, float]], inicio: str, fim: str = None):
    """Média dos percentuais com data_pesquisa em [inicio, fim) — ou
    [inicio, ...] se fim for None. Retorna None se não houver pontos no
    intervalo (equivalente a um AVG(...) SQL retornando NULL)."""
    if fim:
        vals = [pct for dt, pct in pontos if inicio <= dt < fim]
    else:
        vals = [pct for dt, pct in pontos if dt >= inicio]
    return mean(vals) if vals else None
```

- `database.py:59` — the façade already imports `_media_intervalo` from
  `db.kpis`, not from `db.pesquisas`:

```python
from db.kpis import get_kpis_avancados, get_visao_geral, _media_intervalo
```

  This confirms the `db/pesquisas.py` copy is the dead one — the façade
  never re-exports it from there, and nothing imports it directly from
  `db.pesquisas` either.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Confirm no other callers | `grep -rn "_media_intervalo" --include=*.py .` | only 2 definitions (`db/kpis.py`, `db/pesquisas.py` before your edit) + call sites inside `db/kpis.py` |
| Tests | `python -m pytest -q` | all pass |

## Scope

**In scope** (the only file you should modify):
- `db/pesquisas.py` — delete the dead `_media_intervalo` function only.

**Out of scope**:
- `db/kpis.py` — this is the live, correct copy; do not touch it.
- Any other duplicated logic elsewhere in `db/*` — this plan is scoped to this one confirmed-dead function, not a general audit of the split.
- Importing `_media_intervalo` from `db.kpis` into `db.pesquisas` "just in case" — there is no evidence anything in `db/pesquisas.py` needs it; if you find a real caller during Step 1, STOP (see STOP conditions).

## Git workflow

- Branch: `advisor/033-remove-dead-media-intervalo-duplicada`
- Commit message style: `chore(db): remove _media_intervalo duplicada e morta em db/pesquisas.py`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Confirm zero call sites before deleting

Run `grep -rn "_media_intervalo" --include=*.py .` and confirm the only
matches are: the function definition in `db/pesquisas.py`, the function
definition in `db/kpis.py`, and its call site(s) inside
`db/kpis.py:get_kpis_avancados`. There must be no `from db.pesquisas import
_media_intervalo` or `pesquisas._media_intervalo(...)` anywhere.

**Verify**: the grep output contains no reference to `_media_intervalo`
qualified by `pesquisas.` or importing it `from db.pesquisas` or `from
database import _media_intervalo` pointing at the pesquisas copy specifically.

### Step 2: Delete the dead function from `db/pesquisas.py`

Remove the entire `_media_intervalo` function (the 9 lines shown in
"Current state" above, `db/pesquisas.py:426-434`) from `db/pesquisas.py`.
Leave one blank line where it was (match the file's existing blank-line
spacing between top-level functions — two blank lines is this repo's
convention, visible elsewhere in the same file).

**Verify**: `grep -n "_media_intervalo" db/pesquisas.py` → no output (zero matches).

### Step 3: Run the full test suite

**Verify**: `python -m pytest -q` → all pass, same result as before your change.

## Test plan

No new tests needed — this removes unreachable dead code with zero
behavioral surface. The existing test suite (particularly
`tests/test_agregacao.py`, which is the numerical contract test for
`db/kpis.py`'s aggregation logic per `CLAUDE.md`) already covers the live
`_media_intervalo` in `db/kpis.py`, which this plan does not touch.

- Verification: `python -m pytest -q` → all pass, identical to the baseline before this change (no test count should change).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "_media_intervalo" db/pesquisas.py` returns no matches
- [ ] `grep -n "_media_intervalo" db/kpis.py` still shows the function definition and its call site(s), unchanged
- [ ] `python -m pytest -q` exits 0, same pass count as baseline
- [ ] No files outside `db/pesquisas.py` are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Step 1's grep turns up any real caller of `db.pesquisas._media_intervalo` — that would mean the dead-code determination in this plan was wrong; do not delete, report back instead.
- `db/pesquisas.py`'s copy has diverged from `db/kpis.py`'s copy (different body, not byte-for-byte identical) — that would mean someone modified one but not the other since this plan was written; report which one looks more correct instead of guessing.
- The test suite shows failures after deletion that reference `_media_intervalo` — revert the deletion and report.

## Maintenance notes

- This is the only confirmed dead-code leftover from plan 029's split found
  during this audit; the rest of the split (façade completeness, import
  cycles) was cross-checked clean. No further db/-split cleanup is expected
  from this plan.
- If a future split/refactor needs `_media_intervalo` in more than one
  module, the correct fix is a shared import (`from db.kpis import
  _media_intervalo`), not another copy-paste.
