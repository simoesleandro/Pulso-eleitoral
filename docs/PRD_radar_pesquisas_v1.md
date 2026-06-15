# PRD — Radar de Pesquisas Eleitorais 2026
**Versão:** 1.0  
**Data:** Junho 2026  
**Autor:** Leandro Simões  
**Status:** Draft

---

## 1. Visão Geral

### Problema
Partidos e campanhas políticas consomem pesquisas eleitorais de forma fragmentada — cada instituto publica no seu site, em formatos diferentes, sem histórico consolidado nem análise de tendência. Identificar movimentos nas intenções de voto exige horas de trabalho manual.

### Solução
Dashboard centralizado que agrega pesquisas eleitorais de múltiplos institutos, normaliza os dados, exibe evolução temporal e cruza com eventos da campanha para identificar o que moveu as pesquisas — com análise de sentimento e alertas automáticos de variação relevante.

### Proposta de Valor
> "Todos os institutos, um único painel. Veja as ondas antes dos adversários."

---

## 2. Contexto e Escopo

### Eleições Alvo
- **Outubro 2026** — Eleições Gerais Brasileiras
- **Cargos monitorados:** Presidente + Governador do Rio de Janeiro

### Institutos Monitorados
| Instituto | Frequência | Fonte |
|-----------|-----------|-------|
| Datafolha | Mensal/quinzenal | datafolha.folha.uol.com.br |
| Quaest | Quinzenal | quaest.com.br |
| AtlasIntel | Semanal | atlasintel.org |
| PoderData | Quinzenal | poder360.com.br |
| Paraná Pesquisas | Mensal | paranapesquisas.com.br |
| MDA/CNT | Mensal | cnt.org.br |
| Real Time Big Data | Quinzenal | realtimebigdata.com.br |

### Escopo MVP
- Presidente: top 5 candidatos por intenção de voto
- Governador RJ: top 5 candidatos
- Série histórica desde janeiro 2026
- Alertas de variação > 2 pontos percentuais

### Fora do Escopo MVP
- Outros estados além do RJ
- Pesquisas de segundo turno
- Simulações eleitorais
- Integração com redes sociais

---

## 3. Usuários

### Primário
**Analista Político de Partido/Campanha**
- Precisa acompanhar evolução diária das pesquisas
- Quer identificar tendências antes da imprensa
- Precisa correlacionar eventos com variações nas pesquisas
- Usa para embasar decisões estratégicas de campanha

### Secundário
**Coordenador de Campanha**
- Quer visão executiva rápida — sem mergulhar nos dados
- Recebe resumo diário automatizado
- Aciona a equipe quando há variação relevante

---

## 4. Funcionalidades

### F1 — Agregador de Pesquisas (MVP)
- Coleta automática de novas pesquisas via scraping
- Normalização dos dados (% intenção de voto por candidato)
- Deduplicação (mesma pesquisa publicada em múltiplos veículos)
- Histórico desde jan/2026
- Fonte e metodologia de cada pesquisa acessíveis

### F2 — Dashboard de Evolução (MVP)
- Gráfico de linha temporal por candidato (presidente e governador RJ)
- Filtros: cargo, candidato, instituto, período
- Média agregada de todos os institutos (poll of polls)
- Destaque visual quando pesquisa nova é adicionada

### F3 — Poll of Polls (MVP)
- Média ponderada das últimas pesquisas por instituto
- Peso maior para pesquisas mais recentes
- Margem de erro agregada
- Atualização automática quando nova pesquisa entra

### F4 — Linha do Tempo de Eventos (MVP)
- Cadastro manual de eventos da campanha (debate, escândalo, comício)
- Exibição no gráfico como marcadores verticais
- Correlação visual entre evento e variação nas pesquisas

### F5 — Alertas de Variação (MVP)
- Notificação via Telegram quando:
  - Candidato varia > 2pp em relação à pesquisa anterior do mesmo instituto
  - Nova pesquisa de qualquer instituto é detectada
  - Candidato atinge novo pico ou mínimo histórico
- Resumo diário às 8h com pesquisas das últimas 24h

### F6 — Análise de Tendência com IA (MVP)
- Gemini analisa a série histórica e gera narrativa de tendência
- "Candidato X está em trajetória de alta há 3 semanas consecutivas"
- Identificação de momento de virada (inflection point)
- Gerado automaticamente a cada nova pesquisa inserida

### F7 — Comparativo de Institutos (pós-MVP)
- Identifica institutos sistematicamente otimistas/pessimistas por candidato
- House effect de cada instituto
- Credibilidade histórica baseada em eleições passadas

---

## 5. Arquitetura Técnica

### Fluxo de Dados

```
Sites dos institutos
        ↓
   Scraper Python
  (BeautifulSoup + requests)
        ↓
   Parser + Normalização
  (extrai %, candidato, data, instituto)
        ↓
      SQLite
        ↓
   Gemini API          APScheduler
  (análise tendência)  (coleta diária 6h)
        ↓
   Dashboard Flask     Telegram Bot
```

### Stack
| Camada | Tecnologia |
|--------|-----------|
| Backend | Python 3.11, Flask, Waitress |
| Scraping | requests, BeautifulSoup4 |
| Banco | SQLite |
| IA | Gemini API |
| Scheduler | APScheduler |
| Frontend | Vanilla JS, Chart.js |
| Notificações | Telegram Bot API |
| Deploy | Fly.io |

### Schema Principal

```sql
CREATE TABLE institutos (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    sigla TEXT,
    site TEXT,
    ativo INTEGER DEFAULT 1
);

CREATE TABLE pesquisas (
    id INTEGER PRIMARY KEY,
    instituto_id INTEGER REFERENCES institutos(id),
    cargo TEXT,  -- 'presidente' | 'governador_rj'
    data_pesquisa TEXT,
    data_publicacao TEXT,
    tamanho_amostra INTEGER,
    margem_erro REAL,
    contratante TEXT,
    registro_tse TEXT,
    fonte_url TEXT,
    coletado_em TEXT DEFAULT (datetime('now'))
);

CREATE TABLE intencoes (
    id INTEGER PRIMARY KEY,
    pesquisa_id INTEGER REFERENCES pesquisas(id),
    candidato TEXT,
    partido TEXT,
    percentual REAL,
    tipo TEXT  -- 'espontanea' | 'estimulada'
);

CREATE TABLE eventos (
    id INTEGER PRIMARY KEY,
    data TEXT,
    titulo TEXT,
    descricao TEXT,
    cargo TEXT,
    impacto TEXT  -- 'positivo' | 'negativo' | 'neutro' | 'indefinido'
);

CREATE TABLE alertas (
    id INTEGER PRIMARY KEY,
    tipo TEXT,
    candidato TEXT,
    cargo TEXT,
    variacao REAL,
    pesquisa_id INTEGER REFERENCES pesquisas(id),
    enviado_telegram INTEGER DEFAULT 0,
    criado_em TEXT DEFAULT (datetime('now'))
);
```

---

## 6. Fases de Desenvolvimento

### Fase 1 — Fundação (Semana 1)
- [ ] Schema SQLite + modelos
- [ ] Scraper manual para 2 institutos (Datafolha + Quaest)
- [ ] Parser e normalização dos dados
- [ ] Inserção histórica desde jan/2026

### Fase 2 — Dashboard (Semana 2)
- [ ] Gráfico de evolução temporal (Chart.js)
- [ ] Poll of polls
- [ ] Filtros por cargo, candidato, instituto, período
- [ ] Linha do tempo de eventos

### Fase 3 — Inteligência (Semana 3)
- [ ] Alertas via Telegram
- [ ] Análise de tendência com Gemini
- [ ] Relatório diário automático (APScheduler)
- [ ] Coleta automática dos 7 institutos

### Fase 4 — Deploy e Produção (Semana 4)
- [ ] Deploy Fly.io
- [ ] Autenticação básica (login/senha para o cliente)
- [ ] Documentação de uso
- [ ] Testes e ajustes finais

---

## 7. Desafios Técnicos

### Scraping de Sites de Notícias
Cada instituto publica de forma diferente. Estratégia por instituto:

| Instituto | Estratégia |
|-----------|-----------|
| Datafolha | Scraping da página de pesquisas eleitorais |
| Quaest | PDF público + parser de tabela |
| AtlasIntel | API pública (tem endpoint REST) |
| PoderData | Poder360 — scraping da seção pesquisas |
| Paraná Pesquisas | PDF + scraping do site |
| MDA/CNT | PDF público |
| Real Time Big Data | Scraping + PDF |

### Normalização de Candidatos
Cada instituto usa nomes diferentes (ex: "Lula", "Luiz Inácio Lula da Silva", "PT - Lula"). Necessário dicionário de normalização por candidato.

---

## 8. Métricas de Sucesso

| Métrica | Meta MVP |
|---------|----------|
| Institutos integrados | ≥ 4 no MVP |
| Latência nova pesquisa → dashboard | < 2h |
| Precisão da extração | > 95% |
| Uptime | > 99% |
| Alertas entregues no Telegram | 100% |

---

## 9. Riscos e Mitigações

| Risco | Probabilidade | Mitigação |
|-------|--------------|-----------|
| Site muda layout e quebra scraper | Alta | Parser por instituto isolado, fácil de corrigir |
| Instituto publica só em PDF | Média | Parser de PDF com pdfplumber |
| Candidatos variam (desistem, entram) | Alta | Dicionário de normalização atualizável |
| Dados divergentes entre institutos | Baixa | Exibir fonte sempre, nunca agregar sem indicar |

---

## 10. Próximos Passos

1. Aprovação do PRD
2. Wireframes das 3 telas principais (visão geral, presidente, governador RJ)
3. Design system (identidade visual do produto)
4. Início Fase 1 — scraper Datafolha + Quaest
5. Nome do produto

---

*Documento interno — Leandro Simões | Junho 2026*
