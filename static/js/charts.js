/**
 * PULSO ELEITORAL — Charts & Helpers
 * Versão: 1.0 | Junho 2026
 * Requer: Chart.js 4.x + chartjs-plugin-annotation
 */

'use strict';

/* ── Tokens (espelham tokens.css) ────────────────────────── */
const PE = {
  navy:    '#0A2240',
  red:     '#C0392B',
  surface: '#E8EDF2',
  muted:   '#5a7184',
  hint:    '#9aaab8',
  up:      '#1a7a4a',
  down:    '#A32D2D',
  warn:    '#BA7517',
  warnBg:  '#FAEEDA',
  warnText:'#633806',

  candidates: [
    '#0A2240',  // 1 · navy
    '#C0392B',  // 2 · vermelho
    '#5a7184',  // 3 · slate
    '#B4B2A9',  // 4 · gray
    '#1D9E75',  // 5 · teal
  ],

  font: {
    sans: "'Inter', system-ui, sans-serif",
    mono: "'JetBrains Mono', monospace",
  }
};

/* ── Defaults globais Chart.js ───────────────────────────── */
const PE_CHART_DEFAULTS = {
  responsive: true,
  maintainAspectRatio: false,
  animation: { duration: 400 },
  plugins: {
    legend: { display: false },
    tooltip: {
      backgroundColor: PE.navy,
      titleColor: '#fff',
      bodyColor: 'rgba(255,255,255,0.75)',
      borderColor: 'rgba(255,255,255,0.12)',
      borderWidth: 0.5,
      padding: 10,
      cornerRadius: 6,
      callbacks: {
        label: ctx => ` ${ctx.parsed.y.toFixed(1)}%`
      }
    }
  },
  scales: {
    x: {
      grid: { color: 'rgba(10,34,64,0.06)', drawBorder: false },
      ticks: {
        color: PE.muted,
        font: { size: 11, family: PE.font.mono },
        maxRotation: 0
      }
    },
    y: {
      grid: { color: 'rgba(10,34,64,0.06)', drawBorder: false },
      ticks: {
        color: PE.muted,
        font: { size: 11, family: PE.font.mono },
        callback: v => v + '%'
      },
      suggestedMin: 0,
      suggestedMax: 60
    }
  }
};

/* ── Dataset padrão para um candidato ───────────────────── */
function peCandidateDataset(label, data, candidateIndex, options = {}) {
  const color = PE.candidates[candidateIndex] ?? PE.muted;
  return {
    label,
    data,
    borderColor: color,
    backgroundColor: color + '18',
    borderWidth: 2,
    pointRadius: 3,
    pointHoverRadius: 5,
    pointBackgroundColor: color,
    tension: 0.3,
    fill: false,
    ...options
  };
}

/* ── Anotação de evento na linha do tempo ────────────────── */
function peEventAnnotation(xValue, label) {
  return {
    type: 'line',
    xMin: xValue,
    xMax: xValue,
    borderColor: PE.warn,
    borderDash: [4, 4],
    borderWidth: 1.5,
    label: {
      display: true,
      content: label,
      color: PE.warnText,
      backgroundColor: PE.warnBg,
      font: { size: 9, family: PE.font.mono },
      padding: { x: 4, y: 2 },
      position: 'start',
      yAdjust: 6
    }
  };
}

/* ── Criar gráfico de linha temporal ────────────────────── */
function peCreateLineChart(canvasId, labels, datasets, events = [], options = {}) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;

  const annotations = {};
  events.forEach((evt, i) => {
    annotations[`event_${i}`] = peEventAnnotation(evt.x, evt.label);
  });

  return new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      ...PE_CHART_DEFAULTS,
      plugins: {
        ...PE_CHART_DEFAULTS.plugins,
        annotation: { annotations },
        ...options.plugins
      },
      scales: {
        ...PE_CHART_DEFAULTS.scales,
        ...options.scales
      }
    }
  });
}

/* ── Formatar data para exibição ─────────────────────────── */
function peFormatDate(isoDate) {
  if (!isoDate) return '—';
  const [y, m, d] = isoDate.split('-');
  return `${d}/${m}/${y}`;
}

/* ── Formatar variação com sinal ─────────────────────────── */
function peFormatDelta(value) {
  if (value === null || value === undefined) return '—';
  const fixed = Math.abs(value).toFixed(1);
  if (value > 0) return `+${fixed}pp`;
  if (value < 0) return `−${fixed}pp`;
  return `${fixed}pp`;
}

/* ── Classe CSS de tendência ─────────────────────────────── */
function peDeltaClass(value) {
  if (value > 0.1)  return 'pe-up-text';
  if (value < -0.1) return 'pe-down-text';
  return 'pe-flat-text';
}

/* ── Badge de instituto ──────────────────────────────────── */
function peBadgeInst(nome) {
  return `<span class="pe-badge pe-badge--inst">${nome}</span>`;
}

/* ── Badge de cargo ──────────────────────────────────────── */
function peBadgeCargo(cargo) {
  const label = cargo === 'presidente' ? 'presidente' : 'gov. rj';
  return `<span class="pe-badge pe-badge--cargo">${label}</span>`;
}

/* ── Renderizar linha de poll bar ────────────────────────── */
function pePollRow(nome, percentual, delta, color) {
  const deltaClass = peDeltaClass(delta);
  const deltaStr   = delta !== null ? peFormatDelta(delta) : '—';
  return `
    <div class="pe-poll__row">
      <span class="pe-poll__name">${nome}</span>
      <div class="pe-poll__bar-wrap">
        <div class="pe-poll__bar" style="width:${percentual}%;background:${color};"></div>
      </div>
      <span class="pe-poll__pct">${percentual.toFixed(1)}%</span>
      <span class="pe-poll__delta ${deltaClass}">${deltaStr}</span>
    </div>
  `;
}

/* ── Renderizar alerta ───────────────────────────────────── */
function peAlertRow(texto, tipo, tempo) {
  const cls = tipo === 'up' ? 'pe-alert--up' : 'pe-alert--down';
  const icon = tipo === 'up' ? 'ti-trending-up' : 'ti-trending-down';
  return `
    <div class="pe-alert ${cls}">
      <i class="ti ${icon}" aria-hidden="true" style="font-size:13px;flex-shrink:0;"></i>
      <span>${texto}</span>
      <span class="pe-alert__time">${tempo}</span>
    </div>
  `;
}

/* ── Fetch helper com erro tratado ───────────────────────── */
async function peFetch(url, params = {}) {
  const qs = new URLSearchParams(params).toString();
  const fullUrl = qs ? `${url}?${qs}` : url;
  try {
    const res = await fetch(fullUrl);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error('[Pulso] fetch error:', url, err);
    return null;
  }
}

const PE_CANDIDATE_COLORS = [
  '#0A2240',  // cand-1
  '#C0392B',  // cand-2
  '#5a7184',  // cand-3
  '#B4B2A9',  // cand-4
  '#1D9E75',  // cand-5
];

/* ── Export ──────────────────────────────────────────────── */
window.PE = PE;
window.PE_CANDIDATE_COLORS = PE_CANDIDATE_COLORS;
window.PE_CHART_DEFAULTS = PE_CHART_DEFAULTS;
window.peCandidateDataset  = peCandidateDataset;
window.peCreateLineChart   = peCreateLineChart;
window.peEventAnnotation   = peEventAnnotation;
window.peFormatDate        = peFormatDate;
window.peFormatDelta       = peFormatDelta;
window.peDeltaClass        = peDeltaClass;
window.peBadgeInst         = peBadgeInst;
window.peBadgeCargo        = peBadgeCargo;
window.pePollRow           = pePollRow;
window.peAlertRow          = peAlertRow;
window.peFetch             = peFetch;
