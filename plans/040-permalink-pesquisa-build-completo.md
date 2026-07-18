# Plan 040: Permalink de produção por pesquisa (`/pesquisa/<id>`) — build completo

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 8081abf..HEAD -- app.py database.py db/pesquisas.py templates/ static/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts below against the live code before proceeding;
> on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW — purely additive (new route, new template, new query
  function); no existing route, query, or template is modified.
- **Depends on**: none (supersedes the throwaway prototype from plan 039,
  which was merged then reverted — see "Relationship to plan 039" below)
- **Category**: direction (product feature, promoted from spike)
- **Planned at**: commit `8081abf`, 2026-07-17

## Why this matters

`PRODUCT.md` names "Jornalista/imprensa" as an explicit persona who needs
to "citar números em matéria" with "fonte, instituto e metodologia claros
e verificáveis" and "navega direto para dado específico (instituto, data,
candidato)." The doc states the product's own success metric: **"Sucesso =
ser citável e confiável."** Today the dashboard exposes only four broad
section anchors — nothing addresses one specific poll. Plan 039 (a spike)
validated the core idea with a throwaway, unstyled prototype and wrote a
recommendation (`docs/spike-permalink-pesquisa.md`, preserved on branch
`advisor/039-spike-permalink-pesquisa-candidato`, commit `3d2c2c3` — not on
`main`) recommending this exact feature (Option A: permalink por pesquisa)
as the first step, with Option B (permalink por candidato) as a deliberate
follow-up. This plan is the real build: production styling matching the
site's design system, Open Graph tags for the WhatsApp/Twitter sharing
context `PRODUCT.md` describes, and a decision on search-engine
indexability — the three things the spike explicitly flagged as unresolved
and unsuitable for merge as-is.

### Product decisions already made (do not re-litigate these)

The maintainer resolved the spike's three open questions before this plan
was written. Build to these decisions directly — do not present them as
open questions again:

1. **URL scheme**: numeric internal ID (`/pesquisa/<id>`), not a slug. Lower
   effort, already validated in the prototype; accepted the tradeoff that
   the URL isn't human-readable.
2. **SEO**: pages **should be indexable** by search engines (no `noindex`).
   This aligns with `PRODUCT.md`'s citability goal and may become an
   organic-traffic channel.
3. **Open Graph**: **include** `og:title`, `og:description`, and
   `og:image`-equivalent (see Step 4 — this repo has no per-poll chart
   image generation, so `og:image` falls back to a site-wide default image;
   generating a per-poll chart image is explicitly out of scope, see
   below) in this first build, not deferred to a later iteration.

## Relationship to plan 039

Plan 039 was executed as a spike, merged into `main`, then **reverted**
before push (commit `4fc586f` reverts merge `1c3f40f`) because the
prototype exposed an unstyled, unauthenticated route to production. The
spike's code (`get_pesquisa_por_id`, the bare route, the bare template) only
exists today on branch `advisor/039-spike-permalink-pesquisa-candidato` —
it is **not** in your starting `main` checkout. This plan does not depend on
that branch and does not assume its code is present; every "Current state"
excerpt below reflects what's actually on `main` today. Where useful, this
plan reuses the *query logic* the spike validated (same SQL shape), but
you are writing it fresh into `db/pesquisas.py`, not cherry-picking the old
branch.

## Current state

- `db/pesquisas.py:25-58` — `get_comparativo_candidato`, the closest
  existing exemplar for query style in this file (parameterized SQL,
  `get_db()` context manager, returns a plain dict):

```python
def get_comparativo_candidato(candidato: str, cargo: str) -> dict:
    """Retorna a pesquisa mais recente de cada instituto para o candidato/cargo."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT inst.nome AS instituto, i.percentual,
                   p.data_pesquisa AS data, p.margem_erro
            FROM intencoes i
            JOIN pesquisas p ON i.pesquisa_id = p.id
            JOIN institutos inst ON p.instituto_id = inst.id
            WHERE i.candidato = ? AND p.cargo = ?
            AND p.id = (
                ...
            )
        """).fetchall()
        ...
```

  No function named `get_pesquisa_por_id` exists in `db/pesquisas.py` today
  — confirm with `grep -n "get_pesquisa_por_id" db/pesquisas.py` (expected:
  no matches).

- `schema.sql:4-27` — the columns available on `pesquisas` and `institutos`
  that a full detail page should surface (the spike's prototype only used a
  subset — this build should use more, per `PRODUCT.md`'s "metodologia
  sempre visível" principle):

```sql
CREATE TABLE IF NOT EXISTS institutos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    sigla TEXT,
    site TEXT,
    ativo INTEGER DEFAULT 1,
    criado_em TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS pesquisas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instituto_id INTEGER NOT NULL,
    cargo TEXT NOT NULL,
    data_pesquisa TEXT NOT NULL,      -- período de campo
    data_publicacao TEXT NOT NULL,    -- quando foi divulgada
    tamanho_amostra INTEGER NOT NULL,
    margem_erro REAL NOT NULL,
    contratante TEXT,
    registro_tse TEXT NOT NULL UNIQUE, -- verificabilidade — mostrar isso
    fonte_url TEXT,
    coletado_em TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY(instituto_id) REFERENCES institutos(id) ON DELETE CASCADE
);
```

  `intencoes` rows for a poll have `candidato`, `partido`, `percentual`,
  `tipo` (`'espontanea'` | `'estimulada'`) — the detail page must show
  `tipo` per `PRODUCT.md` design principle 2 ("tipo (estimulada/espontânea)
  acompanham todo número").

- `db/candidatos.py:143-145` — `get_cores_candidatos()`, already used
  elsewhere in this codebase to color candidates by identity (per
  `PRODUCT.md` design principle 4, "cor por identidade do candidato, nunca
  por posição/ranking" — already implemented for the dashboard's charts via
  plan 027). This detail page's candidate list should use the same color
  mapping, not an arbitrary per-row color:

```python
def get_cores_candidatos() -> dict:
    """{nome_canonico -> cor_hex} dos candidatos com cor definida."""
    return _carregar_candidatos_cache()["cores"]
```

- `templates/base.html:1-21` — the shared layout every page extends,
  including a `head_meta` block that renders *before* `<title>` — this is
  where Open Graph `<meta>` tags belong (Step 4 needs this exact block):

```html
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  {% block head_meta %}{% endblock %}
  <title>{% block title %}Pulso Eleitoral 2026{% endblock %}</title>
  ...
  {% block head %}{% endblock %}
</head>
```

- `templates/metodologia.html:1-60` — the closest existing exemplar of a
  standalone, styled, non-dashboard page (not part of the big SPA-like
  `dashboard.html`) — use this file's structure/conventions (scoped
  `<style>` block in `{% block head %}`, CSS custom properties from
  `static/css/tokens.css` like `var(--pe-navy)`, `var(--pe-surface)`) as
  the pattern for the new detail page's visual design. Do not attempt to
  match `dashboard.html`'s complexity (charts, JS data loading) — a poll
  detail page is server-rendered, static content, closer in spirit to
  `metodologia.html`.

- No `robots.txt` or `sitemap.xml` exists anywhere in this repo today
  (confirmed via `find . -iname "robots.txt" -o -iname "sitemap*.xml"`,
  scoped outside `.claude/worktrees`). Building a sitemap is a larger,
  site-wide concern **out of scope** for this plan (see Scope) — "SEO:
  indexable" for this plan means simply *not* adding a `noindex` meta tag
  and using real, accurate `<title>`/`<meta name="description">` content,
  not building crawl infrastructure.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Tests | `python -m pytest -q` | all pass |
| Manual check | `python app.py`, visit `/pesquisa/<id>` in a browser | renders styled page with real data |
| OG tag check | `curl -s http://127.0.0.1:<port>/pesquisa/<id> \| grep -i "og:"` | shows populated `og:title`/`og:description` |

## Scope

**In scope**:
- `db/pesquisas.py` — new function `get_pesquisa_por_id(pesquisa_id)`.
- `database.py` — re-export `get_pesquisa_por_id` from the façade (follow
  the existing pattern at `database.py`'s `from db.pesquisas import (...)`
  block — add the name to that import list).
- `app.py` — new route `GET /pesquisa/<int:pesquisa_id>`; add its endpoint
  name to `require_login`'s `allowed_endpoints` whitelist (this route must
  be public — a permalink that requires login does not serve the
  journalist use case `PRODUCT.md` describes; this is a deliberate,
  intentional addition, not a bug — see `app.py`'s existing
  `allowed_endpoints` list for the pattern, e.g. `'metodologia'` is already
  public the same way if present, otherwise match how `api_rejeicao` etc.
  are listed).
- `templates/pesquisa_detalhe.html` — new, real, styled template (not the
  spike's throwaway `pesquisa_detalhe_spike.html`, which does not exist on
  `main` — you are writing this fresh).
- `tests/test_dashboard.py` (or a new `tests/test_pesquisa_detalhe.py` if
  you prefer a dedicated file — match whichever existing convention feels
  more consistent after looking at how `tests/test_dashboard.py` is
  organized) — tests for the new route and query function.

**Out of scope — do not build these as part of this plan**:
- **Option B** (permalink por candidato, `/comparativo/<candidato>`) — the
  spike's recommendation explicitly sequences this as a separate follow-up
  plan after Option A ships. Do not fold it into this plan.
- **`robots.txt`/`sitemap.xml` generation** — "indexable" for this plan
  means not blocking crawlers on this one page; a real sitemap is a
  site-wide concern spanning every route, not scoped to one permalink.
- **Per-poll chart image generation for `og:image`** — no chart-image
  rendering pipeline exists in this codebase (charts are all client-side
  Chart.js, rendered in-browser, not server-side images). Use a static,
  site-wide fallback image for `og:image` (see Step 4) rather than building
  new server-side image generation — that's a materially larger feature.
- **Modifying any existing route, query function, or template** — this
  plan is purely additive.
- **A slug-based URL scheme** — already decided against (see "Product
  decisions already made").

## Git workflow

- Branch: `advisor/040-permalink-pesquisa-build-completo`
- Commit message style: `feat(dashboard): permalink de produção por pesquisa (/pesquisa/<id>)`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Write `get_pesquisa_por_id` in `db/pesquisas.py`

Add a new function returning a poll's full detail — institute, all
methodology fields (`data_pesquisa`, `data_publicacao`, `margem_erro`,
`tamanho_amostra`, `contratante`, `registro_tse`, `fonte_url`), and its
full list of `intencoes` (candidate, party, percentual, tipo), ordered by
`percentual DESC`. Return `None` if the id doesn't exist. Follow
`get_comparativo_candidato`'s style exactly (parameterized SQL, `get_db()`
context manager, plain dict/list return — no ORM).

**Verify**: `grep -n "def get_pesquisa_por_id" db/pesquisas.py` → 1 match. `python -c "import ast; ast.parse(open('db/pesquisas.py').read())"` → no output.

### Step 2: Re-export from the façade

Add `get_pesquisa_por_id` to `database.py`'s existing
`from db.pesquisas import (...)` block (the multi-line import already
listing `get_comparativo_candidato`, `get_pesquisas_mais_recentes`, etc.).

**Verify**: `python -c "import os; os.environ['TESTING']='True'; import database; assert hasattr(database, 'get_pesquisa_por_id')"` → no output (no `AssertionError`).

### Step 3: Add the route in `app.py`

Add `GET /pesquisa/<int:pesquisa_id>`, calling `get_pesquisa_por_id`, returning
a 404 with a simple message if `None`, otherwise rendering the new
template. Add the route's endpoint name (the function name, e.g.
`pesquisa_detalhe`) to `require_login`'s `allowed_endpoints` list so the
route is public — read `app.py`'s `require_login` function first to see the
exact current list and match its style (one string per line or however the
list is currently formatted).

**Verify**: `grep -n "def pesquisa_detalhe\|'pesquisa_detalhe'" app.py` → both the route function and its whitelist entry appear.

### Step 4: Build the real template with Open Graph tags

Create `templates/pesquisa_detalhe.html`, extending `base.html`, following
`metodologia.html`'s structural pattern (scoped `<style>` in `{% block
head %}`, design tokens from `tokens.css`). Content requirements, all
driven by `PRODUCT.md`'s design principles:

- **Design Principle 1** (um cargo por vez): show the poll's `cargo`
  clearly labeled (Presidente vs. Governador RJ), no ambiguity.
- **Design Principle 2** (metodologia sempre visível): show instituto,
  `data_pesquisa`, `data_publicacao`, `margem_erro`, `tamanho_amostra`,
  `registro_tse`, and `fonte_url` as a visible link — not hidden behind a
  tooltip or a separate page.
- **Design Principle 4** (cor por identidade): each candidate row's
  accent/indicator color comes from `get_cores_candidatos()[nome_canonico]`
  — pass this mapping into the template context from the route, matching
  how other charts in this codebase resolve candidate color (do not
  hardcode colors or derive them from row position).
- Show each candidate's `tipo` (estimulada/espontânea) next to their
  percentual, per Design Principle 2 above and the `intencoes.tipo` field.

In `{% block head_meta %}` (see `base.html`'s exact block name from Current
state), add:

```html
<meta property="og:title" content="{{ pesquisa.instituto }} — {{ pesquisa.cargo|title }} ({{ pesquisa.data_pesquisa }})">
<meta property="og:description" content="Pesquisa eleitoral {{ pesquisa.instituto }}, {{ pesquisa.data_pesquisa }}. Ver intenções de voto completas no Pulso Eleitoral.">
<meta property="og:image" content="{{ url_for('static', filename='<escolha um asset existente em static/ apropriado como fallback>', _external=True) }}">
<meta property="og:type" content="article">
```

For `og:image`, inspect `static/` for an existing site-wide image/logo
asset suitable as a fallback (check `static/` subdirectories with
`ls static/` or equivalent) — use whatever the site already has for social
previews elsewhere, if one exists; if none exists anywhere in the repo,
STOP and report rather than inventing a new image asset (image creation is
outside a code-executor's scope).

Do **not** add a `<meta name="robots" content="noindex">` tag — the absence
of a noindex tag is what "indexable" means for this plan (see Scope — no
sitemap/robots.txt infrastructure is being built).

**Verify**: `python app.py`, `curl -s http://127.0.0.1:<port>/pesquisa/<id-real> | grep -c "og:"` → 4 (title, description, image, type).

### Step 5: Manual browser verification

Start the app locally, visit `/pesquisa/<id>` for a real seeded poll and
confirm: page renders with the site's visual design (not raw HTML like the
spike), all methodology fields visible, candidate rows colored by identity,
`tipo` shown per candidate, `/pesquisa/999999` (nonexistent) returns a
clean 404. Use the `webapp-testing` skill if available for this
verification; otherwise use `curl`/manual browser check.

**Verify**: manual confirmation of all points above.

### Step 6: Tests

Write tests covering: `get_pesquisa_por_id` returns correct data for a
seeded poll id and `None` for a nonexistent id; the route returns 200 with
expected content for a real id and 404 for a nonexistent one; the OG meta
tags are present in the response body. Model the Flask test-client pattern
after existing tests in `tests/test_dashboard.py` (e.g. any test using the
`client` fixture).

**Verify**: `python -m pytest -q -k pesquisa_detalhe` → all new tests pass. Then `python -m pytest -q` → all pass, baseline + new tests.

## Test plan

- New tests (exact count and location left to your judgment per Step 6,
  but must cover): `get_pesquisa_por_id` happy path + not-found path; route
  200 + 404; OG tags present.
- Structural pattern: existing Flask `client` fixture tests in
  `tests/test_dashboard.py`.
- Verification: `python -m pytest -q` → all pass, baseline + new tests, exit 0.

## Done criteria

Machine-checkable + manual. ALL must hold:

- [ ] `get_pesquisa_por_id` exists in `db/pesquisas.py`, re-exported from `database.py`
- [ ] `GET /pesquisa/<id>` route exists in `app.py`, publicly accessible (in `allowed_endpoints`)
- [ ] `templates/pesquisa_detalhe.html` exists, extends `base.html`, uses design tokens (not inline/raw HTML like the spike)
- [ ] Candidate rows use `get_cores_candidatos()` for color, not hardcoded/positional color
- [ ] `tipo` (estimulada/espontânea) shown per candidate
- [ ] `registro_tse`, `fonte_url`, `data_publicacao`, `margem_erro`, `tamanho_amostra` all visible on the page
- [ ] OG meta tags (`og:title`, `og:description`, `og:image`, `og:type`) present in `head_meta` block
- [ ] No `noindex` meta tag added
- [ ] `python -m pytest -q` exits 0, includes new tests for the route and query function
- [ ] No files outside the Scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- No existing site-wide image asset suitable for `og:image` fallback exists in `static/` — report this rather than generating/inventing an image.
- `require_login`'s `allowed_endpoints` list or its surrounding function has structurally changed since this plan was written in a way that makes adding the new endpoint ambiguous — report what you found.
- `metodologia.html`'s structure has changed enough that it's no longer a good pattern to follow — pick a different existing standalone page as the exemplar and note the substitution, don't guess at conventions from scratch.
- Any step requires modifying an existing route, query function, or template not listed in Scope.

## Maintenance notes

- **Option B is the natural next plan** once this ships — permalink by
  candidate, reusing `get_comparativo_candidato` (already exists, zero new
  query needed per the spike's analysis). Write it as its own plan when
  ready; don't retrofit it into this one.
- If a real per-poll chart-image pipeline is ever built (server-side render
  of the candidate bars for `og:image`), this template's `og:image` tag is
  the place to swap the static fallback for a dynamic one.
- If a sitemap/robots.txt is ever built site-wide, this route's inclusion
  in it should be automatic (no `noindex`), but building that
  infrastructure is unrelated future work, not blocked by this plan.
