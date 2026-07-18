# Product

## Register

product

## Users

Três públicos sobrepostos no mesmo dashboard público:
- **Eleitor comum**: checa o cenário casualmente, quer entender rápido quem
  lidera, se há empate técnico, e como isso mudou recentemente — sem jargão
  estatístico.
- **Jornalista/imprensa**: cita números em matéria, precisa de fonte,
  instituto e metodologia claros e verificáveis; navega direto para dado
  específico (instituto, data, candidato).
- **Analista político**: quer profundidade — histórico, house effects,
  volatilidade, simulação de 2º turno — usa as seções de Análise/Dados.

Contexto de uso: acesso via link direto (WhatsApp, Twitter/X, matéria),
sessões curtas, majoritariamente mobile. Eleição 2026 (presidente + governador
do Rio de Janeiro).

## Product Purpose

Agregador transparente ("poll-of-polls") de pesquisas eleitorais brasileiras.
Existe para dar uma leitura mais estável do cenário do que uma pesquisa
isolada, sendo explícito sobre metodologia (ponderação por amostra × recência,
1 pesquisa por instituto, filtro estimulada-only) em `/metodologia`. Sucesso =
ser citável e confiável — número certo, fonte visível, sem viés aparente.

## Brand Personality

Editorial e didático: jornalismo de dados que explica o "porquê" dos números
para quem não é especialista, sem soar como um terminal de analista nem como
imprensa partidária. Precisão antes de personalidade, mas com espaço para
explicar (rótulos com contexto, não só o número cru).

## Anti-references

- Não deve parecer site de apostas/mercado de previsão (gamificado, "odds").
- Não deve parecer painel de analista de dados cru (SaaS denso, sem
  explicação, jargão de terminal).
- Não deve parecer veículo de imprensa partidário (ênfase visual em um lado
  do espectro político).

## Design Principles

1. **Um cargo por vez, visualmente.** Nunca misturar dado de presidente e de
   governador RJ na mesma seção/bloco sem rótulo explícito do cargo — é a
   fonte nº1 de confusão hoje (ver auditoria de IA em curso).
2. **Metodologia sempre visível, nunca escondida.** Fonte, instituto, data e
   tipo (estimulada/espontânea) acompanham todo número, não só um link para
   `/metodologia`.
3. **Escaneável antes de exaustivo.** Um eleitor casual deve entender o
   cenário em poucos segundos rolando a página; o analista que quer
   profundidade navega para uma seção dedicada, não precisa que a home
   carregue tudo.
4. **Neutralidade visual entre candidatos.** Cor por identidade do candidato
   (já implementado), nunca por posição/ranking — evitar qualquer leitura de
   "o de cima é o certo".

## Accessibility & Inclusion

Já passou por uma rodada de a11y básica (headings semânticos, aria-label nos
gráficos, aria-pressed nos toggles) — ver plano 028. Ainda sem auditoria WCAG
completa formal; tratar como produto público de uso geral (não há requisito
declarado de usuário com necessidade específica além disso).
