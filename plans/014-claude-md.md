# Plan 014: Criar CLAUDE.md com as regras não-óbvias do repo

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b3b92ef..HEAD -- README.md requirements.txt .github/`
> Se o plano 011 já rodou, o CLAUDE.md deve refletir o estado NOVO (playwright
> declarado, pyproject existente) — verifique qual é o caso antes de escrever.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (idealmente após 011, para documentar o estado final)
- **Category**: dx
- **Planned at**: commit `b3b92ef`, 2026-07-07

## Why this matters

Planos deste repositório são executados por agentes. Sem `CLAUDE.md`, cada
agente re-deriva do zero as regras que não estão em lugar nenhum: que a coleta
roda **só localmente** (o Fly nunca executa o scheduler), que `sync_db.py`
troca o banco de produção inteiro, que `TESTING=True` precisa existir antes de
importar `app`, que playwright tem instalação especial. Errar qualquer uma
dessas custa um deploy quebrado ou um banco de produção sobrescrito.

## Current state

- Não existem `CLAUDE.md` nem `AGENTS.md` na raiz (verificado em `b3b92ef`).
- Fatos verificados no código que o arquivo deve registrar (fontes citadas):
  - Testes: `python -m pytest -q`; os arquivos de teste setam
    `os.environ['TESTING']='True'` antes de importar `app`/`database`
    (`tests/test_dashboard.py:1-3`) — qualquer script novo que importe `app`
    em contexto de teste precisa disso.
  - Scheduler NÃO roda em produção: `app.py:105` —
    `if not app.testing and os.getenv('TESTING') != 'True' and not os.getenv('FLY_APP_NAME') and not scheduler.running:`.
  - Fluxo de dados: coleta local (Task Scheduler → `coletar.py`) → SQLite local
    → `scripts/sync_db.py` faz upload e POST `/admin/apply-db` → troca
    `/data/pulso.db` no Fly e reinicia. `sync_db.py` NÃO faz deploy de código;
    só `flyctl deploy` reconstrói a imagem.
  - `/admin/apply-db`: auth por header `X-Admin-Pass`, fail-closed
    (`app.py:842-846`); é `@csrf.exempt` de propósito (chamado headless).
  - Playwright: importado no load por 7 coletores; (pré-011) não está em
    `requirements.txt` — CI instala à parte; (pós-011) está declarado.
  - Tabela `candidatos` é fonte única de verdade para normalização de nomes,
    espectro e cores; populada no `init_db`; cache em memória por processo.
  - Agregação usa só pesquisas `estimulada` (ou `tipo IS NULL` legado);
    poll-of-polls é ponderado (amostra × 0.9^dias, 1 pesquisa/instituto) —
    documentado em `/metodologia`.
  - Deploy: push na `main` → GitHub Actions roda pytest como gate → `flyctl deploy`.
  - Idioma do código/commits: português; commits estilo conventional
    (`fix(...)`, `feat(...)` — ver `git log --oneline`).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Suíte (sanity, nada deve mudar) | `python -m pytest -q` | exit 0 |

## Scope

**In scope**:
- `CLAUDE.md` (criar, na raiz)

**Out of scope** (NÃO tocar): qualquer outro arquivo.

## Git workflow

- Commit: `docs: adiciona CLAUDE.md com convenções e regras não-óbvias do repo`.

## Steps

### Step 1: Escrever o arquivo

Criar `CLAUDE.md` (~60–90 linhas, em português) com estas seções, usando os
fatos de "Current state" — cada afirmação deve ser conferida contra o código
atual antes de escrita (os planos 006–013 podem ter mudado detalhes):

1. **O que é** — 2 linhas (radar de pesquisas, presidente + governador RJ, Flask + SQLite + Gemini).
2. **Comandos** — rodar testes, rodar app local, coleta manual (`python coletar.py`), sync (`python scripts/sync_db.py`).
3. **Arquitetura em 5 linhas** — coleta local → SQLite → sync → Fly; Fly NUNCA coleta.
4. **Regras que quebram deploys** — TESTING antes de importar app; playwright; `sync_db.py` ≠ deploy; apply-db troca o banco de produção (não mexer sem `tests/test_apply_db.py` verde).
5. **Domínio** — tabela `candidatos` como fonte de verdade; agregação estimulada-only; mudanças de metodologia exigem atualizar `/metodologia` e os testes numéricos (`tests/test_agregacao.py`, se o plano 010 já rodou).
6. **Convenções** — português, conventional commits, testes pytest com fixtures de `tests/conftest.py` (Playwright e Gemini são mockados globalmente).
7. **Planos** — apontar para `plans/README.md`.

**Verify**: arquivo existe; `python -m pytest -q` → exit 0 (nada de código mudou).

## Test plan

Nenhum teste novo (é documentação). Verificação = revisão fatual: cada
afirmação com fonte no código.

## Done criteria

- [ ] `CLAUDE.md` existe na raiz com as 7 seções
- [ ] Nenhuma afirmação contradiz o código atual (spot-check das linhas citadas em Current state)
- [ ] `git status` mostra apenas `CLAUDE.md` (+ README dos planos)
- [ ] Linha de status atualizada em `plans/README.md`

## STOP conditions

- Uma "regra" de Current state não se confirmar no código atual (ex.: plano 011
  mudou o setup) — atualizar a redação para o estado real, e se o estado real
  for ambíguo, reportar.

## Maintenance notes

- CLAUDE.md deve ser atualizado quando os planos 006–013 mudarem convenções
  (ex.: contrato do coletor do 013).
- Manter curto: é contexto de agente, não documentação de usuário (essa é o README).
