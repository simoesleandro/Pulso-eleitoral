# Pulso Eleitoral

Radar de pesquisas eleitorais brasileiras (presidente + governador RJ, eleições
2026). Flask + SQLite + Gemini, com coleta via Playwright/BeautifulSoup e
dashboard público (Chart.js).

## Comandos

```bash
python -m pytest -q                    # suíte de testes (config em pyproject.toml)
python app.py                          # roda o app localmente (Waitress/Flask)
python coletar.py                      # coleta manual (todos os institutos)
python scripts/sync_db.py              # sincroniza banco local → Fly.io
python scripts/sync_tse.py             # registro oficial do TSE (dry-run)
python scripts/sync_tse.py --aplicar   # ...e grava os casamentos
```

`TESTING=True` precisa estar setado **antes** de importar `app`/`database` —
todo arquivo em `tests/` faz isso na primeira linha. Um script novo que
importe `app` em contexto de teste precisa do mesmo cuidado.

## Arquitetura em 5 linhas

`app.py` roda localmente como serviço Windows (WinSW, `PulsoEleitoral.xml`)
com um `BackgroundScheduler` interno que dispara `run_all_collectors()` às
segundas e quintas, 10h (`app.py`, 2x/semana para poupar a cota de gasto
mensal do Gemini; gate: desliga sob `TESTING=True` e sob `FLY_APP_NAME`) →
coleta com todos os `ALL_COLLECTORS` (`collectors/__init__.py`, fonte única
de verdade da lista — `coletar.py` também importa dali) → grava em SQLite
local → se houve pesquisa/intenção nova, chama `sync_para_fly()`
(`scripts/sync_db.py`) automaticamente, que sobe o arquivo e chama
`POST /admin/apply-db` → Fly.io troca `/data/pulso.db` e reinicia o processo
→ dashboard público serve os dados. **O Fly nunca coleta**. `coletar.py`
continua existindo para coleta manual/ad-hoc e replica o mesmo contrato
(conta pesquisas/intenções antes/depois, sincroniza só se houve dado novo),
mas também envia notificações Telegram e roda alerta de variação brusca —
coisas que o scheduler interno do `app.py` não faz.

## Regras que quebram deploy ou banco de produção

- **`sync_db.py` ≠ deploy**: ele só troca o SQLite e reinicia o processo.
  Só `flyctl deploy` reconstrói a imagem/código. Mudança de código sem commit
  na `main` (que dispara o CI → deploy) não chega à produção via sync.
- **`/admin/apply-db`** troca o banco de produção inteiro (fail-closed sem
  `ADMIN_PASS`, `app.py:852-855`). Não mexer nessa rota sem
  `tests/test_apply_db.py` verde — ela já cobre auth, path traversal e
  validação de integridade do SQLite recebido.
- **Playwright** é importado no load por 7 módulos de coletores; está
  declarado em `requirements.txt` (`playwright>=1.40.0`) desde jul/2026 — CI e
  Dockerfile instalam do `requirements.lock` (gerado via `pip-compile`, sob
  Python 3.12 local; produção/CI/Docker fixam 3.11 — divergência de versão do
  interpretador de geração, não de execução).
- **Deploy**: push na `main` → GitHub Actions roda `pytest` como gate →
  `flyctl deploy`. Um teste vermelho bloqueia o deploy.

## Domínio

- **Tabela `candidatos`** é a fonte única de verdade para normalização de
  nomes, espectro político e cores — populada no `init_db`, cacheada em
  memória por processo (`database._carregar_candidatos_cache`). A falha
  transitória na carga não é memoizada (evita envenenar a normalização para
  sempre); `apply-db` invalida esse cache junto com o Flask-Caching.
- **Agregação** (`get_media_agregada`, poll-of-polls) usa só pesquisas
  `estimulada` (ou `tipo IS NULL`, legado) e pondera por amostra × recência
  (`0.9 ** dias`), uma pesquisa por instituto — documentado em `/metodologia`.
  O peso de amostra tem teto em **2× a mediana** da janela (`_teto_amostra`),
  para que um tracking de amostra atípica não dite a média sozinho. Percentil
  90 foi tentado e descartado: com 5–10 institutos o nearest-rank do p90
  devolve o próprio máximo e o teto nunca morde (teste de regressão em
  `tests/test_agregacao.py`).
  O contrato numérico dessa lógica está fixado em `tests/test_agregacao.py`;
  qualquer mudança na fórmula exige atualizar os dois (testes e
  `/metodologia`) e é o gate de equivalência para refatorar
  `get_kpis_avancados`/`get_historico_multi`.
- **Contrato do coletor**: `BaseCollector` exige `_get_page` (abstrato — usado
  por `/admin/coletar-url`) e `_parse_release` (default: delega ao parser
  Gemini). Um coletor novo sem `_get_page` falha na instanciação, não em
  request. `collectors/paraná_pesquisas.py` existe mas não está em
  `ALL_COLLECTORS` — stub nunca implementado (`fetch()` retorna `[]`).
- **Extração via Gemini** (`collectors/gemini_extractor.py`): saída do LLM é
  tratada como não-confiável — candidato malformado é descartado
  individualmente (`_to_pct` coage percentuais em formatos comuns), nunca
  derruba a pesquisa inteira. `gerar_com_cascata()` é o único helper de
  cascata de modelos/retry (503) — não duplicar essa lógica em rota nova.
  `PROMPT_EXTRACAO`/`PROMPT_EXTRACAO_REGIONAL` nascem de uma base
  compartilhada (`_PROMPT_BASE_EXTRACAO`) + deltas nomeados.
- **Coleta**: `collectors/base.py.save()` commita cada release
  individualmente — uma falha num release não derruba as demais do mesmo
  lote. `run()` retorna
  `{"status": "ok"|"vazio"|"parcial"|"erro", "salvas", "falhas"}`. `"vazio"`
  (rodou sem exceção, salvou zero) é distinto de `"ok"` de propósito: antes
  os dois eram `"ok"` e coletor quebrado ficava invisível no log.
- **Registro do TSE** (`tse/`): `dataset.py` baixa/parseia o CSV de dados
  abertos (latin-1, `;`, sentinela `#NULO#`), `sync.py` faz upsert em
  `pesquisas_tse` por protocolo **preservando `pesquisa_id`** (re-sync diário
  não pode desfazer casamento), `matcher.py` liga registro ↔ pesquisa por
  `institutos.cnpj` + janela de datas. `pesquisa_id IS NULL` é a fila de
  cobertura. Regras não-óbvias: o casador **nunca resolve ambiguidade por
  chute** (falso positivo envenena a série em silêncio); o backfill de
  `tamanho_amostra` só preenche quando falta, porque o TSE guarda a amostra
  *registrada* e o release publica a *realizada*; e `popular_cnpjs` roda em
  `init_db` **depois** do `seed.sql` (antes dele os institutos não existem e
  o UPDATE não acha linha). O sync **não chama o Gemini** — por isso roda
  diariamente (9h30), enquanto a coleta roda 2x/semana por causa da cota.
- **Cache**: 13 endpoints de leitura usam `@cache.cached(timeout=300)`
  (`query_string=True` onde há parâmetros). `apply-db` já invalida tudo via
  `cache.clear()`. Sob `TESTING=True` o cache vira `NullCache` (SimpleCache é
  global no processo e vazaria entre testes).

## Convenções

- Código e commits em **português**; mensagens estilo conventional commits
  (`fix(...)`, `feat(...)`, `refactor(...)`, `chore(...)`, `perf(...)`,
  `test(...)`, `docs(...)` — ver `git log --oneline`).
- Testes pytest; `tests/conftest.py` mocka Playwright (`_get_page_playwright`
  retorna `""`) e o extrator Gemini globalmente (exceto para
  `test_gemini_extractor.py`, que testa o extrator de verdade com
  `genai.Client` mockado).
- Config do pytest em `pyproject.toml` (`testpaths`, `addopts`).

## Planos de melhoria

`plans/README.md` é o índice de planos executáveis (auditoria da skill
`improve`) — ordem recomendada, dependências e status (TODO/DONE/BLOCKED) de
cada um.
