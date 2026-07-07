# Plan 017: Aviso de defasagem — sinalizar quando a pesquisa mais recente está velha

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b3b92ef..HEAD -- templates/dashboard.html database.py`
> Os planos 015/016 tocam `dashboard.html` de propósito (devem estar DONE).

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: após 016 (mesmo `templates/dashboard.html`)
- **Category**: direction
- **Planned at**: commit `b3b92ef`, 2026-07-07

## Why this matters

Item #10c do roadmap de junho/2026. Um dashboard de "pulso" que exibe médias
calculadas sobre pesquisas de 3 semanas atrás sem avisar induz o leitor a erro.
O dado já existe: `get_visao_geral()` calcula `dias_desde_ultima` — falta só
exibir o aviso. Honestidade metodológica barata, alinhada ao tom da página
/metodologia ("não é previsão").

## Current state

- `database.py:1412-1443` — `get_visao_geral()` já retorna `dias_desde_ultima`
  (int, `None` se não há pesquisas) e `ultima_atualizacao` (dd/mm/yyyy):

```python
        ultima_atualizacao = None
        dias_desde_ultima = None
        if max_data:
            try:
                dt = datetime.datetime.strptime(max_data, "%Y-%m-%d").date()
                today = datetime.date.today()
                dias_desde_ultima = max(0, (today - dt).days)
                ultima_atualizacao = dt.strftime("%d/%m/%Y")
```

- `templates/dashboard.html` — `carregarVisaoGeral()` consome `/api/visao-geral`
  e preenche os KPIs do topo (localizar a função pelo nome; ela está registrada
  no `Promise.all` de `inicializar()`, linha ~1063). A seção de visão geral tem
  id `secao-visao-geral`.
- Tokens de estilo: `var(--pe-*)` (ver `static/css/tokens.css`); exemplos de
  markup de aviso/nota no próprio dashboard (rodapés das tabelas).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Suíte | `python -m pytest -q` | exit 0, 0 failed |

## Scope

**In scope**:
- `templates/dashboard.html` (banner condicional)
- `tests/test_dashboard.py` (1 teste do payload, se ainda não coberto)

**Out of scope** (NÃO tocar):
- `database.py` (o dado já existe; nada a mudar)
- Alertas Telegram de defasagem (follow-up, não MVP)
- `/metodologia`

## Git workflow

- Commit: `feat(dashboard): aviso de defasagem quando a última pesquisa passa de 10 dias (#10c roadmap)`.

## Steps

### Step 1: Banner no dashboard

Em `templates/dashboard.html`, dentro de `carregarVisaoGeral()` (após popular
os KPIs): se `json.dias_desde_ultima != null && json.dias_desde_ultima > 10`,
tornar visível um banner (div já presente no HTML com `display:none`, inserida
no topo da `secao-visao-geral`):

```html
<div id="aviso-defasagem" style="display:none; padding:10px 14px; border-radius:8px;
     background:rgba(245,158,11,0.12); border:1px solid rgba(245,158,11,0.4);
     color:var(--pe-text); font-size:13px; margin-bottom:12px;">
  ⏳ <strong>Dados defasados:</strong> a pesquisa mais recente é de
  <span id="aviso-defasagem-data"></span> (<span id="aviso-defasagem-dias"></span> dias atrás).
  Interprete as médias com cautela.
</div>
```

JS: preencher `aviso-defasagem-data` com `json.ultima_atualizacao`,
`aviso-defasagem-dias` com `json.dias_desde_ultima`, e `display='block'`.
Threshold 10 dias como constante JS nomeada (`const LIMIAR_DEFASAGEM_DIAS = 10`)
no topo do bloco de script — pesquisas presidenciais saem a cada 1–2 semanas,
10 dias é "esperando a próxima", 20+ é seca real; o valor fica trivialmente
ajustável.

**Verify**: `python -m pytest -q` → exit 0. Manual: com o banco local (última
pesquisa recente), banner invisível; editando `LIMIAR_DEFASAGEM_DIAS = 0`
temporariamente, banner aparece — reverter.

### Step 2: Teste do contrato do payload

Em `tests/test_dashboard.py`: garantir que `/api/visao-geral` retorna as chaves
`dias_desde_ultima` e `ultima_atualizacao` com seed conhecido (se um teste
existente já cobre as chaves, apenas estender o assert).

**Verify**: `python -m pytest tests/test_dashboard.py -q` → exit 0.

## Test plan

Ver Step 2. O comportamento visual é JS puro sobre payload testado — sem teste
de browser (o repo não tem infra E2E; não criar uma para isto).

## Done criteria

- [ ] `python -m pytest -q` exit 0
- [ ] Banner `#aviso-defasagem` existe no template e é ativado por `dias_desde_ultima > 10`
- [ ] Teste cobre as chaves do payload
- [ ] `git status` limpo fora do escopo
- [ ] Linha de status atualizada em `plans/README.md`

## STOP conditions

- `carregarVisaoGeral` não existir mais com esse nome/estrutura (drift dos
  planos 015/016) — localizar o consumidor atual de `/api/visao-geral` e, se
  ambíguo, reportar.

## Maintenance notes

- Follow-up: incluir o aviso no resumo diário do Telegram quando
  `dias_desde_ultima` cruzar o limiar (aproveitar `coletar.py`).
- Se o plano 009 cacheou `/api/visao-geral` (300s), o banner tem a mesma
  defasagem máxima de 5 min — irrelevante para um limiar de 10 dias.
