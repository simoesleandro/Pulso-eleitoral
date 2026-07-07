# Implementation Plans

Gerado pela skill `improve`. Duas rodadas de auditoria: 2026-06-26 (planos
001–005, segurança/baseline — concluída) e **2026-07-07** (planos 006–017,
confiabilidade/performance/higiene/produto). Execute na ordem abaixo,
respeitando as dependências. Cada executor: leia o plano inteiro antes de
começar, honre as "STOP conditions" e atualize a linha de status ao terminar.

Planos 001–005 escritos contra o commit `2b49ba3`; planos 006–017 contra `b3b92ef`.

## Ordem de execução & status

| Plano | Título | Prioridade | Esforço | Depende de | Status |
|-------|--------|-----------|---------|------------|--------|
| 001 | Restaurar suíte de testes verde (baseline) | P1 | M | — | DONE |
| 002 | Gate de testes no CI antes do deploy | P1 | S | 001 | DONE |
| 003 | Endurecer `/admin/apply-db` (auth + validação do DB) | P1 | M | — | DONE |
| 004 | Exigir `SECRET_KEY` (remover fallback commitado) | P1 | S | — | DONE |
| 005 | Remover senha admin default `pulso2026` | P1 | S | — | DONE |
| 006 | Coleta: falha de persistência visível e parcial (fim da perda silenciosa de lote) | P1 | M | — | TODO |
| 007 | Validação tolerante da saída do Gemini (candidato malformado não descarta a pesquisa) | P1 | M | 006* | TODO |
| 008 | Cache de candidatos resiliente + invalidação no apply-db | P1 | S | — | TODO |
| 010 | Testes numéricos do poll-of-polls + caracterização dos KPIs | P1 | M | — | TODO |
| 009 | Cache nos endpoints, eliminação de N+1 e índices | P2 | M | **010** | TODO |
| 011 | Empacotamento (playwright, pyproject, lockfile) e docs corretos | P2 | S–M | — | TODO |
| 012 | DRY camada Gemini (prompts compostos + cascata única) | P2 | M | **007** | TODO |
| 014 | CLAUDE.md com regras não-óbvias do repo | P2 | S | 011* | TODO |
| 013 | Contrato do coletor no ABC + remoção de código morto | P3 | S | **006, 007** | TODO |
| 015 | Linha do tempo de eventos (F4 do PRD): CRUD admin + marcadores no gráfico | P2 | M | 009* | TODO |
| 016 | House effects por instituto (#5 roadmap / F7 PRD) | P3 | M | **010, 015** | TODO |
| 017 | Aviso de defasagem no dashboard (#10c roadmap) | P3 | S | **016** | TODO |

Valores de status: TODO | IN PROGRESS | DONE | BLOCKED (motivo em uma linha) | REJECTED (motivo).
Dependências em **negrito** são obrigatórias; com `*` são só ordem recomendada
(mesmos arquivos — evita conflito de merge).

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
- `detectar_variacoes_bruscas` (`database.py:405-441`): `GROUP BY` com colunas
  não-agregadas — o alerta pode atribuir instituto/valor de uma linha
  arbitrária. MED confiança, M esforço. Corrigir com subquery de max-|Δ| por
  candidato + teste de caracterização.
- Testes para `scripts/sync_db.py` (orquestrador do push a produção; o lado
  receptor `apply-db` já é coberto). Mock de `subprocess.run`/`requests.post`.
- Split do god-module `database.py` (1695 linhas, ~6 responsabilidades) em
  `db/…` com façade de re-export. L, fazer só com a suíte 010 no lugar.
- Consolidar helpers duplicados dos coletores (`_norm` ×5, dedup de links,
  `_salvar_regional` ×3, `HEADERS`) em `collectors/utils.py`/`BaseCollector`.
- Convergir os 3 padrões de acesso a DB (`get_db()` vs `get_conn()` vs
  `sqlite3.connect` direto nos coletores) e a política engolir-vs-propagar.
- Monte Carlo: não reter 30k dicts de runs por cache-miss (acumular contador
  de vitórias inline). Mitigado pelo cache de 300s.
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
