# Auditoria — setembro de 2026

Diagnóstico de dois problemas relatados no dashboard e registro das
correções feitas em seguida.

- **Problema 1:** pesquisas de governador do RJ não aparecem no dashboard.
- **Problema 2:** bugs na exibição dos gráficos e na classificação do tipo de
  pesquisa (estimulada / espontânea / rejeição / cenários).

| | |
|---|---|
| Data | 2026-09-29 |
| Base auditada | `765e580` (main de 05/08/2026) |
| Lotes de correção | A, B, C e D1 concluídos; D2a na `main` com deploy pendente; D2a2 em andamento (ver [Status dos lotes](#status-dos-lotes)) |

## Resumo

A pesquisa de governador mais recente aparece, mas quase todo o resto da seção
fica vazio. Só 3 das 33 pesquisas de governador RJ registradas no TSE
chegaram à produção, todas do Paraná, e a mais nova era de 30/07. Todas as
análises usam janela de 30 dias.

O zigue-zague dos gráficos vem de misturar institutos numa mesma linha, não
de cenários empilhados na mesma pesquisa. O toggle estimulada/espontânea
estava quebrado por cache, e não existe nenhuma intenção espontânea de
presidente no banco de produção.

## Método

- **Somente leitura.** Nenhum arquivo do projeto e nenhum banco foram
  alterados durante o diagnóstico.
- **Banco local:** lido com SQLite em modo somente leitura. Não é
  representativo: 1 pesquisa, gravada em 05/08. A coleta migrou para o Fly
  em jul/2026 (commit `906c6de`).
- **Produção:** o `flyctl` não estava instalado na máquina da auditoria. A
  leitura foi feita pelos GETs públicos: `/api/v1/export/pesquisas.csv`
  (todas as pesquisas e intenções) e as rotas `/api/*`. A tabela
  `candidatos` de produção não foi lida diretamente.
- **Registro do TSE:** snapshot da tabela `pesquisas_tse` do banco local.
- **Números de linha:** as evidências da tabela abaixo citam a base
  `765e580`. Depois dos lotes A e B, várias linhas mudaram de lugar.

## Números de base (produção, 2026-09-29)

- 44 pesquisas e 330 intenções.
  - 41 de presidente.
  - 3 de `governador_rj`, todas do Paraná: 03/06 (só espontânea), 01/07 e
    30/07.
- `cargo` NULL ou vazio: 0, no local e em produção. Não existem outros
  valores de cargo.
- Registro do TSE para governador RJ: 33 pesquisas (31 estaduais).
  - Vetor Arrow 13, Prefab Future 5, Paraná 4, Verita 3, Quaest 2,
    Real Time 2, Gerp 2, 100 Cidades 1, Agora 1.
  - Só 1 das 33 está casada com uma pesquisa coletada.

## Os 18 bugs

**Status:** ✅ corrigido · ⬜ aberto. Os hashes estão na seção
[Status dos lotes](#status-dos-lotes).

| # | Bug | Evidência | Causa raiz | Correção proposta | Risco | Status |
|---|---|---|---|---|---|---|
| 1 | Verita quebra em todo PDF de governador RJ, e a coleta inteira do Verita vira "erro" | `collectors/verita.py:158` usa `date.today()` sem importar `date` (imports nas linhas 14–20). Reproduzido: `NameError: name 'date' is not defined`. Produção: Verita com 1 pesquisa, a última de 04/04; o TSE tem 3 de governador RJ | Import faltando. A exceção sobe por `fetch()` e o `run()` descarta tudo, inclusive o nacional | Importar `date`; isolar a falha por PDF | Baixo | ✅ Lote A (`8c4a436`, `6d311f0`). Ver item novo N1 |
| 2 | Quaest nunca grava governador | `_inferir_cargo` (`quaest.py:75`, `atlas.py:73`) só é chamado por testes (`test_quaest.py:66`, `test_atlas.py:66`). O `_parse_release` usa `PROMPT_EXTRACAO`, que manda ignorar pesquisas estaduais (`gemini_extractor.py:173-178`). Produção: Quaest com 0 pesquisas; o TSE tem 2 de governador RJ | Inferência de cargo é código morto; o prompt nacional descarta conteúdo estadual | Mandar releases de governador RJ para `extrair_governador_rj`, como o Paraná faz, com critério que não use `'governo'` | Médio: `test_quaest.py:73` exige que `'governo'` resulte em governador (casaria com "avaliação do governo") | ⏸ Adiado para depois do 1º turno: ver [N5](#n5--quaest-descoberta-quebrada-e-números-do-rj-só-em-imagem) |
| 3 | Agregadores (Gazeta, CNN, Poder360) descartam governador. Vetor, Prefab, Real Time e Gerp não têm caminho algum | Com UF detectada, os dados vão para `_salvar_regional`, que filtra só presidenciáveis (`_filtrar_presidenciais` em `base.py`; `gazetadopovo.py:155-158`; `cnn_brasil.py:85-88`). Sem UF, cai no prompt nacional. Resultado: 0 de 22 pesquisas desses institutos | Governador só é previsto por coletor próprio de instituto | Com UF RJ e texto de governador: `extrair_governador_rj` + gravar com `cargo=governador_rj` | Médio: a detecção de instituto do Poder360 cai em `inst_id = 1` (Datafolha) quando não reconhece o nome (`_parse_com_gemini`) | ⬜ |
| 4 | Datafolha manda HTML cru para o extrator de governador e tem falso positivo no roteamento | `datafolha.py:381` passa o `html` sem limpar, e o extrator corta em 8000 caracteres (`gemini_extractor.py:565`). `'rio' in url` casa com "cenarios": uma URL "…lula-lidera-em-todos-os-cenarios-e-governo…" vai para o extrator de governador | Texto não limpo como em `_parse_com_gemini`; busca por substring solta | Limpar o texto com BeautifulSoup; regex com fronteira de palavra (`rio-de-janeiro`, `\brj\b`) | Baixo | ✅ Lote D2a (`5daf944`) |
| 5 | Paraná trata RS, RN e releases nacionais como se fossem do RJ | Os marcadores em `paraná_pesquisas.py:36` incluem `"rio"`. `_e_release_rj` dá True para "…rio-grande-do-sul…", "…rio-grande-do-norte…" e "cenarios-presidente-brasil…". Só os 10 primeiros links são processados (linha 177) | Marcador genérico demais | Remover o `"rio"` solto e manter só marcadores específicos | Baixo | ✅ Lote D2a (`926f4e9`) |
| 6 | Um único `tipo` por release e reextração a cada coleta; o estimulado some, e em presidente não existe espontânea | `base.py:340` e o `_build_items` do Paraná (linha 134) aplicam um só `tipo` a todos os candidatos. Deduplicação por instituto+cargo+URL (`base.py:138`), com DELETE e reinserção (`base.py:186`). Produção: a pesquisa 30 (Paraná, 03/06) só tem espontânea; presidente tem 312 linhas, todas estimuladas | O extrator devolve um bloco só; o `save` sobrescreve a cada execução, e uma nova extração do Gemini pode trocar o tipo | Extrator devolve lista de blocos `{tipo, candidatos}`; gravar por (pesquisa, tipo); não reextrair pesquisa já casada com o TSE | Médio: muda o contrato do `save` (`test_collectors`) | ⬜ |
| 7 | Candidatos novos de governador nunca entram em banco já existente | `db/candidatos.py:71` sai se a tabela tem qualquer linha. Local: 31 linhas, governador só com Paes, Castro, Freixo e Neves (o seed tem 13). Produção: as cores de Garotinho (`#C0392B`) e Ruas (`#5a7184`) são a paleta de fallback (`pesquisas.py:15`), não as do seed (`#BA7517`, `#C0392B`). "Garotinho" e "Anthony Garotinho" viram séries separadas | O seed só roda com a tabela vazia | Migração idempotente: `INSERT OR IGNORE` por `nome_canonico` + juntar apelidos | Médio: não pode sobrescrever `status`/`ativo` editados à mão | ✅ Lote C (`6802740`, `9653baf`) |
| 8 | Seção de governador vazia: média, Monte Carlo, KPIs e rejeição | `/api/media-agregada?cargo=governador_rj` devolve `candidatos: []`. Com `dias=365`, só 4 de 7 candidatos (somem Garotinho, com 11,0%, Busnello e Cyro). Monte Carlo com `candidatos_simulados: []`; KPIs com `top2_soma: 0.0` | Janela de 30 dias (`pesquisas.py:242`) contra última pesquisa de 61 dias atrás, mais o corte de pelo menos 2 entradas (`pesquisas.py:310`) | Primeiro resolver a cobertura (#1–5). Depois, com dado escasso, mostrar a última pesquisa com aviso de defasagem | Alto se mexer no corte de 2 entradas: contrato de `test_agregacao.py` + `/metodologia` | ⬜ |
| 9 | Toggle estimulada/espontânea de presidente devolve o que estiver em cache | `app.py:857`: `@cache.cached(timeout=300)` sem chave própria (o padrão do flask-caching 2.4 é `query_string=False`). Produção: `?tipo=espontanea` devolveu `"tipo":"estimulada"` com os mesmos dados de `?tipo=estimulada`, embora não exista nenhuma espontânea | A chave de cache ignora `?tipo`. O filtro no SQL existe (`pesquisas.py:67-72`) mas não chega a rodar | Chave normalizada incluindo o `tipo`; teste com SimpleCache | Baixo | ✅ Lote A (`e2b4b6d`) |
| 10 | Zigue-zague nas séries | Não há cenários empilhados: 0 pesquisas com candidato repetido por tipo e 0 com soma acima de 105%. `get_historico_multi` (`pesquisas.py:504-546`) põe todos os institutos numa linha só. Lula em 23/09: 43,0 / 41,0 / 46,3 / 40,0; Flávio em 16/09: Gerp 44 × PoderData 36. No front, `porData[d.data] = d` (`dashboard.html:605`, `:719`) sobrescreve pontos da mesma data, e o tooltip pega o primeiro da data | Série por candidato em vez de candidato+instituto; índice só por data | Pontos por instituto (dispersão) + uma linha de tendência agregada; indexar por data+instituto | Médio (visual) | ⬜ |
| 11 | Escolha dos "top 3" mistura tipos e cenários antigos | `get_top_candidatos` (`pesquisas.py:489-501`) faz média de todo o histórico sem filtrar tipo, curadoria ou status. Tarcísio (4 pesquisas Datafolha de 2025, cenário sem Flávio) fica em 3º. No governador, Garotinho passa Ruas porque a espontânea de Ruas (2,7) puxa a média dele para baixo | Ranking sem filtros | Montar o ranking a partir de `get_media_agregada` | Baixo | ⬜ |
| 12 | Pesquisa duplicada | Real Time, pesquisas 22 e 28: percentuais idênticos, datas 21/07 e 20/07, dois registros sintéticos `GEN-` | Deduplicação por URL (`base.py:138`) | Deduplicar também por instituto + data ±3 dias + percentuais iguais | Baixo | ⬜ |
| 13 | Banda de incerteza zerada | Datafolha: 5 pesquisas com margem 0,0 e 6 com amostra 0 | `base.py:198/201` gravam 0 em vez de NULL quando o dado falta | Gravar NULL; o gráfico trata como "sem banda" | Baixo | ⬜ |
| 14 | Funções auxiliares do Monte Carlo não seguem os filtros da média | `monte_carlo.py:60-75` (margem) e `:78-90` (% que pode mudar de voto): sem janela e sem curadoria. `:92-105` (bucket de indecisos): sem filtro de tipo. `:272-288` (contagem): sem curadoria | Filtros duplicados à mão, divergindo de `get_media_agregada` | Um filtro base único compartilhado | Baixo. Efeito em produção não verificado | ⬜ |
| 15 | Rejeição sem normalização de nomes nem curadoria | `/api/rejeicao?cargo=presidente`: "Clariana Barao" e "Clariana Barão" separados; "Veterinário Wilson Grassi" e "Wilson Grassi" também. A consulta (`app.py:1393-1401`) não filtra por `agregar` | `normalizar_nome` devolve o nome cru quando ele não está no roster | Completar o roster + filtro `agregar = 1` | Baixo | ⬜ |
| 16 | Testes acessavam a rede real e o Gemini | `test_run_all_collectors` (`test_scheduler.py:40`) levou 137s sozinho, com `400 API_KEY_INVALID` da API real no log. O conftest só mockava `extrair_com_gemini`. A chave falsa vazava de `test_dashboard.py:305` (`os.environ` sem restaurar); o `.env` real era carregado por `load_dotenv` | Mock incompleto; variáveis de ambiente vazando entre testes | Mockar os extratores e o HTTP; `monkeypatch.setenv`; `.env` fora da suíte | Baixo | ✅ Lote B (`3697676`, `518a450`) |
| 17 | Front mostrava números fabricados | `dashboard.html:347-353`: "Quaest (Fallback)" com Cláudio Castro 23,8% (status `inelegivel`). Também havia "Atlas (Fallback)" para presidente | Fallback com dado inventado | Estado vazio explícito, sem números | Baixo | ✅ Lote A (`6d64a2c`) |
| 18 | Documentação desatualizada | CLAUDE.md dizia "O Fly nunca coleta", mas `coleta_agendada.yml` chama `/admin/coletar-async` | Migração de 30/07 (`906c6de`) não refletida no documento | Atualizar a seção de arquitetura | Nenhum | ✅ Lote A (`b87ed2e`); trava do sync descrita em `60b2377` |

### Respostas diretas

- **Filtro fixo que exclua governador (A5):** a API e o JS não têm. O
  Paraná tem `agregar = 1`, e o `tipo=estimulada` fixo em
  `dashboard.html:691` só tira a pesquisa 30. O que esvazia a seção é a
  janela de 30 dias (#8) somada à falta de cobertura (#1–5).
- **Valores de tipo (B1):** só `estimulada` e `espontanea`. Nenhuma
  variação de grafia ou maiúscula, nenhum NULL. O problema é a falta de dado
  espontâneo (#6), não inconsistência de valores.
- **Cenários empilhados (B2):** não há. O zigue-zague vem de #10, #11 e #12.
- **O toggle filtra na API? (B3):** sim, no SQL, mas o cache anulava o
  filtro (#9, corrigido). Governador não tem toggle.
- **Poll-of-polls e Monte Carlo misturam coisas? (B4):**
  - A média usa só estimulada.
  - Rejeição e 2º turno ficam em tabelas próprias.
  - Há uma pesquisa por instituto, com um só cenário cada.
  - A mistura está nas funções auxiliares (#11, #14) e numa inconsistência
    de contagem: o corte de 2 entradas conta a janela inteira, não as
    pesquisas selecionadas. Por isso Clariana Barão aparece na média com
    `pesquisas_count: 1`.
- **Suíte na auditoria (B5):** 295 passaram, 0 falharam, em 259s. Nenhum
  teste cobria #1, #7 ou #9.

## Status dos lotes

### Lote A — concluído e publicado

Houve um rebase sobre o commit remoto `4f77bbc` ("alinha badge de fallback
com tipo selecionado"). O único conflito foi em `carregarPresidente()`: ficou
o estado vazio do Lote A, e o selo continua mostrando o tipo selecionado no
toggle, que era a intenção do remoto. Os hashes abaixo são os de depois do
rebase.

| Commit | Bug | O que fez |
|---|---|---|
| `6d64a2c` | #17 | Removeu os fallbacks fabricados de governador e presidente; estado vazio explícito |
| `e2b4b6d` | #9 | Chave de cache normalizada em `/api/pesquisas/presidente`. As outras 19 rotas cacheadas foram auditadas: nenhuma com o mesmo bug |
| `8c4a436` | #1 | `from datetime import date` no Verita |
| `6d311f0` | #1 | Falha em um PDF é isolada: `log.error`, entra no resumo e o status fica `parcial` |
| `b87ed2e` | #18 | CLAUDE.md: a coleta roda no Fly via GitHub Actions |

### Lote B — concluído e publicado

| Commit | Bug | O que fez |
|---|---|---|
| `60b2377` | novo (risco de perda de dados) | A coleta local não chama mais `sync_para_fly()`. O sync exige `--force-sync` e aborta se o banco local tiver menos pesquisas que produção, ou se não conseguir contar as de produção |
| `3697676` | #16 | `.env` neutralizado na suíte; chaves de API removidas do ambiente em cada teste; `monkeypatch.setenv` no lugar de `os.environ` |
| `518a450` | #16 | Rede, Playwright e cliente Gemini bloqueados na suíte padrão. Tentativa engolida pelo código também reprova o teste. Marker `network` fica fora da execução padrão e do CI |

Suíte depois do Lote B: **319 passed, 3 deselected, em ~54s**. Antes eram
~220s, porque os testes batiam na rede real. O CI (`fly-deploy.yml`) roda
`python -m pytest -q`, que herda o `-m 'not network'` do `pyproject.toml`.

### Lote C — concluído e aplicado em produção

| Commit | Bug | O que fez |
|---|---|---|
| `6802740` | #7 | Migração idempotente do roster em todo `init_db`: `INSERT OR IGNORE` por `nome_canonico` e soma dos apelidos do seed que faltam. Campo de candidato existente nunca é alterado |
| `9653baf` | #7 | `scripts/migrate_unificar_apelidos.py`: renomeia as intenções gravadas com apelido para o nome canônico. Dry-run por padrão, `--aplicar` grava; conflito na mesma pesquisa e tipo não é unificado, só reportado |

Em produção:

- **Roster:** a migração inseriu 9 candidatos.
- **Unificação do Garotinho:** aplicada. "Garotinho" e "Anthony Garotinho"
  viraram uma série só.
- **Backup** do banco de antes do Lote C: `/data/backup_pre_lote_c.db`, no
  volume do Fly.

### Mudanças de infra — período eleitoral (até 25/10)

Commit `580664d` (`fly.toml`):

- **Máquina sempre ligada:** `auto_stop_machines = 'off'` e
  `min_machines_running = 1`. Causa: o auto stop do Fly derrubava a máquina
  com a coleta rodando. A coleta roda numa thread em background, disparada
  por `POST /admin/coletar-async`, e o auto stop decide pelo tráfego HTTP,
  não pelo trabalho em andamento no processo. Evidência: log de produção
  às 14:57:28 com "autostopping machine" durante a coleta.
- **1 GB de RAM** (antes 512 MB): 512 MB ficava apertado para o Chromium do
  Playwright junto com o app.
- **Reverter depois do 2º turno (25/10):** voltar para
  `auto_stop_machines = 'stop'` e `min_machines_running = 0`, como registra o
  comentário no `fly.toml`, e a memória para 512 MB. A memória não está
  anotada no `fly.toml`.

### Lote D1 — concluído e publicado (observabilidade e capacidade)

Preparação para a semana do 1º turno (04/10).

Achados nos logs de produção que motivaram o lote:

- O app não configurava logging: só WARNING ou acima chegava ao
  `flyctl logs`.
- O stdout estava com buffer: "Iniciando na porta 8080" só aparecia no
  desligamento, depois do SIGINT.
- A fila do Waitress chegou a 7 requisições com uma pessoa só abrindo o
  dashboard. O padrão do Waitress é 4 threads, e o dashboard dispara 12
  chamadas de API ao carregar.

| Commit | O que fez |
|---|---|
| `76e0441` | `configurar_logging()`: raiz em INFO, com horário, nível e nome do logger, sem duplicar o `basicConfig()` do Waitress. Uma linha INFO por coletor com status, gravadas, falhas e duração. Timeout do coletor vira WARNING com o nome, logado no estouro. `PYTHONUNBUFFERED=1` no `fly.toml` |
| `1bb5957` | `WAITRESS_THREADS`, padrão 16, também no `fly.toml`. Valor inválido cai no padrão sem derrubar o boot |

Antes de subir as threads, conferido: o SQLite abre uma conexão por
chamada (`get_conn`/`get_db` em `db/core.py`), e nenhuma conexão é
compartilhada entre threads.

Suíte depois do D1: **347 passed, 3 deselected, em ~40s**.

Fica para outro lote: o logger `COLLECTOR` (`collectors/base.py`) tem
handler próprio com `propagate = False` e formato sem horário nem nível.
Suas linhas continuam saindo, mas fora do formato novo.

### Lote D2a — concluído, deploy pendente (cobertura de governador RJ, parte 1)

O push entrou na `main`. O deploy falhou por infraestrutura do Fly (volume
num host inacessível), não por código.

| Commit | Bug | O que fez |
|---|---|---|
| `926f4e9` | #5 | Paraná: RJ reconhecido por `rio-de-janeiro`, `fluminense`, `estado/governo-do-rio` (sem "-grande") ou `rj` como token. Fora também a pesquisa de presidente feita no RJ (`…para-o-cargo-de-presidente-…br-01920`) |
| `5daf944` | #4 | Datafolha: texto limpo (`BaseCollector._texto_limpo`) para o extrator de governador; roteamento com fronteira de palavra. Na listagem real, o release de governador **de SP** com "cenarios" no slug ia para o extrator do RJ |
| `89e8be7` | #2 | Quaest adiada: ver [N5](#n5--quaest-descoberta-quebrada-e-números-do-rj-só-em-imagem) |

- **Limite de 10 links do Paraná:** mantido. Ele se aplica depois do filtro
  de RJ, e a página 1 da listagem tem 1 release do RJ entre 14 posts.
- **Datafolha:** não há release de governador do RJ na listagem, e o TSE
  não tem pesquisa Datafolha de governador RJ. A correção é defensiva.

**Expectativa de cobertura**, contra as 33 pesquisas de governador RJ do
snapshot do TSE (sincronizado em 05/08):

| Instituto | TSE | Já em produção | Novas com D2a/D2a2 |
|---|---|---|---|
| Paraná | 4 | 3 | 0. Falta a RJ-04997 (abril), fora da página 1 da listagem, a única varrida |
| Datafolha | 0 | 0 | 0 |
| Quaest | 2 | 0 | 0 (adiada, N5) |
| Verita | 3 | 0 | até 1: a RJ-03394 (abril). Maio (RJ-08977) e junho (RJ-00542) não estão publicadas no site |
| Vetor, Prefab, Real Time, Gerp, 100 Cidades, Agora | 24 | 0 | Lote D2b (agregadores) |

Fora do snapshot: a Paraná RJ-04036 (setembro) está na página 1 e deve
entrar na próxima coleta. A RJ-01671 (setembro) e a RJ-02422 (agosto) já
saíram da página 1 e só entram pelo `/admin/coletar-url`.

### Lote D2a2 — em andamento (Verita e resumo da coleta)

Branch `fix/lote-d2a2-verita`, ainda sem push.

| Commit | O que fez |
|---|---|
| `d8c92ac` | Verita: causa raiz do "0 candidatos de governador RJ" era roteamento, não truncamento. Os PDFs de produção (BR-02698, BR-09535) são pesquisas de presidente feitas no RJ, sem pergunta de governador. Listagem filtrada pelo título do card (5 de 95 links). O extrator recebe só o cabeçalho e "Nome Frequência Porcentual" da pergunta estimulada de governador. Tabela não reconhecida: PDF pulado com WARNING, nunca texto bruto |
| `4cac1a8` | `normalizar_nome` tira o partido colado ao nome ("Eduardo Paes (PSD)", "Lula – PT"), por lista explícita de partidos |
| `fa9acce` | `/metodologia`: percentuais sobre o total de entrevistados, não sobre os votos válidos, e por quê |
| `744975f` | Resumo da coleta: depois do timeout, vale o resultado real do `run()`; o atraso vira marcador (`status=ok_com_atraso` no log; `"atraso": true` no dict). TimeoutError do próprio `run()` vira erro |

- **PDFs do Verita de presidente no RJ** (BR-02698, BR-09535): pulados.
  Não são nacionais e não podem entrar na série de presidente. Dá para
  gravar em `pesquisas_regionais` (a infraestrutura está comentada em
  `collectors/verita.py`) num lote futuro.

### Achados da linha de base da coleta (anotados, não corrigidos)

Vistos nos logs de produção depois do Lote D1.

- **A coleta completa passa de 20 min.** Os coletores rodam em sequência.
  Com o auto stop antigo, a máquina desligava antes de o Verita terminar
  (e antes do CNN, do QuaestRegional e do Paraná, que vêm depois dele).
- **Reextração a cada execução.** O Datafolha reprocessa 15 releases e o
  Verita percorria 95 pesquisas, cada uma com chamada ao Gemini quando há
  PDF que passa no filtro. Há risco de esgotar a cota do Gemini no domingo.
  O filtro da listagem do D2a2 reduz o Verita a 5 links, mas o
  reprocessamento do que já foi gravado continua (ver #6: "não reextrair
  pesquisa já casada com o TSE").
- **O Datafolha raspa releases estaduais (MG, CE, PI) que não viram dado.**
  Gasta página e chamada ao Gemini sem resultado.
- **A Gazeta só processa 3 releases por coleta.**

### Achados que surgiram durante a execução e já foram corrigidos

- **Sync automático sobrescreveria produção.** Com a coleta no Fly, uma
  coleta local com o banco local defasado (1 pesquisa contra 44) disparava
  `sync_para_fly()` e substituía o banco de produção. Corrigido em `60b2377`.
- **Mais vazamentos de variáveis de ambiente, além do #16.**
  `test_scheduler.py:119` escrevia `ADMIN_PASS` em `os.environ` sem
  restaurar. `test_usuarios.py` e `test_rate_limiting.py` definiam a senha
  falsa no import. Corrigido em `3697676`.
- **Subprocesso escapava do isolamento.** O teste de CLI do sync chamava um
  subprocesso, que escapava do bloqueio de rede e do `.env` neutralizado.
  Passou a chamar `main()` no próprio processo, em `518a450`.

### Incidentes de processo

- **Possíveis chamadas reais ao Gemini (Lote A).** Uma execução de
  `tests/test_collectors.py` foi feita sem esvaziar `GEMINI_API_KEY`. O
  Paraná e o QuaestRegional podem ter chamado o Gemini com a chave real. Não
  há como saber quantas chamadas houve sem repetir o teste. Desde `518a450`
  isso não é mais possível na suíte padrão.
- **Script de sync real executado (Lote B).** O teste de CLI rodou o
  `scripts/sync_db.py` real antes de a trava existir. Não houve efeito
  porque o `flyctl` não estava instalado na máquina, e o script terminou em
  "flyctl não encontrado". O teste hoje roda dentro do processo, com tudo
  mockado.

## Itens novos (abertos)

### N1 — Timeout de 45s por coletor não interrompe o coletor

`run_all_collectors` (`app.py:152-166`) chama `future.result(timeout=45)`
dentro de `with ThreadPoolExecutor(...)`. Na saída do `with`, o executor
chama `shutdown(wait=True)` e espera a thread terminar.

Verificado isoladamente, com timeout de 1s e uma tarefa de 3s: o laço só foi
liberado depois de 3,0s, e a tarefa terminou normalmente.

Consequências:

- **O timeout não protege contra travamento.** O objetivo do commit
  `2e76d91` ("evitar congelamento no Playwright") não é atingido.
- **O status mente.** Um coletor lento, como o Verita (Playwright por
  página e `sleep(2)` entre PDFs), termina e grava as pesquisas, mas o
  resumo registra `timeout` ("foi cancelado") e perde a contagem de falhas
  do `run()`. Corrigido no Lote D2a2 (`744975f`): o resumo usa o resultado
  real, com o atraso como marcador.
- **Verificado em produção:** o Datafolha e a Gazeta passam de 45s, e a
  coleta completa, de 20 min.

**Correção proposta:**
- Para um limite real: executor fora do `with`, com `shutdown(wait=False)`
  e cancelamento cooperativo, ou um processo separado por coletor.
- Para o Verita: prazo por página e total próprio.
- Registrar a duração real de cada coletor no log. Feito no Lote D1
  (`76e0441`), que também passou a logar o timeout no momento do estouro.
  O limite continua sem interromper o coletor.

**Risco:** médio. Uma thread abandonada continua gravando no SQLite.

### N2 — Sync do TSE não roda em produção

- O job `_job_sync_tse` (09h30, `app.py:312-318`) vive no
  `BackgroundScheduler` interno. O scheduler só liga fora do Fly
  (`app.py:320`, gate em `FLY_APP_NAME`).
- Nenhum workflow do GitHub Actions dispara o sync do TSE.
- O commit `580664d` deixou a máquina sempre ligada durante as eleições,
  mas isso não muda nada aqui: o gate é a variável de ambiente, não a
  máquina estar ligada.

Consequência: o registro do TSE em produção só é atualizado quando alguém
roda `scripts/sync_tse.py` e sincroniza o banco. A fila de cobertura de
`/admin/cobertura` e o bloco público "em campo agora" (`/api/em-campo`,
vazio em 2026-09-29) ficam defasados.

**Correção proposta:** workflow agendado (como `coleta_agendada.yml`)
chamando uma rota admin que roda `sincronizar_tse(dry_run=False)` no Fly. Não
consome cota do Gemini.

**Risco:** baixo. Exige rota nova autenticada por `X-Admin-Pass`, fora da
allowlist pública.

### N3 — Rótulos fixos no card de 2º turno

| Linha (`templates/dashboard.html`) | O que está fixo |
|---|---|
| 1145 | Rótulo "Lula (PT)" do cenário principal |
| 1158 | Rótulo "Flávio Bolsonaro (PL)" do cenário principal |
| 1183 | "Lula (PT)" como candidato A dos cenários alternativos. O candidato B vem da API (`${b.nome}`), mas o A é sempre "Lula (PT)", mesmo que a API devolva outro nome |
| 1202 | Texto "Votos do Flávio Bolsonaro redistribuídos … com peso ≈75%". O 75% duplica à mão o `mu_override={'Flávio Bolsonaro': 0.75}` de `db/monte_carlo.py:437` |

Os números exibidos vêm da API, então isso não é dado fabricado. Mas os
rótulos, os partidos e o peso ficam errados em silêncio se o cenário ou o
backend mudarem.

**Correção proposta:** a API passa a devolver nome, partido e peso de
redistribuição, e o card usa `a.nome` e esses campos.

**Risco:** baixo.

### N4 — Campo `tipo` ausente na resposta vazia de `/api/pesquisas/presidente`

- **Sem dado:** a rota devolve `candidatos`, `percentuais`, `data_coleta`,
  `instituto` e `margem_erro`, **sem** `tipo` (`app.py:881-888`).
- **Governador sem dado:** devolve `"tipo": null`.
- **Com dado:** `tipo` vem da pesquisa.

O front atual não quebra: sem dado, ele mostra o estado vazio com o selo do
tipo selecionado. Mas quem consome a API (incluindo o export) recebe formas
diferentes conforme haja dado ou não.

**Correção proposta:** devolver `"tipo": <tipo pedido>` também na resposta
vazia, porque o cliente pediu um tipo específico, e fixar o formato num
teste.

**Risco:** baixo.

### N5 — Quaest: descoberta quebrada e números do RJ só em imagem

Encontrado ao executar o #2 no Lote D2a (2026-09-29). Muda a correção
proposta para o #2.

- **Descoberta quebrada.** `LISTING_URLS` aponta para
  `/category/politica/`, que não existe mais. As categorias do WordPress
  hoje são `analises-de-pesquisas`, `noticias-quaest` e outras. Por
  requests, a página volta com ~140 KB e nenhum post. O fallback para
  Playwright não dispara, porque a página passa de 5.000 caracteres e não
  tem "cookie" no começo. Renderizada com Playwright, cai em "Política de
  Cookies". Nenhum release chega ao `_parse_release`. É por isso que a
  Quaest tem 0 pesquisas em produção, inclusive de presidente.
- **Números do RJ só em imagem.** As 2 pesquisas da Quaest de governador
  RJ no TSE (RJ-00613/2026, divulgada em 27/04, e RJ-02671/2026, em
  27/07) saem em posts de vários estados
  (`genial-quaest-cenarios-eleitorais-rj-pr-pa` e `…-2`, "RJ, PR e PA").
  O texto do post só traz "Paes entre 38% e 42% nos três cenários" e os
  números de **2º turno** (Paes 48% × Garotinho 18%; Paes 52% × Ruas 16%).
  Os números de 1º turno por candidato estão nas imagens `RJ1…RJ10.jpeg`
  do post.

**Por que foi adiado:** extrair o governador a partir do texto, como
propunha o #2, gravaria números de 2º turno como 1º turno, sem erro
aparente. E hoje não renderia nada, porque a descoberta não acha os posts.

**Correção proposta (lote próprio, depois do 1º turno):**
- Descoberta pela WP REST API (`/wp-json/wp/v2/posts`), que o
  `QuaestRegionalColetor` já usa. Isso também passa a trazer os releases
  nacionais de presidente, e muda a série de presidente.
- Extração das imagens `RJ*.jpeg` com Gemini multimodal.
- Roteamento de governador sem `'governo'` solto. `_inferir_cargo`
  continua morto na Quaest e no Atlas (Atlas bloqueado por DNS, não
  mexido).

**Risco:** médio. Muda a série de presidente e cria um caminho novo de
extração por imagem.

## Ordem recomendada para o que falta

1. ~~**#7:** migração do roster de candidatos.~~ Feito no Lote C.
2. ~~**#5, #4:**~~ Feito no Lote D2a. **#2** adiado (N5). **#3** no Lote
   D2b, junto com a deduplicação do #12: dois agregadores publicando a mesma
   pesquisa a gravariam duas vezes, com peso dobrado na média. Depois, uma
   coleta e conferir `/admin/cobertura?cargo=governador_rj`.
3. **N1:** timeout real, para que a cobertura nova não trave a coleta nem
   minta no resumo.
4. **N2:** sync do TSE em produção. A cobertura depende do registro
   atualizado.
5. **#6:** extração com vários tipos por release. Destrava a espontânea e o
   toggle.
6. **#12, #13, #15, N4:** higiene de dados e de contrato da API.
7. **#10, #11, N3:** gráficos e card de 2º turno.
8. **#8:** só depois de a cobertura normalizar, e só se ainda fizer falta.
   Muda o contrato de `test_agregacao.py` e `/metodologia`.
9. **#14.**
