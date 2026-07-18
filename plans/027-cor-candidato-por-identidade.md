# Plan 027: Cor do candidato nos gráficos por identidade, não por posição no array

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat f53d533..HEAD -- templates/dashboard.html static/js/charts.js`
> If either file changed since this plan was written, compare the "Current
> state" excerpts below against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug (UX)
- **Planned at**: commit `f53d533`, 2026-07-16

## Why this matters

The presidente and governador bar charts color each bar by
`PE_CANDIDATE_COLORS[ctx2.dataIndex % PE_CANDIDATE_COLORS.length]` — i.e.
by the candidate's **position** in the API response array, not by who they
are. If the backend ever returns candidates in a different order between
two requests (a new poll changes the ranking, a different institute lists
candidates in a different order, `tipo` toggles between estimulada/
espontânea and the candidate set/order shifts), the same candidate can be
rendered in a different color on reload — undermining the one piece of
visual consistency a reader relies on to track a specific candidate across
views. There's already a `getCandidateColor(name)` function in the file
that attempts to solve this by name, but it's **dead code** — hardcoded to
5 specific presidential names, never called from either chart, and would
return the same grey fallback (`'#5a7184'`) for every RJ governor
candidate even if it were called. This plan replaces both the dead
function and the position-based coloring with one memoized, name-keyed
color assignment that works for any candidate in any race.

## Current state

- `templates/dashboard.html:332-339` — the dead, presidente-only function:

```js
function getCandidateColor(name) {
  if (name === 'Lula') return PE_CANDIDATE_COLORS[0];
  if (name === 'Flávio Bolsonaro') return PE_CANDIDATE_COLORS[1];
  if (name === 'Tarcísio de Freitas') return PE_CANDIDATE_COLORS[2];
  if (name === 'Ciro Gomes') return PE_CANDIDATE_COLORS[3];
  if (name === 'Simone Tebet') return PE_CANDIDATE_COLORS[4];
  return '#5a7184';
}
```

  Confirmed dead: `grep -n "getCandidateColor(" templates/dashboard.html`
  shows only the function definition itself, no call sites.

- `templates/dashboard.html:378` and `:436` — the two bar-chart
  `backgroundColor` callbacks that color by array position (presidente and
  governador charts respectively):

```js
datasets: [{ data: data.percentuais, backgroundColor: ctx2 => PE_CANDIDATE_COLORS[ctx2.dataIndex % PE_CANDIDATE_COLORS.length], borderRadius: 4, barThickness: 16 }]
```

  (identical on both lines — same bug in both charts)

- `static/js/charts.js:223-229` — the 5-color palette these callbacks pull
  from:

```js
const PE_CANDIDATE_COLORS = [
  '#0A2240',  // cand-1
  '#C0392B',  // cand-2
  '#5a7184',  // cand-3
  '#B4B2A9',  // cand-4
  '#1D9E75',  // cand-5
];
```

  Exported as `window.PE_CANDIDATE_COLORS` — already global, available to
  `dashboard.html`'s inline script.

- The two charts (`chart-presidente`, `chart-governador`) are independent
  `Chart.js` instances, each destroyed and recreated on data reload
  (`carregarPresidente`/`carregarGovernador`, both call `chartXxx.destroy()`
  before creating a new one) — a color-assignment cache must therefore live
  **outside** either function (module-level in the inline script), so it
  persists across reloads/toggles and isn't reset every time a chart is
  recreated.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Run tests | `TESTING=True python -m pytest -q` | all pass (this is a frontend-only change; confirms nothing else broke) |
| Manual check | reload the dashboard a few times, toggle estimulada/espontânea, confirm the same candidate name keeps the same bar color across reloads even if their rank/position changes | color stable per name |

## Scope

**In scope**:
- `templates/dashboard.html` — remove `getCandidateColor` (dead code),
  add a shared memoized color-by-name assigner, and update both chart
  `backgroundColor` callbacks (presidente and governador) to use it

**Out of scope**:
- `static/js/charts.js` / `PE_CANDIDATE_COLORS` itself — the 5-color
  palette stays as-is; this plan only changes *how* a color is picked from
  it, not the palette.
- Any other chart in the file (historico-multi already assigns its own
  `cor` per series server-side via `data.series[i].cor`, per
  `carregarHistoricoMulti` — confirm this is untouched by re-reading that
  function, but don't modify it; it's a different, already-stable
  mechanism).
- Persisting the color assignment across page reloads (a full browser
  refresh) — an in-memory `Map` reset on refresh is acceptable; the bug
  being fixed is same-session inconsistency (toggle/reload without a full
  page refresh), not cross-session persistence.

## Git workflow

- Branch: `advisor/027-cor-candidato-por-identidade`
- Commit message style: conventional commits in Portuguese, e.g.
  `fix(dashboard): cor do candidato nos gráficos por identidade, não posição`
- Do NOT push or open a PR unless explicitly instructed.

## Steps

### Step 1: Replace `getCandidateColor` with a memoized, name-keyed assigner

Replace the dead function at `templates/dashboard.html:332-339` with a
generic version that works for any candidate name (presidente or
governador), assigning the next unused palette color the first time a name
is seen and remembering it thereafter:

```js
const _candidateColorMap = new Map();
let _candidateColorNextIndex = 0;

function getCandidateColor(name) {
  if (!_candidateColorMap.has(name)) {
    _candidateColorMap.set(name, PE_CANDIDATE_COLORS[_candidateColorNextIndex % PE_CANDIDATE_COLORS.length]);
    _candidateColorNextIndex++;
  }
  return _candidateColorMap.get(name);
}
```

Note this single map is shared between the presidente and governador
charts (both draw from the same `PE_CANDIDATE_COLORS` palette and the
races don't overlap in candidate names in practice, so sharing is fine and
simpler than two separate maps — if you find a real name collision between
races during testing, switch to two separate `Map`s, one per race, and
note why in your report).

**Verify**: `grep -n "_candidateColorMap" templates/dashboard.html` shows
the new module-level state.

### Step 2: Update the presidente chart's `backgroundColor` callback

At `templates/dashboard.html:378` (inside `carregarPresidente`), change:

```js
datasets: [{ data: data.percentuais, backgroundColor: ctx2 => PE_CANDIDATE_COLORS[ctx2.dataIndex % PE_CANDIDATE_COLORS.length], borderRadius: 4, barThickness: 16 }]
```

to:

```js
datasets: [{ data: data.percentuais, backgroundColor: ctx2 => getCandidateColor(data.candidatos[ctx2.dataIndex]), borderRadius: 4, barThickness: 16 }]
```

(`data.candidatos` is the same array Chart.js is already using for
`labels:` a few lines above in the same `new Chart({...})` call — confirm
it's in scope/accessible at this point in the function before assuming
this works verbatim.)

**Verify**: reload the presidente chart with different `tipo` toggles
(estimulada/espontânea) — Lula (or whichever candidate) keeps the same bar
color across toggles, even if percentuais/order shift.

### Step 3: Update the governador chart's `backgroundColor` callback

Same change at `templates/dashboard.html:436` (inside `carregarGovernador`),
using that function's own `data.candidatos` array.

**Verify**: same manual check as Step 2, for the governador chart.

### Step 4: Confirm no other caller depended on the old positional behavior

Search for any other reference to the removed function's old 5-name
hardcoded behavior (`grep -n "Tarcísio de Freitas\|Simone Tebet"
templates/dashboard.html` — these two names only appeared inside the dead
function, so this should return no matches after Step 1's edit; if it
does, something else was depending on the old function, and you should
stop and investigate before proceeding).

**Verify**: `grep -n "Tarcísio de Freitas" templates/dashboard.html`
returns no matches (confirms the dead code and its hardcoded names are
fully gone, not partially).

## Test plan

- This is a frontend-only, purely visual change — no new Python test is
  required. `TESTING=True python -m pytest -q` should pass unaffected
  (confirms no Python-side test asserts on the removed function name or
  the old `PE_CANDIDATE_COLORS[ctx2.dataIndex...]` pattern — check with
  `grep -rn "getCandidateColor\|dataIndex" tests/` first, should be empty).
- Manual verification (Steps 2 and 3) is the real test here, since the
  behavior only manifests visually in a live chart re-render.

## Done criteria

- [ ] `TESTING=True python -m pytest -q` exits 0
- [ ] `grep -n "PE_CANDIDATE_COLORS\[ctx2.dataIndex" templates/dashboard.html` returns no matches (both chart callbacks migrated)
- [ ] `grep -n "getCandidateColor(data.candidatos\[ctx2.dataIndex\])" templates/dashboard.html` shows 2 matches (presidente + governador)
- [ ] `grep -n "Tarcísio de Freitas\|Simone Tebet" templates/dashboard.html` returns no matches (dead hardcoded names removed)
- [ ] Manual check: same candidate name keeps the same color across a
      tipo-toggle reload in both charts
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row for 027 updated

## STOP conditions

- `templates/dashboard.html:332-339`, `:378`, or `:436` don't match the
  excerpts above (file has drifted) — re-grep and re-read before editing.
- `data.candidatos` isn't actually in scope at the point where the
  `backgroundColor` callback runs inside either `new Chart({...})` call
  (e.g. it's been renamed or restructured) — re-read the full
  `carregarPresidente`/`carregarGovernador` functions to find the correct
  variable name before assuming this plan's snippet applies verbatim.
- You find a real candidate-name collision between the presidente and
  governador races (unlikely, but check `data/pulso.db` or ask) — in that
  case use two separate `Map`s instead of one shared one, per the note in
  Step 1.

## Maintenance notes

- If a chart is added for a race with more distinct candidates than
  `PE_CANDIDATE_COLORS.length` (5), the modulo wrap in
  `_candidateColorNextIndex % PE_CANDIDATE_COLORS.length` means the 6th
  candidate reuses the 1st candidate's color — this was already true of
  the old positional scheme too, so it's not a regression, but worth
  knowing if the palette ever needs to grow.
- The `historico-multi` chart's own per-series `cor` field (assigned
  server-side) is a separate, already-stable mechanism — don't merge it
  into this client-side map; they solve the same problem for a different
  chart and don't need to share code.
