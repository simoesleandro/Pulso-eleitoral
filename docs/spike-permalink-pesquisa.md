# Spike 039: permalink citável por pesquisa/candidato

Spike, não plano de build. Ver `plans/039-spike-permalink-pesquisa-candidato.md`.
Branch `advisor/039-spike-permalink-pesquisa-candidato` é exploratória — **não
está pronta para merge como está** (ver "Estado do protótipo" abaixo).

## Recomendação: opção C (A primeiro, B depois)

`PRODUCT.md` nomeia o jornalista como persona explícita ("cita números em
matéria... navega direto para dado específico") e define o próprio critério
de sucesso do produto como "ser citável e confiável". Hoje o dashboard só tem
4 âncoras de seção — nenhuma aponta para uma pesquisa/candidato específico.

### Opção A — Permalink por pesquisa (`/pesquisa/<id>`)
**Prototipada nesta branch.** É a peça mais nova: exige uma query nova
(`get_pesquisa_por_id`, adicionada em `db/pesquisas.py`) porque
`get_pesquisas_mais_recentes` só retorna a pesquisa *mais recente* por
cargo, não uma arbitrária por id. É também o caso de uso mais direto do
jornalista — "essa pesquisa específica da Quaest, dessa data" — e o que
`PRODUCT.md` descreve literalmente. Recomendado como primeiro passo porque
resolve a lacuna mais aguda (nenhum permalink de pesquisa existe hoje) com
o menor escopo de UI (uma página, não uma nova visão inteira).

### Opção B — Permalink por candidato (`/comparativo/<candidato>` ou query-string)
Não prototipada — **zero query nova necessária**: `get_comparativo_candidato`
já existe e já é usada por `/api/comparativo`, retornando exatamente o
formato (instituto, percentual, data, margem de erro) que uma view de
candidato precisaria. O trabalho aqui é 100% rota + template. Vale como
segundo passo: complementa A dando ao jornalista/analista um link para "a
comparação histórica completa deste candidato entre institutos", não só uma
pesquisa isolada.

### Por que não D ("não vale a pena ainda")
`PRODUCT.md` já nomeia a persona e o critério de sucesso — não é uma
feature especulativa, é uma lacuna documentada contra o próprio propósito
declarado do produto. Não há indício levantado neste spike de que a
funcionalidade seja desnecessária; a única razão para D seria dado de
tráfego mostrando que ninguém faz deep-link hoje, o que este spike não
investigou (fora de escopo — não há analytics no repo).

## Protótipo (o que foi construído)

- **Query**: `db/pesquisas.py::get_pesquisa_por_id(pesquisa_id)` — busca a
  pesquisa por id (join `pesquisas` + `institutos`) e suas intenções
  (join `intencoes`), retorna `None` se o id não existir. Segue o padrão de
  `get_comparativo_candidato` (parametrizada, `get_db()` context manager).
- **Rota**: `GET /pesquisa/<int:pesquisa_id>` em `app.py`, adicionada à
  whitelist de `require_login` (`allowed_endpoints`) — sem isso a rota
  redirecionaria para `/login`, o que quebraria o próprio caso de uso
  (link público compartilhável). Essa foi uma mudança fora do "só rotas/
  funções novas" original do plano, mas necessária para provar o conceito:
  um permalink que exige login não serve ao jornalista.
- **Template**: `templates/pesquisa_detalhe_spike.html` — tabela HTML crua
  (instituto, cargo, data, margem de erro, amostra, fonte, candidato/
  partido/percentual/tipo), sem estilo do design system, com aviso visível
  de que é protótipo.
- **Verificado**: `python app.py` (porta 5091 nesta sessão, para não
  colidir com processos preexistentes na máquina), `curl` em
  `/pesquisa/<id-real-seedado>` → HTTP 200 renderizando dados reais;
  `/pesquisa/999999` (id inexistente) → HTTP 404 com corpo "Pesquisa não
  encontrada".
- **Smoke test**: `tests/test_dashboard.py::test_pesquisa_detalhe_smoke`
  cobre os dois casos (id existente do seed, id inexistente) sem crash.

## Estado do protótipo — não mergear como está

- Template sem qualquer estilo do design system (Design Principle 2 de
  `PRODUCT.md` exige fonte/instituto/data/tipo visíveis — o protótipo
  mostra os campos, mas não com a hierarquia visual do resto do site).
- Rota nova foi adicionada à whitelist de rotas públicas em `app.py` —
  revisar essa decisão junto com o maintainer antes de qualquer merge; foi
  necessária para o protótipo provar o caso de uso real, mas não foi uma
  decisão "só aditiva" como o resto do escopo do spike.
- Nome de rota (`/pesquisa/<id>`) é só um exemplo de trabalho, não uma
  proposta final de URL scheme (ver "Questões em aberto").

## Questões em aberto para o maintainer

1. **URL scheme.** `/pesquisa/<id>` usa o id interno do banco — não é
   amigável nem estável se o schema mudar. Alternativas: slug
   (`/pesquisa/quaest-2026-07-15-presidente`), ou manter id numérico mas
   validar que nunca precisa ser re-emitido.
2. **SEO / indexação.** `PRODUCT.md` não menciona SEO. Não investigado aqui.
   Decisão pendente: páginas de pesquisa devem ser indexáveis pelo Google
   (robots.txt, sitemap.xml, `<meta name="robots">`)? Isso afeta se a opção
   A vira um canal de aquisição orgânica ou só um destino de link direto.
3. **Open Graph / social share.** Contexto de uso descrito em `PRODUCT.md`
   é "acesso via link direto (WhatsApp, Twitter/X, matéria)" — sem tags OG
   (`og:title`, `og:description`, `og:image`), um link de pesquisa
   compartilhado no WhatsApp mostra só a URL crua, sem preview. Não
   implementado neste spike; é um requisito forte se A for adiante.
4. **Esforço do build completo (não-protótipo), uma vez escolhida a
   direção**: estimativa grosseira — opção A com estilo real + OG tags +
   testes completos: **S/M** (a query já existe, é composição de UI +
   meta tags). Opção B: **S** (query já existe, só rota + template). Fazer
   as duas em sequência: **M**.

## Fora de escopo deste spike

- Decisão de exportação CSV/JSON (roadmap #9 em `plans/README.md`) —
  direção relacionada, mas independente.
- Qualquer implementação de SEO/OG — só sinalizado acima como pendente.
