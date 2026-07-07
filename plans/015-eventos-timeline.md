# Plan 015: Linha do tempo de eventos — F4 do PRD (cadastro admin + marcadores no gráfico)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b3b92ef..HEAD -- templates/dashboard.html templates/admin.html app.py database.py schema.sql`
> Divergência relevante nos trechos citados = comparar antes de prosseguir.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (toca o gráfico principal do dashboard)
- **Depends on**: recomendado após 009 (mesmo `app.py`); OBRIGATORIAMENTE antes de 016/017 (todos tocam `templates/dashboard.html` — ordem evita conflito)
- **Category**: direction
- **Planned at**: commit `b3b92ef`, 2026-07-07

## Why this matters

O PRD (`docs/PRD_radar_pesquisas_v1.md`, seção F4 — escopo **MVP**) promete:
"Cadastro manual de eventos da campanha (debate, escândalo, comício); exibição
no gráfico como marcadores verticais; correlação visual entre evento e variação
nas pesquisas". A tabela `eventos` existe no schema desde o início
(`schema.sql:41-49`) e os wireframes têm o botão "eventos" — mas **nenhum
código de aplicação a usa**. É a feature que transforma o dashboard de
"agregador de números" em "pulso da eleição": ver O QUE moveu a curva. Usuário
primário do PRD: analista político correlacionando eventos com variações.

## Current state

- `schema.sql:41-49` — tabela pronta:

```sql
CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data TEXT NOT NULL, -- Formato YYYY-MM-DD
    titulo TEXT NOT NULL,
    descricao TEXT,
    cargo TEXT NOT NULL, -- 'presidente' | 'governador_rj' | 'geral'
    impacto TEXT NOT NULL, -- 'positivo' | 'negativo' | 'neutro' | 'indefinido'
    criado_em TEXT DEFAULT (datetime('now', 'localtime'))
);
```

- `templates/dashboard.html` — o gráfico de tendência é `chartHistoricoMulti`
  (`new Chart(ctx, {type:'line', ...})` na linha ~470, dentro de
  `renderizarHistoricoMulti(series)`); labels do eixo X são
  `todasDatas.map(formatarData)` onde `todasDatas` são strings `YYYY-MM-DD`
  ordenadas. Datasets de banda usam `_band: true` e são filtrados da legenda.
  A inicialização (`inicializar()`, linha ~1063) roda 13 fetches em `Promise.all`.
- `app.py` — padrão de rota admin de escrita: `admin_criar_usuario`
  (`app.py:342-362`): `@app.route('/admin/usuarios/criar', methods=['POST'])` +
  `@login_required` + `request.form.get` + `flash` + `redirect(url_for(...))`.
  CSRF global via Flask-WTF: forms POST de template precisam de
  `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` (ver
  forms existentes em `templates/admin_usuarios.html` como exemplar).
- `app.py:111-131` — `before_request` exige login exceto endpoints na lista
  `allowed_endpoints`; o novo endpoint público de leitura precisa ser
  adicionado lá.
- `database.py` — helpers de leitura seguem o padrão `with get_db() as conn:`
  (ex.: `get_media_agregada`, linha 482).
- Design system: `docs/DESIGN_SYSTEM.md` + tokens CSS em `static/css/tokens.css`
  (`var(--pe-*)` usados no dashboard — ver excertos `var(--pe-text-muted)`,
  `var(--pe-surface)` em `templates/dashboard.html:1040-1055`). Usar os tokens,
  não cores hardcoded novas.
- CSP (hardening anterior) permite scripts inline e jsDelivr — mas este plano
  NÃO adiciona dependência externa: o marcador é um plugin inline do Chart.js.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Suíte | `python -m pytest -q` | exit 0, 0 failed |
| App local (verificação manual) | `python app.py` e abrir `http://localhost:5080/dashboard` | gráfico com marcadores |

## Scope

**In scope**:
- `database.py` (3 funções novas: `listar_eventos(cargo=None)`, `criar_evento(...)`, `remover_evento(id)`)
- `app.py` (rotas: GET `/api/eventos` público; POST `/admin/eventos/criar` e POST `/admin/eventos/<id>/remover` com login)
- `templates/admin.html` (seção de cadastro/lista de eventos)
- `templates/dashboard.html` (fetch de eventos + plugin de marcadores no `chartHistoricoMulti`)
- `tests/test_dashboard.py` (testes das rotas)

**Out of scope** (NÃO tocar):
- Schema (a tabela já existe).
- Os gráficos `chartPres`/`chartGov` (marcadores só no histórico multi — MVP).
- Notificações/alertas de eventos.
- Detecção automática de eventos (é cadastro manual por design do PRD).

## Git workflow

- Commits em português por camada, ex.: `feat(eventos): CRUD admin + API pública`,
  `feat(eventos): marcadores verticais no gráfico de tendência`.

## Steps

### Step 1: Camada de dados

Em `database.py`, adicionar (padrão `with get_db() as conn:`):
- `listar_eventos(cargo: str | None = None) -> list[dict]` — todos os eventos,
  filtrando `WHERE cargo IN (?, 'geral')` quando `cargo` dado, ordenados por `data`.
- `criar_evento(data: str, titulo: str, cargo: str, impacto: str, descricao: str = None) -> int`
  — valida `impacto in {'positivo','negativo','neutro','indefinido'}` e
  `cargo in {'presidente','governador_rj','geral'}` e formato `YYYY-MM-DD`
  (via `date.fromisoformat`); lança `ValueError` se inválido.
- `remover_evento(evento_id: int) -> bool`.

**Verify**: `python -m pytest tests/test_database.py -q` → exit 0.

### Step 2: Rotas

Em `app.py`:
- `GET /api/eventos` (função `api_eventos`): `?cargo=` opcional; retorna
  `jsonify({"eventos": listar_eventos(cargo)})`. Adicionar `'api_eventos'` à
  lista `allowed_endpoints` do `before_request` (app.py:115-130). Com o plano
  009 aplicado, decorar com `@cache.cached(timeout=300, query_string=True)`.
- `POST /admin/eventos/criar` + `POST /admin/eventos/<int:evento_id>/remover`,
  ambos `@login_required`, seguindo byte-a-byte o padrão de
  `admin_criar_usuario` (form → flash → redirect para `admin`). `ValueError`
  do `criar_evento` vira `flash(..., "danger")`.

**Verify**: `python -m pytest tests/test_dashboard.py -q` → exit 0.

### Step 3: Admin UI

Em `templates/admin.html`, adicionar uma seção "Eventos da campanha" com:
form (data `type=date`, título, cargo select com os 3 valores, impacto select,
descrição opcional, `csrf_token` hidden — copiar o padrão de form de
`templates/admin_usuarios.html`) e tabela dos eventos existentes com botão
remover (form POST individual, também com csrf). Estilo: classes/tokens já
usados no próprio admin.html.

**Verify**: manual — logar no admin local, criar um evento, vê-lo na lista,
remover. (Sem browser disponível: `client.post('/admin/eventos/criar', ...)`
nos testes do Step 5 cobre o fluxo.)

### Step 4: Marcadores no gráfico

Em `templates/dashboard.html`:
1. No `inicializar()`, adicionar `carregarEventos()` ao `Promise.all`; a função
   faz `fetch('/api/eventos?cargo=presidente')` e guarda em variável global
   `eventosTimeline` (mesmo padrão de `ultimasSeries`).
2. Definir um plugin inline do Chart.js e registrá-lo **apenas** no
   `chartHistoricoMulti` (passar em `plugins: [eventosMarkerPlugin]` no config
   do `new Chart` da linha ~470):

```js
const eventosMarkerPlugin = {
  id: 'eventosMarkers',
  afterDatasetsDraw(chart) {
    if (!window.eventosTimeline?.length) return;
    const { ctx, chartArea, scales } = chart;
    const labels = chart.data.labels;               // datas formatadas
    const brutas = chart.$_datasBrutas || [];        // YYYY-MM-DD, setado na renderização
    window.eventosTimeline.forEach(ev => {
      const idx = brutas.indexOf(ev.data);
      if (idx === -1) return;                        // evento fora do range plotado
      const x = scales.x.getPixelForValue(idx);
      ctx.save();
      ctx.strokeStyle = 'rgba(10,34,64,0.35)';
      ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(x, chartArea.top); ctx.lineTo(x, chartArea.bottom); ctx.stroke();
      ctx.setLineDash([]);
      ctx.font = '10px "JetBrains Mono", monospace';
      ctx.fillStyle = 'rgba(10,34,64,0.6)';
      ctx.textAlign = 'left';
      ctx.fillText(ev.titulo.slice(0, 18), x + 4, chartArea.top + 10);
      ctx.restore();
    });
  }
};
```

   Na `renderizarHistoricoMulti`, após montar `todasDatas`, setar
   `chartHistoricoMulti.$_datasBrutas = todasDatas` (ou anexar via config
   `options.plugins` custom); eventos cujo `ev.data` não coincide com uma data
   plotada podem ser ancorados na data plotada mais próxima ≤ `ev.data` — se
   isso complicar, MVP aceita só datas coincidentes (documentar no commit).
3. Limite visual: se houver >8 eventos no range, desenhar só a linha (sem
   texto) a partir do 9º para não poluir.

**Verify**: `python -m pytest -q` → exit 0 (templates são cobertos por
`test_templates_refactor.py` — nenhuma regressão); verificação manual com um
evento seedado.

### Step 5: Testes

Em `tests/test_dashboard.py` (padrão dos testes de API existentes):
1. `GET /api/eventos` sem login → 200 (endpoint público) e shape
   `{"eventos": [...]}`.
2. `POST /admin/eventos/criar` sem login → redirect para login.
3. Fluxo logado (usar o padrão de login dos testes de `tests/test_usuarios.py`):
   criar evento válido → aparece em `/api/eventos`; impacto inválido → flash de
   erro e nada criado; remover → some da lista.

**Verify**: `python -m pytest tests/test_dashboard.py -q` → todos passam,
incluindo os novos.

## Test plan

Ver Step 5 (4+ testes novos). Verificação manual do desenho do marcador em
`http://localhost:5080/dashboard` com evento seedado.

## Done criteria

- [ ] `python -m pytest -q` exit 0
- [ ] `GET /api/eventos` público retorna eventos criados via admin
- [ ] Gráfico de tendência desenha linha vertical + título para evento dentro do range
- [ ] CSRF token presente nos forms novos
- [ ] `git status` limpo fora do escopo
- [ ] Linha de status atualizada em `plans/README.md`

## STOP conditions

- A estrutura de `renderizarHistoricoMulti`/labels divergir do descrito
  (drift no dashboard.html).
- O plugin inline conflitar com o plugin `datalabels` já registrado — se o
  marcador não renderizar após 2 tentativas, reportar com screenshot/console.
- Qualquer necessidade de mudar o schema.

## Maintenance notes

- Follow-up natural (fora deste MVP): tooltip do marcador com `descricao`;
  marcadores nos gráficos de barras; filtro por cargo no gráfico de governador.
- O plano 016 (house effects) e 017 (defasagem) tocam o mesmo template —
  executar em ordem 015 → 016 → 017.
- Revisor: checar que o endpoint público não expõe nada sensível (eventos são
  conteúdo editorial público por natureza).
