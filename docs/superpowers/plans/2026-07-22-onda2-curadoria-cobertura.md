# Onda 2 — Curadoria e Cobertura: Plano de Implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar tarefa a tarefa. Os passos usam checkbox (`- [ ]`).

**Objetivo:** fazer a curadoria de institutos valer no agregado e dar uma tela que mostre o que falta coletar, com ligação manual registro↔pesquisa.

**Arquitetura:** `institutos.agregar` passa a filtrar as 7 consultas que produzem número agregado ou afirmação editorial. Um módulo novo `db/cobertura.py` concentra as consultas de leitura da tela; `tse/matcher.py` cede o backfill para uma função reusável que a ligação manual também chama. A tela vive em `/admin/cobertura`, atrás de `@login_required`.

**Stack:** Python 3.11 (produção/CI) / 3.12 (local), Flask, SQLite, Jinja2, pytest.

**Spec:** `docs/superpowers/specs/2026-07-22-curadoria-cobertura-design.md`

## Restrições globais

- `TESTING=True` na **primeira linha** de todo arquivo de teste, antes de importar `app`/`database`.
- Rodar testes com `.venv/Scripts/python.exe -m pytest` (o python global não tem pytest).
- Código, comentários e commits em **português**; conventional commits.
- Nunca `git push` — a `main` dispara CI → `flyctl deploy`. Trabalho fica na branch `feat/curadoria-cobertura`.
- `tests/test_agregacao.py` é o contrato numérico. Ele deve continuar verde **sem alteração dos números esperados**. Se um número mudar, pare e reporte.
- Toda migração é idempotente: rodar duas vezes não muda o resultado.
- Rejeitar um instituto nunca pode ser desfeito por uma migração posterior.

---

### Task 1: Curadoria no schema — promover os institutos do seed

Sem isto, o filtro da Task 2 zera o dashboard: os 14 institutos estão com `agregar = 0`.

**Arquivos:**
- Criar: `scripts/migrate_curadoria.py`
- Modificar: `seed.sql:8`
- Modificar: `db/core.py` (registrar a chamada depois do seed)
- Teste: `tests/test_curadoria.py`

**Interfaces:**
- Produz: `promover_institutos_do_seed(conn) -> int` (devolve quantas linhas promoveu)

- [ ] **Passo 1: Escrever o teste que falha**

Criar `tests/test_curadoria.py`:

```python
import os
os.environ['TESTING'] = 'True'

import sqlite3

import pytest

from database import DB_PATH, get_conn, init_db
from scripts.migrate_curadoria import (INSTITUTOS_AGREGADOS,
                                       promover_institutos_do_seed)


@pytest.fixture(autouse=True)
def cleanup():
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass
    yield
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass


def test_init_db_promove_institutos_do_seed():
    """Guarda contra o dashboard zerar: depois do init_db nenhum instituto
    do seed pode ficar fora do agregado."""
    init_db(force_seed=True)
    conn = get_conn()
    try:
        fora = conn.execute(
            "SELECT nome FROM institutos WHERE agregar = 0"
        ).fetchall()
    finally:
        conn.close()
    assert [r["nome"] for r in fora] == [], "instituto do seed ficou fora do agregado"


def test_promocao_e_idempotente():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE institutos (id INTEGER PRIMARY KEY, nome TEXT, agregar INTEGER DEFAULT 0)")
    conn.execute("INSERT INTO institutos (nome) VALUES ('Datafolha')")
    conn.commit()

    primeira = promover_institutos_do_seed(conn)
    segunda = promover_institutos_do_seed(conn)

    assert primeira == 1
    assert segunda == 0, "segunda passada não deve mexer em nada"
    conn.close()


def test_promocao_nao_ressuscita_instituto_rejeitado():
    """Instituto descoberto pelo TSE e rejeitado tem agregar=0 de propósito.
    A migração roda a cada init_db e não pode desfazer essa decisão."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE institutos (id INTEGER PRIMARY KEY, nome TEXT, agregar INTEGER DEFAULT 0)")
    conn.execute("INSERT INTO institutos (nome, agregar) VALUES ('Vetor Arrow', 0)")
    conn.commit()

    promover_institutos_do_seed(conn)

    agregar = conn.execute(
        "SELECT agregar FROM institutos WHERE nome = 'Vetor Arrow'").fetchone()[0]
    assert agregar == 0, "rejeição manual não pode ser desfeita pela migração"
    conn.close()


def test_lista_cobre_os_institutos_do_seed():
    """A lista explícita e o seed.sql não podem divergir em silêncio."""
    init_db(force_seed=True)
    conn = get_conn()
    try:
        nomes = {r["nome"] for r in conn.execute("SELECT nome FROM institutos")}
    finally:
        conn.close()
    assert nomes == set(INSTITUTOS_AGREGADOS), (
        "seed.sql e INSTITUTOS_AGREGADOS divergiram — "
        "instituto novo no seed precisa de decisão explícita de curadoria"
    )
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python.exe -m pytest tests/test_curadoria.py -v`
Esperado: FAIL com `ModuleNotFoundError: No module named 'scripts.migrate_curadoria'`

- [ ] **Passo 3: Criar a migração**

Criar `scripts/migrate_curadoria.py`:

```python
"""Promove ao agregado os institutos que vieram do seed (curadoria inicial).

`institutos.agregar` nasceu na migração da Onda 1 com default 0 e ninguém
promoveu os institutos já curados. Enquanto nada lia o flag isso era
inofensivo; a partir do filtro de curadoria, 14 institutos em 0 significam
dashboard vazio.

A lista é **explícita** de propósito. Um `UPDATE institutos SET agregar = 1`
sem cláusula promoveria também os institutos descobertos pelo TSE e
rejeitados à mão — a migração roda a cada `init_db` e desfaria a decisão do
operador em silêncio. Mesmo motivo pelo qual `CNPJ_POR_INSTITUTO` é um mapa
explícito em `scripts/migrate_pesquisas_tse.py`.
"""
import logging
import sqlite3

logger = logging.getLogger(__name__)

# Os 14 institutos do seed.sql, curados à mão antes de a curadoria existir.
# Instituto novo no seed.sql precisa ser adicionado aqui conscientemente —
# tests/test_curadoria.py trava a divergência.
INSTITUTOS_AGREGADOS = (
    "Datafolha",
    "Ibope/IPEC",
    "Quaest",
    "Genial/Quaest",
    "Atlas",
    "Paraná",
    "Real Time",
    "Nexus/BTG Pactual",
    "Verita",
    "Futura Inteligência",
    "PoderData",
    "Meio/Ideia",
    "Vox Populi",
    "Instituto Gerp",
)


def promover_institutos_do_seed(conn: sqlite3.Connection) -> int:
    """Marca `agregar = 1` nos institutos do seed que ainda estiverem em 0.

    Idempotente: a cláusula `agregar = 0` faz a segunda passada não tocar em
    nada. Devolve quantas linhas foram promovidas.
    """
    marcadores = ",".join("?" * len(INSTITUTOS_AGREGADOS))
    cursor = conn.execute(
        f"UPDATE institutos SET agregar = 1 "
        f"WHERE nome IN ({marcadores}) AND agregar = 0",
        INSTITUTOS_AGREGADOS,
    )
    conn.commit()
    if cursor.rowcount:
        logger.info("Curadoria: %d institutos do seed promovidos ao agregado.",
                    cursor.rowcount)
    return cursor.rowcount
```

- [ ] **Passo 4: Ligar no `init_db`, depois do seed**

Em `db/core.py`, logo abaixo da chamada de `_popular_cnpjs(conn)` (a
ordenação é a mesma e pelo mesmo motivo: em banco novo os institutos só
existem depois do `seed.sql`):

```python
    # Curadoria: promove ao agregado os institutos do seed. Depois do seed
    # pelo mesmo motivo de _popular_cnpjs — antes dele não há linha para
    # atualizar. Não ressuscita instituto rejeitado à mão (lista explícita).
    from scripts.migrate_curadoria import promover_institutos_do_seed as _promover
    _promover(conn)
```

- [ ] **Passo 5: Deixar o seed.sql já nascer curado**

Em `seed.sql:8`, trocar o cabeçalho do INSERT para incluir a coluna. Banco
novo não depende da migração; a migração serve aos bancos que já existem.

```sql
INSERT INTO institutos (id, nome, sigla, site, ativo, agregar) VALUES
```

E acrescentar `, 1` ao final de cada uma das 14 tuplas de valores.

- [ ] **Passo 6: Rodar os testes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_curadoria.py -v`
Esperado: 4 passed

- [ ] **Passo 7: Rodar a suíte inteira (nada pode ter mudado ainda)**

Run: `.venv/Scripts/python.exe -m pytest -q`
Esperado: exit 0. Nenhum número de `test_agregacao.py` muda — o filtro só entra na Task 2.

- [ ] **Passo 8: Commit**

```bash
git add scripts/migrate_curadoria.py tests/test_curadoria.py seed.sql db/core.py
git commit -m "feat(curadoria): promove institutos do seed ao agregado"
```

---

### Task 2: Filtro de curadoria nas consultas agregadas

**Arquivos:**
- Modificar: `db/pesquisas.py` (linhas 85, 131, 134, 247, 375, 498)
- Modificar: `db/kpis.py` (linhas 210, 240)
- Modificar: `db/pesquisas.py:571` (`get_institutos_com_totais` ganha o status)
- Teste: `tests/test_curadoria_agregacao.py`

**Interfaces:**
- Consome: `agregar` promovido na Task 1
- Produz: nenhuma assinatura nova; `get_institutos_com_totais` passa a devolver a chave `agregar`

- [ ] **Passo 1: Escrever o teste que falha**

Criar `tests/test_curadoria_agregacao.py`:

```python
import os
os.environ['TESTING'] = 'True'

from datetime import date, timedelta

import pytest

from database import (DB_PATH, get_conn, get_media_agregada,
                      get_pesquisa_por_id, init_db)


@pytest.fixture(autouse=True)
def cleanup():
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass
    yield
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass


def _base():
    """Schema + seed, sem as pesquisas de demonstração."""
    init_db(force_seed=True)
    conn = get_conn()
    conn.execute("DELETE FROM intencoes")
    conn.execute("DELETE FROM pesquisas")
    conn.commit()
    return conn


def _instituto(conn, nome, agregar):
    cur = conn.execute(
        "INSERT INTO institutos (nome, sigla, agregar) VALUES (?, ?, ?)",
        (nome, nome, agregar))
    conn.commit()
    return cur.lastrowid


def _pesquisa(conn, instituto_id, pct, amostra=1000, dias=1):
    data = (date.today() - timedelta(days=dias)).isoformat()
    cur = conn.execute(
        "INSERT INTO pesquisas (instituto_id, cargo, data_pesquisa, "
        "data_publicacao, tamanho_amostra, margem_erro, registro_tse, fonte_url) "
        "VALUES (?, 'presidente', ?, ?, ?, 2.0, ?, 'http://x')",
        (instituto_id, data, data, amostra, f"GEN-{instituto_id}-{pct}"))
    pid = cur.lastrowid
    conn.execute(
        "INSERT INTO intencoes (pesquisa_id, candidato, percentual, tipo) "
        "VALUES (?, 'Lula', ?, 'estimulada')", (pid, pct))
    conn.execute(
        "INSERT INTO intencoes (pesquisa_id, candidato, percentual, tipo) "
        "VALUES (?, 'Tarcísio', ?, 'estimulada')", (pid, 100 - pct))
    conn.commit()
    return pid


def test_instituto_nao_aprovado_fica_fora_da_media():
    conn = _base()
    try:
        aprovado = _instituto(conn, "Aprovado A", agregar=1)
        _pesquisa(conn, aprovado, pct=40)
        _pesquisa(conn, _instituto(conn, "Aprovado B", agregar=1), pct=40)
        # Instituto não aprovado com número absurdo: se entrasse, a média
        # de Lula sairia bem longe de 40.
        _pesquisa(conn, _instituto(conn, "Nao Aprovado", agregar=0), pct=90)
    finally:
        conn.close()

    media = get_media_agregada(cargo='presidente')
    lula = next(c for c in media['candidatos'] if c['candidato'] == 'Lula')

    assert lula['media'] == pytest.approx(40.0, abs=0.5)


def test_instituto_nao_aprovado_continua_visivel_no_detalhe():
    """O outro lado da decisão: fora da média, mas não escondido."""
    conn = _base()
    try:
        pid = _pesquisa(conn, _instituto(conn, "Nao Aprovado", agregar=0), pct=90)
    finally:
        conn.close()

    detalhe = get_pesquisa_por_id(pid)

    assert detalhe is not None, "pesquisa de instituto não aprovado sumiu do detalhe"
    assert detalhe['instituto'] == "Nao Aprovado"


def test_media_ignora_completamente_instituto_nao_aprovado():
    """Com apenas institutos não aprovados, não há agregado."""
    conn = _base()
    try:
        _pesquisa(conn, _instituto(conn, "Nao Aprovado", agregar=0), pct=90)
    finally:
        conn.close()

    media = get_media_agregada(cargo='presidente')

    assert media['candidatos'] == []
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python.exe -m pytest tests/test_curadoria_agregacao.py -v`
Esperado: FAIL — `test_instituto_nao_aprovado_fica_fora_da_media` dá média puxada para cima (~56), e `test_media_ignora_completamente_instituto_nao_aprovado` devolve candidatos.

- [ ] **Passo 3: Aplicar o filtro nas 7 consultas**

Em cada local abaixo, acrescentar a condição na cláusula `WHERE`. **Não**
mudar o `JOIN` para `INNER JOIN ... AND` — manter o filtro no `WHERE` deixa a
intenção explícita e legível.

`db/pesquisas.py:88` (corrida atual) — acrescentar após `WHERE p.cargo = ?`:

```sql
            AND inst.agregar = 1
```

e dentro da subconsulta, que escolhe a pesquisa mais recente, trocar:

```sql
                SELECT p2.id FROM pesquisas p2
                JOIN intencoes i2 ON i2.pesquisa_id = p2.id
                JOIN institutos inst2 ON p2.instituto_id = inst2.id
                WHERE p2.cargo = ? AND {filtro_sub} AND inst2.agregar = 1
```

Sem isso a subconsulta escolheria uma pesquisa de instituto não aprovado e a
consulta externa devolveria vazio.

`db/pesquisas.py:249` (`get_media_agregada`) — após `WHERE p.cargo = ? AND p.data_pesquisa >= ?`:

```sql
            AND inst.agregar = 1
```

`db/pesquisas.py:131,134` (`detectar_variacoes_bruscas`) — na cláusula `WHERE` do CTE `pares`:

```sql
        AND inst_recente.agregar = 1 AND inst_anterior.agregar = 1
```

`db/pesquisas.py:375` (house effects) — após o `WHERE`:

```sql
            AND inst.agregar = 1
```

`db/pesquisas.py:498` (`get_historico_multi`) — após o `WHERE`:

```sql
            AND inst.agregar = 1
```

`db/kpis.py:210` e `db/kpis.py:240` (líder presidente / líder gov RJ) — após o `WHERE` de cada:

```sql
            AND inst.agregar = 1
```

- [ ] **Passo 4: Rodar o teste novo**

Run: `.venv/Scripts/python.exe -m pytest tests/test_curadoria_agregacao.py -v`
Esperado: 3 passed

- [ ] **Passo 5: Rodar o contrato numérico — gate de equivalência**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agregacao.py -v`
Esperado: todos passam **com os mesmos números de antes**. Os institutos das
fixtures vêm do seed e a Task 1 os promoveu, então nada muda.
Se algum número mudar: **pare e reporte** — significa que o filtro pegou algo
que não devia.

- [ ] **Passo 6: Expor o status em `get_institutos_com_totais`**

Em `db/pesquisas.py:576`, trocar a consulta por (só o `SELECT` muda — **não**
acrescentar `WHERE`, esta lista mostra todos):

```sql
            SELECT inst.nome, inst.agregar, COUNT(p.id) AS total,
                   MAX(p.data_pesquisa) AS ultima_coleta
            FROM institutos inst
            LEFT JOIN pesquisas p ON p.instituto_id = inst.id
            GROUP BY inst.id, inst.nome, inst.agregar
            ORDER BY total DESC, inst.nome ASC
```

- [ ] **Passo 7: Suíte inteira**

Run: `.venv/Scripts/python.exe -m pytest -q`
Esperado: exit 0

- [ ] **Passo 8: Commit**

```bash
git add db/pesquisas.py db/kpis.py tests/test_curadoria_agregacao.py
git commit -m "feat(curadoria): só institutos aprovados entram no agregado"
```

---

### Task 3: Extrair o backfill do casador

A ligação manual precisa do mesmo efeito do casamento automático. Hoje ele é
inline no laço de `tse/matcher.py`.

**Arquivos:**
- Modificar: `tse/matcher.py:108-128`
- Teste: `tests/test_tse_matcher.py` (acrescentar)

**Interfaces:**
- Produz: `aplicar_ligacao(conn, protocolo, pesquisa_id, amostra_tse, data_fim) -> None`

- [ ] **Passo 1: Escrever o teste que falha**

Acrescentar a `tests/test_tse_matcher.py`:

```python
def test_aplicar_ligacao_isolada():
    """A ligação é reusável fora do casamento automático (ligação manual)."""
    from tse.matcher import aplicar_ligacao

    conn = _conn()
    _tse(conn, "BR000012026", "2026-07-01", "2026-07-03", "2026-07-05", amostra=2004)
    pid = _pesquisa(conn, "2026-07-05", amostra=0)

    aplicar_ligacao(conn, protocolo="BR000012026", pesquisa_id=pid,
                    amostra_tse=2004, data_fim="2026-07-03")
    conn.commit()

    tse = conn.execute("SELECT pesquisa_id FROM pesquisas_tse WHERE protocolo = ?",
                       ("BR000012026",)).fetchone()
    pesquisa = conn.execute(
        "SELECT tamanho_amostra, data_pesquisa, registro_tse FROM pesquisas WHERE id = ?",
        (pid,)).fetchone()

    assert tse["pesquisa_id"] == pid
    assert pesquisa["tamanho_amostra"] == 2004
    assert pesquisa["data_pesquisa"] == "2026-07-03"
    assert pesquisa["registro_tse"] == "BR000012026"
    conn.close()


def test_aplicar_ligacao_preserva_amostra_realizada():
    """Mesma regra do casamento automático, agora na função extraída."""
    from tse.matcher import aplicar_ligacao

    conn = _conn()
    _tse(conn, "BR000012026", "2026-07-01", "2026-07-03", "2026-07-05", amostra=2000)
    pid = _pesquisa(conn, "2026-07-05", amostra=2003)

    aplicar_ligacao(conn, protocolo="BR000012026", pesquisa_id=pid,
                    amostra_tse=2000, data_fim="2026-07-03")
    conn.commit()

    amostra = conn.execute(
        "SELECT tamanho_amostra FROM pesquisas WHERE id = ?", (pid,)).fetchone()[0]
    assert amostra == 2003
    conn.close()
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tse_matcher.py -v -k aplicar_ligacao`
Esperado: FAIL com `ImportError: cannot import name 'aplicar_ligacao'`

- [ ] **Passo 3: Extrair a função**

Em `tse/matcher.py`, acrescentar antes de `casar`:

```python
def aplicar_ligacao(conn: sqlite3.Connection, protocolo: str, pesquisa_id: int,
                    amostra_tse: int, data_fim: str) -> None:
    """Liga um registro do TSE a uma pesquisa e faz o backfill dos metadados.

    Usada tanto pelo casamento automático quanto pela ligação manual da tela
    de cobertura — a regra de backfill é do domínio, não do casador.

    **Não commita**: quem chama decide a transação (o casador aplica vários
    pares de uma vez; a rota manual aplica um só).
    """
    conn.execute(
        "UPDATE pesquisas_tse SET pesquisa_id = ? WHERE protocolo = ?",
        (pesquisa_id, protocolo),
    )
    # A amostra do TSE é a REGISTRADA (planejada); o release publica a
    # REALIZADA, que pode diferir (visto: 2000 registrado vs 2003 realizado).
    # Só preenche quando falta — nunca sobrescreve um valor real por um
    # planejado.
    conn.execute("""
        UPDATE pesquisas
        SET tamanho_amostra = CASE
                WHEN tamanho_amostra IS NULL OR tamanho_amostra = 0
                THEN ? ELSE tamanho_amostra END,
            data_pesquisa = ?,
            registro_tse = ?
        WHERE id = ?
    """, (amostra_tse, data_fim, protocolo, pesquisa_id))
```

E substituir o corpo do `if not dry_run:` em `casar` por:

```python
    if not dry_run:
        for par in casados:
            aplicar_ligacao(conn, protocolo=par["protocolo"],
                            pesquisa_id=par["pesquisa_id"],
                            amostra_tse=par["amostra_tse"],
                            data_fim=par["data_tse"])
        conn.commit()
        logger.info("Casamento aplicado: %d pares, %d ambíguos, %d sem par.",
                    len(casados), len(ambiguos), sem_par)
```

- [ ] **Passo 4: Rodar os testes do casador**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tse_matcher.py -v`
Esperado: 10 passed. Os 8 antigos passam **sem alteração** — é o que prova que
a extração não mudou o comportamento.

- [ ] **Passo 5: Commit**

```bash
git add tse/matcher.py tests/test_tse_matcher.py
git commit -m "refactor(tse): extrai aplicar_ligacao do casador"
```

---

### Task 4: Consultas da tela de cobertura

**Arquivos:**
- Criar: `db/cobertura.py`
- Modificar: `database.py` (re-exportar na façade)
- Teste: `tests/test_cobertura.py`

**Interfaces:**
- Produz:
  - `fila_de_trabalho(cargo, limite=50, offset=0) -> list[dict]`
  - `contar_fila(cargo) -> int`
  - `institutos_para_descobrir() -> list[dict]`
  - `em_campo_hoje() -> list[dict]`
  - `agendadas() -> list[dict]`

- [ ] **Passo 1: Escrever o teste que falha**

Criar `tests/test_cobertura.py`:

```python
import os
os.environ['TESTING'] = 'True'

import sqlite3
from datetime import date, timedelta

from db.cobertura import (_agendadas, _em_campo_hoje, _fila_de_trabalho,
                          _institutos_para_descobrir)
from scripts.migrate_pesquisas_tse import aplicar_migracao


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE institutos (id INTEGER PRIMARY KEY, nome TEXT, agregar INTEGER DEFAULT 0)")
    conn.execute("""CREATE TABLE pesquisas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, instituto_id INTEGER, cargo TEXT,
        data_pesquisa TEXT, data_publicacao TEXT, tamanho_amostra INTEGER,
        margem_erro REAL, registro_tse TEXT UNIQUE, fonte_url TEXT)""")
    aplicar_migracao(conn)
    return conn


def _reg(conn, protocolo, cnpj, inicio, fim, cargo="presidente",
         abrangencia="nacional", pesquisa_id=None, empresa="EMPRESA X"):
    conn.execute("""INSERT INTO pesquisas_tse
        (protocolo, cargo, cnpj_empresa, nome_empresa, data_inicio, data_fim,
         data_divulgacao, qt_entrevistado, abrangencia, pesquisa_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1200, ?, ?)""",
        (protocolo, cargo, cnpj, empresa, inicio, fim, fim, abrangencia, pesquisa_id))
    conn.commit()


def _dia(delta):
    return (date.today() + timedelta(days=delta)).isoformat()


def test_fila_traz_so_encerradas_de_instituto_aprovado():
    conn = _conn()
    conn.execute("INSERT INTO institutos (nome, agregar) VALUES ('Aprovado', 1)")
    conn.execute("UPDATE institutos SET cnpj = '111' WHERE nome = 'Aprovado'")
    conn.execute("INSERT INTO institutos (nome, agregar, cnpj) VALUES ('Rejeitado', 0, '222')")
    conn.commit()

    _reg(conn, "P1", "111", _dia(-10), _dia(-8))          # entra
    _reg(conn, "P2", "222", _dia(-10), _dia(-8))          # instituto rejeitado
    _reg(conn, "P3", "333", _dia(-10), _dia(-8))          # instituto desconhecido
    _reg(conn, "P4", "111", _dia(-2), _dia(+2))           # ainda em campo
    _reg(conn, "P5", "111", _dia(-10), _dia(-8), pesquisa_id=1)  # já ligada

    fila = _fila_de_trabalho(conn, cargo="presidente")

    assert [f["protocolo"] for f in fila] == ["P1"]
    conn.close()


def test_fila_exclui_municipal():
    conn = _conn()
    conn.execute("INSERT INTO institutos (nome, agregar, cnpj) VALUES ('Aprovado', 1, '111')")
    conn.commit()
    _reg(conn, "R1", "111", _dia(-10), _dia(-8), cargo="governador_rj",
         abrangencia="estadual")
    _reg(conn, "R2", "111", _dia(-10), _dia(-8), cargo="governador_rj",
         abrangencia="municipal")

    fila = _fila_de_trabalho(conn, cargo="governador_rj")

    assert [f["protocolo"] for f in fila] == ["R1"], "pesquisa municipal não é série estadual"
    conn.close()


def test_fila_ordena_por_fim_de_campo_decrescente():
    conn = _conn()
    conn.execute("INSERT INTO institutos (nome, agregar, cnpj) VALUES ('Aprovado', 1, '111')")
    conn.commit()
    _reg(conn, "VELHA", "111", _dia(-40), _dia(-38))
    _reg(conn, "NOVA", "111", _dia(-5), _dia(-3))

    fila = _fila_de_trabalho(conn, cargo="presidente")

    assert [f["protocolo"] for f in fila] == ["NOVA", "VELHA"]
    conn.close()


def test_descoberta_traz_so_cnpj_sem_instituto():
    conn = _conn()
    conn.execute("INSERT INTO institutos (nome, agregar, cnpj) VALUES ('Conhecido', 1, '111')")
    conn.commit()
    _reg(conn, "A1", "111", _dia(-10), _dia(-8), empresa="CONHECIDO")
    _reg(conn, "B1", "999", _dia(-10), _dia(-8), empresa="NOVO INSTITUTO LTDA")
    _reg(conn, "B2", "999", _dia(-20), _dia(-18), empresa="NOVO INSTITUTO LTDA")

    descoberta = _institutos_para_descobrir(conn)

    assert len(descoberta) == 1
    assert descoberta[0]["cnpj_empresa"] == "999"
    assert descoberta[0]["registros"] == 2
    assert descoberta[0]["nome_empresa"] == "NOVO INSTITUTO LTDA"
    conn.close()


def test_descoberta_nao_traz_instituto_rejeitado():
    """Rejeitar cria linha com agregar=0 justamente para sumir da descoberta."""
    conn = _conn()
    conn.execute("INSERT INTO institutos (nome, agregar, cnpj) VALUES ('Rejeitado', 0, '999')")
    conn.commit()
    _reg(conn, "B1", "999", _dia(-10), _dia(-8))

    assert _institutos_para_descobrir(conn) == []
    conn.close()


def test_em_campo_hoje_exclui_agendada():
    conn = _conn()
    _reg(conn, "AGORA", "111", _dia(-1), _dia(+1))
    _reg(conn, "AGENDADA", "111", _dia(+10), _dia(+13))
    _reg(conn, "ENCERRADA", "111", _dia(-10), _dia(-8))

    assert [r["protocolo"] for r in _em_campo_hoje(conn)] == ["AGORA"]
    assert [r["protocolo"] for r in _agendadas(conn)] == ["AGENDADA"]
    conn.close()
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cobertura.py -v`
Esperado: FAIL com `ModuleNotFoundError: No module named 'db.cobertura'`

- [ ] **Passo 3: Criar o módulo**

Criar `db/cobertura.py`:

```python
"""Leitura da cobertura: o que o TSE registrou e o Pulso ainda não tem.

As funções com prefixo `_` recebem a conexão e existem para o teste poder
usar um banco em memória; as públicas abrem a conexão sozinhas, como o resto
de `db/*`.
"""
from datetime import date

from db.core import get_db

# Registro de pesquisa municipal não pertence a uma série estadual/nacional —
# fica fora da fila mesmo quando o instituto é aprovado.
_NAO_MUNICIPAL = "(t.abrangencia IS NULL OR t.abrangencia != 'municipal')"


def _fila_de_trabalho(conn, cargo: str, limite: int = 50, offset: int = 0) -> list[dict]:
    """Registros encerrados, de instituto aprovado, ainda sem pesquisa."""
    rows = conn.execute(f"""
        SELECT t.protocolo, t.nome_empresa, t.data_inicio, t.data_fim,
               t.qt_entrevistado, t.abrangencia, i.nome AS instituto
        FROM pesquisas_tse t
        JOIN institutos i ON i.cnpj = t.cnpj_empresa
        WHERE t.cargo = ? AND t.pesquisa_id IS NULL
          AND t.data_fim < ? AND i.agregar = 1 AND {_NAO_MUNICIPAL}
        ORDER BY t.data_fim DESC, t.protocolo
        LIMIT ? OFFSET ?
    """, (cargo, date.today().isoformat(), limite, offset)).fetchall()
    return [dict(r) for r in rows]


def _contar_fila(conn, cargo: str) -> int:
    return conn.execute(f"""
        SELECT COUNT(*)
        FROM pesquisas_tse t
        JOIN institutos i ON i.cnpj = t.cnpj_empresa
        WHERE t.cargo = ? AND t.pesquisa_id IS NULL
          AND t.data_fim < ? AND i.agregar = 1 AND {_NAO_MUNICIPAL}
    """, (cargo, date.today().isoformat())).fetchone()[0]


def _institutos_para_descobrir(conn) -> list[dict]:
    """CNPJs do registro sem linha em `institutos` — nunca avaliados.

    Rejeitar cria a linha com agregar=0, então o instituto rejeitado some
    daqui e não reaparece a cada sync diário.
    """
    rows = conn.execute("""
        SELECT t.cnpj_empresa,
               MAX(t.nome_empresa) AS nome_empresa,
               COUNT(*) AS registros,
               CAST(AVG(t.qt_entrevistado) AS INTEGER) AS amostra_media,
               MAX(t.data_fim) AS ultimo_campo
        FROM pesquisas_tse t
        LEFT JOIN institutos i ON i.cnpj = t.cnpj_empresa
        WHERE i.id IS NULL AND t.cnpj_empresa != ''
        GROUP BY t.cnpj_empresa
        ORDER BY registros DESC, amostra_media DESC
    """).fetchall()
    return [dict(r) for r in rows]


def _em_campo_hoje(conn) -> list[dict]:
    hoje = date.today().isoformat()
    rows = conn.execute("""
        SELECT t.protocolo, t.cargo, t.nome_empresa, t.data_inicio, t.data_fim,
               t.qt_entrevistado
        FROM pesquisas_tse t
        WHERE t.data_inicio <= ? AND t.data_fim >= ?
        ORDER BY t.data_fim, t.protocolo
    """, (hoje, hoje)).fetchall()
    return [dict(r) for r in rows]


def _agendadas(conn) -> list[dict]:
    rows = conn.execute("""
        SELECT t.protocolo, t.cargo, t.nome_empresa, t.data_inicio, t.data_fim,
               t.qt_entrevistado
        FROM pesquisas_tse t
        WHERE t.data_inicio > ?
        ORDER BY t.data_inicio, t.protocolo
    """, (date.today().isoformat(),)).fetchall()
    return [dict(r) for r in rows]


def fila_de_trabalho(cargo: str, limite: int = 50, offset: int = 0) -> list[dict]:
    with get_db() as conn:
        return _fila_de_trabalho(conn, cargo, limite, offset)


def contar_fila(cargo: str) -> int:
    with get_db() as conn:
        return _contar_fila(conn, cargo)


def institutos_para_descobrir() -> list[dict]:
    with get_db() as conn:
        return _institutos_para_descobrir(conn)


def em_campo_hoje() -> list[dict]:
    with get_db() as conn:
        return _em_campo_hoje(conn)


def agendadas() -> list[dict]:
    with get_db() as conn:
        return _agendadas(conn)
```

- [ ] **Passo 4: Re-exportar na façade**

Em `database.py`, junto dos outros imports de `db.*`:

```python
from db.cobertura import (agendadas, contar_fila, em_campo_hoje,
                          fila_de_trabalho, institutos_para_descobrir)
```

- [ ] **Passo 5: Rodar os testes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cobertura.py -v`
Esperado: 6 passed

- [ ] **Passo 6: Commit**

```bash
git add db/cobertura.py database.py tests/test_cobertura.py
git commit -m "feat(cobertura): consultas de fila, descoberta e campo ativo"
```

---

### Task 5: Ligação manual — rota e guardas

**Arquivos:**
- Criar: `db/curadoria.py`
- Modificar: `app.py` (rota nova)
- Teste: `tests/test_ligacao_manual.py`

**Interfaces:**
- Consome: `aplicar_ligacao` (Task 3)
- Produz: `ligar_manual(conn, protocolo, pesquisa_id) -> dict` com `{"ok": bool, "erro": str | None}`

- [ ] **Passo 1: Escrever o teste que falha**

Criar `tests/test_ligacao_manual.py`:

```python
import os
os.environ['TESTING'] = 'True'

import sqlite3

from db.curadoria import ligar_manual
from scripts.migrate_pesquisas_tse import aplicar_migracao


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE institutos (id INTEGER PRIMARY KEY, nome TEXT, agregar INTEGER DEFAULT 1)")
    conn.execute("""CREATE TABLE pesquisas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, instituto_id INTEGER, cargo TEXT,
        data_pesquisa TEXT, data_publicacao TEXT, tamanho_amostra INTEGER,
        margem_erro REAL, registro_tse TEXT UNIQUE, fonte_url TEXT)""")
    aplicar_migracao(conn)
    conn.execute("INSERT INTO institutos (id, nome, cnpj) VALUES (1, 'Quaest', '111')")
    conn.commit()
    return conn


def _reg(conn, protocolo, cargo="presidente", pesquisa_id=None):
    conn.execute("""INSERT INTO pesquisas_tse
        (protocolo, cargo, cnpj_empresa, nome_empresa, data_inicio, data_fim,
         data_divulgacao, qt_entrevistado, abrangencia, pesquisa_id)
        VALUES (?, ?, '111', 'QUAEST', '2026-07-01', '2026-07-03',
                '2026-07-05', 2004, 'nacional', ?)""",
        (protocolo, cargo, pesquisa_id))
    conn.commit()


def _pesquisa(conn, cargo="presidente", registro="GEN-1", amostra=0):
    cur = conn.execute("""INSERT INTO pesquisas
        (instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra,
         margem_erro, registro_tse, fonte_url)
        VALUES (1, ?, '2026-07-10', '2026-07-10', ?, 2.0, ?, 'http://x')""",
        (cargo, amostra, registro))
    conn.commit()
    return cur.lastrowid


def test_ligacao_feliz():
    conn = _conn()
    _reg(conn, "BR001")
    pid = _pesquisa(conn)

    resultado = ligar_manual(conn, "BR001", pid)

    assert resultado["ok"] is True
    linha = conn.execute(
        "SELECT tamanho_amostra, data_pesquisa, registro_tse FROM pesquisas WHERE id = ?",
        (pid,)).fetchone()
    assert linha["tamanho_amostra"] == 2004
    assert linha["data_pesquisa"] == "2026-07-03"
    assert linha["registro_tse"] == "BR001"
    conn.close()


def test_recusa_protocolo_ja_ligado():
    conn = _conn()
    outra = _pesquisa(conn, registro="GEN-outra")
    _reg(conn, "BR001", pesquisa_id=outra)
    pid = _pesquisa(conn, registro="GEN-nova")

    resultado = ligar_manual(conn, "BR001", pid)

    assert resultado["ok"] is False
    assert "já está ligado" in resultado["erro"]
    conn.close()


def test_recusa_pesquisa_ja_ligada_a_outro_protocolo():
    conn = _conn()
    pid = _pesquisa(conn)
    _reg(conn, "BR001", pesquisa_id=pid)
    _reg(conn, "BR002")

    resultado = ligar_manual(conn, "BR002", pid)

    assert resultado["ok"] is False
    assert "já está ligada" in resultado["erro"]
    conn.close()


def test_recusa_cargo_divergente():
    """Registro de governador não pode ser ligado a pesquisa de presidente."""
    conn = _conn()
    _reg(conn, "RJ001", cargo="governador_rj")
    pid = _pesquisa(conn, cargo="presidente")

    resultado = ligar_manual(conn, "RJ001", pid)

    assert resultado["ok"] is False
    assert "cargo" in resultado["erro"]
    conn.close()


def test_recusa_protocolo_inexistente():
    conn = _conn()
    pid = _pesquisa(conn)

    resultado = ligar_manual(conn, "NAOEXISTE", pid)

    assert resultado["ok"] is False
    assert "não encontrado" in resultado["erro"]
    conn.close()


def test_recusa_pesquisa_inexistente():
    conn = _conn()
    _reg(conn, "BR001")

    resultado = ligar_manual(conn, "BR001", 9999)

    assert resultado["ok"] is False
    assert "não encontrada" in resultado["erro"]
    conn.close()


def test_recusa_nao_deixa_efeito_parcial():
    conn = _conn()
    _reg(conn, "RJ001", cargo="governador_rj")
    pid = _pesquisa(conn, cargo="presidente")

    ligar_manual(conn, "RJ001", pid)

    ligado = conn.execute(
        "SELECT pesquisa_id FROM pesquisas_tse WHERE protocolo = 'RJ001'").fetchone()[0]
    registro = conn.execute(
        "SELECT registro_tse FROM pesquisas WHERE id = ?", (pid,)).fetchone()[0]
    assert ligado is None
    assert registro == "GEN-1", "recusa não pode ter escrito nada"
    conn.close()
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ligacao_manual.py -v`
Esperado: FAIL com `ModuleNotFoundError: No module named 'db.curadoria'`

- [ ] **Passo 3: Implementar**

Criar `db/curadoria.py`:

```python
"""Escrita da curadoria: ligação manual registro↔pesquisa e aprovação de
institutos descobertos pelo TSE.

Toda operação valida antes de escrever. Ligação errada é pior que ligação
ausente: envenena a série histórica em silêncio e desfazer exige saber que
aconteceu. É o mesmo princípio que faz o casador automático recusar
ambiguidade em vez de chutar.
"""
import sqlite3

from db.core import get_db
from tse.matcher import aplicar_ligacao


def ligar_manual(conn: sqlite3.Connection, protocolo: str,
                 pesquisa_id: int) -> dict:
    """Liga um registro do TSE a uma pesquisa existente, com validação.

    Devolve {"ok": True, "erro": None} ou {"ok": False, "erro": "<motivo>"}.
    Em caso de recusa, nada é escrito.
    """
    registro = conn.execute(
        "SELECT protocolo, cargo, qt_entrevistado, data_fim, pesquisa_id "
        "FROM pesquisas_tse WHERE protocolo = ?", (protocolo,)).fetchone()
    if registro is None:
        return {"ok": False, "erro": f"Protocolo {protocolo} não encontrado."}
    if registro["pesquisa_id"] is not None:
        return {"ok": False,
                "erro": f"Protocolo {protocolo} já está ligado à pesquisa "
                        f"{registro['pesquisa_id']}."}

    pesquisa = conn.execute(
        "SELECT id, cargo FROM pesquisas WHERE id = ?", (pesquisa_id,)).fetchone()
    if pesquisa is None:
        return {"ok": False, "erro": f"Pesquisa {pesquisa_id} não encontrada."}

    ja_ligada = conn.execute(
        "SELECT protocolo FROM pesquisas_tse WHERE pesquisa_id = ?",
        (pesquisa_id,)).fetchone()
    if ja_ligada is not None:
        return {"ok": False,
                "erro": f"Pesquisa {pesquisa_id} já está ligada ao protocolo "
                        f"{ja_ligada['protocolo']}."}

    if pesquisa["cargo"] != registro["cargo"]:
        return {"ok": False,
                "erro": f"Cargo divergente: registro é {registro['cargo']}, "
                        f"pesquisa é {pesquisa['cargo']}."}

    aplicar_ligacao(conn, protocolo=protocolo, pesquisa_id=pesquisa_id,
                    amostra_tse=registro["qt_entrevistado"],
                    data_fim=registro["data_fim"])
    conn.commit()
    return {"ok": True, "erro": None}


def ligar(protocolo: str, pesquisa_id: int) -> dict:
    with get_db() as conn:
        return ligar_manual(conn, protocolo, pesquisa_id)
```

- [ ] **Passo 4: Rodar os testes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ligacao_manual.py -v`
Esperado: 7 passed

- [ ] **Passo 5: Commit**

```bash
git add db/curadoria.py tests/test_ligacao_manual.py
git commit -m "feat(cobertura): ligação manual registro-pesquisa com guardas"
```

---

### Task 6: Aprovar e rejeitar instituto descoberto

**Arquivos:**
- Modificar: `db/curadoria.py`
- Teste: `tests/test_ligacao_manual.py` (acrescentar)

**Interfaces:**
- Produz: `avaliar_instituto(conn, cnpj, nome_exibicao, aprovar: bool) -> dict`

- [ ] **Passo 1: Escrever o teste que falha**

Acrescentar a `tests/test_ligacao_manual.py`:

```python
def test_aprovar_instituto_cria_linha_agregada():
    from db.curadoria import avaliar_instituto

    conn = _conn()
    _reg(conn, "X1")
    conn.execute("UPDATE pesquisas_tse SET cnpj_empresa = '999', "
                 "nome_empresa = 'VETOR ARROW LTDA' WHERE protocolo = 'X1'")
    conn.commit()

    resultado = avaliar_instituto(conn, cnpj="999",
                                  nome_exibicao="Vetor Arrow", aprovar=True)

    assert resultado["ok"] is True
    linha = conn.execute(
        "SELECT nome, agregar FROM institutos WHERE cnpj = '999'").fetchone()
    assert linha["nome"] == "Vetor Arrow", "nome de exibição, não razão social"
    assert linha["agregar"] == 1
    conn.close()


def test_rejeitar_instituto_cria_linha_fora_do_agregado():
    from db.curadoria import avaliar_instituto

    conn = _conn()
    resultado = avaliar_instituto(conn, cnpj="999",
                                  nome_exibicao="Instituto Qualquer", aprovar=False)

    assert resultado["ok"] is True
    agregar = conn.execute(
        "SELECT agregar FROM institutos WHERE cnpj = '999'").fetchone()[0]
    assert agregar == 0
    conn.close()


def test_avaliar_instituto_ja_cadastrado_e_recusado():
    from db.curadoria import avaliar_instituto

    conn = _conn()  # já tem Quaest com cnpj 111
    resultado = avaliar_instituto(conn, cnpj="111",
                                  nome_exibicao="Duplicata", aprovar=True)

    assert resultado["ok"] is False
    assert "já cadastrado" in resultado["erro"]
    total = conn.execute(
        "SELECT COUNT(*) FROM institutos WHERE cnpj = '111'").fetchone()[0]
    assert total == 1
    conn.close()


def test_avaliar_exige_nome_de_exibicao():
    from db.curadoria import avaliar_instituto

    conn = _conn()
    resultado = avaliar_instituto(conn, cnpj="999", nome_exibicao="  ",
                                  aprovar=True)

    assert resultado["ok"] is False
    assert "nome" in resultado["erro"].lower()
    conn.close()
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ligacao_manual.py -v -k "avaliar or aprovar or rejeitar"`
Esperado: FAIL com `ImportError: cannot import name 'avaliar_instituto'`

- [ ] **Passo 3: Implementar**

Acrescentar a `db/curadoria.py`:

```python
def avaliar_instituto(conn: sqlite3.Connection, cnpj: str, nome_exibicao: str,
                      aprovar: bool) -> dict:
    """Cria a linha de `institutos` para um CNPJ descoberto no registro do TSE.

    Aprovar grava `agregar = 1`; rejeitar grava 0. Rejeitar **precisa** criar
    a linha: é o que tira o instituto da lista de descoberta e impede que ele
    reapareça a cada sync diário.

    O nome vem do operador, não do TSE: o dataset traz a razão social
    (`VETOR ARROW INSTITUTO DE PESQUISA E OPINIAO LTDA`), que não serve para
    exibir no dashboard.
    """
    nome = (nome_exibicao or "").strip()
    if not nome:
        return {"ok": False, "erro": "Nome de exibição é obrigatório."}

    existente = conn.execute(
        "SELECT nome FROM institutos WHERE cnpj = ?", (cnpj,)).fetchone()
    if existente is not None:
        return {"ok": False,
                "erro": f"CNPJ {cnpj} já cadastrado como {existente['nome']}."}

    conn.execute(
        "INSERT INTO institutos (nome, sigla, cnpj, agregar) VALUES (?, ?, ?, ?)",
        (nome, nome, cnpj, 1 if aprovar else 0))
    conn.commit()
    return {"ok": True, "erro": None}


def avaliar(cnpj: str, nome_exibicao: str, aprovar: bool) -> dict:
    with get_db() as conn:
        return avaliar_instituto(conn, cnpj, nome_exibicao, aprovar)
```

- [ ] **Passo 4: Rodar os testes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ligacao_manual.py -v`
Esperado: 11 passed

- [ ] **Passo 5: Commit**

```bash
git add db/curadoria.py tests/test_ligacao_manual.py
git commit -m "feat(curadoria): aprovar e rejeitar instituto descoberto no TSE"
```

---

### Task 7: Tela `/admin/cobertura`

**Arquivos:**
- Modificar: `app.py` (3 rotas)
- Criar: `templates/admin_cobertura.html`
- Teste: `tests/test_rotas_cobertura.py`

**Interfaces:**
- Consome: `db/cobertura.py` (Task 4), `db/curadoria.py` (Tasks 5–6)

- [ ] **Passo 1: Escrever o teste que falha**

Criar `tests/test_rotas_cobertura.py`:

```python
import os
os.environ['TESTING'] = 'True'

import pytest

from app import app
from database import DB_PATH, get_conn, init_db


@pytest.fixture
def cliente():
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass
    init_db(force_seed=True)
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as c:
        yield c


def _logar(cliente):
    with cliente.session_transaction() as sessao:
        sessao['user_id'] = 1
        sessao['username'] = 'admin'


def test_cobertura_exige_login(cliente):
    resposta = cliente.get('/admin/cobertura')
    assert resposta.status_code in (302, 401)


def test_cobertura_abre_logado(cliente):
    _logar(cliente)
    resposta = cliente.get('/admin/cobertura')
    assert resposta.status_code == 200
    assert 'cobertura' in resposta.get_data(as_text=True).lower()


def test_ligar_exige_login(cliente):
    resposta = cliente.post('/admin/cobertura/ligar',
                            data={'protocolo': 'X', 'pesquisa_id': '1'})
    assert resposta.status_code in (302, 401)


def test_avaliar_instituto_exige_login(cliente):
    resposta = cliente.post('/admin/cobertura/instituto',
                            data={'cnpj': '999', 'nome': 'X', 'acao': 'aprovar'})
    assert resposta.status_code in (302, 401)


def test_ligar_com_protocolo_inexistente_nao_quebra(cliente):
    _logar(cliente)
    resposta = cliente.post('/admin/cobertura/ligar',
                            data={'protocolo': 'NAOEXISTE', 'pesquisa_id': '1'},
                            follow_redirects=True)
    assert resposta.status_code == 200
    assert 'não encontrado' in resposta.get_data(as_text=True)
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python.exe -m pytest tests/test_rotas_cobertura.py -v`
Esperado: FAIL — 404 nas rotas.

- [ ] **Passo 3: Implementar as rotas**

Em `app.py`, junto das demais rotas `/admin/*` (depois de `admin_coletar_url`):

```python
@app.route('/admin/cobertura')
@login_required
def admin_cobertura():
    """Fila do que o TSE registrou e o Pulso ainda não tem."""
    from database import (agendadas, contar_fila, em_campo_hoje,
                          fila_de_trabalho, institutos_para_descobrir)

    pagina = max(1, request.args.get('pagina', 1, type=int))
    cargo = request.args.get('cargo', 'presidente')
    if cargo not in ('presidente', 'governador_rj'):
        cargo = 'presidente'
    por_pagina = 50
    offset = (pagina - 1) * por_pagina

    total = contar_fila(cargo)
    return render_template(
        'admin_cobertura.html',
        cargo=cargo,
        pagina=pagina,
        por_pagina=por_pagina,
        total_fila=total,
        tem_proxima=(offset + por_pagina) < total,
        fila=fila_de_trabalho(cargo, limite=por_pagina, offset=offset),
        descoberta=institutos_para_descobrir(),
        em_campo=em_campo_hoje(),
        agendadas=agendadas(),
    )


@app.route('/admin/cobertura/ligar', methods=['POST'])
@login_required
def admin_cobertura_ligar():
    """Liga um registro do TSE a uma pesquisa existente."""
    from db.curadoria import ligar

    protocolo = (request.form.get('protocolo') or '').strip()
    pesquisa_id = request.form.get('pesquisa_id', type=int)
    if not protocolo or pesquisa_id is None:
        flash('Informe protocolo e id da pesquisa.', 'erro')
        return redirect(url_for('admin_cobertura'))

    resultado = ligar(protocolo, pesquisa_id)
    flash(resultado['erro'] if not resultado['ok']
          else f'Protocolo {protocolo} ligado à pesquisa {pesquisa_id}.',
          'erro' if not resultado['ok'] else 'ok')
    return redirect(url_for('admin_cobertura'))


@app.route('/admin/cobertura/instituto', methods=['POST'])
@login_required
def admin_cobertura_instituto():
    """Aprova ou rejeita um instituto descoberto no registro do TSE."""
    from db.curadoria import avaliar

    cnpj = (request.form.get('cnpj') or '').strip()
    nome = (request.form.get('nome') or '').strip()
    aprovar = request.form.get('acao') == 'aprovar'

    resultado = avaliar(cnpj, nome, aprovar)
    flash(resultado['erro'] if not resultado['ok']
          else f"{nome} {'aprovado' if aprovar else 'rejeitado'}.",
          'erro' if not resultado['ok'] else 'ok')
    return redirect(url_for('admin_cobertura'))
```

Conferir no topo de `app.py` que `flash`, `redirect`, `url_for` e `request`
já estão importados de `flask`; acrescentar os que faltarem.

- [ ] **Passo 4: Criar o template**

Criar `templates/admin_cobertura.html`, seguindo o padrão de
`templates/admin_usuarios.html` (mesmo `{% extends %}` e mesmas classes):

```html
{% extends "base.html" %}
{% block title %}Cobertura — Pulso Eleitoral{% endblock %}
{% block content %}
<h1>Cobertura</h1>

{% with mensagens = get_flashed_messages(with_categories=true) %}
  {% for categoria, texto in mensagens %}
    <p class="flash flash-{{ categoria }}">{{ texto }}</p>
  {% endfor %}
{% endwith %}

<nav>
  <a href="{{ url_for('admin_cobertura', cargo='presidente') }}">Presidente</a> ·
  <a href="{{ url_for('admin_cobertura', cargo='governador_rj') }}">Governador RJ</a>
</nav>

<h2>Fila de trabalho — {{ total_fila }} registro(s)</h2>
<p>Registrado no TSE por instituto aprovado, com campo encerrado, sem pesquisa no Pulso.</p>
<table>
  <thead><tr><th>Fim do campo</th><th>Instituto</th><th>Amostra</th><th>Protocolo</th><th>Ligar a</th></tr></thead>
  <tbody>
  {% for item in fila %}
    <tr>
      <td>{{ item.data_fim }}</td>
      <td>{{ item.instituto }}</td>
      <td>{{ item.qt_entrevistado }}</td>
      <td>{{ item.protocolo }}</td>
      <td>
        <form method="post" action="{{ url_for('admin_cobertura_ligar') }}">
          <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
          <input type="hidden" name="protocolo" value="{{ item.protocolo }}">
          <input type="number" name="pesquisa_id" placeholder="id" required>
          <button type="submit">Ligar</button>
        </form>
      </td>
    </tr>
  {% else %}
    <tr><td colspan="5">Nada na fila.</td></tr>
  {% endfor %}
  </tbody>
</table>

{% if pagina > 1 %}
  <a href="{{ url_for('admin_cobertura', cargo=cargo, pagina=pagina - 1) }}">← anterior</a>
{% endif %}
{% if tem_proxima %}
  <a href="{{ url_for('admin_cobertura', cargo=cargo, pagina=pagina + 1) }}">próxima →</a>
{% endif %}

<h2>Institutos por avaliar — {{ descoberta | length }}</h2>
<p>Aparecem no registro do TSE e nunca foram avaliados. Rejeitar tira da lista para sempre.</p>
<table>
  <thead><tr><th>Razão social</th><th>Registros</th><th>Amostra média</th><th>Último campo</th><th>Decisão</th></tr></thead>
  <tbody>
  {% for inst in descoberta %}
    <tr>
      <td>{{ inst.nome_empresa }}</td>
      <td>{{ inst.registros }}</td>
      <td>{{ inst.amostra_media }}</td>
      <td>{{ inst.ultimo_campo }}</td>
      <td>
        <form method="post" action="{{ url_for('admin_cobertura_instituto') }}">
          <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
          <input type="hidden" name="cnpj" value="{{ inst.cnpj_empresa }}">
          <input type="text" name="nome" placeholder="nome de exibição" required>
          <button type="submit" name="acao" value="aprovar">Aprovar</button>
          <button type="submit" name="acao" value="rejeitar">Rejeitar</button>
        </form>
      </td>
    </tr>
  {% else %}
    <tr><td colspan="5">Nenhum instituto pendente.</td></tr>
  {% endfor %}
  </tbody>
</table>

<h2>Em campo hoje — {{ em_campo | length }}</h2>
<ul>
{% for item in em_campo %}
  <li>{{ item.nome_empresa }} · {{ item.cargo }} · {{ item.data_inicio }} a {{ item.data_fim }} · n={{ item.qt_entrevistado }}</li>
{% else %}
  <li>Nenhuma pesquisa em campo hoje.</li>
{% endfor %}
</ul>

<h2>Agendadas — {{ agendadas | length }}</h2>
<ul>
{% for item in agendadas %}
  <li>{{ item.nome_empresa }} · {{ item.cargo }} · campo de {{ item.data_inicio }} a {{ item.data_fim }} · n={{ item.qt_entrevistado }}</li>
{% else %}
  <li>Nenhuma pesquisa agendada.</li>
{% endfor %}
</ul>
{% endblock %}
```

`base.html` define `{% block content %}` (linha 54) e `admin_usuarios.html`
já usa esse padrão — o template acima está alinhado com os dois.

- [ ] **Passo 5: Rodar os testes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_rotas_cobertura.py -v`
Esperado: 5 passed

- [ ] **Passo 6: Link no painel admin**

Em `templates/admin.html`, acrescentar o link junto dos demais:

```html
<a href="{{ url_for('admin_cobertura') }}">Cobertura</a>
```

- [ ] **Passo 7: Suíte inteira**

Run: `.venv/Scripts/python.exe -m pytest -q`
Esperado: exit 0

- [ ] **Passo 8: Commit**

```bash
git add app.py templates/admin_cobertura.html templates/admin.html tests/test_rotas_cobertura.py
git commit -m "feat(cobertura): tela de fila, descoberta e campo ativo"
```

---

### Task 8: Bloco público "em campo agora"

**Arquivos:**
- Modificar: `app.py` (endpoint de leitura + cache)
- Modificar: `templates/dashboard.html`
- Teste: `tests/test_rotas_cobertura.py` (acrescentar)

**Interfaces:**
- Consome: `em_campo_hoje()` (Task 4)

- [ ] **Passo 1: Escrever o teste que falha**

Acrescentar a `tests/test_rotas_cobertura.py`:

```python
def test_api_em_campo_e_publica(cliente):
    """Sem login: é conteúdo do dashboard."""
    resposta = cliente.get('/api/em-campo')
    assert resposta.status_code == 200
    assert isinstance(resposta.get_json(), list)


def test_api_em_campo_nao_traz_agendada(cliente):
    from datetime import date, timedelta

    conn = get_conn()
    try:
        futuro_inicio = (date.today() + timedelta(days=10)).isoformat()
        futuro_fim = (date.today() + timedelta(days=13)).isoformat()
        hoje = date.today().isoformat()
        conn.execute("""INSERT INTO pesquisas_tse
            (protocolo, cargo, cnpj_empresa, nome_empresa, data_inicio,
             data_fim, data_divulgacao, qt_entrevistado, abrangencia)
            VALUES ('AGENDADA', 'presidente', '999', 'FUTURA LTDA', ?, ?, ?, 14000, 'nacional')""",
            (futuro_inicio, futuro_fim, futuro_fim))
        conn.execute("""INSERT INTO pesquisas_tse
            (protocolo, cargo, cnpj_empresa, nome_empresa, data_inicio,
             data_fim, data_divulgacao, qt_entrevistado, abrangencia)
            VALUES ('AGORA', 'presidente', '888', 'ATUAL LTDA', ?, ?, ?, 2000, 'nacional')""",
            (hoje, hoje, hoje))
        conn.commit()
    finally:
        conn.close()

    protocolos = [item['protocolo'] for item in cliente.get('/api/em-campo').get_json()]

    assert 'AGORA' in protocolos
    assert 'AGENDADA' not in protocolos, "tracking agendado não é 'em campo agora'"
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python.exe -m pytest tests/test_rotas_cobertura.py -v -k em_campo`
Esperado: FAIL com 404

- [ ] **Passo 3: Implementar o endpoint**

Em `app.py`, junto dos demais `/api/*`:

```python
@app.route('/api/em-campo')
@cache.cached(timeout=300)
def api_em_campo():
    """Pesquisas registradas no TSE que estão em campo hoje.

    Só `data_inicio <= hoje <= data_fim`. Registro com data futura é
    tracking agendado — anunciá-lo daria destaque público a instituto que
    talvez nunca seja aprovado, e um mesmo instituto encheria a lista.
    Não traz percentual: o dataset do TSE registra a pesquisa, não o
    resultado.
    """
    from database import em_campo_hoje
    return jsonify(em_campo_hoje())
```

- [ ] **Passo 4: Consumir no dashboard**

Em `templates/dashboard.html`, acrescentar a seção seguindo o padrão de
carregamento das demais (fetch + render). Deixar o bloco oculto quando a
lista vier vazia — dia sem pesquisa em campo não deve mostrar caixa vazia.

```html
<section id="em-campo" hidden>
  <h2>Em campo agora</h2>
  <p class="sub">Pesquisas registradas no TSE com coleta em andamento hoje. Resultado ainda não publicado.</p>
  <ul id="em-campo-lista"></ul>
</section>
<script>
fetch('/api/em-campo')
  .then(function (r) { return r.json(); })
  .then(function (itens) {
    if (!itens.length) { return; }
    var lista = document.getElementById('em-campo-lista');
    itens.forEach(function (item) {
      var li = document.createElement('li');
      li.textContent = item.nome_empresa + ' · ' + item.data_inicio + ' a ' +
                       item.data_fim + ' · n=' + item.qt_entrevistado;
      lista.appendChild(li);
    });
    document.getElementById('em-campo').hidden = false;
  })
  .catch(function () { /* bloco opcional: falha não pode derrubar o dashboard */ });
</script>
```

- [ ] **Passo 5: Rodar os testes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_rotas_cobertura.py -v`
Esperado: 7 passed

- [ ] **Passo 6: Commit**

```bash
git add app.py templates/dashboard.html tests/test_rotas_cobertura.py
git commit -m "feat(dashboard): bloco público de pesquisas em campo agora"
```

---

### Task 9: Documentação

**Arquivos:**
- Modificar: `templates/metodologia.html`
- Modificar: `CLAUDE.md`

- [ ] **Passo 1: Explicar a curadoria em `/metodologia`**

Acrescentar depois do parágrafo de `templates/metodologia.html:347` (o que
explica a janela de 30 dias e uma pesquisa por instituto):

```html
        <p>Só entram na média pesquisas de institutos aprovados. O registro oficial do TSE lista quase cem empresas de pesquisa em 2026, muitas de atuação local e amostra pequena; incluir todas degradaria a média em vez de melhorá-la. Pesquisas de institutos não aprovados continuam publicadas e consultáveis no site, marcadas como fora da média.</p>
```

- [ ] **Passo 2: Corrigir a frase que a curadoria torna enganosa**

`templates/metodologia.html:356` afirma hoje que "nenhum instituto recebe
peso extra por reputação ou histórico de acertos". Com a curadoria, a
reputação não muda o peso mas passa a decidir a **entrada** — deixar a frase
intacta viraria meia-verdade. Trocar o fim do parágrafo por:

```html
        <p>Amostras maiores pesam mais (menor margem de erro estatístico) e pesquisas mais antigas dentro da janela perdem peso gradualmente — uma pesquisa de hoje pesa mais que uma de 20 dias atrás. Entre os institutos aprovados, nenhum recebe peso extra por reputação ou histórico de acertos: a curadoria decide quem entra na média, não quanto cada um vale dentro dela.</p>
```

- [ ] **Passo 3: Registrar no `CLAUDE.md`**

Na seção **Domínio**, acrescentar:

```markdown
- **Curadoria** (`institutos.agregar`): só instituto com `agregar = 1` entra
  na média e nas afirmações derivadas (líder, variação, house effects,
  série do gráfico e "corrida atual"). Detalhe da pesquisa, comparativo e
  histórico por candidato **não** filtram — pesquisa de instituto não
  aprovado fica visível, marcada. Três estados: sem linha em `institutos` =
  nunca avaliado (aparece na descoberta de `/admin/cobertura`);
  `agregar = 1` = aprovado; `agregar = 0` = rejeitado. Rejeitar **precisa**
  criar a linha, senão o instituto volta à descoberta a cada sync diário.
  `scripts/migrate_curadoria.py` promove os institutos do seed por lista
  explícita — um `UPDATE` sem cláusula desfaria rejeições manuais.
  `institutos.ativo` é coluna morta (nunca lida); não usar.
- **Ligação manual** (`db/curadoria.py`): `/admin/cobertura` liga registro do
  TSE a pesquisa existente quando o casador automático recusou por
  ambiguidade ou a janela de ±3 dias não alcançou. Valida antes de escrever
  (protocolo/pesquisa já ligados, cargo divergente, inexistentes) e
  compartilha `tse.matcher.aplicar_ligacao` com o casador — a regra de não
  sobrescrever amostra realizada vale nos dois caminhos.
```

Na seção **Comandos**, nada muda.

- [ ] **Passo 4: Suíte inteira**

Run: `.venv/Scripts/python.exe -m pytest -q`
Esperado: exit 0

- [ ] **Passo 5: Commit**

```bash
git add templates/metodologia.html CLAUDE.md
git commit -m "docs: registra curadoria e ligação manual"
```

---

## Depois de todas as tarefas

1. Rodar a suíte inteira e conferir que `tests/test_agregacao.py` continua com
   os mesmos números.
2. Rodar contra o banco real em dry-run e reportar: quantos entram na fila de
   cada cargo, quantos institutos na descoberta, e se a média agregada mudou
   em relação a antes da onda. **Fazer backup de `data/pulso.db` antes.**
3. Usar superpowers:finishing-a-development-branch.

**Nunca** fazer `git push` sem decisão explícita do dono: a `main` dispara
CI → `flyctl deploy`, e esta onda muda número público.
