# Plan 010: Testes numéricos do poll-of-polls e caracterização dos KPIs

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b3b92ef..HEAD -- database.py tests/`
> Se `get_media_agregada`, `get_kpis_avancados` ou `get_historico_multi` em
> `database.py` mudaram desde `b3b92ef`, comparar com os excertos abaixo; em
> divergência de comportamento, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (só adiciona testes)
- **Depends on**: none — e é **pré-requisito do plano 009**
- **Category**: tests
- **Planned at**: commit `b3b92ef`, 2026-07-07

## Why this matters

`get_media_agregada` é o número que todo visitante do dashboard vê — média
ponderada por amostra e recência, uma pesquisa por instituto, corte de
candidatos com <2 pesquisas. Hoje o único teste é um smoke ("retorna chaves").
Um expoente errado, uma troca de peso ou uma regressão no dedup passariam no CI.
Este plano fixa o contrato numérico com valores calculados à mão e cria testes
de caracterização para `get_kpis_avancados` e `get_historico_multi`, destravando
o plano 009 (que reescreve as queries dessas funções).

## Current state

- `database.py:467-593` — `get_media_agregada(cargo, dias=30)`. Algoritmo
  (confirmado no código):
  1. Seleciona intenções `estimulada OR NULL` da janela, cargo dado, excluindo
     candidatos com status != 'ativo' e rótulos outros/nulos/brancos/indecisos/
     não sabe/não respondeu.
  2. **Uma pesquisa por instituto**: a de `data_pesquisa` mais recente
     (desempate por maior `pesquisa_id`) — linhas 516–522.
  3. Score da pesquisa = `peso_amostra * peso_recencia`, onde
     `peso_amostra = tamanho_amostra` (ou 1000 se 0/None) e
     `peso_recencia = 0.9 ** dias_desde` (dias desde `data_pesquisa` até hoje,
     mínimo 0) — linhas 524–535.
  4. Candidato precisa de **≥2 entradas na janela** (linha 544: `if len(entradas) < 2: continue`)
     — senão é omitido do resultado.
  5. `media = SUM(pct*score)/SUM(score)` sobre as pesquisas selecionadas em que
     o candidato aparece, arredondada a 1 casa (linhas 547–564, 576).
  6. `variacao_30d`: média das entradas da metade recente da janela menos média
     da metade antiga (todas as pesquisas, não só as selecionadas), `None` se
     uma das metades for vazia (linhas 566–572).
  7. Retorno: dict com `candidatos` ordenado por `media` desc; cada item tem
     `candidato, media, min, max, variacao_30d, pesquisas_count`.
- `database.py:1150-1317` — `get_kpis_avancados(cargo)`: margem_lideranca
  (classificações: <5 empate_tecnico, ≤10 lideranca_moderada, >10
  lideranca_confortavel), probabilidade_segundo_turno, tendencia_aceleracao
  (janelas 15/30/60 dias), campo_minado (média 2–15%, crescimento relativo,
  `em_ascensao` se >20%), concentracao_voto (top2 >70 bipolar, ≥55 moderado),
  volatilidade (stdev, <2 baixa, ≤4 media).
- `database.py:1340-1370` — `get_historico_multi(candidatos, cargo, tipo)`:
  série por candidato com `data, percentual, margem_erro, instituto` e cor.
- Testes existentes: `tests/test_dashboard.py:192` (`test_api_media_agregada`,
  só shape); `tests/test_monte_carlo.py` é o **exemplar de teste numérico** do
  repo (seeds controlados, asserts de valores).

Padrão de fixture (de `tests/test_dashboard.py:1-40`): `os.environ['TESTING']='True'`
no topo, fixture `cleanup` autouse apaga `DB_PATH`, `init_db(force_seed=True)`
ou schema puro via `schema.sql`, inserts diretos com `sqlite3`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Novo arquivo | `python -m pytest tests/test_agregacao.py -q` | exit 0 |
| Suíte | `python -m pytest -q` | exit 0, 0 failed |

## Scope

**In scope**:
- `tests/test_agregacao.py` (criar)

**Out of scope** (NÃO tocar):
- `database.py` — este plano NÃO corrige nada; se um teste calculado à mão
  divergir do código, ver STOP conditions.
- Testes existentes.

## Git workflow

- Commit em português, ex.: `test(agregacao): fixa contrato numérico do poll-of-polls e caracteriza KPIs`

## Steps

### Step 1: Infra do arquivo de teste

Criar `tests/test_agregacao.py` no padrão de `tests/test_database.py`: setar
`TESTING`, importar `database`, helper `_seed(polls)` que insere institutos,
`pesquisas` e `intencoes` com datas relativas a `date.today()` (as funções
usam `date.today()` — datas absolutas apodrecem). Cada poll do seed:
`(instituto_id, data_pesquisa=hoje-N dias, tamanho_amostra, candidatos={nome: pct})`,
`cargo='presidente'`, `tipo='estimulada'`, `registro_tse` único.
Usar nomes de candidatos reais do seed de `candidatos` (ex.: os presentes em
`database._CANDIDATOS_SEED`) para não esbarrar no filtro de status — ou inserir
candidatos próprios na tabela `candidatos` com `ativo=1, status='ativo'`.

**Verify**: `python -m pytest tests/test_agregacao.py -q` → exit 0 (arquivo com
1 teste trivial do helper).

### Step 2: Testes numéricos de `get_media_agregada`

Casos (todos com valores esperados **calculados à mão no próprio teste**, em
comentário mostrando a conta):

1. **Média ponderada básica**: 2 institutos, 1 pesquisa cada, mesmo dia
   (hoje−1): inst A amostra 2000, candidato X=40; inst B amostra 1000, X=34.
   Esperado: `media == round((40*2000*0.9 + 34*1000*0.9)/(2000*0.9 + 1000*0.9), 1) == 38.0`.
2. **Decaimento por recência**: mesmo candidato, inst A hoje (X=40, amostra
   1000), inst B hoje−7 (X=30, amostra 1000). Peso B = 0.9**7≈0.478.
   Esperado `media == round((40*1000 + 30*478.3)/(1000+478.3), 1)` — calcular
   com `0.9**7` exato no teste, sem arredondar o peso.
3. **1 pesquisa por instituto**: inst A com duas pesquisas na janela (hoje−10
   X=30, hoje−1 X=40) + inst B (hoje−1 X=40). Só a mais recente de A entra na
   média (X=40 dos dois → media 40.0), mas `variacao_30d` usa as três entradas.
4. **Corte <2 entradas**: candidato Y presente numa única pesquisa → ausente de
   `candidatos` no retorno.
5. **Amostra ausente → default 1000**: inst com `tamanho_amostra=0` pesa como 1000.
6. **Filtro espontânea**: intenção `tipo='espontanea'` não entra; `tipo=NULL` entra.

**Verify**: `python -m pytest tests/test_agregacao.py -q` → todos passam.

### Step 3: Caracterização de `get_kpis_avancados`

Com um seed fixo (3+ candidatos, 2 institutos, pesquisas em hoje−2 e hoje−20),
asserts sobre: `margem_lideranca.classificacao` para margens conhecidas (<5,
entre 5 e 10, >10 — três seeds ou parametrize), `probabilidade_segundo_turno.provavel`
(líder <50 → True), presença e shape de `tendencia_aceleracao` (3 itens, chaves
`tendencia_15d/tendencia_30d/aceleracao`), `concentracao_voto.classificacao`
para top2_soma conhecido. Não asserte valores de aceleração no detalhe — o
objetivo é caracterizar o comportamento atual para o plano 009 refatorar as
queries com segurança.

**Verify**: `python -m pytest tests/test_agregacao.py -q` → todos passam.

### Step 4: Caracterização de `get_historico_multi`

Seed com 2 candidatos, 2 pesquisas cada; assert: uma série por candidato, dados
ordenados por data asc, cada ponto com `data, percentual, margem_erro, instituto`;
`tipo='espontanea'` filtra exato; candidato inexistente → série com `dados == []`.

**Verify**: `python -m pytest -q` → exit 0, suíte inteira verde.

## Test plan

É o próprio plano (Steps 2–4). Total esperado: ~12 testes novos em
`tests/test_agregacao.py`, modelados em `tests/test_monte_carlo.py` (numérico)
e `tests/test_database.py` (fixtures).

## Done criteria

- [ ] `python -m pytest tests/test_agregacao.py -q` exit 0, ≥12 testes
- [ ] `python -m pytest -q` exit 0
- [ ] Cada teste numérico tem a conta esperada em comentário
- [ ] Nenhum arquivo fora do escopo modificado (`git status`)
- [ ] Linha de status atualizada em `plans/README.md`

## STOP conditions

- Um valor calculado à mão divergir do que o código retorna **após você
  conferir a conta duas vezes**: isso é um possível bug real na agregação —
  STOP e reporte a divergência com o caso mínimo; não "ajuste" o esperado para
  o que o código devolve sem entender o porquê.
- O seed de `candidatos` rejeitar os nomes do teste por normalização
  inesperada (usar nomes canônicos exatos da tabela).

## Maintenance notes

- O plano 009 depende destes testes para refatorar `get_kpis_avancados` e
  `get_historico_multi` — mantê-los verdes é o critério de equivalência.
- Se a fórmula de ponderação mudar de propósito no futuro (ex.: decaimento
  0.95), atualizar os testes E a página /metodologia juntos.
