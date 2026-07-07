# Plan 006: Tornar falhas de persistência da coleta visíveis e parciais (fim da perda silenciosa de lote)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b3b92ef..HEAD -- collectors/base.py coletar.py notifier.py tests/test_collectors.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `b3b92ef`, 2026-07-07

## Why this matters

Hoje, **qualquer** exceção durante a gravação de um lote de coleta (colisão de
`registro_tse` UNIQUE, violação de NOT NULL, banco travado) faz `save()` dar
rollback de **todas** as pesquisas daquele coletor e engolir o erro. `run()`
então loga "Dados processados e salvos com sucesso", o `coletar.py` marca o
coletor como `status: "ok"`, e o resumo do Telegram reporta sucesso. A perda de
dados é invisível e indistinguível de "não havia pesquisa nova". Com a eleição
em outubro/2026 e o volume de pesquisas crescendo, esse é o defeito de maior
impacto do pipeline. Depois deste plano: cada release é commitado
individualmente (uma falha não derruba as demais) e falhas de persistência
sobem até o resumo da coleta.

## Current state

- `collectors/base.py` — classe `BaseCollector`; `run()` (linhas 51–60) chama
  `fetch()` e `save()`; `save()` (linhas 62–197) grava tudo numa transação única.
- `coletar.py` — script standalone (Task Scheduler); linhas 66–79 montam
  `resultados` com `status: "ok"` sempre que `run()` não lança (e `run()` nunca lança).
- `notifier.py` — `montar_mensagem_coleta(resultados, ...)` monta o resumo do Telegram.

Excerto de `collectors/base.py:51-60` (hoje):

```python
    def run(self):
        """Executa o ciclo completo de coleta: busca, logs e persistência."""
        logger.info("[%s] Iniciando execução do coletor...", self.name)
        try:
            pesquisas = self.fetch()
            logger.info("[%s] Coleta concluída com sucesso. %d registros obtidos.", self.name, len(pesquisas))
            self.save(pesquisas)
            logger.info("[%s] Dados processados e salvos com sucesso.", self.name)
        except Exception as e:
            logger.error("[%s] Erro durante a execução do coletor: %s", self.name, str(e))
```

Excerto de `collectors/base.py:191-197` (fim do `save()`, hoje):

```python
            conn.commit()
            logger.info("[COLLECTOR] Salvo: %d pesquisas, %d intenções, %d rejeições", n_pesquisas, n_intencoes, n_rejeicoes)
        except Exception as e:
            conn.rollback()
            logger.error("[COLLECTOR] Erro ao salvar pesquisas no banco: %s", str(e))
        finally:
            conn.close()
```

Estrutura do `save()`: agrupa os dicts por `(inst_id, cargo, dt_coleta, url)`
em `groups` (linhas 77–92) e itera `for (inst_id, cargo, dt_coleta, url),
group_items in groups.items():` (linha 98). Cada grupo = um release/pesquisa.

Excerto de `coletar.py:66-79` (hoje):

```python
    for c in coletores:
        try:
            c.run()
            resultados.append({
                "coletor": c.__class__.__name__,
                "status": "ok"
            })
        except Exception as e:
            ...
            resultados.append({... "status": "erro", "msg": str(e)})
```

Convenções do repo: logs via `logger` de módulo em português; testes em
`tests/test_collectors.py` usam SQLite real em `DB_PATH` de teste (ver
`tests/conftest.py` e `tests/test_dashboard.py:1-40` como padrão — `TESTING=True`
setado antes dos imports, fixture `cleanup` autouse).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Testes  | `python -m pytest -q` | exit 0, 0 failed |
| Testes do arquivo | `python -m pytest tests/test_collectors.py -q` | exit 0 |

## Scope

**In scope** (únicos arquivos a modificar):
- `collectors/base.py` (métodos `save` e `run`)
- `coletar.py` (interpretação do retorno de `run()`)
- `notifier.py` (apenas se necessário exibir contagem de falhas — mudança mínima)
- `tests/test_collectors.py` (novos testes)

**Out of scope** (NÃO tocar):
- A lógica de dedup por `fonte_url` e o formato do `registro_tse` (decididos por design).
- `app.py` (a rota `/admin/coletar-url` usa `_parse_release` + `save` — ela se
  beneficia automaticamente; não alterar).
- Qualquer mudança de schema.

## Git workflow

- Commits em português no padrão do repo, ex.: `fix(collectors): commit por release no save() e propagação de falhas parciais`
- Não fazer push nem abrir PR sem instrução do operador.

## Steps

### Step 1: Commit por grupo no `save()` e retorno estruturado

Em `collectors/base.py`, alterar `save()` para:

1. Mover o `try/except` para **dentro** do loop de grupos: cada
   `(inst_id, cargo, dt_coleta, url)` tenta gravar e faz `conn.commit()` ao
   final do próprio grupo; em exceção, `conn.rollback()`, loga
   `logger.error("[COLLECTOR] Falha ao salvar release %s: %s", url, e)` e
   acumula `(url, str(e))` numa lista `falhas`.
2. Manter o `finally: conn.close()` externo.
3. `save()` passa a **retornar** um dict:
   `{"pesquisas": n_pesquisas, "intencoes": n_intencoes, "rejeicoes": n_rejeicoes, "falhas": falhas}`
   (retornar esse dict também no caminho `if not pesquisas: return` — com zeros
   e `falhas: []`).

Atenção: `n_rejeicoes` hoje é resetado dentro do loop (linha 180) — ao
refatorar, acumule um total fora do loop para o retorno.

**Verify**: `python -m pytest tests/test_collectors.py -q` → exit 0 (os testes
existentes não inspecionam o retorno de `save()`, devem continuar verdes).

### Step 2: `run()` propaga o resultado

Alterar `run()` para capturar o retorno de `save()` e **retornar** um dict:
`{"status": "ok" | "parcial" | "erro", "salvas": int, "falhas": list}`.
Regras: `"erro"` se `fetch()`/`save()` lançou (manter o `except` atual, mas
retornar o dict em vez de só logar); `"parcial"` se `falhas` não-vazio;
`"ok"` caso contrário. Trocar o log "Dados processados e salvos com sucesso"
por uma mensagem que inclua contagens e nº de falhas.

**Verify**: `python -m pytest -q` → exit 0.

### Step 3: `coletar.py` usa o retorno

Em `coletar.py:66-79`, usar `resultado = c.run()` e montar a entrada de
`resultados` a partir dele: `status` vindo do dict (mantendo o fallback
`"erro"` no `except` externo), incluindo `"falhas": len(resultado["falhas"])`
quando houver. Não mudar a assinatura de `salvar_log_scheduler(resultados)` —
ela persiste JSON arbitrário.

**Verify**: `python -m pytest -q` → exit 0.

### Step 4 (mínimo): resumo do Telegram menciona falhas

Em `notifier.py`, `montar_mensagem_coleta`: se algum resultado tiver
`status == "parcial"` ou `falhas > 0`, acrescentar uma linha tipo
`⚠️ N release(s) falharam ao salvar`. Mudança mínima — não redesenhar a mensagem.

**Verify**: `python -m pytest tests/test_notifier.py -q` → exit 0.

## Test plan

Novos testes em `tests/test_collectors.py` (seguir o padrão dos existentes no
mesmo arquivo — coletor concreto mínimo ou uso direto de `BaseCollector` com DB
de teste):

1. **Falha parcial não derruba o lote**: dois grupos (duas `fonte_url`
   distintas), o segundo com um valor que viola o schema (ex.: `percentual=None`
   → NOT NULL em `intencoes`). Asserts: o primeiro grupo está no banco; retorno
   tem `falhas` com 1 item; `run()`/`save()` não lança.
2. **Sucesso total**: retorno `{"status": "ok"}` e `falhas == []`.
3. **Regressão**: lote vazio retorna dict com zeros (não `None`).

Verificação: `python -m pytest tests/test_collectors.py -q` → todos passam,
incluindo os 3 novos.

## Done criteria

- [ ] `python -m pytest -q` exit 0
- [ ] `save()` retorna dict com `falhas`; commit é por grupo (não há mais um único `conn.commit()` pós-loop)
- [ ] `coletar.py` registra `status: "parcial"` quando há falhas
- [ ] Nenhum arquivo fora do escopo modificado (`git status`)
- [ ] Linha de status atualizada em `plans/README.md`

## STOP conditions

- Os excertos de "Current state" não batem com o código (drift).
- Algum teste existente de `test_collectors.py`/`test_scheduler.py` depende do
  retorno `None` de `run()`/`save()` e quebra de forma não trivial.
- A mudança parecer exigir alterar o schema ou a lógica de dedup.

## Maintenance notes

- O plano 013 (contrato do coletor) toca o mesmo arquivo — executar este primeiro.
- Revisor deve verificar que o commit por grupo não deixa a conexão em estado
  de transação aberta entre grupos (sqlite3 em modo autocommit implícito inicia
  transação no primeiro DML; o `rollback()` do grupo com falha deve limpar).
- Follow-up deferido: expor `falhas` no painel `/admin` (hoje só Telegram/log).
