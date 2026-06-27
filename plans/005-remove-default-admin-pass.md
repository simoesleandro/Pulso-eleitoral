# Plan 005: Remover a senha admin default `pulso2026` (sem credencial conhecida)

> **Executor instructions**: Siga o plano passo a passo. Rode cada verificação antes
> de avançar. Se algo nas "STOP conditions" ocorrer, pare e reporte. Ao terminar,
> atualize a linha de status em `plans/README.md`.
>
> **Drift check (rode primeiro)**:
> `git diff --stat 2b49ba3..HEAD -- database.py README.md .env.example tests/test_database.py`
> Se algum desses mudou desde `2b49ba3`, confirme os trechos de "Current state".

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: MED (mexe no seed do usuário admin; uma falha pode trancar o login.
  Há acoplamento com testes de auth e com o CI — ler "Current state" inteiro)
- **Depends on**: none (mas veja a nota de overlap com Plano 001)
- **Category**: security
- **Planned at**: commit `2b49ba3`, 2026-06-26

## Why this matters

`database.py:70` semeia o usuário admin com a senha default **`pulso2026`** quando
`ADMIN_PASS` não está setada — e essa senha está **documentada publicamente** no
`README.md:206`. Qualquer deploy que esqueça de configurar `ADMIN_PASS` aceita
`admin / pulso2026`, ou seja, login admin trivial para qualquer leitor do repo. O
fix: nunca semear uma senha conhecida. Se `ADMIN_PASS` não estiver definida, gerar
uma senha aleatória, avisar nos logs e remover a credencial documentada.

## Current state

`database.py:64-77`:
```python
    # 3. Inicializa o usuário admin padrão se não houver usuários cadastrados
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    count_usuarios = cursor.fetchone()[0]
    if count_usuarios == 0:
        from dotenv import load_dotenv
        load_dotenv()
        admin_pass = os.getenv('ADMIN_PASS', 'pulso2026')
        admin_user = 'admin'
        password_hash = bcrypt.hashpw(admin_pass.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute(
            "INSERT INTO usuarios (username, password_hash, nome, ativo) VALUES (?, ?, ?, 1)",
            (admin_user, password_hash, 'Administrador')
        )
        conn.commit()
```

`README.md:206` (tabela de variáveis de ambiente) documenta o default:
```
| `ADMIN_PASS` | Senha do usuário admin | `pulso2026` |
```

`.env.example` (hoje) **não** lista `ADMIN_PASS` e tem um BOM UTF-8 na 1ª linha:
```
GEMINI_API_KEY=sua_chave_aqui
TELEGRAM_BOT_TOKEN=seu_token_aqui
TELEGRAM_CHAT_ID=seu_chat_id_aqui
SECRET_KEY=troque_por_string_aleatoria
```

**Acoplamento com testes (importante):**
- `tests/test_database.py:156` faz login com `password='admin123'` e espera 302
  (sucesso). Isso só passa hoje porque o `.env` local define `ADMIN_PASS=admin123` e
  `load_dotenv()` o carrega. **NÃO** confie nesse comportamento implícito.
- `tests/test_usuarios.py:153,166` lê `os.getenv('ADMIN_PASS', 'pulso2026')`.
- `import os` e `import bcrypt` já estão no topo de `database.py`.

**Overlap com Plano 001**: ambos editam `tests/test_database.py`, mas em regiões
diferentes (Plano 001 nas linhas ~76-80 de institutos; este nas ~134-163 de auth).
Se executar os dois em branches separados, faça rebase para evitar conflito.

## Commands you will need

| Propósito | Comando | Esperado |
|-----------|---------|----------|
| Testes | `python -m pytest -q` | `0 failed` |
| Auth test | `python -m pytest tests/test_database.py::test_auth_blocks_routes_without_login -q` | passa |
| Grep do default | `grep -rn "pulso2026" database.py README.md` | sem resultado ao fim |

## Scope

**In scope**:
- `database.py` (o bloco de seed do admin, `:67-77`)
- `tests/test_database.py` (tornar o teste de auth determinístico)
- `README.md` (remover o default documentado)
- `.env.example` (adicionar `ADMIN_PASS`, corrigir BOM)

**Out of scope**:
- `tests/test_usuarios.py` — deixe como está (passa hoje; o default `'pulso2026'` ali
  é só o fallback de leitura no teste, não cria vulnerabilidade de produção). NÃO
  edite sem necessidade.
- Qualquer rota/lógica de login.

## Git workflow

- Branch: `advisor/005-remove-default-admin-pass`
- Commit único; ex.: `fix(security): remove senha admin default pulso2026`.
- Sem push/PR salvo pedido do operador.

## Steps

### Step 1: Gerar senha aleatória quando `ADMIN_PASS` não estiver definida
Em `database.py`, substitua a linha 70:
```python
        admin_pass = os.getenv('ADMIN_PASS', 'pulso2026')
```
por:
```python
        admin_pass = os.getenv('ADMIN_PASS')
        if not admin_pass:
            import secrets
            admin_pass = secrets.token_urlsafe(16)
            logger.warning(
                "ADMIN_PASS não configurada — senha admin aleatória gerada e "
                "descartada. Defina ADMIN_PASS e recrie o usuário admin para ter "
                "uma senha conhecida."
            )
```
> Verifique se há um `logger` no módulo. Se `database.py` não tiver um logger no
> escopo, use `print(...)` para o aviso, OU adicione no topo
> `import logging; logger = logging.getLogger(__name__)`. NÃO logue o valor de
> `admin_pass`.

**Verify**: `python -c "import database"` → exit 0;
`grep -n "pulso2026" database.py` → sem resultado.

### Step 2: Tornar o teste de auth determinístico (não depender do `.env`)
Em `tests/test_database.py::test_auth_blocks_routes_without_login`, defina
`ADMIN_PASS` explicitamente **antes** de `init_db(force_seed=True)` e use o mesmo
valor no login. Adicione o parâmetro `monkeypatch` à assinatura do teste (`:134`) e,
logo no início do corpo (antes de `init_db` em `:137`):
```python
    monkeypatch.setenv('ADMIN_PASS', 'senha-de-teste-005')
```
Depois troque o login de sucesso (`:156`) para usar essa senha:
```python
    response_login_success = client.post('/login', data={'username': 'admin', 'password': 'senha-de-teste-005'})
```
Isso remove a dependência do `.env` e mantém o teste verde no CI (que não tem `.env`).

> Se o `init_db` já tiver rodado/cacheado antes do `setenv`, garanta que a fixture
> `setup_and_teardown` (`:10-27`) apaga o DB antes do teste (ela apaga) — o seed roda
> de novo com a env já setada.

**Verify**: `python -m pytest tests/test_database.py::test_auth_blocks_routes_without_login -q` → passa.

### Step 3: Remover o default documentado no README
Em `README.md:206`, troque a célula de default de `` `pulso2026` `` por algo como
`— (obrigatória)` e, se quiser, acrescente uma frase: "Se não definida, uma senha
aleatória é gerada e descartada — configure `ADMIN_PASS` para ter login admin."

**Verify**: `grep -n "pulso2026" README.md` → sem resultado.

### Step 4: Completar o `.env.example`
Acrescente ao `.env.example` a variável faltante (e remova o BOM da 1ª linha, se o
editor permitir salvar em UTF-8 sem BOM):
```
ADMIN_PASS=defina_uma_senha_forte
```

**Verify**: `grep -n "ADMIN_PASS" .env.example` → retorna a linha.

### Step 5: Suíte inteira verde
**Verify**: `python -m pytest -q` → `0 failed`.

## Test plan

- Ajuste em `tests/test_database.py::test_auth_blocks_routes_without_login`: passa a
  setar `ADMIN_PASS` via `monkeypatch` (determinístico, independe de `.env`/CI).
- Padrão: o próprio teste já usa o fixture `client`; só adicionamos `monkeypatch`.
- Verificação: `python -m pytest -q` → `0 failed`.

## Done criteria

ALL devem valer:

- [ ] `grep -rn "pulso2026" database.py README.md` não retorna nada.
- [ ] Sem `ADMIN_PASS` no ambiente, o seed gera senha aleatória e loga aviso (sem
      imprimir a senha).
- [ ] `tests/test_database.py::test_auth_blocks_routes_without_login` seta `ADMIN_PASS`
      via `monkeypatch` e passa.
- [ ] `.env.example` lista `ADMIN_PASS`.
- [ ] `python -m pytest -q` sai com código 0.
- [ ] Linha de status do Plano 005 atualizada em `plans/README.md`.

## STOP conditions

Pare e reporte se:
- Os trechos de "Current state" divergirem do código vivo.
- Após o Step 1/2, algum outro teste de login/usuário quebrar de forma não óbvia
  (pode haver outra dependência implícita em `.env`).
- O módulo `database.py` não tiver um `logger` nem aceitar `print` sem efeitos
  colaterais em testes.

## Maintenance notes

- **Operação**: como `ADMIN_PASS` agora é efetivamente obrigatória para ter login
  admin conhecido, configure-a como secret no Fly (`flyctl secrets set ADMIN_PASS=...`)
  ANTES do primeiro boot em produção; senão o admin é criado com senha aleatória
  inacessível (precisaria recriar o usuário).
- **CI (Plano 002)**: o gate de testes roda sem `.env`. O teste de auth agora seta a
  própria `ADMIN_PASS` via `monkeypatch`, então não precisa de env no workflow. Se
  outros testes futuros dependerem de `ADMIN_PASS`, exporte-a no job `test`.
- `ADMIN_PASS` é usada em três lugares (`database.py` seed, `app.py:719` apply-db,
  `scripts/sync_db.py`). O Plano 003 endurece o uso em apply-db; mantenha os três
  consistentes.
- O revisor deve confirmar que nenhuma senha (default ou gerada) aparece em logs ou
  respostas.
