# Plan 025: Política mínima de senha ao criar usuário admin

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat f53d533..HEAD -- app.py database.py templates/admin_usuarios.html`
> If any of these changed since this plan was written, compare the
> "Current state" excerpts below against the live code before proceeding;
> on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `f53d533`, 2026-07-16

## Why this matters

`admin_criar_usuario()` only checks that `username`/`password` are
non-empty strings — a 1-character password is accepted and hashed with
bcrypt just like a strong one. Combined with the rate limiting added in
plan 020 (5 attempts/min on `/login`), a weak password is still the
easiest way to defeat that defense: a trivial password makes brute force
fast even at a throttled rate. This is a small, additive validation change.

## Current state

- `app.py:380-400` — `admin_criar_usuario()`, the only validation gate:

```python
@app.route('/admin/usuarios/criar', methods=['POST'])
@login_required
def admin_criar_usuario():
    """Cria um novo usuário."""
    username = request.form.get('username')
    password = request.form.get('password')
    nome = request.form.get('nome')

    from flask import flash
    if not username or not password:
        flash("Usuário e senha são obrigatórios.", "danger")
        return redirect(url_for('admin_usuarios'))

    from database import criar_usuario
    sucesso = criar_usuario(username, password, nome)
    if sucesso:
        flash("Usuário criado com sucesso!", "success")
    else:
        flash("Nome de usuário já existe.", "danger")

    return redirect(url_for('admin_usuarios'))
```

- `database.py:1836` — `criar_usuario(username, password, nome=None)`: does
  `bcrypt.hashpw` on whatever string arrives, no length/strength check of
  its own (read the function body before editing to confirm this is still
  the case).

- `templates/admin_usuarios.html` — the create-user form has `required` on
  the password `<input>` but no `minlength` attribute (client-side hint
  only; this plan's real gate is server-side, since client-side validation
  is trivially bypassed).

- This route is only reachable by an already-authenticated admin
  (`@login_required`) — the threat here is a weak password being *created*
  (by mistake or under duress), not an unauthenticated attacker calling
  this route directly.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|----------------------|
| Run tests | `TESTING=True python -m pytest -q` | all pass, exit 0 |

## Scope

**In scope**:
- `app.py` — `admin_criar_usuario()` (add the length check before calling
  `criar_usuario`)
- `templates/admin_usuarios.html` — add `minlength="8"` to the password
  `<input>` as a client-side hint (does not replace the server check)
- `tests/` — a test confirming a short password is rejected with a flash
  message and the user is NOT created

**Out of scope**:
- Password complexity rules beyond length (no character-class
  requirements) — length is the single highest-leverage, lowest-friction
  check; don't over-engineer this into a full password-policy framework.
- Changing `bcrypt` cost factor or any other part of the hashing mechanism.
- Retroactively validating/forcing a reset of existing admin passwords
  already in the database — this plan only gates new user creation.

## Git workflow

- Branch: `advisor/025-politica-senha-admin`
- Commit message style: conventional commits in Portuguese, e.g.
  `fix(seguranca): exige senha com pelo menos 8 caracteres ao criar usuário`
- Do NOT push or open a PR unless explicitly instructed.

## Steps

### Step 1: Add the server-side length check

In `app.py`'s `admin_criar_usuario()`, add a length check right after the
existing empty-check, before calling `criar_usuario`:

```python
    from flask import flash
    if not username or not password:
        flash("Usuário e senha são obrigatórios.", "danger")
        return redirect(url_for('admin_usuarios'))

    if len(password) < 8:
        flash("A senha deve ter pelo menos 8 caracteres.", "danger")
        return redirect(url_for('admin_usuarios'))

    from database import criar_usuario
```

**Verify**: `TESTING=True python -c "
import app
c = app.app.test_client()
with c.session_transaction() as sess:
    sess['logged_in'] = True
r = c.post('/admin/usuarios/criar', data={'username': 'novo', 'password': '123', 'nome': 'Teste'})
print(r.status_code)
"` → 302 (redirect back to admin_usuarios; the actual rejection is verified via the flash message / DB state in Step 2's test, not the status code alone, since the redirect happens either way).

### Step 2: Add the client-side hint

In `templates/admin_usuarios.html`, find the password `<input>` in the
create-user form and add `minlength="8"` alongside the existing `required`
attribute — purely a UX nicety (browser-native validation feedback before
submit), not a security control.

**Verify**: `grep -n 'minlength="8"' templates/admin_usuarios.html` shows
the attribute present.

### Step 3: Add the regression test

Add a test that logs in (or simulates a logged-in session, matching
whatever pattern existing admin-route tests use — check
`tests/test_usuarios.py` for the established session-mocking convention in
this repo), POSTs to `/admin/usuarios/criar` with a short password, and
asserts the user was NOT created (query `listar_usuarios()` or the DB
directly) — plus one case confirming an 8+ character password still
succeeds (regression guard against the check being too strict).

**Verify**: `TESTING=True python -m pytest -q -k politica_senha` → passes
(adjust the `-k` filter to match whatever you name the test).

## Test plan

- New test: password shorter than 8 chars → user not created, flash
  message shown (redirect status is 302 either way, so assert on DB state,
  not status code).
- New test (regression guard): password of exactly 8 chars → user IS
  created successfully.
- Pattern to follow: `tests/test_usuarios.py` for how this repo
  authenticates a test client against `@login_required` routes.
- Verification: `TESTING=True python -m pytest -q` → all pass, including
  both new tests.

## Done criteria

- [ ] `TESTING=True python -m pytest -q` exits 0
- [ ] `grep -n "len(password) < 8" app.py` shows the new check inside
      `admin_criar_usuario`
- [ ] New tests exist and pass, covering both the rejection and the
      boundary-acceptance case
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row for 025 updated

## STOP conditions

- `app.py:380-400` doesn't match the excerpt above (route restructured) —
  re-read before editing.
- `tests/test_usuarios.py` uses a session-mocking pattern significantly
  different from a simple `session_transaction()` — follow whatever that
  file actually does rather than the sketch in Step 1's verify command.

## Maintenance notes

- If a self-service "change my own password" flow is ever added, apply the
  same 8-character minimum there too — this plan only covers admin-created
  accounts via `/admin/usuarios/criar`.
