# Plan 003: Endurecer a rota `/admin/apply-db` (auth fail-closed + validação do DB)

> **Executor instructions**: Siga o plano passo a passo. Rode cada verificação antes
> de avançar. Se algo nas "STOP conditions" ocorrer, pare e reporte. Ao terminar,
> atualize a linha de status em `plans/README.md`.
>
> **Drift check (rode primeiro)**:
> `git diff --stat 2b49ba3..HEAD -- app.py scripts/sync_db.py`
> Se `app.py` mudou desde `2b49ba3`, confirme que o trecho de "Current state" ainda
> bate antes de editar.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (mexe em auth de uma rota usada pelo `sync_db.py`; um erro pode
  quebrar o sync de banco para produção — testar com cuidado)
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `2b49ba3`, 2026-06-26

## Why this matters

`/admin/apply-db` substitui **o banco de produção inteiro** (`shutil.move` sobre
`/data/pulso.db`). Hoje ela tem três falhas que se somam:

1. **Bypass de auth quando `ADMIN_PASS` não está setada.** `os.getenv('ADMIN_PASS')`
   retorna `None`; se o atacante omitir o header, `request.headers.get(...)` também é
   `None`, e `None != None` é `False` → a checagem **não** retorna 401, passa direto.
   A rota está em `allowed_endpoints` (`app.py:98`) e **não** tem `@login_required`,
   então o header é a única proteção.
2. **Comparação não-constante** (`!=`) — vaza timing do segredo; e o segredo trafega
   em header simples (pode parar em logs de proxy).
3. **Validação inexistente do arquivo.** Só confere prefixo/sufixo do nome. Um `.db`
   corrompido derruba o app; e `pulso_upload_/../../x.db` passa no check (path
   traversal na origem do move).

Resultado desejado: a rota **falha fechada** (sem `ADMIN_PASS` configurada, recusa
tudo), compara em tempo constante, valida que o arquivo é um SQLite íntegro com as
tabelas esperadas antes de promover, e rejeita nomes com separadores de caminho.

**Restrição crítica**: `scripts/sync_db.py:75-80` chama esta rota de forma headless
com o header `X-Admin-Pass` (sem sessão). **NÃO** troque o mecanismo por
`@login_required` — isso quebraria o sync. Mantenha a auth por header, só endureça.

## Current state

`app.py:717-731` (rota integral hoje):
```python
@app.route('/admin/apply-db', methods=['POST'])
def apply_db():
    if request.headers.get('X-Admin-Pass') != os.getenv('ADMIN_PASS'):
        return jsonify({'error': 'unauthorized'}), 401
    import shutil
    body = request.get_json(silent=True) or {}
    filename = body.get('filename', '')
    if not (filename.startswith('pulso_upload_') and filename.endswith('.db')):
        return jsonify({'error': 'filename inválido'}), 400
    new_db = f'/data/{filename}'
    current_db = '/data/pulso.db'
    if not os.path.exists(new_db):
        return jsonify({'error': f'{filename} não encontrado'}), 404
    shutil.move(new_db, current_db)
    return jsonify({'ok': True, 'msg': 'banco aplicado'})
```

Chamador legítimo — `scripts/sync_db.py:74-80`:
```python
resp = requests.post(
    url_apply,
    headers={'X-Admin-Pass': admin_pass, 'Content-Type': 'application/json'},
    json={'filename': filename},
    timeout=15
)
```
O `filename` gerado é `f"pulso_upload_{timestamp}.db"` (`sync_db.py:62`) — sempre um
basename simples, sem separadores. A correção não pode quebrar esse formato.

Convenções: o arquivo já usa `os` e `os.getenv` no topo (`app.py:1`); `import json`
no topo. `hmac` e `sqlite3` ainda **não** estão importados em `app.py` — adicione os
imports no topo do arquivo, junto dos demais (`import os`, `import datetime`, etc. em
`app.py:1-11`), seguindo o estilo de imports no topo do módulo.

## Commands you will need

| Propósito | Comando | Esperado |
|-----------|---------|----------|
| Testes | `python -m pytest -q` | `0 failed` |
| Só os novos testes | `python -m pytest tests/test_apply_db.py -q` | passam |
| Sanidade de import | `python -c "import app"` | exit 0 |

## Scope

**In scope**:
- `app.py` (a função `apply_db` e os imports no topo)
- `tests/test_apply_db.py` (criar)

**Out of scope** (NÃO toque):
- `scripts/sync_db.py` — o chamador deve continuar funcionando sem mudanças; valide
  isso, não o altere.
- `app.py:98` (`allowed_endpoints`) — manter `apply_db` lá é intencional (a rota é
  headless). A segurança vem da checagem de header endurecida, não do middleware.
- Qualquer outra rota.

## Git workflow

- Branch: `advisor/003-secure-apply-db`
- Commit único; mensagem ex.: `fix(security): apply-db fail-closed + valida SQLite + path safe`.
- Sem push/PR salvo pedido do operador.

## Steps

### Step 1: Adicionar imports `hmac` e `sqlite3` no topo de `app.py`
Junto ao bloco de imports (`app.py:1-11`), acrescente:
```python
import hmac
import sqlite3
```

**Verify**: `python -c "import app"` → exit 0.

### Step 2: Reescrever `apply_db` com auth fail-closed, compare constante e validação
Substitua a função inteira (`app.py:717-731`) por:
```python
@app.route('/admin/apply-db', methods=['POST'])
def apply_db():
    import shutil

    # 1. Auth fail-closed: sem ADMIN_PASS configurada, recusa tudo.
    expected = os.getenv('ADMIN_PASS')
    provided = request.headers.get('X-Admin-Pass')
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        return jsonify({'error': 'unauthorized'}), 401

    # 2. Validação do nome: basename simples, sem separadores de caminho.
    body = request.get_json(silent=True) or {}
    filename = body.get('filename', '')
    if (os.path.basename(filename) != filename
            or not filename.startswith('pulso_upload_')
            or not filename.endswith('.db')):
        return jsonify({'error': 'filename inválido'}), 400

    new_db = f'/data/{filename}'
    current_db = '/data/pulso.db'
    if not os.path.exists(new_db):
        return jsonify({'error': f'{filename} não encontrado'}), 404

    # 3. Validação de integridade: precisa ser um SQLite válido com a tabela 'pesquisas'.
    try:
        conn = sqlite3.connect(new_db)
        try:
            ok = conn.execute("PRAGMA integrity_check").fetchone()
            has_tabela = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='pesquisas'"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        ok, has_tabela = None, None
    if not ok or ok[0] != 'ok' or not has_tabela:
        return jsonify({'error': 'arquivo não é um banco SQLite válido do Pulso'}), 422

    shutil.move(new_db, current_db)
    return jsonify({'ok': True, 'msg': 'banco aplicado'})
```

Notas:
- `os.path.basename(filename) != filename` rejeita qualquer `/` ou `\` (mata o path
  traversal) mantendo `pulso_upload_<timestamp>.db` válido.
- `hmac.compare_digest` exige duas strings não-vazias; por isso o guard `not provided`.
- A checagem de integridade abre o `.db` candidato e exige `integrity_check == ok` e a
  presença da tabela `pesquisas` (núcleo do schema do Pulso) antes de promover.

**Verify**: `python -c "import app"` → exit 0.

### Step 3: Criar testes para a rota endurecida
Crie `tests/test_apply_db.py` seguindo o padrão estrutural de
`tests/test_database.py` (mesmo cabeçalho `os.environ['TESTING']='True'`, fixture
`client` com `flask_app.test_client()`). Cubra:
1. **Sem `ADMIN_PASS` no ambiente + sem header** → 401 (regressão do bypass
   `None==None`). Use `monkeypatch.delenv('ADMIN_PASS', raising=False)`.
2. **`ADMIN_PASS` setada + header errado** → 401.
3. **Header correto + filename com `..` ou `/`** (ex.: `pulso_upload_/../x.db`) → 400.
4. **Header correto + filename válido + arquivo inexistente** → 404.
5. (Opcional, se viável criar um arquivo em `/data` no ambiente de teste) header
   correto + um `.db` inválido (arquivo de texto) → 422.

Use `monkeypatch.setenv('ADMIN_PASS', 'senha-de-teste')` e o header
`{'X-Admin-Pass': 'senha-de-teste'}` nos casos autenticados. **Não** coloque
segredos reais; use um valor de teste fixo.

> Nota sobre caminhos: a rota usa caminhos absolutos `/data/...` (ambiente Fly). No
> ambiente de teste local (Windows), os casos 1–4 não dependem de `/data` existir
> (param antes do move). O caso 5 pode ser pulado se `/data` não for gravável —
> documente o skip com `pytest.mark.skipif`.

**Verify**: `python -m pytest tests/test_apply_db.py -q` → todos passam.

### Step 4: Garantir que a suíte inteira segue verde
**Verify**: `python -m pytest -q` → `0 failed`.

## Test plan

- Arquivo novo `tests/test_apply_db.py` com os 4–5 casos acima; o caso #1 é a
  regressão direta do bug de bypass.
- Padrão estrutural: `tests/test_database.py` (fixture `client`, asserts em
  `response.status_code` / `response.json`).
- Verificação: `python -m pytest tests/test_apply_db.py -q` → todos passam.

## Done criteria

ALL devem valer:

- [ ] `apply_db` recusa (401) quando `ADMIN_PASS` está ausente do ambiente, mesmo sem
      header (regressão coberta por teste).
- [ ] A comparação de segredo usa `hmac.compare_digest`.
- [ ] Filenames com separador de caminho retornam 400 (coberto por teste).
- [ ] Arquivo é validado com `PRAGMA integrity_check` + presença de `pesquisas` antes
      do `shutil.move`.
- [ ] `python -m pytest -q` sai com código 0; `tests/test_apply_db.py` existe e passa.
- [ ] `scripts/sync_db.py` NÃO foi modificado (`git status`).
- [ ] Linha de status do Plano 003 atualizada em `plans/README.md`.

## STOP conditions

Pare e reporte se:
- O trecho atual de `apply_db` divergir do "Current state".
- A validação de integridade exigir abrir o banco de uma forma que conflite com o
  fluxo do `sync_db.py` (ex.: arquivo ainda em upload) — reporte para decidir.
- Algum teste existente quebrar por causa desta mudança (não deveria; a rota é
  isolada).

## Maintenance notes

- Se o schema do Pulso mudar a tabela núcleo, ajuste a checagem `name='pesquisas'`.
- O segredo continua sendo um header estático compartilhado. Uma evolução futura
  (fora deste plano) seria assinatura HMAC do payload com timestamp, ou mover o swap
  para um comando `flyctl ssh` em vez de uma rota HTTP pública. Registrar como backlog.
- O revisor deve confirmar: (1) o caminho do `sync_db.py` (header + `filename`
  basename) continua aceito; (2) nenhuma resposta vaza o valor de `ADMIN_PASS`.
- Garanta que `ADMIN_PASS` está configurada como secret no Fly
  (`flyctl secrets list`) — com a auth fail-closed, esquecê-la passa a derrubar o
  sync (falha segura e visível), em vez de abrir a rota.
