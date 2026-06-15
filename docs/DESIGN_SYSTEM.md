# Design System — Pulso Eleitoral
**Versão:** 1.0 | **Data:** Junho 2026 | **Autor:** Leandro Simões

---

## 1. Identidade Visual

### Nome e Tagline
- **Produto:** Pulso Eleitoral
- **Tagline:** monitoramento político · 2026
- **Uso:** sempre em sentence case, nunca em caps

### Logo
O logomark é um ícone de ondas concêntricas (pulso) em vermelho `#C0392B` sobre fundo azul-marinho `#0A2240`, representando monitoramento em tempo real de dados eleitorais.

**Variações:**
- Completo: logomark + nome + tagline (páginas de login, documentos)
- Compacto: logomark + nome (topbar)
- Ícone: só o logomark (favicon, app icon)

---

## 2. Paleta de Cores

### Primárias
| Token | Hex | Uso |
|-------|-----|-----|
| `--pe-navy` | `#0A2240` | cor primária, textos principais, topbar |
| `--pe-navy-light` | `#1B3D6B` | hover, estados ativos |
| `--pe-red` | `#C0392B` | acento eleitoral, logomark, tab ativo |
| `--pe-red-light` | `#E04030` | hover do acento |

### Fundos
| Token | Hex | Uso |
|-------|-----|-----|
| `--pe-bg` | `#F7F9FB` | página |
| `--pe-surface` | `#E8EDF2` | KPI cards, chips, hover de tabela |
| `--pe-surface-2` | `#FFFFFF` | cards primários, modais |

### Semânticas
| Token | Hex | Uso |
|-------|-----|-----|
| `--pe-up` | `#1a7a4a` | alta, variação positiva |
| `--pe-down` | `#A32D2D` | queda, variação negativa, alerta crítico |
| `--pe-warn` | `#BA7517` | atenção, evento na linha do tempo |

### Candidatos (série temporal)
| Token | Hex | Uso |
|-------|-----|-----|
| `--pe-cand-1` | `#0A2240` | candidato 1 (sempre navy) |
| `--pe-cand-2` | `#C0392B` | candidato 2 |
| `--pe-cand-3` | `#5a7184` | candidato 3 |
| `--pe-cand-4` | `#B4B2A9` | candidato 4 |
| `--pe-cand-5` | `#1D9E75` | candidato 5 |
| `--pe-event-line` | `#BA7517` | linha de evento (tracejada) |

> Regra: a cor do candidato é sempre a mesma em todos os gráficos e componentes. Nunca troque as cores entre candidatos.

---

## 3. Tipografia

### Fontes
- **Display/UI:** Inter (Google Fonts) — pesos 400 e 500 apenas
- **Dados/Código:** JetBrains Mono — datas, registros TSE, percentuais em tabelas

### Escala
| Classe | Tamanho | Peso | Uso |
|--------|---------|------|-----|
| `.pe-display` | 22px | 500 | nome do produto, títulos de página |
| `.pe-heading` | 14px | 500 | títulos de seção, aba ativa |
| `.pe-label` | 11px | 500 | labels uppercase, títulos de card |
| `.pe-data` | 28px | 500 | números grandes (KPIs) |
| `.pe-mono` | 12px | 400 | datas, registros, metadados |

> Apenas dois pesos: 400 (regular) e 500 (medium). Nunca usar 600 ou 700.

---

## 4. Componentes

### Topbar
- Fundo: `--pe-navy` (#0A2240)
- Altura: 52px
- Logo à esquerda, nav central, status à direita
- Tab ativo: borda-bottom 1.5px `--pe-red`
- Status dot verde quando sistema online

```html
<nav class="pe-topbar">
  <a class="pe-topbar__logo" href="/">
    <div class="pe-topbar__logomark"><!-- SVG onda --></div>
    <span class="pe-topbar__name">Pulso Eleitoral</span>
  </a>
  <div class="pe-topbar__nav">
    <a class="pe-topbar__nav-item pe-topbar__nav-item--active" href="/">visão geral</a>
    <a class="pe-topbar__nav-item" href="/presidente">presidente</a>
    <a class="pe-topbar__nav-item" href="/governador-rj">gov. rj</a>
    <a class="pe-topbar__nav-item" href="/eventos">eventos</a>
  </div>
  <div class="pe-topbar__meta">
    atualizado há 2h
    <div class="pe-topbar__status-dot"></div>
  </div>
</nav>
```

### KPI Card
```html
<div class="pe-kpi">
  <div class="pe-kpi__label">pesquisas coletadas</div>
  <div class="pe-kpi__value">48</div>
  <div class="pe-kpi__sub">desde jan/2026</div>
</div>
```

### Poll Bar (barra de intenção de voto)
```html
<div class="pe-poll__row">
  <span class="pe-poll__name">Cand. A</span>
  <div class="pe-poll__bar-wrap">
    <div class="pe-poll__bar" style="width: 42%; background: var(--pe-cand-1);"></div>
  </div>
  <span class="pe-poll__pct">42%</span>
  <span class="pe-poll__delta pe-up-text">+1.2</span>
</div>
```

### Badges
```html
<!-- Instituto -->
<span class="pe-badge pe-badge--inst">Datafolha</span>

<!-- Cargo -->
<span class="pe-badge pe-badge--cargo">presidente</span>

<!-- Status -->
<span class="pe-badge pe-badge--new">nova pesquisa</span>
<span class="pe-badge pe-badge--alert">alerta variação</span>
```

### Alerta de variação
```html
<div class="pe-alert pe-alert--up">
  <!-- ícone trending-up -->
  Cand. A subiu 2.1pp na Quaest · maior alta em 30 dias
  <span class="pe-alert__time">há 2h</span>
</div>
```

### Análise IA
```html
<div class="pe-ia-block">
  <p class="pe-ia-block__text">
    Cand. A mantém trajetória de alta há 6 semanas consecutivas...
  </p>
  <div class="pe-ia-block__meta">gerado por gemini · atualizado há 2h</div>
</div>
```

---

## 5. Gráficos (Chart.js)

### Configuração padrão

```javascript
const PE_CHART_DEFAULTS = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { display: false },
    tooltip: {
      backgroundColor: '#0A2240',
      titleColor: '#fff',
      bodyColor: 'rgba(255,255,255,0.7)',
      borderColor: 'rgba(255,255,255,0.1)',
      borderWidth: 0.5,
      padding: 10,
      callbacks: {
        label: ctx => ` ${ctx.parsed.y.toFixed(1)}%`
      }
    }
  },
  scales: {
    x: {
      grid: { color: 'rgba(10,34,64,0.06)' },
      ticks: { color: '#5a7184', font: { size: 11, family: 'JetBrains Mono' } }
    },
    y: {
      grid: { color: 'rgba(10,34,64,0.06)' },
      ticks: {
        color: '#5a7184',
        font: { size: 11, family: 'JetBrains Mono' },
        callback: v => v + '%'
      }
    }
  }
};

const PE_CANDIDATE_COLORS = [
  '#0A2240',  // cand-1
  '#C0392B',  // cand-2
  '#5a7184',  // cand-3
  '#B4B2A9',  // cand-4
  '#1D9E75',  // cand-5
];

// Linha de evento
const PE_EVENT_ANNOTATION = (label) => ({
  type: 'line',
  borderColor: '#BA7517',
  borderDash: [4, 4],
  borderWidth: 1,
  label: {
    display: true,
    content: label,
    color: '#633806',
    backgroundColor: '#FAEEDA',
    font: { size: 9 }
  }
});
```

---

## 6. Estrutura de Arquivos

```
pulso-eleitoral/
├── static/
│   ├── css/
│   │   ├── tokens.css      ← variáveis CSS (este arquivo)
│   │   └── base.css        ← reset + componentes
│   └── js/
│       ├── charts.js       ← config Chart.js + helpers
│       └── app.js          ← lógica das telas
├── templates/
│   ├── base.html           ← layout com topbar
│   ├── index.html          ← visão geral
│   ├── presidente.html     ← detalhe presidente
│   └── governador_rj.html  ← detalhe governador RJ
└── DESIGN_SYSTEM.md        ← este arquivo
```

---

## 7. Regras de Uso

### Pode
- Usar tokens CSS para todas as cores
- Adicionar candidatos usando `--pe-cand-N` na sequência
- Criar variações de componentes mantendo a paleta

### Não pode
- Usar cores fora dos tokens definidos
- Misturar pesos de fonte além de 400 e 500
- Usar ALL CAPS em textos (exceto `.pe-label`)
- Trocar a cor de candidatos entre gráficos diferentes
- Adicionar gradientes, sombras ou efeitos visuais complexos

---

## 8. Acessibilidade

- Contraste mínimo 4.5:1 em todos os textos
- Navy `#0A2240` sobre branco: ratio 13.5:1 ✅
- Vermelho `#C0392B` sobre branco: ratio 5.1:1 ✅
- Foco visível em todos os elementos interativos
- Gráficos com legenda textual acessível

---

*Pulso Eleitoral · Design System v1.0 · Uso restrito*
