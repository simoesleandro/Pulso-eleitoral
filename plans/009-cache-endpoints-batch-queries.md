# Plan 009: Cachear endpoints de agregação, eliminar N+1 e adicionar índices

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b3b92ef..HEAD -- app.py database.py schema.sql`
> Divergência entre os excertos de "Current state" e o código vivo = STOP.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (refatora queries de leitura; mitigado pelos testes do plano 010)
- **Depends on**: plans/010-testes-numericos-agregacao.md (OBRIGATÓRIO — não começar sem ele DONE)
- **Category**: perf
- **Planned at**: commit `b3b92ef`, 2026-07-07

## Why this matters

Cada carga do dashboard dispara 13 fetches (`templates/dashboard.html:1063-1078`).
Só os 2 endpoints Monte Carlo têm cache; `media-agregada`, `kpis-avancados`,
`simulacao-segundo-turno`, `visao-geral` etc. recomputam a agregação completa a
cada request — e `get_kpis_avancados`, `get_simulacao_segundo_turno` e o Monte
Carlo chamam `get_media_agregada` cada um por conta própria (a mesma varredura
multi-JOIN 3–4× por carga). `get_kpis_avancados` ainda emite ~15+ queries AVG
em loops por candidato, e `get_historico_multi` uma query por candidato. No
Fly.io com `auto_stop_machines`, requests a frio pagam tudo isso. Os dados só
mudam via coleta local + `apply-db` (que já chama `cache.clear()`), então cache
de 300s é seguro.

## Current state

- `app.py:609-643` — rotas: `api_media_agregada` (usa query params `cargo`,
  `dias`), `api_kpis_avancados` (`cargo`), `api_simulacao_segundo_turno` (sem
  params), `api_monte_carlo`/`api_monte_carlo_governador_rj` (JÁ têm
  `@cache.cached(timeout=300)`). `app.py:418-422` — `api_visao_geral` (sem
  params). `app.py:584-607` — `api_alertas` (params `limiar`, `janela`, e
  `int()/float()` sem guarda — ver Step 4), `api_pesquisas_historico_multi`
  (params). `app.py:894` — `api_rejeicao`.
- `app.py:888` — `apply_db` chama `cache.clear()` após o swap do banco; o
  comentário no código diz explicitamente que TUDO que é cacheado depende do
  SQLite, então `clear()` total invalida tudo. Cache é Flask-Caching
  (`cache = Cache(...)` já configurado no topo de `app.py`).
- `database.py:1150-1317` — `get_kpis_avancados`: helper `_avg()` roda 4
  SELECTs AVG por candidato do top-3 (12 queries), + 2 por candidato do
  campo_minado, + 1 por candidato de volatilidade.
- `database.py:1340-1370` — `get_historico_multi`: loop
  `for idx, candidato in enumerate(candidatos):` com um SELECT por candidato
  (interpolação segura de `filtro_tipo`, candidato via `?`).
- `schema.sql:88-95` — índices existentes: `intencoes(pesquisa_id)`,
  `intencoes(candidato)`, `pesquisas(cargo)`, `pesquisas(data_pesquisa)`,
  `alertas(cargo)`, `rejeicoes(...)`. **Não existe** índice em
  `pesquisas(instituto_id)` nem composto `pesquisas(cargo, data_pesquisa)`,
  usados por `detectar_variacoes_bruscas` (`database.py:405-441`, joins
  correlacionados por instituto) e por todas as agregações.
- `init_db()` em `database.py` executa `schema.sql` com `CREATE ... IF NOT EXISTS`
  — índices novos aplicam na próxima inicialização. Em produção o banco é
  gerado localmente e enviado via `sync_db.py`, então o índice nasce no banco
  local e viaja junto.

Exemplo do padrão de cache já usado no repo (`app.py:630-634`):

```python
@app.route('/api/monte-carlo')
@cache.cached(timeout=300)
def api_monte_carlo():
    from database import get_simulacao_monte_carlo
    return jsonify(get_simulacao_monte_carlo())
```

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Testes de agregação (baseline do 010) | `python -m pytest tests/test_agregacao.py -q` | exit 0 |
| Suíte | `python -m pytest -q` | exit 0, 0 failed |

## Scope

**In scope**:
- `app.py` (decorators de cache; parse seguro de query params das rotas públicas)
- `database.py` (`get_kpis_avancados`, `get_historico_multi` — apenas as queries;
  `get_media_agregada` NÃO muda)
- `schema.sql` (2 índices novos)
- `tests/test_dashboard.py` (testes de parse de params, se necessário)

**Out of scope** (NÃO tocar):
- A matemática/thresholds de qualquer KPI (os testes do 010 são o contrato).
- O motor Monte Carlo (`_simular_cenario` etc.) — otimização de memória ficou
  fora deste plano de propósito.
- `detectar_variacoes_bruscas` — o bug de GROUP BY dela é um achado separado
  (backlog); os índices beneficiam sem mudar a query.
- Templates/JS.

## Git workflow

- Commits em português, um por step lógico, ex.:
  `perf(api): cacheia endpoints de agregação (300s, invalidado no apply-db)`.

## Steps

### Step 1: Índices

Adicionar em `schema.sql`, junto ao bloco de índices existente:

```sql
CREATE INDEX IF NOT EXISTS idx_pesquisas_instituto_id ON pesquisas(instituto_id);
CREATE INDEX IF NOT EXISTS idx_pesquisas_cargo_data ON pesquisas(cargo, data_pesquisa);
```

**Verify**: `python -m pytest tests/test_database.py -q` → exit 0 (o teste de
tabelas esperadas não valida índices, deve seguir verde). E:
`python -c "import os; os.environ['TESTING']='True'; import database; database.init_db(); import sqlite3; c=sqlite3.connect(database.DB_PATH); print(sorted(r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_pesquisas%'\")))"`
→ lista contém `idx_pesquisas_cargo_data` e `idx_pesquisas_instituto_id`.

### Step 2: Cache nos endpoints de leitura

Em `app.py`, adicionar decorator **entre** o `@app.route` e a função:
- `@cache.cached(timeout=300, query_string=True)` em: `api_media_agregada`,
  `api_kpis_avancados`, `api_alertas`, `api_pesquisas_historico_multi`,
  `api_pesquisas_historico` (tem params), `api_comparativo` (params).
- `@cache.cached(timeout=300)` em: `api_visao_geral`,
  `api_simulacao_segundo_turno`, `api_regional_presidente`, `api_rejeicao`,
  `api_institutos`.

NÃO cachear: `api_visao_geral_analise` (tem cache próprio de 6h no SQLite),
`api_status`, rotas de admin/login.
`query_string=True` é obrigatório nas rotas com query params — sem isso o
cache serviria a resposta de um `cargo` para outro.

**Verify**: `python -m pytest tests/test_dashboard.py -q` → exit 0. Se algum
teste falhar por cache entre testes, configurar `CACHE_TYPE: "NullCache"`
quando `TESTING` (ver como `cache` é inicializado no topo de `app.py` e
condicionar) — e reportar isso no commit message.

### Step 3: Batch em `get_historico_multi`

Substituir o loop por **uma** query:
`WHERE i.candidato IN ({placeholders}) AND p.cargo = ? AND {filtro_tipo} ORDER BY i.candidato, p.data_pesquisa ASC`
(placeholders `?` gerados por `",".join("?"*len(candidatos))`; nunca interpolar
os nomes). Particionar as rows por candidato em Python e montar as mesmas
séries (mesma ordem de `candidatos`, mesmas cores via `get_cores_candidatos()`,
candidato sem rows → `dados: []`). Guard: lista vazia → retornar `[]` sem query.

**Verify**: `python -m pytest tests/test_agregacao.py -q` → exit 0 (testes de
caracterização do 010 continuam verdes).

### Step 4: Uma passada em `get_kpis_avancados`

Substituir os loops de `_avg()`/campo_minado/volatilidade por **uma** query da
janela de 60 dias:

```sql
SELECT i.candidato, p.data_pesquisa, i.percentual
FROM intencoes i JOIN pesquisas p ON i.pesquisa_id = p.id
WHERE p.cargo = ? AND p.data_pesquisa >= ?  -- d60
AND (i.tipo='estimulada' OR i.tipo IS NULL)
ORDER BY i.candidato, p.data_pesquisa
```

e computar em Python, por candidato, as médias das janelas `[d15, hoje]`,
`[d30, d15)`, `[d30, hoje]`, `[d60, d30)` e o stdev de `[d30, hoje]` —
**exatamente os mesmos recortes de data** dos SQLs atuais (atenção: `>= inicio`
e `< fim`, datas como strings ISO comparáveis). Toda a lógica de classificação
(aceleracao, campo_minado, crescimento relativo, volatilidade) permanece
byte-idêntica.

Aproveitar na mesma edição: parse seguro dos query params públicos que hoje
quebram com 500 — `app.py:589-590` (`float(request.args.get('limiar', 3.0))`,
`int(request.args.get('janela', 7))`) e `app.py:614` (`int(...('dias', 30))`):
envolver em `try/except (ValueError, TypeError)` caindo no default.

**Verify**: `python -m pytest tests/test_agregacao.py tests/test_dashboard.py -q`
→ exit 0. Teste manual do parse: adicionar em `tests/test_dashboard.py` um
teste `client.get('/api/media-agregada?dias=abc')` → status 200 (não 500).

## Test plan

- Os testes do plano 010 são o contrato de equivalência (devem passar sem edição).
- Novos: 1 teste de parse seguro (`?dias=abc` → 200) e 1 de `?limiar=x&janela=y`
  → 200, em `tests/test_dashboard.py`, seguindo o padrão dos testes de API do
  arquivo.

## Done criteria

- [ ] `python -m pytest -q` exit 0 (incluindo `tests/test_agregacao.py` sem modificações)
- [ ] Rotas listadas no Step 2 têm `@cache.cached` (conferir com `grep -n "cache.cached" app.py` → ≥13 ocorrências)
- [ ] `get_historico_multi` e `get_kpis_avancados` não têm SELECT dentro de loop `for` por candidato
- [ ] Índices novos presentes no schema
- [ ] `git status` limpo fora do escopo
- [ ] Linha de status atualizada em `plans/README.md`

## STOP conditions

- Plano 010 não está DONE (sem os testes, a refatoração do Step 4 não tem rede).
- Um teste de caracterização do 010 falhar após o Step 4 e a causa não for
  óbvia em 2 tentativas — reportar a divergência numérica em vez de afrouxar o teste.
- Os testes existentes dependerem de respostas não-cacheadas de forma que exija
  redesenhar o setup de cache além do NullCache em TESTING.

## Maintenance notes

- O comentário em `app.py` no `apply_db` documenta o contrato "tudo cacheado
  depende do SQLite" — os novos decorators respeitam isso; se algum cache futuro
  não depender do banco, migrar para invalidação por prefixo.
- Se o dashboard ganhar novos endpoints de leitura, cacheá-los é o default.
- Deferido de propósito: otimização de memória do Monte Carlo (retém 30k dicts
  por miss; mitigado pelo cache de 300s) e o fix do GROUP BY de
  `detectar_variacoes_bruscas` (backlog no README dos planos).
