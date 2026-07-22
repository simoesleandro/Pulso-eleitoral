# Curadoria de institutos e tela de cobertura (Onda 2)

**Data:** 2026-07-22
**Status:** aprovado, aguardando plano de implementação
**Escopo:** presidente + governador RJ
**Depende de:** [Onda 1](2026-07-22-cobertura-tse-design.md) (merged em `main`, commit `183f8ff`)

## Problema

A Onda 1 tornou a cobertura mensurável e parou aí. O estado medido no banco
local em 2026-07-22, depois do sync e do casamento:

| | Em campo hoje | Agendadas | Encerradas sem pesquisa | Ligadas |
|---|---|---|---|---|
| Presidente | 14 | 2 | **465** | 2 |
| Governador RJ | 1 | 8 | 19 (17 estaduais) | 2 |

Três coisas ficaram travadas:

1. **`institutos.agregar` existe e ninguém lê.** A coluna nasceu com default 0
   e os 14 institutos curados nunca foram promovidos. Hoje isso é inofensivo
   porque nada consome o flag; no instante em que a agregação passar a
   respeitá-lo, **os 14 estão em 0 e o dashboard zera**. O backfill tem que
   ir no mesmo commit que o filtro.
2. **18 ligações presas.** O casador recusou 13 pares ambíguos em presidente
   (Verita e Real Time, registros sobrepostos) e não alcançou as 5 pesquisas
   do Datafolha, cuja distância entre campo e publicação excede a folga de 3
   dias. As 5 seguem com `tamanho_amostra = 0`, entrando na média com o
   fallback de 1000 em vez dos ~2004 reais.
3. **465 registros de presidente não são uma fila de trabalho.** Ninguém
   preenche 465 pesquisas à mão, e boa parte vem de instituto local pequeno.
   Uma tela que liste isso cru nasce inútil.

### O buraco não está onde parecia

Separando a fila por instituto já cadastrado:

| | Instituto já cadastrado | Nunca avaliado |
|---|---|---|
| Presidente, encerradas sem pesquisa | **213** | 252 |
| Gov RJ, estaduais encerradas sem pesquisa | **8** | 9 |

Os 10 institutos já curados registraram **215 pesquisas de presidente** no
TSE. O Pulso tem **2**. A maior perda de cobertura não são os institutos
desconhecidos — são as pesquisas dos institutos que já foram aprovados e que
os coletores nunca capturaram. Isso reordena as prioridades desta onda: a
fila de trabalho dos aprovados é o bloco principal da tela, e a descoberta
dos 88 é secundária.

Também explica por que a Onda 1 encontrou coletores em silêncio: o status
`"vazio"` foi criado exatamente para isso, e a fila agora quantifica o
prejuízo. Consertar coletor é trabalho de outra onda; esta apenas torna o
tamanho do problema visível e ordenável.

## Decisões

### Curadoria opera sobre institutos, não sobre pesquisas

465 decisões repetidas viram **88 decisões permanentes**. O registro do TSE
tem 98 CNPJs distintos; 10 já casam com institutos nossos, 88 nunca foram
avaliados. Aprovado o instituto, os registros dele entram na fila sozinhos.

Amostra do que a descoberta apresenta hoje, por volume de registro:

| Registros | Amostra típica | Instituto |
|---|---|---|
| 22 | ~1.372 | 100 Cidades |
| 16 | ~11.372 | Vetor Arrow |
| 14 | ~607 | Amostragem Opinião e Mercado |
| 11 | ~1.404 | Instituto Seta |

Volume e amostra são o contexto da decisão, não a decisão: a Vetor Arrow é a
segunda em volume e a primeira em amostra, e é exatamente o instituto cujo
n=14.000 motivou o teto de peso da Onda 1.

### Três estados, sem coluna nova

| Estado | Representação |
|---|---|
| Nunca avaliado | CNPJ em `pesquisas_tse`, **sem linha** em `institutos` |
| Aprovado | linha em `institutos` com `agregar = 1` |
| Rejeitado | linha em `institutos` com `agregar = 0` |

Rejeitar cria a linha justamente para o instituto não voltar à descoberta a
cada sync diário.

`institutos.ativo` **não** é reaproveitado: a coluna existe desde o schema
original e não é lida em lugar nenhum do código (verificado — todas as
ocorrências de `ativo` são `usuarios.ativo` ou `candidatos.status`). Empilhar
semântica numa coluna morta cria duas fontes de verdade. Fica como está.

### Instituto não aprovado aparece, mas não conta

A pesquisa segue visível na lista e na página de detalhe, marcada como fora
do agregado, e não entra em nenhum número derivado. Aprovar depois é um
toggle, sem recoletar nada.

## Onde o filtro entra

Onze pontos do código juntam `institutos`. A divisão segue uma regra única:
**se o resultado é um número agregado ou uma afirmação editorial, filtra; se
é a exibição de uma pesquisa individual, não filtra.**

**Com `AND inst.agregar = 1`:**

| Local | Função |
|---|---|
| `db/pesquisas.py:247` | `get_media_agregada` — o poll-of-polls |
| `db/pesquisas.py:131,134` | `variacao_30d` / alerta de variação brusca |
| `db/pesquisas.py:375` | viés por instituto (house effects) |
| `db/pesquisas.py:498` | `get_historico_multi` — a série do gráfico |
| `db/pesquisas.py:85` | corrida atual ("a pesquisa mais recente") |
| `db/kpis.py:210,240` | líder presidente / líder governador RJ |

`pesquisas.py:85` foi o caso limítrofe: não é média, mas define qual é o
retrato de hoje. Um instituto não aprovado não deveria fazer essa afirmação.
Decidido por revisão explícita do dono do produto.

O viés por instituto (375) filtra porque compara cada instituto contra a
média dos outros: incluir um não aprovado distorceria o denominador de todos
os demais, não só a linha dele.

**Sem filtro:**

| Local | Função |
|---|---|
| `db/pesquisas.py:552` | `get_pesquisa_por_id` — página de detalhe |
| `db/pesquisas.py:33` | `get_comparativo_candidato` — lista por instituto |
| `db/pesquisas.py:531` | `get_historico_candidato` |
| `db/pesquisas.py:571` | `get_institutos_com_totais` — ganha coluna de status |

## Tela `/admin/cobertura`

Atrás de `@login_required`, como o resto do admin. Quatro blocos:

1. **Fila de trabalho** — registros com `data_fim < hoje`, `pesquisa_id IS
   NULL`, instituto aprovado e `abrangencia != 'municipal'`. É o que falta
   coletar de quem já foi curado: hoje **213 de presidente e 8 do RJ**.
   Ordenada por data de fim de campo decrescente — o topo é o que ainda é
   notícia. Agrupada por instituto, para que um coletor quebrado apareça como
   bloco e não como 40 linhas soltas.

   O filtro de abrangência importa: das 19 do RJ encerradas sem pesquisa, 2
   são municipais e não pertencem a uma série estadual.

2. **Ligação manual** — os ambíguos que o casador recusou e a busca por
   pesquisa existente, para o caso da janela ter sido curta demais.
3. **Descoberta de institutos** — as 88 linhas, com contagem de registros e
   amostra média, cada uma com aprovar/rejeitar.
4. **Em campo e agendadas** — visibilidade operacional do que vem por aí.

A descoberta não pagina: 88 linhas cabem numa página e a lista encolhe a cada
decisão. A fila de trabalho pagina, porque 213 linhas não cabem e a ordenação
por recência é o que a torna útil.

## Ligação manual

`POST /admin/cobertura/ligar` recebe protocolo + `pesquisa_id` e aplica o
mesmo efeito do casamento automático: grava `pesquisas_tse.pesquisa_id`,
substitui o `registro_tse` sintético pelo protocolo real, corrige
`data_pesquisa` com a data de fim de campo e preenche `tamanho_amostra`
**apenas quando falta**.

Isso exige extrair o backfill de dentro do laço de `tse/matcher.py:109-128`
para uma função reusável — hoje ele é inline. A regra de não sobrescrever
amostra realizada por amostra registrada é do domínio, não do casador
automático, e já tem teste (`test_backfill_nao_sobrescreve_amostra_realizada`);
a extração precisa mantê-lo verde sem alterá-lo.

Guardas obrigatórias, cada uma com teste:

- protocolo já ligado a outra pesquisa → recusa
- pesquisa já ligada a outro protocolo → recusa
- protocolo ou pesquisa inexistente → recusa
- cargo do registro diferente do cargo da pesquisa → recusa

Ligação errada é pior que ligação ausente: envenena a série em silêncio, e
desfazer exige saber que aconteceu. O mesmo princípio que fez o casador
recusar ambiguidade se aplica aqui.

## Bloco público "em campo agora"

No dashboard, alimentado por `data_inicio <= hoje <= data_fim`. Hoje: 14 de
presidente e 1 do RJ.

A regra exclui as agendadas de propósito. Das 9 do RJ com data futura, **8
são a Vetor Arrow**, tracking semanal registrado antecipadamente até 28 de
setembro. Incluí-las encheria a seção com o mesmo instituto oito vezes — e
anunciaria publicamente pesquisa de instituto que talvez nunca seja aprovado.

O bloco mostra instituto, período e amostra registrada. Não mostra resultado:
o dataset do TSE não traz percentual.

## Testes

- `tests/test_agregacao.py` continua sendo o contrato numérico. O filtro de
  curadoria muda **quais** pesquisas entram, não a fórmula; os testes
  existentes precisam de institutos com `agregar = 1` nas fixtures e devem
  continuar com os mesmos números.
- Teste de regressão do backfill: depois de `init_db` num banco novo, nenhum
  instituto do seed pode ficar com `agregar = 0`. É o guarda contra o
  dashboard zerar.
- Teste de que pesquisa de instituto não aprovado **aparece** no detalhe e
  **não aparece** na média — os dois lados da decisão, no mesmo teste.
- Ligação manual: uma por guarda, mais o caminho feliz.
- Descoberta: instituto rejeitado não reaparece depois de um novo sync.

## Falhas previstas

- **Dashboard zerado** pelo default 0 — mitigado pelo backfill no mesmo
  commit e pelo teste de regressão acima. É a falha mais provável desta onda.
- **Instituto com CNPJ ausente nunca casa.** Quatro dos nossos estão assim:
  Genial/Quaest, Futura Inteligência, Meio/Ideia e Vox Populi. Não bloqueia a
  Onda 2 (nenhum deles tem pesquisa coletada hoje), mas eles não aparecem na
  fila nem na descoberta enquanto o CNPJ faltar. Fica registrado como dívida.
- **CNPJ como chave de casamento** assume que o instituto registra sempre com
  a mesma pessoa jurídica. Filial ou troca de CNPJ vira "instituto novo" na
  descoberta — visível, não silencioso.
- **Nome do TSE é o razão social** (`VETOR ARROW INSTITUTO DE PESQUISA E
  OPINIAO LTDA`), não o nome de mercado. A aprovação precisa deixar o operador
  editar o nome exibido, senão o dashboard mostra razão social.

## Fora de escopo

- **Preenchimento de pesquisa** (URL, texto/PDF, digitação) — é a Onda 3.
  Esta onda deixa a fila pronta e as ligações destravadas.
- **Mudança na fórmula de agregação** — o teto de peso foi na Onda 1 e não se
  mexe de novo aqui. Se a média mudar depois desta onda, a causa é a
  curadoria e as amostras corrigidas, não o cálculo.
- **Ampliar a folga de ±3 dias do casador automático** — a ligação manual
  cobre os casos que escapam. Afrouxar a janela aumentaria o número de
  ambíguos, que é justamente o que exige trabalho humano.
- **Consertar os coletores** que explicam as 213 pesquisas faltando de
  institutos aprovados. A fila mede o prejuízo e mostra qual instituto está
  em silêncio; corrigir cada coletor é trabalho dirigido por esse dado, em
  outra onda.
- **Outras 25 UFs.**
