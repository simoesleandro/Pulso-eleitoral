# Plan 013: Formalizar o contrato do coletor e remover código morto

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b3b92ef..HEAD -- collectors/ app.py check.py check_tables.py scripts/`
> Os planos 006/007 editam `collectors/base.py`/`gemini_extractor.py` de
> propósito (devem estar DONE). Divergência além disso = STOP.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW–MED (deleção de arquivos; mitigada por greps de uso)
- **Depends on**: plans/006-*.md e plans/007-*.md (mesmos arquivos; evitar conflito)
- **Category**: tech-debt
- **Planned at**: commit `b3b92ef`, 2026-07-07

## Why this matters

A rota `/admin/coletar-url` chama `coletor._get_page(url)` e
`coletor._parse_release(html, url)` em qualquer coletor resolvido por domínio —
mas esses métodos **não fazem parte** do contrato abstrato (`BaseCollector` só
exige `name`, `instituto_id`, `fetch`). Um coletor novo (ou um stub reaproveitado)
sem esses métodos exatos falha com `AttributeError` em request, não na
instanciação. Além disso o repo carrega stubs mortos (`ibope.py`, `real_time.py`,
`genial_quaest.py` — `fetch()` retorna `[]`, fora de `coletar.py` e de
`_COLETORES_DISPONIVEIS`), scripts one-off na raiz (`check.py`,
`check_tables.py`) e debug scripts apontando para módulo deletado
(`scripts/debug_uol.py` referencia `uol.py`, que não existe). Item #6 do
roadmap de junho/2026.

## Current state

- `collectors/base.py:17-49` — ABC com `name`/`instituto_id` (properties
  abstratas) e `fetch()` abstrato; `_get_page`/`_parse_release` ausentes do contrato.
- `app.py:696-703` — dict `_COLETORES_DISPONIVEIS` (domínio → classe);
  `app.py:716` — `_COLETOR_FALLBACK = 'gazetadopovo'`; `app.py:788-795` —
  `_coletar_url_especifica` chama `coletor._get_page(url)` e depois
  `coletor._parse_release(html, url)`, com special-case para `quaest_regional`
  (que expõe `_parse_page`) em `app.py:792`.
- Cada coletor concreto define `_get_page` por conta própria
  (`cnn_brasil.py:31`, `gazetadopovo.py:72`, `datafolha.py:51`, `quaest.py:33`,
  `atlas.py:31`, `poder360.py:42`, `verita.py:103`).
- Stubs mortos: `collectors/ibope.py`, `collectors/real_time.py`,
  `collectors/genial_quaest.py` — não importados por `coletar.py` (confirmado:
  imports de `coletar.py:37-44` são datafolha, quaest, gazetadopovo, atlas,
  poder360, verita, cnn_brasil, quaest_regional).
- Raiz: `check.py` (11 linhas), `check_tables.py` (4 linhas) — scripts one-off.
- `scripts/`: `debug_riomaframix.py`, `debug_riomaframix_gemini.py`,
  `debug_uol.py`, `debug_verita.py` (untracked), `check_datafolha_db.py`,
  `fix_datafolha_data_pesquisa.py` — one-offs. ATENÇÃO: `scripts/sync_db.py`,
  `scripts/migrate_candidatos_status.py` e `scripts/migrate_pesquisas_volatilidade.py`
  são **produção** (migrations são importadas pelo `init_db`) — não tocar.
- `.gitignore` já reserva `scratch/` para descartáveis.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Suíte | `python -m pytest -q` | exit 0, 0 failed |
| Uso de um módulo antes de deletar | `grep -rn "ibope" --include="*.py" .` | apenas o próprio arquivo (e possivelmente comentários) |

## Scope

**In scope**:
- `collectors/base.py` (contrato)
- Deleção: `collectors/ibope.py`, `collectors/real_time.py`,
  `collectors/genial_quaest.py`, `check.py`, `check_tables.py`,
  `scripts/debug_riomaframix.py`, `scripts/debug_riomaframix_gemini.py`,
  `scripts/debug_uol.py`, `scripts/check_datafolha_db.py`,
  `scripts/fix_datafolha_data_pesquisa.py`
- `tests/test_collectors.py` (teste do contrato; remoção de referências a stubs, se houver)

**Out of scope** (NÃO tocar):
- `scripts/sync_db.py`, `scripts/migrate_*.py` (produção).
- `scripts/seed_pesquisa_manual.py`, `scripts/debug_verita.py` (untracked —
  decisão do dono; não deletar nem commitar).
- `app.py` `_coletar_url_especifica` e o special-case do quaest_regional
  (comportamento atual preservado).
- `PulsoEleitoral.exe`, `depois.json`, `*.bat`, `*.xml` (artefatos locais do host).

## Git workflow

- Dois commits: `refactor(collectors): _get_page/_parse_release entram no contrato do BaseCollector` e
  `chore: remove stubs de coletores e scripts one-off mortos`.

## Steps

### Step 1: Verificar não-uso e deletar os mortos

Para CADA arquivo da lista de deleção, rodar
`grep -rn "<basename sem .py>" --include="*.py" .` e confirmar que só o próprio
arquivo (ou nada) referencia. Então `git rm` os arquivos. Se `tests/` referencia
algum stub (ex.: um teste de que `ibope.fetch() == []`), remover esse teste no
mesmo commit.

**Verify**: `python -m pytest -q` → exit 0;
`python -c "import app"` com `TESTING=True` no ambiente → sem ImportError.

### Step 2: Contrato no ABC

Em `collectors/base.py`, adicionar ao `BaseCollector`:

```python
    @abstractmethod
    def _get_page(self, url: str) -> str:
        """Busca o HTML de uma URL específica (usado pelo admin coletar-url)."""

    def _parse_release(self, html: str, url: str) -> list[dict]:
        """Parseia um release individual. Default: delega ao parser Gemini."""
        return self._parse_com_gemini(html, url, self.instituto_id)
```

Decisão embutida: `_get_page` vira **abstrato** (todo coletor vivo já o define —
lista em "Current state"); `_parse_release` ganha **default concreto** (evita
quebrar `quaest_regional`, que usa `_parse_page` e é special-cased no app.py).
Antes de finalizar, confirmar com grep que todos os coletores em
`_COLETORES_DISPONIVEIS` (`app.py:696-703`) definem `_get_page`:
`grep -ln "_get_page" collectors/*.py`.

**Verify**: `python -m pytest tests/test_collectors.py -q` → exit 0 (nenhum
coletor vivo deixa de instanciar).

### Step 3: Teste do contrato

Em `tests/test_collectors.py`, adicionar um teste que itera as classes de
`app._COLETORES_DISPONIVEIS` (importar de `app`), instancia cada uma com
`db_path` de teste e asserta `callable(getattr(c, '_get_page'))` e
`callable(getattr(c, '_parse_release'))`. Isso transforma o `AttributeError`
de request-time em falha de CI.

**Verify**: `python -m pytest tests/test_collectors.py -q` → exit 0, incluindo o novo teste.

## Test plan

- Novo teste de contrato (Step 3).
- A suíte existente é o guard-rail das deleções.

## Done criteria

- [ ] `python -m pytest -q` exit 0
- [ ] `ls collectors/` sem `ibope.py`, `real_time.py`, `genial_quaest.py`; raiz sem `check.py`/`check_tables.py`
- [ ] `BaseCollector` declara `_get_page` (abstrato) e `_parse_release` (default)
- [ ] Teste de contrato sobre `_COLETORES_DISPONIVEIS` existe e passa
- [ ] `git status` limpo fora do escopo
- [ ] Linha de status atualizada em `plans/README.md`

## STOP conditions

- Um grep de não-uso retornar referência viva a um arquivo da lista de deleção.
- Tornar `_get_page` abstrato impedir a instanciação de algum coletor de
  `_COLETORES_DISPONIVEIS` ou de `coletar.py` — reportar qual, não improvisar wrapper.
- Planos 006/007 não estarem DONE (conflito de merge em base.py).

## Maintenance notes

- Coletor novo agora falha na instanciação se não implementar `_get_page` —
  documentar no CLAUDE.md (plano 014).
- Follow-up deferido: normalizar `quaest_regional._parse_page` para a assinatura
  `_parse_release` e remover o special-case de `app.py:792`.
- Follow-up deferido: consolidar helpers duplicados entre coletores (`_norm`,
  dedup de links, `_salvar_regional`) em `collectors/utils.py` — achado DEBT-04
  da auditoria, no backlog.
