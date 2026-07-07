# Plan 016: House effects — viés sistemático de cada instituto vs. a média agregada

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b3b92ef..HEAD -- database.py app.py templates/dashboard.html templates/metodologia.html`
> Os planos 009/015 tocam esses arquivos de propósito (devem estar DONE).

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: LOW (feature aditiva, só leitura)
- **Depends on**: plans/010 (usa a mesma infra de teste); após 015 (mesmo `templates/dashboard.html`)
- **Category**: direction
- **Planned at**: commit `b3b92ef`, 2026-07-07

## Why this matters

PRD seção F7 (pós-MVP): "Identifica institutos sistematicamente
otimistas/pessimistas por candidato — house effect de cada instituto". Item #5
do roadmap de auditoria de junho/2026 (primeiro pendente da fila). O dado já
existe: é essencialmente um GROUP BY por instituto sobre a mesma janela que
`get_media_agregada` usa. Valor de produto: credibilidade metodológica (é o
que diferencia agregadores sérios — FiveThirtyEight etc.) e contexto para o
leitor ("Instituto X costuma dar +3pp para o candidato Y").

## Current state

- `database.py:467-593` — `get_media_agregada(cargo, dias)`: já monta, em
  memória, a estrutura `polls: {pesquisa_id: {instituto, data, amostra, cands: {nome: pct}}}`
  com todos os filtros certos (estimulada, ativos, janela, exclusão de
  outros/nulos/brancos). O house effect usa exatamente os mesmos filtros.
- Definição a implementar (simples e defensável): para cada `(instituto,
  candidato)` com pesquisas na janela de N dias (default 90), o desvio médio
  entre o percentual do instituto e a **média das médias dos demais institutos**
  para o mesmo candidato na mesma janela:
  `house_effect = media_instituto(candidato) - media_geral_sem_instituto(candidato)`.
  Reportar apenas quando: o candidato tem pesquisas de ≥3 institutos na janela
  E o instituto tem ≥2 pesquisas na janela (senão é ruído, não viés).
- `app.py` — padrão de endpoint público de leitura: ver `api_media_agregada`
  (`app.py:609-615`), incluindo entrada na lista `allowed_endpoints`
  (`app.py:115-130`) e, pós-plano-009, `@cache.cached(timeout=300, query_string=True)`.
- `templates/dashboard.html` — a seção "dados" (`secao-dados`) contém tabelas
  renderizadas por JS (ex.: `carregarInstitutos`, linha ~509; tabela de
  rejeição, linhas ~1040-1055 — usar como exemplar de markup/tokens).
- `templates/metodologia.html` — página pública com as 7 seções de metodologia;
  nova metodologia exibida ao usuário DEVE ser documentada lá
  (memória do projeto: mudanças de agregação sempre refletem na /metodologia).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Testes | `python -m pytest tests/test_agregacao.py tests/test_dashboard.py -q` | exit 0 |
| Suíte | `python -m pytest -q` | exit 0 |

## Scope

**In scope**:
- `database.py` (nova função `get_house_effects(cargo, dias=90)`)
- `app.py` (rota `GET /api/house-effects`)
- `templates/dashboard.html` (tabela na seção de dados)
- `templates/metodologia.html` (parágrafo/subseção explicando o cálculo)
- `tests/test_agregacao.py` (testes numéricos)

**Out of scope** (NÃO tocar):
- `get_media_agregada` — o house effect NÃO ajusta a média agregada (isso
  seria um passo metodológico maior; registrado como follow-up).
- Credibilidade histórica/acurácia em eleições passadas (parte 2 do F7 — sem
  dados para isso hoje).

## Git workflow

- Commit: `feat(house-effects): desvio sistemático por instituto vs média dos demais (#5 roadmap)`.

## Steps

### Step 1: `get_house_effects` em `database.py`

Nova função com a MESMA query base de `get_media_agregada` (copiar o SELECT
das linhas 483-500 com os mesmos filtros; janela `dias=90`). Em Python:
1. `media_por_inst_cand[(instituto, candidato)] = mean(pcts)` e contagem.
2. Para cada candidato com ≥3 institutos: para cada instituto com ≥2 pesquisas
   do candidato, `efeito = round(media_inst - mean(medias dos DEMAIS institutos), 1)`.
3. Retorno:

```python
{
  "cargo": cargo, "janela_dias": dias,
  "institutos": [
    {"instituto": "Quaest", "efeitos": [
        {"candidato": "Lula", "efeito_pp": +1.8, "n_pesquisas": 4}, ...],
     "tendencia": "otimista_esquerda" | None  # opcional, só se trivial; senão omitir
    }, ...
  ]
}
```

Manter simples: sem classificação de "tendência" se exigir julgamento — os
números por candidato bastam para o MVP.

**Verify**: `python -m pytest tests/test_agregacao.py -q` → exit 0 (com os
testes novos do Step 4).

### Step 2: Rota

`GET /api/house-effects` (`?cargo=`, default `presidente`), pública
(adicionar `'api_house_effects'` em `allowed_endpoints`), com
`@cache.cached(timeout=300, query_string=True)` se o plano 009 estiver aplicado.

**Verify**: `python -m pytest tests/test_dashboard.py -q` → exit 0.

### Step 3: UI + metodologia

- `templates/dashboard.html`: na seção de dados (`secao-dados`), nova tabela
  "Tendência por instituto (house effect)" — colunas Instituto / Candidato /
  Desvio (pp, com sinal e cor: positivo `var(--pe-*)` verde-ish, negativo
  vermelho-ish — reutilizar os tokens já usados na tabela de rejeição) /
  Nº pesquisas. Fetch em função `carregarHouseEffects()` adicionada ao
  `Promise.all` do `inicializar()`. Nota de rodapé: "Desvio médio vs. os demais
  institutos nos últimos 90 dias. Não é erro — é diferença metodológica."
- `templates/metodologia.html`: subseção curta explicando o cálculo e o
  disclaimer (desvio ≠ erro; referência: prática padrão de agregadores).

**Verify**: `python -m pytest -q` → exit 0; verificação manual da tabela.

### Step 4: Testes numéricos

Em `tests/test_agregacao.py` (reusar o helper `_seed` do plano 010):
1. 3 institutos, candidato X: A=40 (2 pesquisas), B=36, C=38 → efeito de A =
   `40 - mean(36,38) = +3.0` (conta em comentário).
2. Instituto com 1 pesquisa só → excluído dos efeitos.
3. Candidato com 2 institutos apenas → não reportado.
4. Janela: pesquisa fora dos 90 dias não conta.

**Verify**: `python -m pytest tests/test_agregacao.py -q` → todos passam.

## Test plan

Ver Step 4 (4 testes numéricos) + 1 teste de rota (`GET /api/house-effects` →
200, shape com `institutos`).

## Done criteria

- [ ] `python -m pytest -q` exit 0
- [ ] `/api/house-effects` público retorna efeitos calculados
- [ ] Tabela no dashboard + subseção na /metodologia
- [ ] `git status` limpo fora do escopo
- [ ] Linha de status atualizada em `plans/README.md`

## STOP conditions

- Plano 010 não DONE (sem o helper `_seed`, os testes teriam que reinventar a infra).
- Os thresholds (≥3 institutos, ≥2 pesquisas) zerarem o resultado com os dados
  reais do banco de produção — reportar (talvez a janela precise ser maior);
  não afrouxar os thresholds por conta própria.

## Maintenance notes

- Follow-up explícito: usar o house effect para AJUSTAR a média agregada
  (como agregadores maduros fazem) — mudança metodológica, exige decisão do
  dono + atualização da /metodologia + testes do plano 010.
- Quando houver dados de governador RJ suficientes, o endpoint já aceita
  `?cargo=governador_rj` sem mudança.
