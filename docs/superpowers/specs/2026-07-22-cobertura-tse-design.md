# Cobertura e confiabilidade da captura de pesquisas (TSE como espinha dorsal)

**Data:** 2026-07-22
**Status:** aprovado, aguardando plano de implementação
**Escopo:** presidente + governador RJ

## Problema

O poll-of-polls do Pulso Eleitoral produz números enviesados e cobre uma
fração mínima das pesquisas existentes. Medido no banco local em 2026-07-22:

| | Pulso | Registrado no TSE | Cobertura |
|---|---|---|---|
| Presidente | 12 pesquisas, 7 institutos | 484 pesquisas, 96 institutos | ~2,5% |
| Governador RJ | 2 pesquisas, **1 instituto** | 19 realizadas, 9 institutos | ~11% |

O total de presidente (484) inclui registros de data futura, ainda em campo;
o de governador RJ já está descontado deles (30 registros → 28 estaduais → 19
com campo encerrado até 2026-07-22).

Governador RJ tem um único instituto (Paraná Pesquisas). Um poll-of-polls com
um instituto não é um poll-of-polls.

Além da cobertura, quatro defeitos corrompem os números que já existem:

1. **Datafolha entra subponderado.** As 5 pesquisas do Datafolha têm
   `tamanho_amostra = 0`. A agregação já tem guarda em `db/pesquisas.py:255`
   (`amostra if amostra > 0 else 1000`), então o instituto **não** é anulado —
   entra com peso 1000 em vez dos ~2004 reais, cerca de metade do devido.
   Bug real, de severidade modesta: com a janela padrão de 30 dias a pesquisa
   de março sequer é incluída. O backfill do TSE corrige a distorção sem
   precisar mexer na guarda.
2. **A mesma pesquisa entra duas vezes.** `registro_tse` é sintético —
   `GEN-{inst}-{cargo}-{data_coleta}-{sha1(url)}` (`collectors/base.py:195`).
   A chave usa a URL da matéria, então duas matérias sobre a mesma pesquisa
   viram duas pesquisas. Confirmado nos ids 27 e 28 (Real Time, 2026-07-20,
   n=2000, me=2.0) — e a id 27 é uma extração **truncada**, com 2 candidatos
   contra 6 da id 28. A média escolhe uma pesquisa por instituto e o desempate
   por id maior salva a completa por acaso, mas a `variacao_30d`
   (`db/pesquisas.py:293`) usa todas as pesquisas da janela, então o valor
   duplicado entra duas vezes no sinal de variação. A chave também embute a
   data da coleta, então recoletar duplica de novo.
3. **`data_pesquisa == data_publicacao` nas 14 linhas.** O período de campo
   nunca é extraído. Como a recência é `0.9^dias`, toda pesquisa é tratada
   como mais fresca do que é — erro sistemático, sempre na mesma direção.
4. **Coletor falha em silêncio.** `run()` devolve `"ok"` com zero pesquisas
   salvas (`collectors/base.py:68`). Quaest, Atlas e Poder360 nunca gravaram
   uma linha e o log do scheduler mostra `"ok"` nos 9 coletores.

## Fonte: dados abertos do TSE

`https://cdn.tse.jus.br/estatistica/sead/odsele/pesquisa_eleitoral/pesquisa_eleitoral_2026.zip`

ZIP de ~2 MB, um CSV por UF mais `BRASIL.csv`, regerado diariamente de manhã
(verificado: geração de 22/07/2026 às 05:46). Encoding `latin-1`, delimitador
`;`, sentinela `#NULO#`.

Colunas relevantes: `NR_PROTOCOLO_REGISTRO`, `NR_CNPJ_EMPRESA`, `NM_EMPRESA`,
`NM_EMPRESA_FANTASIA`, `DS_CARGO`, `DT_INICIO_PESQUISA`, `DT_FIM_PESQUISA`,
`DT_DIVULGACAO`, `QT_ENTREVISTADO`, `SG_UE`.

**Filtros validados contra o arquivo real:**

- Presidente: `SG_UE == "BR"` e `"Presidente" in DS_CARGO` → 484 linhas. O
  filtro é limpo: pesquisas municipais não listam Presidente no cargo.
- Governador RJ: `pesquisa_eleitoral_2026_RJ.csv`, `"Governador" in DS_CARGO`
  → 30 linhas, das quais 2 são de abrangência municipal (detectáveis por
  menção a "município de X" em `DS_METODOLOGIA_PESQUISA`/`DS_DADO_MUNICIPIO`)
  e 9 têm data futura (registro antecipado, ainda em campo). Realizadas e
  estaduais: 19.

**Limite da fonte:** o dataset traz o *registro*, não os *percentuais*. Ele
não substitui a raspagem de releases — serve como índice, fila de trabalho e
fonte de verdade dos metadados.

## Arquitetura

Alternativa escolhida: tabela de registros separada, ligada aos resultados.
Descartadas: enriquecer `pesquisas` no lugar (não revela o que falta, que é o
ganho principal) e usar o TSE como chave primária de tudo (quebra em registro
atrasado e engessa a coleta atual).

```
CSV TSE (diário, cdn.tse.jus.br)
        │  sincronizador
        ▼
  pesquisas_tse ──────────► FILA DE COBERTURA (admin)
  (registro oficial)         "19 realizadas · 2 no Pulso · 17 faltando"
        │                              │
        │ casamento por                │ preenchimento (URL | texto/PDF | manual)
        │ CNPJ + período + cargo       ▼
        ▼                        prévia editável (Gemini)
    pesquisas ◄────────────────────────┘
   (resultados)     ▲
                    │
              coletores atuais (inalterados)
```

Três componentes independentes:

1. **Sincronizador** — baixa o ZIP, filtra, normaliza e faz upsert em
   `pesquisas_tse`. Idempotente por protocolo. Sem custo de Gemini.
2. **Casador** — liga registro ↔ resultado por CNPJ + período + cargo. Onde
   casa, faz backfill de `tamanho_amostra`, `data_pesquisa` e protocolo real.
   Onde não casa, o registro fica na fila.
3. **Tela de cobertura** — lista o que falta, com os três modos de
   preenchimento convergindo numa prévia editável.

### Modelo de dados

```sql
CREATE TABLE pesquisas_tse (
  protocolo        TEXT PRIMARY KEY,   -- NR_PROTOCOLO_REGISTRO
  cargo            TEXT NOT NULL,      -- 'presidente' | 'governador_rj'
  cnpj_empresa     TEXT NOT NULL,
  nome_empresa     TEXT NOT NULL,
  data_inicio      TEXT NOT NULL,
  data_fim         TEXT NOT NULL,
  data_divulgacao  TEXT,
  qt_entrevistado  INTEGER NOT NULL,
  abrangencia      TEXT,               -- 'nacional' | 'estadual' | 'municipal'
  pesquisa_id      INTEGER REFERENCES pesquisas(id),  -- NULL = fila
  sincronizado_em  TEXT
);
```

Colunas novas em `institutos`: `cnpj` (casamento estável) e `agregar`
(curadoria, default 0).

### Curadoria

Somente institutos com `agregar = 1` entram na média. Instituto novo
descoberto pelo TSE entra como pendente — visível na fila, fora do número.
Ingerir os 96 institutos sem curadoria degradaria o agregado: muitos são
locais e pequenos (amostra mínima observada: n=300).

### Teto de peso

A Vetor Arrow registrou tracking semanal de RJ com n=14.000 — dez vezes o
Quaest (n=1.200). Pela ponderação por amostra, uma única aprovação errada
dominaria a média sozinha. A amostra efetiva usada na ponderação é limitada a
**duas vezes a mediana** das amostras da janela.

Percentil 90 foi a primeira regra escrita aqui e está **descartada**: com o
número de institutos que existe na prática (5 a 10), o nearest-rank do p90
seleciona justamente o maior valor, e o teto nunca morderia — inclusive no
caso da Vetor Arrow que motivou a regra. Descoberto ao implementar, com teste
de regressão em `tests/test_agregacao.py`. A mediana é robusta a outlier por
construção; o fator 2 dá folga para variação legítima.

## Correções destravadas

1. **Amostra real.** Backfill do `QT_ENTREVISTADO`, substituindo o fallback
   fixo de 1000 pelo valor registrado. A guarda de `db/pesquisas.py:255`
   permanece como está — ela já impede peso zero; o que muda é que ela deixa
   de ser acionada quando o TSE conhece a amostra.
2. **Deduplicação.** `registro_tse` passa a ser o protocolo quando há
   casamento. Exige migração que funda as duplicatas existentes antes de
   criar o índice único.
3. **Datas de campo reais** de `DT_INICIO_PESQUISA`/`DT_FIM_PESQUISA`.
4. **Status `"vazio"`** no retorno de `run()`, distinto de `"ok"`. A fila do
   TSE vira o detector real de coletor quebrado.

Das correções acima, só o **teto de peso** altera a fórmula de agregação — as
demais mudam dados, não cálculo. Conforme o `CLAUDE.md`,
`tests/test_agregacao.py` e `/metodologia` mudam no mesmo commit que o teto.

## Ondas

**Onda 1 — fundação.** Sincronizador, `pesquisas_tse`, casador, backfill,
migração de deduplicação, teto de peso, status `"vazio"`. Sem UI nova.
Entrega: números corretos e cobertura mensurável. O sync roda diariamente —
não consome cota do Gemini, ao contrário da coleta (reduzida a 2x/semana por
teto de gasto).

**Onda 2 — curadoria e visibilidade.** `institutos.agregar` e tela de
cobertura, com seção própria para registros de data futura ("pesquisas em
campo agora"), que viram feature de produto em vez de ruído na fila.

**Onda 3 — ingestão assistida.** Botão `[preencher]` com três modos — URL,
texto/PDF colado e digitação manual — convergindo na mesma prévia editável
antes de gravar. A pesquisa nasce ligada ao protocolo, com amostra e datas
vindas do registro; resta preencher candidato e percentual. Reaproveita
`gerar_com_cascata()` e `_to_pct` de `collectors/gemini_extractor.py`; não
introduz lógica de cascata nova.

## Testes

- `tests/test_agregacao.py` é o contrato numérico e o gate de equivalência.
- `tests/test_tse_sync.py` novo: fixture com ~20 linhas reais do CSV
  commitadas (não o arquivo de 5 MB), parsing de encoding/sentinela, filtros
  de cargo e abrangência, idempotência do upsert.
- Casamento: CNPJ + período; caso ambíguo deixa sem casar.
- Migração de deduplicação testada sobre um banco que reproduz os ids 27/28.

## Falhas previstas

- CDN do TSE indisponível: sync falha, loga e não corrompe nada (upsert
  idempotente por protocolo).
- Encoding `latin-1`, `;`, `#NULO#`: normalizar na entrada.
- **Casamento ambíguo** (dois registros do mesmo instituto no mesmo período):
  não adivinhar. Deixa sem casar e manda para ligação manual — casar errado
  envenena a série histórica em silêncio, e o custo de um falso negativo
  (item a mais na fila) é muito menor que o de um falso positivo.
- Registros de data futura: fora do denominador de "faltando".

## Fora de escopo

- **`contratante`** — o CSV do TSE não traz o nome de quem contratou (só
  `ST_PESQUISA_PROPRIA` e `VR_PESQUISA`). Cortado por decisão do dono do
  produto; a dívida segue registrada em `plans/README.md`.
- **`margem_erro` do TSE** — só existe em texto livre em `DS_PLANO_AMOSTRAL`;
  extrair traria risco de erro sem ganho. Mantém a origem atual.
- **Outras 25 UFs** — o schema é `presidente | governador_rj`; ampliar cargo
  é outra discussão.
