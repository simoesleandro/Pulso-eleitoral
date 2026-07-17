# Implementation Plans

Gerado pela skill `improve`. Três rodadas de auditoria: 2026-06-26 (planos
001–005, segurança/baseline — concluída), **2026-07-07** (planos 006–017,
confiabilidade/performance/higiene/produto) e **2026-07-16** (planos
018–030, bugs de dado/UX/segurança/dívida técnica/produto — ver seção
própria abaixo). Execute na ordem abaixo, respeitando as dependências. Cada
executor: leia o plano inteiro antes de começar, honre as "STOP conditions"
e atualize a linha de status ao terminar.

Planos 001–005 escritos contra o commit `2b49ba3`; planos 006–017 contra
`b3b92ef`; planos 018–023 contra `8d3827f`; planos 024–030 contra `f53d533`
(commit após o merge dos planos 018-023).

## Ordem de execução & status

| Plano | Título | Prioridade | Esforço | Depende de | Status |
|-------|--------|-----------|---------|------------|--------|
| 001 | Restaurar suíte de testes verde (baseline) | P1 | M | — | DONE |
| 002 | Gate de testes no CI antes do deploy | P1 | S | 001 | DONE |
| 003 | Endurecer `/admin/apply-db` (auth + validação do DB) | P1 | M | — | DONE |
| 004 | Exigir `SECRET_KEY` (remover fallback commitado) | P1 | S | — | DONE |
| 005 | Remover senha admin default `pulso2026` | P1 | S | — | DONE |
| 006 | Coleta: falha de persistência visível e parcial (fim da perda silenciosa de lote) | P1 | M | — | DONE |
| 007 | Validação tolerante da saída do Gemini (candidato malformado não descarta a pesquisa) | P1 | M | 006* | DONE |
| 008 | Cache de candidatos resiliente + invalidação no apply-db | P1 | S | — | DONE |
| 010 | Testes numéricos do poll-of-polls + caracterização dos KPIs | P1 | M | — | DONE |
| 009 | Cache nos endpoints, eliminação de N+1 e índices | P2 | M | **010** | DONE |
| 011 | Empacotamento (playwright, pyproject, lockfile) e docs corretos | P2 | S–M | — | DONE |
| 012 | DRY camada Gemini (prompts compostos + cascata única) | P2 | M | **007** | DONE |
| 014 | CLAUDE.md com regras não-óbvias do repo | P2 | S | 011* | DONE |
| 013 | Contrato do coletor no ABC + remoção de código morto | P3 | S | **006, 007** | DONE |
| 015 | Linha do tempo de eventos (F4 do PRD): CRUD admin + marcadores no gráfico | P2 | M | 009* | DONE |
| 016 | House effects por instituto (#5 roadmap / F7 PRD) | P3 | M | **010, 015** | DONE |
| 017 | Aviso de defasagem no dashboard (#10c roadmap) | P3 | S | **016** | DONE |
| 018 | `/api/rejeicao` aceita `cargo` (governador_rj deixa de ser invisível) | P1 | S | — | DONE |
| 019 | Corrige `_detectar_coletor` (urlparse não importado, todos institutos afetados) + registra Paraná | P1 | S | — | DONE |
| 020 | Rate limiting em `/login` e endpoints públicos `/api/*` | P1 | S–M | — | DONE |
| 021 | Dashboard responsivo — grids fixos e tabelas sem scroll | P2 | S | — | DONE |
| 022 | Padronizar erro/loading e acabar com fallback mockado silencioso | P2 | M | 021* | DONE |
| 023 | Recoleta de pesquisa existente atualiza metadados (não só intenções) | P2 | M | — | DONE |
| 024 | Configura `MAX_CONTENT_LENGTH` | P3 | S | — | DONE |
| 025 | Política mínima de senha ao criar usuário admin | P3 | S | — | DONE |
| 026 | Cache dos endpoints públicos usa chave normalizada | P3 | S | — | DONE |
| 027 | Cor do candidato nos gráficos por identidade, não posição | P3 | S | — | DONE |
| 028 | Acessibilidade básica do dashboard (headings, aria, gráficos) | P3 | M | — | DONE |
| 030 | Estende Governador RJ (histórico/eventos/alertas/house-effects) | P3 | M | — | DONE |
| 029 | Divide o god-module `database.py` em `db/` com façade de re-export | P4 | L | — | DONE |

Valores de status: TODO | IN PROGRESS | DONE | BLOCKED (motivo em uma linha) | REJECTED (motivo).
Dependências em **negrito** são obrigatórias; com `*` são só ordem recomendada
(mesmos arquivos — evita conflito de merge).

## Rodada 2026-07-16 (planos 018–023)

Auditoria completa (correção/bugs, cobertura de testes, segurança,
dependências, dívida técnica/DX, e uma auditoria dedicada de UX/UI do
dashboard público) disparada após a sessão que corrigiu os cards de RJ
puxando dado de presidente, o bug de `contratante` vazando `tipo`, datas
invertidas em recoleta e a fórmula desatualizada em `/metodologia` (essas
quatro correções já foram commitadas e deployadas antes desta auditoria,
não geraram plano).

Selecionados para virar plano nesta rodada: 018, 019, 020, 021, 022, 023.
Ordem recomendada: **018 → 019 → 020 primeiro** (independentes entre si,
todos P1/P2 de esforço baixo, tocam arquivos diferentes); **021 → 022**
depois (mesmo arquivo, `dashboard.html` — 021 primeiro evita conflito de
merge); **023** pode rodar em qualquer ponto (só toca `collectors/base.py`).

**Achado durante a execução (não estava na auditoria original)**: a 1ª
tentativa de executar o plano 019 parou porque `_detectar_coletor` (`app.py`)
usa `urlparse()` sem importar no escopo do módulo — só existe um import local
dentro de `_url_segura`, outra função. O `NameError` resultante é engolido
por um `except Exception` amplo, então a detecção de domínio **nunca
funcionou pra nenhum instituto** (confirmado ao vivo: `cnnbrasil.com.br`,
`datafolha.folha.uol.com.br` etc. caem todos no fallback `gazetadopovo`).
Plano 019 foi reescrito para incluir esse fix (prioridade elevada P2→P1) e
redisparado. Worktree da 1ª tentativa (`worktree-agent-afe28f1b13e14c6b0`)
foi abandonado sem commit.

### Segunda leva de planos desta rodada (024–030, escritos em 2026-07-16 após 018–023 mergeados)

Depois que 018–023 foram mergeados/deployados, os seguintes achados do
backlog abaixo viraram plano (contra o commit `f53d533`, pós-merge):

- **024** — `MAX_CONTENT_LENGTH`.
- **025** — política mínima de senha admin.
- **026** — cache chaveado por query-string normalizada.
- **027** — cor de candidato por identidade (`getCandidateColor` dead
  code + coloração por `dataIndex`).
- **028** — acessibilidade básica (headings, aria, contraste — a medição
  real de contraste do `--pe-text-muted` fica pro executor confirmar com
  ferramenta própria; uma conta manual durante a escrita do plano deu
  ~4.8:1, não ~4.1:1 como uma estimativa anterior sugeriu — tratar como
  "a confirmar", não como bug certo).
- **029** — split do god-module `database.py` em `db/` com façade
  (P4/L — o mais arriscado e menos urgente desta leva).
- **030** — estender Governador RJ com histórico/eventos/alertas/house-
  effects. Achado favorável durante a escrita: os 4 endpoints de backend
  (`/api/alertas`, `/api/eventos`, `/api/house-effects`,
  `/api/pesquisas/historico-multi`) **já aceitam `cargo=governador_rj`** —
  a feature é 100% frontend, sem mudança de backend.

Ordem recomendada pra essa leva: **024, 025, 026, 027 primeiro**
(independentes entre si, S de esforço); **028** depois (M, mesmo arquivo
`dashboard.html` que 027 — rodar em sequência evita conflito); **030**
quando houver espaço pra uma feature maior (M, também toca
`dashboard.html` — considerar depois de 027/028 pra evitar 3 PRs
conflitando no mesmo arquivo); **029** por último e isolado (L, maior
risco, não combinar com nenhum outro plano tocando `database.py` no mesmo
lote).

### Não confirmados / adiados (não viraram plano nesta rodada)

- Card "Cenário de Vitória — Governador RJ" fica fisicamente na seção
  Análise, não em Gov. RJ — inconsistência de arquitetura de informação. S
  esforço, achado de UX menor, não selecionado ainda.
- Vazamento de conexão SQLite em `collectors/base.py::_salvar_regional` e
  `collectors/quaest_regional.py::_salvar_regionais` (sem `try/finally` no
  `conn.close()`). S esforço, MED confiança de frequência real.
- `intencoes` sem `UNIQUE(pesquisa_id, candidato, tipo)` — o comentário
  "evita duplicação" no `INSERT OR REPLACE` não é garantido por constraint
  (hoje mitigado só porque os extratores dedupam antes de chamar `save()`).
  S esforço, MED risco (precisa migração pra dados já duplicados antes de
  criar o índice único).
- **[DEBT] Sequela do fix de `contratante` desta sessão**: a coluna nunca
  será populada por nenhum coletor (nenhum extrai isso do Gemini hoje) e o
  campo `metodologia` ficou morto em `collectors/base.py` e
  `collectors/paraná_pesquisas.py` (calculado, nunca lido). Decidir: virar
  feature real (ensinar o prompt Gemini a extrair contratante) ou remover o
  código morto.
- **[DEBT] Sequela da trava de data desta sessão**: quando
  `data_pesquisa_real > data_publicacao_atual`, a correção é rejeitada
  silenciosamente sem log — deveria logar um warning.
- `collectors/paraná_pesquisas.py` tem acento no nome do arquivo — risco de
  portabilidade entre filesystems (não confirmado como bug real, é risco
  latente). S esforço.
- Lockfile (`requirements.lock`) gerado com Python 3.12 mas produção/CI
  fixam 3.11 — sem quebra hoje, risco de deriva futura. Confiança baixa,
  "investigar" não "corrigir".

### Backlog anterior reconciliado nesta rodada

- **Resolvido silenciosamente, não constava atualizado no índice**: nenhum
  dos 11 itens do backlog de 2026-07-07 foi totalmente resolvido, EXCETO a
  suspeita de que "Monte Carlo retendo 30k dicts por cache-miss" já não
  existe mais no código atual (`simular_prob_vitoria_1_turno` e
  `simular_monte_carlo_cargo` só acumulam contador de vitórias) —
  reclassificado como resolvido/não confirmado, removido da lista abaixo.
- **Parcialmente resolvido**: helpers duplicados dos coletores —
  `collectors/utils.py` já existe (`_norm`/`detectar_uf`/`fetch_with_retry`)
  e `_salvar_regional` foi consolidado no `BaseCollector`, mas `_norm`
  local ainda duplicado em 4 arquivos e `HEADERS` redefinido em 7.
- **Ainda válidos, sem mudança**: testes de `sync_db.py`; god-module
  `database.py` (cresceu para 1943 linhas); 3 padrões de acesso a DB
  (`sqlite3.connect()` direto persiste em `collectors/base.py`,
  `collectors/quaest_regional.py` e agora também `app.py:933`);
  investigar necessidade real de Chromium no Dockerfile; cobertura HTTP de
  `/logout`, `/admin/status-coletores`, `/api/rejeicao`,
  `/admin/usuarios/*` (POST); fixture de coletor com HTML real +
  `genai.Client` mockado; pesquisas por macrorregião retornam vazio; lint/
  ruff; export CSV/JSON + API documentada.

## Ordem recomendada (rodada 2026-07-07)

1. **Confiabilidade primeiro** (a eleição é em outubro; o pipeline não pode
   perder pesquisa): 006 → 007 → 008.
2. **Rede de testes antes da perf**: 010 → 009.
3. **Higiene** em qualquer folga: 011 → 014; 012 e 013 depois de 006/007.
4. **Produto** por último e em sequência (todos tocam `dashboard.html`):
   015 → 016 → 017.

## Notas de dependência

- **009 depende de 010**: reescreve as queries de `get_kpis_avancados` e
  `get_historico_multi`; os testes numéricos/caracterização são o contrato de
  equivalência.
- **007 antes de 012 e 013**: os três tocam `collectors/gemini_extractor.py`
  e/ou `collectors/base.py`; 006 também toca `base.py`.
- **016 depende de 010** (reusa o helper `_seed` de `tests/test_agregacao.py`)
  e vem depois de 015; **017 depois de 016** (mesmo template).
- 008, 011 e 014 são independentes de tudo.

## Achados considerados e rejeitados (para não re-auditar)

- **XSS em `templates/admin_coletar_url.html`**: valores interpolados são
  inteiros do servidor; erros usam `textContent`. Não explorável. (2026-06)
- **Vazamento de processo Playwright** em `playwright_base.py`: coberto pelo
  context manager `sync_playwright`. Risco desprezível. (2026-06)
- **Dedup sem dimensão de data** em `collectors/base.py`: by-design (uma URL de
  release = uma pesquisa, atualizada in-place). (2026-06)
- **"Dockerfile instala Playwright 2×"**: não confirmado na re-auditoria de
  2026-07 — pip instala 1×; as outras linhas são o binário Chromium e as deps
  de SO (passos distintos). O que existe é a questão "prod precisa de Chromium?"
  — ver backlog. (2026-07)
- **`.exe` commitados no git**: não confirmado — `.gitignore` exclui `*.exe` e
  o histórico está limpo; os instaladores em `docs/` são untracked (só ocupam
  disco local). (2026-07)

## Hardening de segurança — 2ª rodada (2026-06-27) — DONE

CSRF (Flask-WTF) nas rotas de escrita; cookies HTTPONLY/SAMESITE/SECURE;
headers via `after_request` (XFO, nosniff, HSTS, Referrer-Policy, CSP);
guarda anti-SSRF em `/admin/coletar-url`. Sem rotas de escrita abertas.

## Backlog (auditado, não planejado — disponível para virar plano)

Da rodada 2026-07-07:
- ~~`detectar_variacoes_bruscas`: `GROUP BY` com colunas não-agregadas~~ —
  **RESOLVIDO** no commit `347d8d3` ("fim do GROUP BY arbitrário"), antes da
  auditoria de 2026-07-16 confirmar.
- Testes para `scripts/sync_db.py` (orquestrador do push a produção; o lado
  receptor `apply-db` já é coberto). Mock de `subprocess.run`/`requests.post`.
  Reconfirmado ainda válido em 2026-07-16.
- Split do god-module `database.py` (**1943 linhas** em 2026-07-16, era 1695
  em 2026-07-07 — cresceu, não encolheu) em `db/…` com façade de re-export.
  L, fazer só com a suíte 010 no lugar.
- Consolidar helpers duplicados dos coletores — **parcialmente resolvido**:
  `collectors/utils.py` já existe (`_norm`/`detectar_uf`/`fetch_with_retry`)
  e `_salvar_regional` foi consolidado no `BaseCollector`, mas `_norm` local
  ainda duplicado em `cnn_brasil.py`, `gazetadopovo.py`,
  `quaest_regional.py`, `datafolha.py`, e `HEADERS` redefinido em 7
  arquivos. `verita.py:72-76` tem bloco `_salvar_regional` morto/comentado
  a remover junto.
- Convergir os 3 padrões de acesso a DB (`get_db()` vs `get_conn()` vs
  `sqlite3.connect` direto nos coletores) e a política engolir-vs-propagar.
  Reconfirmado em 2026-07-16 — `sqlite3.connect()` direto também apareceu em
  `app.py:933` (`/admin/apply-db`), além dos coletores.
- ~~Monte Carlo: não reter 30k dicts de runs por cache-miss~~ — **não
  encontrado no código atual** (2026-07-16): `simular_prob_vitoria_1_turno`
  e `simular_monte_carlo_cargo` já só acumulam contador de vitórias, não uma
  lista de dicts por run. Removido da lista ativa.
- Injeção de prompt de 2ª ordem: nomes extraídos de fontes scrapeadas fluem
  para o prompt de análise (`app.py:462-464`) e para HTML do Telegram
  (`notifier.py:82-93`) — sanitizar/escapar. Severidade baixa (superfície
  interna), mas real.
- SSRF TOCTOU em `_url_segura` (`app.py:752-766`): valida DNS separado do
  fetch — pin do IP resolvido. Só alcançável por admin logado.
- Dockerfile: verificar se produção realmente precisa do Chromium (~150MB por
  imagem); scheduler é gated fora do Fly, mas `/admin/coletar-url` em prod
  pode usar Playwright — investigar antes de cortar.
- Cobertura de rotas: `/logout`, `/admin/status-coletores`, `/api/rejeicao`,
  `/admin/usuarios/*` no nível HTTP.
- Testes de coletor com fixture HTML real via `genai.Client` mockado (hoje o
  conftest substitui o extrator inteiro por um mini-parser).
- Pesquisas com recorte por macrorregião retornam vazio (limitação conhecida
  do extrator). Baixa prioridade.

Da rodada 2026-06 (ainda válidos): lint/format/typecheck (ruff) — decisão de
tooling do dono; exportação pública CSV/JSON + API documentada (#9 do roadmap
— achado de direção, não selecionado nesta rodada).
