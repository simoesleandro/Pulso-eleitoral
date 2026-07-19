<div align="center">

<img src="docs/screenshot.png" alt="Pulso Eleitoral screenshot" width="100%">

<br/>

# Pulso Eleitoral

**PT:** Radar de pesquisas eleitorais brasileiras — coleta automática, análise com IA e dashboard público  
**EN:** Brazilian electoral polls radar — automated collection, AI analysis and public dashboard

<br/>

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-22c55e?style=flat-square)](LICENSE)
[![Last Commit](https://img.shields.io/github/last-commit/simoesleandro/Pulso-eleitoral?style=flat-square&color=8b5cf6)](https://github.com/simoesleandro/Pulso-eleitoral/commits)
[![Issues](https://img.shields.io/github/issues/simoesleandro/Pulso-eleitoral?style=flat-square&color=f59e0b)](https://github.com/simoesleandro/Pulso-eleitoral/issues)
[![Flask](https://img.shields.io/badge/Flask-3.x-lightgrey?style=flat-square&logo=flask)](https://flask.palletsprojects.com)
[![Gemini](https://img.shields.io/badge/Gemini-2.5--Flash-4285F4?style=flat-square&logo=google)](https://aistudio.google.com)
[![Deploy](https://img.shields.io/badge/deploy-Fly.io-7C3AED?style=flat-square&logo=fly.io)](https://pulso-eleitoral.fly.dev/dashboard)

<br/>

[🔗 Demo ao vivo](https://pulso-eleitoral.fly.dev/dashboard) &nbsp;·&nbsp;
[🐛 Reportar bug](https://github.com/simoesleandro/Pulso-eleitoral/issues) &nbsp;·&nbsp;
[💡 Sugerir feature](https://github.com/simoesleandro/Pulso-eleitoral/issues)

</div>

---

## 📋 Índice / Table of Contents

- [Sobre / About](#-sobre--about)
- [Por que importa / Why it matters](#-por-que-importa--why-it-matters)
- [Competências demonstradas / Skills demonstrated](#-competências-demonstradas--skills-demonstrated)
- [Demo](#-demo)
- [Funcionalidades / Features](#-funcionalidades--features)
- [Metodologia / Methodology](#-metodologia--methodology)
- [Stack](#-stack)
- [Instalação / Setup](#-instalação--setup)
- [Variáveis de Ambiente / Environment Variables](#-variáveis-de-ambiente--environment-variables)
- [Arquitetura / Architecture](#-arquitetura--architecture)
- [Testes / Tests](#-testes--tests)
- [O que aprendi / What I learned](#-o-que-aprendi--what-i-learned)
- [Roadmap](#-roadmap)
- [Autor / Author](#-autor--author)

---

## 📌 Sobre / About

**PT:**  
Pulso Eleitoral é um radar de pesquisas eleitorais para as eleições brasileiras de 2026. Coleta automaticamente dados de institutos como Quaest via Playwright + Gemini, armazena em SQLite e exibe em dashboard público com gráficos, tendências e análise de cenário gerada por IA. Deploy no Fly.io com coleta local agendada via Task Scheduler.

**EN:**  
Pulso Eleitoral is an electoral polls radar for the 2026 Brazilian elections. It automatically collects data from institutes like Quaest via Playwright + Gemini, stores it in SQLite and displays it in a public dashboard with charts, trends and AI-generated scenario analysis. Deployed on Fly.io with local scheduled collection via Task Scheduler.

---

## 🎯 Por que importa / Why it matters

**PT:**  
Pesquisas eleitorais aparecem em muitos formatos: páginas dinâmicas, releases, PDFs, agregadores e notícias. O Pulso Eleitoral organiza essas fontes em um fluxo único para acompanhar tendências, comparar institutos e visualizar séries históricas em um dashboard público.

O objetivo é tornar a leitura do cenário mais transparente: separar coleta, normalização, armazenamento e visualização, registrando de onde cada dado veio e tratando limitações de fonte como parte do sistema.

**EN:**  
Electoral polls appear in many formats: dynamic pages, releases, PDFs, aggregators and news articles. Pulso Eleitoral organizes these sources into one workflow to track trends, compare institutes and visualize historical series in a public dashboard.

The goal is to make the electoral landscape easier to inspect: separating collection, normalization, storage and visualization, while keeping source limitations explicit.

---

## 🧠 Competências demonstradas / Skills demonstrated

| Área / Area | Evidência no projeto / Evidence |
|-------------|---------------------------------|
| Backend Python | Flask app, rotas de dashboard/admin, scripts de coleta e sincronização |
| Scraping e automação | Playwright, BeautifulSoup/lxml e coletores por instituto |
| IA aplicada | Gemini para extração estruturada e análise de cenário |
| Dados | SQLite, schema relacional, normalização de candidatos e séries históricas |
| Visualização | Dashboard público com Chart.js, KPIs e filtros de candidatos |
| Deploy | Fly.io em região GRU e sincronização de banco local para produção |
| Testes | Pytest cobrindo coletores, dashboard, banco, scheduler, usuários e notificações |

---

## 🎯 Demo

🔗 **Ao vivo / Live:** [pulso-eleitoral.fly.dev/dashboard](https://pulso-eleitoral.fly.dev/dashboard)

<details>
<summary>📸 Screenshots</summary>
<br/>

![Dashboard](docs/screenshot.png)

</details>

---

## ✨ Funcionalidades / Features

> **PT:** Monitoramento contínuo do cenário eleitoral brasileiro com IA  
> **EN:** Continuous monitoring of the Brazilian electoral landscape with AI

- ✅ Coleta automática diária via Playwright + Gemini
- ✅ Coletores para Quaest, Datafolha, Gazeta do Povo e Verita
- ✅ Dashboard público com gráficos Chart.js (Presidente + Gov. RJ)
- ✅ KPIs em tempo real — líder, tendências, institutos ativos
- ✅ Análise de cenário gerada por Gemini com cache de 6h
- ✅ Série histórica de intenções de voto por candidato
- ✅ Painel admin com gerenciamento de usuários (bcrypt)
- ✅ Notificações Telegram a cada nova coleta
- ✅ Deploy Fly.io + WinSW local (porta 5080)
- 🚧 Atlas Intel — coletor criado, limitado por indisponibilidade/DNS da fonte
- 🚧 Poder360 — coletor criado, limitado por paywall/produto pago

---

## 📐 Metodologia / Methodology

O pipeline separa responsabilidades para manter rastreabilidade:

1. **Coleta:** cada instituto tem um coletor próprio quando a fonte exige regra específica.
2. **Extração:** Playwright acessa páginas dinâmicas; Gemini ajuda a transformar textos/releases em dados estruturados.
3. **Normalização:** nomes de candidatos e institutos são padronizados antes de persistir.
4. **Persistência:** pesquisas e intenções de voto ficam em SQLite.
5. **Visualização:** o dashboard apresenta KPIs, tendências e séries históricas.
6. **Análise:** Gemini gera leitura de cenário com cache para evitar custo/latência desnecessários.

Limitações externas são tratadas explicitamente. Quando uma fonte muda para paywall, SPA fechada, PDF inconsistente ou domínio indisponível, o coletor é mantido documentado e desabilitado até haver caminho confiável.

---

## 🛠 Stack

| Camada / Layer | Tecnologia / Technology |
|----------------|------------------------|
| Backend | Python 3.11, Flask, Waitress |
| Frontend | HTML/CSS/JS, Chart.js 4 |
| Banco de dados / Database | SQLite |
| IA / AI | Gemini 2.5 Flash (google-genai) |
| Scraping | Playwright, BeautifulSoup4, lxml |
| Deploy | Fly.io (região GRU) |
| Testes / Tests | pytest (165 testes) |

---

## 🚀 Instalação / Setup

### Pré-requisitos / Prerequisites

- Python 3.11+
- pip
- Playwright (`python -m playwright install chromium`)

### Instalação / Installation

```bash
# Clone o repositório / Clone the repository
git clone https://github.com/simoesleandro/Pulso-eleitoral
cd Pulso-eleitoral

# Instale as dependências / Install dependencies
pip install -r requirements.txt
python -m playwright install chromium

# Configure as variáveis de ambiente / Set up environment variables
cp .env.example .env
# Edite .env com suas chaves / Edit .env with your keys

# Inicialize o banco / Initialize the database
python -c "import database; database.init_db()"

# Rode o projeto / Run the project
python app.py
```

---

## 💻 Uso / Usage

### Coleta manual de pesquisas

```bash
python coletar.py
```

### Sincronizar banco local com Fly.io

```bash
python scripts/sync_db.py
```

---

## 🔐 Variáveis de Ambiente / Environment Variables

| Variável | Descrição / Description | Padrão / Default |
|----------|------------------------|-----------------|
| `GEMINI_API_KEY` | Chave API Google Gemini | — |
| `TELEGRAM_BOT_TOKEN` | Token do bot Telegram | — |
| `TELEGRAM_CHAT_ID` | Chat ID para notificações | — |
| `ADMIN_PASS` | Senha do usuário admin | — (obrigatória; se ausente, uma senha aleatória é gerada e descartada) |
| `SECRET_KEY` | Chave secreta Flask session | — |

> Lista completa em / Full list in: [`.env.example`](.env.example)

---

## 🏗 Arquitetura / Architecture

```
Pulso-eleitoral/
├── collectors/          # Coletores por instituto (Quaest, Atlas, Poder360)
├── static/css/          # Design system (tokens.css, base.css)
├── static/js/           # Chart.js helpers (charts.js)
├── templates/           # Dashboard, login, admin
├── tests/               # 165 testes pytest
├── scripts/             # sync_db.py (local → Fly.io)
├── app.py               # Flask + rotas + APScheduler
├── database.py          # SQLite helpers
├── coletar.py           # Script standalone de coleta
└── notifier.py          # Notificações Telegram
```

**Fluxo principal / Main flow:**

```
Serviço Windows (WinSW) roda app.py 24/7 → scheduler interno dispara seg/qui às 10h
      ↓
Playwright abre browser → coleta HTML do instituto
      ↓
Gemini 2.5 Flash extrai candidatos + percentuais
      ↓
SQLite (pesquisas + intencoes)
      ↓
scripts/sync_db.py → Fly.io /data/pulso.db
      ↓
Dashboard público (pulso-eleitoral.fly.dev)
```

---

## 🧪 Testes / Tests

```bash
# Rodar todos os testes / Run all tests
pytest

# Com cobertura / With coverage
pytest --cov=. --cov-report=term-missing

# Teste específico / Specific test
pytest tests/test_dashboard.py -v
```

> **165 testes** cobrindo coletores, dashboard, banco, scheduler, notificações e usuários.

---

## 📚 O que aprendi / What I learned

- Projetar coletores resilientes para fontes heterogêneas, com regras diferentes por instituto.
- Usar IA como camada de extração e análise, mantendo persistência e visualização separadas.
- Normalizar entidades de domínio, como candidatos e institutos, antes de gerar gráficos.
- Lidar com limites reais de fontes públicas: paywalls, mudanças de layout, PDFs, SPAs e domínios instáveis.
- Publicar um dashboard com dados atualizados em produção e sincronização controlada de banco.
- Escrever testes para coletores e fluxos de dashboard, reduzindo risco quando fontes externas mudam.

---

## 🗺 Roadmap

- [x] Scraper Quaest com Playwright + Gemini
- [x] Scraper Datafolha com Playwright
- [x] Coletor Gazeta do Povo
- [x] Coletor Verita via PDF/texto
- [x] Dashboard público Chart.js
- [x] Deploy Fly.io
- [x] Análise de cenário com Gemini (cache 6h)
- [x] Notificações Telegram
- [x] Sistema de usuários com bcrypt
- [ ] Reavaliar Atlas Intel quando a fonte estiver acessível
- [ ] Reavaliar Poder360 se houver acesso confiável ao agregador
- [ ] Dados regionais (mapa por estado)
- [ ] Probabilidade de 2º turno

---

## 👤 Autor / Author

<div align="center">

**Leandro Simões**

[![LinkedIn](https://img.shields.io/badge/LinkedIn-0077B5?style=flat-square&logo=linkedin&logoColor=white)](https://linkedin.com/in/leandro-sim%C3%B5es-7a0b3537b)
[![GitHub](https://img.shields.io/badge/GitHub-181717?style=flat-square&logo=github&logoColor=white)](https://github.com/simoesleandro)
[![Portfolio](https://img.shields.io/badge/Portfolio-06b6d4?style=flat-square&logo=safari&logoColor=white)](https://simoesleandro.github.io/portfolio)

*Fullstack · IA Aplicada · Civic Tech*

</div>

---

<div align="center">

Feito com ☕ e IA em / Made with ☕ and AI in 🇧🇷 Rio de Janeiro

</div>
