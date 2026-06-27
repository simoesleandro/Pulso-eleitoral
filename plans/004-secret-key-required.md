# Plan 004: Exigir `SECRET_KEY` (remover fallback commitado e forjável)

> **Executor instructions**: Siga o plano passo a passo. Rode cada verificação antes
> de avançar. Se algo nas "STOP conditions" ocorrer, pare e reporte. Ao terminar,
> atualize a linha de status em `plans/README.md`.
>
> **Drift check (rode primeiro)**:
> `git diff --stat 2b49ba3..HEAD -- app.py`
> Se `app.py` mudou desde `2b49ba3`, confirme o trecho de "Current state".

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (em dev/test gera chave efêmera; só falha fechado em produção)
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `2b49ba3`, 2026-06-26

## Why this matters

`app.py:19` assina as sessões Flask com um fallback **fixo e commitado**:
```python
app.secret_key = os.getenv('SECRET_KEY', 'default-session-secret-key-9999')
```
Se `SECRET_KEY` não estiver setada em produção, qualquer pessoa que leia o código
(o repo é público) conhece a chave e pode **forjar um cookie de sessão** com
`logged_in=True` → acesso total ao painel admin sem senha. O fix: em produção
(Fly) a ausência de `SECRET_KEY` deve **falhar fechado** (não subir com chave
conhecida); em dev/test, gerar uma chave aleatória efêmera e avisar.

## Current state

`app.py:16-21`:
```python
app = Flask(__name__)

# Configurações do Flask
app.secret_key = os.getenv('SECRET_KEY', 'default-session-secret-key-9999')

cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache', 'CACHE_DEFAULT_TIMEOUT': 300})
```

Fatos:
- Produção é detectada por `os.getenv('FLY_APP_NAME')` — esse padrão já é usado em
  `app.py:75` e `app.py:783`. Reuse-o (consistência).
- Os testes sobrescrevem a chave **após** o import:
  `flask_app.config['SECRET_KEY'] = 'test-secret-key'` (`tests/test_dashboard.py:29`,
  `tests/test_database.py:33`). Logo, gerar uma chave efêmera no import não atrapalha
  os testes — eles definem a sua própria.
- `import os` já está no topo (`app.py:1`).

## Commands you will need

| Propósito | Comando | Esperado |
|-----------|---------|----------|
| Sanidade de import (dev) | `python -c "import app"` | exit 0, sem raise |
| Falha em "produção" sem chave | `FLY_APP_NAME=x python -c "import app"` (bash) | `RuntimeError` |
| Testes | `python -m pytest -q` | `0 failed` |

> No PowerShell do Windows, o teste de produção é:
> `$env:FLY_APP_NAME='x'; python -c "import app"; Remove-Item Env:FLY_APP_NAME`
> (deve levantar `RuntimeError`).

## Scope

**In scope**:
- `app.py` (somente a atribuição de `app.secret_key`, `app.py:19`)

**Out of scope**:
- Qualquer outra config ou rota.
- `.env` / secrets do Fly (configuração de ambiente, não de código) — mas veja
  "Maintenance notes".

## Git workflow

- Branch: `advisor/004-secret-key-required`
- Commit único; ex.: `fix(security): exige SECRET_KEY em produção, efêmera em dev`.
- Sem push/PR salvo pedido do operador.

## Steps

### Step 1: Substituir o fallback fixo por fail-closed em produção
Troque `app.py:19` por:
```python
_secret = os.getenv('SECRET_KEY')
if not _secret:
    if os.getenv('FLY_APP_NAME'):
        raise RuntimeError(
            "SECRET_KEY não configurada em produção. "
            "Defina com: flyctl secrets set SECRET_KEY=<string aleatória>"
        )
    import secrets as _secrets
    _secret = _secrets.token_hex(32)
    app.logger.warning(
        "SECRET_KEY não definida — usando chave efêmera (sessões não persistem "
        "entre reinícios). Defina SECRET_KEY no .env para desenvolvimento estável."
    )
app.secret_key = _secret
```

**Verify**:
- `python -c "import app"` → exit 0 (dev: gera efêmera).
- (bash) `FLY_APP_NAME=x python -c "import app"` → termina com `RuntimeError`
  mencionando `SECRET_KEY`.

### Step 2: Garantir que a suíte segue verde
**Verify**: `python -m pytest -q` → `0 failed`. Os testes definem a própria chave
após o import, então não devem ser afetados.

## Test plan

- Não há arquivo de teste novo obrigatório (o comportamento de produção é um `raise`
  no import, difícil de cobrir sem reimportar o módulo). Opcional: um teste que usa
  `importlib.reload` com `monkeypatch.setenv('FLY_APP_NAME','x')` e
  `monkeypatch.delenv('SECRET_KEY')` e espera `RuntimeError` — só adicione se for
  trivial no ambiente; caso contrário, a verificação manual do Step 1 basta.
- Verificação principal: `python -m pytest -q` continua `0 failed`.

## Done criteria

ALL devem valer:

- [ ] `grep -n "default-session-secret-key" app.py` não retorna nada.
- [ ] Import em modo dev (sem `FLY_APP_NAME`) funciona e gera chave efêmera.
- [ ] Import com `FLY_APP_NAME` setado e sem `SECRET_KEY` levanta `RuntimeError`.
- [ ] `python -m pytest -q` sai com código 0.
- [ ] Nenhum arquivo fora de `app.py` foi modificado.
- [ ] Linha de status do Plano 004 atualizada em `plans/README.md`.

## STOP conditions

Pare e reporte se:
- `app.py:19` divergir do "Current state".
- Algum teste passar a falhar por causa da mudança (investigue se algum teste depende
  do valor literal antigo — não deveria).

## Maintenance notes

- **Ação de operação obrigatória**: garanta que `SECRET_KEY` está nas secrets do Fly
  (`flyctl secrets list`). Com este plano, esquecê-la passa a **impedir o boot** em
  produção (falha visível) em vez de subir com chave forjável. Defina antes de fazer
  deploy: `flyctl secrets set SECRET_KEY=<openssl rand -hex 32>`.
- Para o CI de testes (Plano 002), nada a fazer: o job roda sem `FLY_APP_NAME`, então
  gera chave efêmera e os testes definem a sua própria.
- O revisor deve confirmar que nenhuma resposta/loga expõe o valor da chave.
