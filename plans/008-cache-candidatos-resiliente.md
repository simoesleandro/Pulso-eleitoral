# Plan 008: Cache de candidatos resiliente — sem envenenamento permanente e invalidado no apply-db

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b3b92ef..HEAD -- database.py app.py tests/test_database.py tests/test_apply_db.py`
> Divergência entre os excertos de "Current state" e o código vivo = STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `b3b92ef`, 2026-07-07

## Why this matters

O cache em memória da tabela `candidatos` (normalização de nomes, espectro
político, cores) é carregado uma vez por processo. Se a **primeira** carga
falhar por qualquer erro transitório (banco travado durante escrita
concorrente, troca de volume no meio do `apply-db`), o `except` grava mapas
**vazios** no global e todas as chamadas seguintes os reutilizam para sempre:
a normalização vira no-op, cores/espectro somem, e as simulações de 2º turno
degradam — até reiniciar o processo. Além disso, a rota `/admin/apply-db`
troca o arquivo SQLite inteiro mas só limpa o Flask-Caching, deixando o cache
de candidatos apontando para o roster do banco antigo até o restart.

## Current state

- `database.py` — `_carregar_candidatos_cache()` (linhas ~98–156); global
  `_cache_candidatos` (linha ~77); `_invalidar_cache_candidatos()` existe e é
  chamada no seed do `init_db`.
- `app.py` — rota `apply_db` (função termina ~linha 892); após o
  `shutil.move` chama `cache.clear()` (linha ~888).

Excerto de `database.py:150-156` (hoje — o bug):

```python
    except Exception:
        # DB ainda sem a tabela/dados: devolve mapas vazios (normalização vira no-op).
        _cache_candidatos = {
            "mapa": {}, "espectro": {}, "cores": {},
            "presidenciais": set(), "presidenciais_canonicos": [], "ignorar": [],
        }
    return _cache_candidatos
```

E o guard no topo (linhas 112–114):

```python
    global _cache_candidatos
    if _cache_candidatos is not None:
        return _cache_candidatos
```

Excerto de `app.py:876-890` (hoje — só Flask-Caching é invalidado):

```python
    shutil.move(new_db, current_db)
    ...
    cache.clear()
    from datetime import datetime
    app.logger.info(f"[apply-db] cache invalidado após troca do banco em {datetime.now().isoformat()}")
```

Convenções: testes do apply-db em `tests/test_apply_db.py` (auth por header
`X-Admin-Pass`, monkeypatch de caminhos `/data/...`); testes de banco em
`tests/test_database.py`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Testes  | `python -m pytest tests/test_database.py tests/test_apply_db.py -q` | exit 0 |
| Suíte   | `python -m pytest -q` | exit 0, 0 failed |

## Scope

**In scope**:
- `database.py` (apenas o `except` de `_carregar_candidatos_cache`)
- `app.py` (apenas a rota `apply_db`, adição de 1 chamada)
- `tests/test_database.py`, `tests/test_apply_db.py` (novos testes)

**Out of scope** (NÃO tocar):
- A estratégia de swap do arquivo (`shutil.move`) e as validações de
  integridade do `apply_db` — endurecidas em auditoria anterior.
- `_invalidar_cache_candidatos` em si e os pontos de chamada no seed.

## Git workflow

- Commit em português, ex.: `fix(db): não memoiza falha na carga do cache de candidatos; invalida no apply-db`

## Steps

### Step 1: Falha não memoiza

Em `database.py`, no `except Exception` de `_carregar_candidatos_cache`,
**não** atribuir ao global: construir o dict vazio numa variável local e
retorná-lo, deixando `_cache_candidatos = None` para que a próxima chamada
tente recarregar. Manter o comentário explicando (bootstrap sem tabela ainda
funciona — só deixa de ser permanente).

**Verify**: `python -m pytest tests/test_database.py -q` → exit 0.

### Step 2: apply-db invalida o cache de candidatos

Em `app.py`, na rota `apply_db`, logo após `cache.clear()`, adicionar:

```python
    from database import _invalidar_cache_candidatos
    _invalidar_cache_candidatos()
```

**Verify**: `python -m pytest tests/test_apply_db.py -q` → exit 0.

## Test plan

1. Em `tests/test_database.py`: monkeypatch de `database.get_db` para lançar na
   primeira chamada e funcionar na segunda; chamar
   `database._carregar_candidatos_cache()` duas vezes (resetando
   `database._cache_candidatos = None` antes do teste); assert de que a segunda
   chamada retorna o mapa populado (não o vazio memoizado).
2. Em `tests/test_apply_db.py` (seguir o padrão dos testes existentes do
   arquivo): após um apply-db bem-sucedido, assert de que
   `database._cache_candidatos is None` (foi invalidado).

Verificação: `python -m pytest tests/test_database.py tests/test_apply_db.py -q`
→ todos passam, incluindo os 2 novos.

## Done criteria

- [ ] `python -m pytest -q` exit 0
- [ ] O `except` de `_carregar_candidatos_cache` não atribui a `_cache_candidatos`
- [ ] `apply_db` chama `_invalidar_cache_candidatos()` após `cache.clear()`
- [ ] Nenhum arquivo fora do escopo modificado (`git status`)
- [ ] Linha de status atualizada em `plans/README.md`

## STOP conditions

- Excertos não batem com o código vivo.
- Algum teste existente depende do comportamento de memoizar o vazio (improvável;
  reportar em vez de reescrever o teste).

## Maintenance notes

- Se um dia a carga do cache passar a ser cara (hoje é um SELECT pequeno), o
  retry-a-cada-chamada em cenário de falha persistente vira custo — nesse caso
  adicionar backoff, não voltar a memoizar o vazio.
- Revisor: conferir que nenhum caminho de import circular surge do
  `from database import _invalidar_cache_candidatos` dentro da rota (import
  local, padrão já usado no arquivo).
