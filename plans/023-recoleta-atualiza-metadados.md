# Plan 023: Recoleta de uma pesquisa existente atualiza metadados, não só intenções

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 8d3827f..HEAD -- collectors/base.py`
> If the file changed since this plan was written, compare the "Current
> state" excerpt below against the live code before proceeding — this
> function was touched this session (contratante fix, date guard), so
> re-read it carefully even if the diff looks small; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `8d3827f`, 2026-07-16

## Why this matters

When `BaseCollector.save()` re-processes a URL it already has a `pesquisas`
row for (same `instituto_id` + `cargo` + `fonte_url`), it deletes and
re-inserts `intencoes`/`rejeicoes` with fresh values, but only
conditionally updates `data_pesquisa` — every other metadata column
(`margem_erro`, `tamanho_amostra`, `contratante`, `pct_pode_mudar_voto`) is
set once at INSERT time and never touched again. If a source page is later
corrected (larger published sample size, revised margin of error, a
`pct_pode_mudar_voto` figure added in an update to the article), the vote
shares update correctly on re-scrape but the metadata that feeds Monte
Carlo confidence bands and the dashboard's margin-of-error display stays
frozen at whatever the first extraction produced — silently wrong for the
life of that row, with no way to detect it short of manually diffing the
DB against the source.

## Current state

- `collectors/base.py:132-151` — the full update branch as it exists today
  (already includes this session's `contratante` and date-guard fixes; read
  this fresh, don't assume the excerpt below is still byte-exact if the
  drift check above shows changes):

```python
if row:
    pesquisa_id = row[0]
    # Atualiza data_pesquisa se o item traz uma data real (não apenas hoje),
    # mas nunca aceita uma data de campo posterior à publicação já registrada
    # (reextração não-determinística do Gemini já produziu esse absurdo).
    first = group_items[0]
    data_pesquisa_real = first.get("data_pesquisa")
    if data_pesquisa_real and data_pesquisa_real != dt_coleta:
        cursor.execute(
            "SELECT data_publicacao FROM pesquisas WHERE id=?", (pesquisa_id,)
        )
        data_publicacao_atual = cursor.fetchone()[0]
        if data_pesquisa_real <= data_publicacao_atual:
            cursor.execute(
                "UPDATE pesquisas SET data_pesquisa=? WHERE id=?",
                (data_pesquisa_real, pesquisa_id)
            )
    # Limpa intenções e rejeições anteriores para evitar duplicação
    cursor.execute("DELETE FROM intencoes WHERE pesquisa_id = ?", (pesquisa_id,))
    cursor.execute("DELETE FROM rejeicoes WHERE pesquisa_id = ?", (pesquisa_id,))
```

- For comparison, the INSERT branch that sets these columns the first time
  — `collectors/base.py:152-188` (note the `margem_erro` regex-cleanup
  logic at lines 156-162; any UPDATE-path handling of `margem_erro` must
  apply the same cleanup, not assume the value is already a clean float):

```python
else:
    # b. Se não existe: INSERT INTO pesquisas
    first = group_items[0]
    import hashlib
    margem_erro = first.get("margem_erro")
    if margem_erro is not None:
        import re as _re
        _m = _re.search(r'[\d]+[.,]?[\d]*', str(margem_erro))
        margem_erro = float(_m.group().replace(',', '.')) if _m else 0.0
    else:
        margem_erro = 0.0
    tamanho_amostra = first.get("tamanho_amostra")
    if tamanho_amostra is None:
        tamanho_amostra = 0
    contratante = first.get("contratante")
    data_divulgacao = first.get("data_divulgacao") or dt_coleta
    registro_tse = first.get("registro_tse") or f"GEN-{inst_id}-{cargo}-{dt_coleta}-{hashlib.sha1(url.encode()).hexdigest()[:10]}"

    data_pesquisa = first.get("data_pesquisa") or dt_coleta
    pct_pode_mudar_voto = first.get("pct_pode_mudar_voto")

    cursor.execute("""
        INSERT INTO pesquisas
        (instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url, pct_pode_mudar_voto)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (...))
    pesquisa_id = cursor.lastrowid
    grupo_pesquisas += 1
```

- The reusable test pattern that already exercises a double-`save()` call
  — `tests/test_collectors.py:84` (`test_save_normalizado`), which calls
  `collector.save(dados)` twice with the *same* `dados` and asserts no
  duplication. This plan's new test should follow the same fixture/DB-setup
  shape but call `save()` the second time with **different** metadata
  values in the item dicts, and assert the `pesquisas` row reflects the new
  values.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Run tests | `TESTING=True python -m pytest -q` | all pass |
| Run just the collectors test file | `TESTING=True python -m pytest -q tests/test_collectors.py` | all pass, including new test |

## Scope

**In scope**:
- `collectors/base.py` — the `if row:` branch (lines 132-151) only
- `tests/test_collectors.py` — new characterization/regression test

**Out of scope**:
- The `else:` (INSERT) branch — already correct, do not touch its logic
  (only read it as a reference for how `margem_erro` needs cleanup).
- `registro_tse` — this column has a `UNIQUE` constraint and identifies the
  row; never update it on re-save.
- `data_publicacao` (`data_divulgacao` in the item dict) — updating the
  publication date on re-save is a separate design question (does a
  correction change *when* something was published?) that this plan
  deliberately does not address; leave it INSERT-only as it is today.
- The silent-rejection-without-logging issue in the date-guard code above
  (noted separately in the audit as its own low-priority finding) — not
  bundled into this plan; only touch the metadata-refresh behavior.

## Git workflow

- Branch: `advisor/023-recoleta-atualiza-metadados`
- Commit message style: conventional commits in Portuguese, e.g.
  `fix(coleta): recoleta atualiza margem/amostra/contratante, não só intencoes`
- Do NOT push or open a PR unless explicitly instructed.

## Steps

### Step 1: Decide and implement the null-vs-present semantics

The core design question: when `save()` re-processes a URL, the new
`group_items[0]` (i.e. `first`) may have `None` for a field the Gemini
re-parse didn't manage to extract this time, even though the DB already
has a good value from the first extraction. **Do not overwrite a good
existing value with a `None` from a partial re-extraction.** Use `COALESCE`
in SQL (new value if present, otherwise keep the existing one) — this
mirrors how `first.get("data_publicacao") or dt_coleta` already expresses
"prefer the new value, fall back to a placeholder" in the INSERT branch,
just inverted (fall back to the *existing DB value*, not a placeholder,
since a row already exists here).

In the `if row:` branch (`collectors/base.py:132-151`), after the existing
`data_pesquisa` guard block and before the `DELETE FROM intencoes` lines,
add:

```python
margem_erro_nova = first.get("margem_erro")
if margem_erro_nova is not None:
    import re as _re
    _m = _re.search(r'[\d]+[.,]?[\d]*', str(margem_erro_nova))
    margem_erro_nova = float(_m.group().replace(',', '.')) if _m else None

tamanho_amostra_novo = first.get("tamanho_amostra")
contratante_novo = first.get("contratante")
pct_pode_mudar_voto_novo = first.get("pct_pode_mudar_voto")

cursor.execute(
    """UPDATE pesquisas SET
           margem_erro = COALESCE(?, margem_erro),
           tamanho_amostra = COALESCE(?, tamanho_amostra),
           contratante = COALESCE(?, contratante),
           pct_pode_mudar_voto = COALESCE(?, pct_pode_mudar_voto)
       WHERE id = ?""",
    (margem_erro_nova, tamanho_amostra_novo, contratante_novo, pct_pode_mudar_voto_novo, pesquisa_id)
)
```

Note `tamanho_amostra_novo` here is intentionally **not** defaulted to `0`
the way the INSERT branch defaults it (`collectors/base.py:163-165`) —
that `0` default only makes sense at INSERT time (a new row needs some
value); on UPDATE, `None` must mean "no new info, keep what's there,"
so passing raw `None` through `COALESCE` is correct. Do not copy the INSERT
branch's `if tamanho_amostra is None: tamanho_amostra = 0` fallback into
this UPDATE branch — that would incorrectly zero out a good existing value
whenever a re-extraction fails to find the sample size.

**Verify**: `TESTING=True python -c "import collectors.base"` → no syntax
error.

### Step 2: Combine with the existing `data_pesquisa` update in one clear code block

Keep the existing `data_pesquisa` guard logic (already correct, don't
change its behavior) directly above the new UPDATE statement from Step 1,
so the `if row:` branch reads as one coherent "refresh whatever changed"
block followed by the existing `DELETE FROM intencoes`/`rejeicoes` lines.

**Verify**: read the full `if row:` branch top to bottom and confirm it
still: (a) conditionally updates `data_pesquisa` with the publication-date
guard, (b) now also updates the 4 metadata columns via COALESCE, (c) still
deletes and lets the caller re-insert `intencoes`/`rejeicoes` unchanged.

### Step 3: Add the regression test

In `tests/test_collectors.py`, add a new test modeled on
`test_save_normalizado` (line 84): seed a `pesquisas` row via a first
`save()` call with a known `margem_erro`/`tamanho_amostra`/`contratante`,
then call `save()` again with the same `fonte_url` (so it hits the
`if row:` branch) but different values for those fields, and assert the
`pesquisas` row in the DB now reflects the **new** values. Add a second
assertion case: re-save with `margem_erro=None` (simulating a partial
re-extraction) and confirm the **existing** value is preserved, not
zeroed/nulled.

```python
def test_save_recoleta_atualiza_metadados(tmp_path):
    """Recoleta da mesma pesquisa (mesmo fonte_url) atualiza margem_erro,
    tamanho_amostra, contratante e pct_pode_mudar_voto — não só as
    intencoes. Um valor None na reextração preserva o valor existente
    (evita apagar um dado bom com uma reextração parcial)."""
    # ... setup mirroring test_save_normalizado's tmp_path/schema/institutos ...
    # 1st save: margem_erro=2.0, tamanho_amostra=1000, contratante=None
    # 2nd save (same fonte_url): margem_erro=2.5, tamanho_amostra=1500, contratante="Cliente X"
    # assert pesquisas row now has margem_erro=2.5, tamanho_amostra=1500, contratante="Cliente X"
    # 3rd save (same fonte_url): margem_erro=None
    # assert pesquisas row still has margem_erro=2.5 (preserved, not overwritten with NULL)
```

**Verify**: `TESTING=True python -m pytest -q tests/test_collectors.py -k recoleta_atualiza_metadados` → passes.

## Test plan

- New test `test_save_recoleta_atualiza_metadados` (Step 3), modeled on
  `test_save_normalizado` (`tests/test_collectors.py:84`) for DB/fixture
  setup.
- Cases covered: (1) re-save with new non-null metadata updates the row,
  (2) re-save with `None` for a field preserves the existing value.
- Verification: `TESTING=True python -m pytest -q` → all pass, including
  the new test, and no existing test in `test_collectors.py` regresses
  (particularly `test_save_normalizado` itself, which re-saves identical
  data and must still show no unwanted change).

## Done criteria

- [ ] `TESTING=True python -m pytest -q` exits 0
- [ ] `grep -n "COALESCE" collectors/base.py` shows the new UPDATE statement
- [ ] New test `test_save_recoleta_atualiza_metadados` exists and passes,
      covering both the update case and the null-preservation case
- [ ] `test_save_normalizado` (pre-existing test) still passes unmodified
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row for 023 updated

## STOP conditions

- `collectors/base.py:132-151` doesn't match the excerpt above (this
  function was edited this session and may have drifted further) — re-read
  it fully before touching anything.
- The `margem_erro` regex-cleanup logic (lines 156-162 in the INSERT
  branch) has changed shape since this excerpt was taken — re-derive the
  correct cleanup for the UPDATE branch from the live INSERT branch, don't
  copy this plan's snippet blindly if it no longer matches.
- You find evidence that some caller relies on metadata staying frozen
  after first insert (e.g. a test asserting a specific old value survives a
  second `save()` call) — that would mean the "why this matters" premise is
  wrong for that caller; stop and report rather than breaking that test to
  force this plan through.

## Maintenance notes

- If `registro_tse` or `data_publicacao` update-on-recollect is ever
  requested in the future, treat it as a separate decision (both were
  explicitly kept out of scope here) — don't fold them into this plan's
  commit after the fact without re-deriving the right semantics for each.
- The silent-rejection-without-logging gap in the date-guard code
  (mentioned in "Out of scope") is a known, separate, low-priority finding
  — worth a follow-up plan if the maintainer wants better observability
  into how often reextractions get rejected.
