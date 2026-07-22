# Onda 1 — Fundação TSE e correção dos números — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sincronizar o registro oficial de pesquisas do TSE para dentro do Pulso, casá-lo com as pesquisas já coletadas, corrigir amostra/datas/duplicatas e impedir que um único instituto domine a média agregada.

**Architecture:** Novo pacote `tse/` com três módulos de responsabilidade única — `dataset.py` (baixa e parseia o CSV, sem tocar em banco), `sync.py` (upsert idempotente em `pesquisas_tse`) e `matcher.py` (liga registro ↔ pesquisa coletada, com modo dry-run). Migrações seguem o padrão idempotente já usado em `scripts/migrate_confrontos_2turno.py` e são registradas em `db/core.py::init_db`. Nenhum coletor existente é reescrito.

**Tech Stack:** Python 3.11 (produção/CI) / 3.12 (local), SQLite, `requests`, `csv` da stdlib, pytest, APScheduler.

## Global Constraints

- Código, comentários, docstrings e mensagens de commit em **português**.
- Commits no estilo conventional commits: `feat(...)`, `fix(...)`, `test(...)`, `docs(...)`, `chore(...)`.
- `TESTING=True` precisa estar setado **antes** de importar `app`/`database` — todo arquivo em `tests/` faz isso na primeira linha.
- O contrato numérico de `get_media_agregada` está fixado em `tests/test_agregacao.py`. Qualquer mudança na fórmula exige atualizar os testes **e** `templates/metodologia.html` no mesmo commit (regra do `CLAUDE.md`).
- Migrações são **idempotentes** (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE` guardado por checagem de `PRAGMA table_info`) e seguras para rodar em toda inicialização.
- O sync do TSE **não pode** chamar o Gemini. A cota mensal é o motivo de a coleta rodar só 2x/semana; o sync é gratuito e roda diariamente.
- `db/core.py` lê `database.DB_PATH` em tempo de chamada (live attribute lookup) porque os testes monkeypatcham `database.DB_PATH`. Código novo que abra conexão **deve** usar `get_conn()`/`get_db()` de `db.core`, nunca `sqlite3.connect()` direto.
- Nenhum `git push` neste plano. O trabalho fica na branch `feat/cobertura-tse`; push na `main` dispara CI → `flyctl deploy` e é decisão do dono do produto.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `scripts/migrate_pesquisas_tse.py` (criar) | Tabela `pesquisas_tse`, colunas `institutos.cnpj`/`agregar` e preenchimento do CNPJ dos institutos conhecidos |
| `scripts/migrate_dedup_pesquisas.py` (criar) | Funde pesquisas duplicadas e cria índice único |
| `tse/__init__.py` (criar) | Pacote |
| `tse/dataset.py` (criar) | Baixa o ZIP, parseia CSV, filtra por cargo/abrangência. Sem banco. |
| `tse/sync.py` (criar) | Upsert idempotente em `pesquisas_tse` |
| `tse/matcher.py` (criar) | Casamento registro ↔ pesquisa, dry-run e apply |
| `scripts/sync_tse.py` (criar) | CLI: baixa → sincroniza → casa |
| `tests/fixtures/tse_amostra.csv` (criar) | ~20 linhas reais do CSV do TSE |
| `tests/test_tse_dataset.py` (criar) | Parsing, encoding, filtros |
| `tests/test_tse_sync.py` (criar) | Upsert e idempotência |
| `tests/test_tse_matcher.py` (criar) | Casamento, ambiguidade, backfill |
| `tests/test_dedup_pesquisas.py` (criar) | Fusão de duplicatas |
| `db/core.py:50` (modificar) | Registrar as duas migrações novas em `init_db` |
| `db/pesquisas.py:253-261` (modificar) | Teto de peso na ponderação por amostra |
| `templates/metodologia.html` (modificar) | Documentar o teto de peso |
| `tests/test_agregacao.py` (modificar) | Contrato numérico do teto |
| `collectors/base.py:59-77` (modificar) | Status `"vazio"` distinto de `"ok"` |
| `app.py:152` (modificar) | Job diário de sync do TSE |

---

### Task 1: Migração — tabela `pesquisas_tse` e colunas de curadoria

**Files:**
- Create: `scripts/migrate_pesquisas_tse.py`
- Modify: `db/core.py:85-87` (registrar a migração ao lado das existentes)
- Test: `tests/test_tse_sync.py`

**Interfaces:**
- Consumes: nada.
- Produces: `aplicar_migracao(conn: sqlite3.Connection) -> None`. Cria a tabela `pesquisas_tse` e adiciona `institutos.cnpj TEXT` e `institutos.agregar INTEGER DEFAULT 0`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_tse_sync.py`:

```python
import os
os.environ['TESTING'] = 'True'

import sqlite3

from scripts.migrate_pesquisas_tse import aplicar_migracao


def _colunas(conn, tabela):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({tabela})")}


def test_migracao_cria_tabela_e_colunas():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE institutos (id INTEGER PRIMARY KEY, nome TEXT)")

    aplicar_migracao(conn)

    assert "pesquisas_tse" in {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    cols = _colunas(conn, "pesquisas_tse")
    assert {"protocolo", "cargo", "cnpj_empresa", "data_inicio",
            "data_fim", "qt_entrevistado", "abrangencia", "pesquisa_id"} <= cols
    assert {"cnpj", "agregar"} <= _colunas(conn, "institutos")
    conn.close()


def test_migracao_e_idempotente():
    """Rodar duas vezes não pode levantar (ALTER TABLE repetido é erro no SQLite)."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE institutos (id INTEGER PRIMARY KEY, nome TEXT)")

    aplicar_migracao(conn)
    aplicar_migracao(conn)  # não deve levantar

    assert {"cnpj", "agregar"} <= _colunas(conn, "institutos")
    conn.close()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python -m pytest tests/test_tse_sync.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'scripts.migrate_pesquisas_tse'`

- [ ] **Step 3: Implementar a migração**

Criar `scripts/migrate_pesquisas_tse.py`:

```python
"""
Migration: cria a tabela `pesquisas_tse` (espelho do registro oficial de
pesquisas do TSE) e as colunas de curadoria em `institutos`.

`pesquisas_tse.pesquisa_id` NULL significa "registrada no TSE, sem resultado
no Pulso" — é a fila de cobertura. `institutos.agregar` = 0 mantém o instituto
visível mas fora da média agregada (curadoria manual).

Idempotente: CREATE TABLE IF NOT EXISTS e ALTER TABLE guardado por
PRAGMA table_info. Seguro rodar em toda inicialização (mesmo padrão de
scripts/migrate_confrontos_2turno.py).

Uso: python scripts/migrate_pesquisas_tse.py
"""
import sqlite3

DB_PATH = "data/pulso.db"

_CREATE = """
CREATE TABLE IF NOT EXISTS pesquisas_tse (
    protocolo        TEXT PRIMARY KEY,
    cargo            TEXT NOT NULL,
    cnpj_empresa     TEXT NOT NULL,
    nome_empresa     TEXT NOT NULL,
    data_inicio      TEXT NOT NULL,
    data_fim         TEXT NOT NULL,
    data_divulgacao  TEXT,
    qt_entrevistado  INTEGER NOT NULL,
    abrangencia      TEXT,
    pesquisa_id      INTEGER REFERENCES pesquisas(id) ON DELETE SET NULL,
    sincronizado_em  TEXT
);
"""

_INDICES = [
    "CREATE INDEX IF NOT EXISTS idx_pesquisas_tse_cargo ON pesquisas_tse(cargo)",
    "CREATE INDEX IF NOT EXISTS idx_pesquisas_tse_cnpj ON pesquisas_tse(cnpj_empresa)",
    "CREATE INDEX IF NOT EXISTS idx_pesquisas_tse_pesquisa ON pesquisas_tse(pesquisa_id)",
]


def _tem_coluna(conn: sqlite3.Connection, tabela: str, coluna: str) -> bool:
    return any(r[1] == coluna for r in conn.execute(f"PRAGMA table_info({tabela})"))


def aplicar_migracao(conn: sqlite3.Connection) -> None:
    """Cria pesquisas_tse e as colunas de curadoria em institutos. Idempotente."""
    conn.execute(_CREATE)
    for sql in _INDICES:
        conn.execute(sql)

    if not _tem_coluna(conn, "institutos", "cnpj"):
        conn.execute("ALTER TABLE institutos ADD COLUMN cnpj TEXT")
    if not _tem_coluna(conn, "institutos", "agregar"):
        conn.execute("ALTER TABLE institutos ADD COLUMN agregar INTEGER DEFAULT 0")

    conn.commit()


def main():
    conn = sqlite3.connect(DB_PATH)
    try:
        aplicar_migracao(conn)
        print("Migração aplicada: `pesquisas_tse` + institutos.cnpj/agregar.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `python -m pytest tests/test_tse_sync.py -v`
Expected: PASS (2 testes)

- [ ] **Step 5: Escrever o teste do preenchimento de CNPJ**

Sem CNPJ preenchido o casador da Task 4 não casa **nada** — a coluna sozinha é
inútil. Adicionar a `tests/test_tse_sync.py`:

```python
from scripts.migrate_pesquisas_tse import CNPJ_POR_INSTITUTO, popular_cnpjs


def test_popular_cnpjs_preenche_institutos_conhecidos():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE institutos (id INTEGER PRIMARY KEY, nome TEXT)")
    conn.execute("INSERT INTO institutos (id, nome) VALUES (1, 'Datafolha')")
    conn.execute("INSERT INTO institutos (id, nome) VALUES (3, 'Quaest')")
    aplicar_migracao(conn)

    popular_cnpjs(conn)

    linhas = {r["nome"]: r["cnpj"] for r in conn.execute("SELECT nome, cnpj FROM institutos")}
    assert linhas["Datafolha"] == "07630546000175"
    assert linhas["Quaest"] == "22445600000104"
    conn.close()


def test_popular_cnpjs_nao_sobrescreve_valor_existente():
    """Correção manual de CNPJ não pode ser desfeita pela migração."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE institutos (id INTEGER PRIMARY KEY, nome TEXT)")
    conn.execute("INSERT INTO institutos (id, nome) VALUES (1, 'Datafolha')")
    aplicar_migracao(conn)
    conn.execute("UPDATE institutos SET cnpj = '99999999000199' WHERE nome = 'Datafolha'")
    conn.commit()

    popular_cnpjs(conn)

    cnpj = conn.execute("SELECT cnpj FROM institutos WHERE nome = 'Datafolha'").fetchone()["cnpj"]
    assert cnpj == "99999999000199"
    conn.close()


def test_todo_cnpj_do_mapa_tem_14_digitos():
    for nome, cnpj in CNPJ_POR_INSTITUTO.items():
        assert cnpj.isdigit() and len(cnpj) == 14, f"CNPJ inválido para {nome}: {cnpj}"
```

- [ ] **Step 6: Rodar o teste e confirmar que falha**

Run: `python -m pytest tests/test_tse_sync.py -v -k cnpj`
Expected: FAIL com `ImportError: cannot import name 'CNPJ_POR_INSTITUTO'`

- [ ] **Step 7: Implementar o preenchimento de CNPJ**

Acrescentar a `scripts/migrate_pesquisas_tse.py`, antes de `aplicar_migracao`:

```python
# CNPJ de cada instituto, conferido contra o dataset do TSE de 2026-07-22
# (NR_CNPJ_EMPRESA + NM_EMPRESA). É a chave de casamento entre o registro
# oficial e a tabela `institutos` — nome de instituto varia demais entre
# fontes para servir de chave.
#
# Ausentes de propósito:
#   - "Futura Inteligência" e "Vox Populi": sem nenhum registro em 2026.
#   - "Meio/Ideia": o TSE tem "BOAS IDEIAS INTELIGENCIA EM PESQUISA", que é
#     outro instituto — casar os dois produziria dado errado.
# Homônimos resolvidos:
#   - Nexus: 11077560000160 ("NEXUS PESQUISA E INTELIGENCIA DE DADOS"), não
#     48844295000109 ("NEXUS CONSULTORIA E PESQUISAS").
#   - Verita: 00654576000172 ("INSTITUTO VERITA"), não 27844225000180
#     ("VERITAS PLANEJAMENTO E ASSESSORIA").
CNPJ_POR_INSTITUTO = {
    "Datafolha": "07630546000175",
    "Quaest": "22445600000104",
    "Atlas": "19259002000128",
    "Paraná": "81908345000140",
    "Real Time": "22345021000181",
    "Nexus/BTG Pactual": "11077560000160",
    "Verita": "00654576000172",
    "PoderData": "29550908000150",
    "Ibope/IPEC": "40735589000190",
    "Instituto Gerp": "05270800000146",
}


def popular_cnpjs(conn: sqlite3.Connection) -> int:
    """Preenche institutos.cnpj a partir do mapa conferido. Idempotente.

    Só escreve onde o CNPJ está ausente — uma correção manual feita no admin
    nunca é sobrescrita pela migração.
    """
    preenchidos = 0
    for nome, cnpj in CNPJ_POR_INSTITUTO.items():
        cursor = conn.execute(
            "UPDATE institutos SET cnpj = ? WHERE nome = ? AND (cnpj IS NULL OR cnpj = '')",
            (cnpj, nome),
        )
        preenchidos += cursor.rowcount
    conn.commit()
    return preenchidos
```

E chamar `popular_cnpjs(conn)` no fim de `aplicar_migracao`, depois do `conn.commit()` existente:

```python
    popular_cnpjs(conn)
```

Atualizar também a mensagem do `main()`:

```python
        aplicar_migracao(conn)
        print("Migração aplicada: `pesquisas_tse` + institutos.cnpj/agregar.")
```

- [ ] **Step 8: Rodar o teste e confirmar que passa**

Run: `python -m pytest tests/test_tse_sync.py -v`
Expected: PASS (5 testes)

- [ ] **Step 9: Registrar a migração no init_db**

Em `db/core.py`, logo após o bloco de `_aplicar_migracao_confrontos` (linha ~87), inserir:

```python
    # Migration idempotente: tabela pesquisas_tse + curadoria em institutos
    from scripts.migrate_pesquisas_tse import aplicar_migracao as _aplicar_migracao_tse
    _aplicar_migracao_tse(conn)
```

- [ ] **Step 10: Rodar a suíte inteira**

Run: `python -m pytest -q`
Expected: todos passando. Se algo quebrar aqui, é `init_db` — investigar antes de seguir.

- [ ] **Step 11: Conferir o preenchimento no banco local**

```bash
python scripts/migrate_pesquisas_tse.py && python -c "
import sqlite3
c = sqlite3.connect('data/pulso.db'); c.row_factory = sqlite3.Row
for r in c.execute('SELECT nome, cnpj FROM institutos ORDER BY id'):
    print(f\"{r['nome']:22} {r['cnpj'] or '(sem CNPJ)'}\")
"
```

Expected: 10 dos 14 institutos com CNPJ. Os 4 sem CNPJ (Futura, Vox Populi,
Meio/Ideia, Genial/Quaest) não casarão até alguém preencher manualmente — é o
comportamento correto, não um bug.

- [ ] **Step 12: Commit**

```bash
git add scripts/migrate_pesquisas_tse.py tests/test_tse_sync.py db/core.py
git commit -m "feat(tse): tabela pesquisas_tse, curadoria e CNPJ dos institutos"
```

---

### Task 2: Parsing do CSV do TSE

**Files:**
- Create: `tse/__init__.py`, `tse/dataset.py`
- Create: `tests/fixtures/tse_amostra.csv`
- Test: `tests/test_tse_dataset.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `RegistroTSE` — `dict` com chaves `protocolo, cargo, cnpj_empresa, nome_empresa, data_inicio, data_fim, data_divulgacao, qt_entrevistado, abrangencia`.
  - `parsear_csv(conteudo: bytes, cargo: str) -> list[dict]` — `cargo` é `'presidente'` ou `'governador_rj'`.
  - `detectar_abrangencia(metodologia: str, dado_municipio: str) -> str` — `'nacional' | 'estadual' | 'municipal'`.
  - `baixar_zip(url: str = URL_TSE) -> bytes`.
  - `extrair_csv(zip_bytes: bytes, nome: str) -> bytes`.

- [ ] **Step 1: Gerar a fixture a partir do arquivo real**

O CSV completo tem 5 MB — não commitar. Gerar uma fatia com os casos que importam:

```bash
python - <<'EOF'
import csv, io, urllib.request, zipfile, os

URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/pesquisa_eleitoral/pesquisa_eleitoral_2026.zip"
z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(URL).read()))

def ler(nome):
    txt = z.read(nome).decode("latin-1")
    return list(csv.DictReader(io.StringIO(txt), delimiter=";"))

br = ler("pesquisa_eleitoral_2026_BRASIL.csv")
rj = ler("pesquisa_eleitoral_2026_RJ.csv")

pres = [r for r in br if "Presidente" in r["DS_CARGO"] and r["SG_UE"] == "BR"][:8]
nao_pres = [r for r in br if "Presidente" not in r["DS_CARGO"]][:3]
gov = [r for r in rj if "Governador" in r["DS_CARGO"]][:8]

sel = pres + nao_pres + gov
os.makedirs("tests/fixtures", exist_ok=True)
with open("tests/fixtures/tse_amostra.csv", "w", encoding="latin-1", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(br[0].keys()), delimiter=";")
    w.writeheader()
    w.writerows(sel)
print(f"fixture: {len(sel)} linhas ({len(pres)} pres, {len(nao_pres)} nao-pres, {len(gov)} gov)")
EOF
```

Conferir que a fixture contém pelo menos uma linha com `NM_EMPRESA_FANTASIA` = `#NULO#` e uma de abrangência municipal. Se não contiver, ajustar as fatias acima até conter — os testes dos Steps 3 e 5 dependem disso.

- [ ] **Step 2: Escrever o teste que falha**

Criar `tests/test_tse_dataset.py`:

```python
import os
os.environ['TESTING'] = 'True'

from pathlib import Path

from tse.dataset import parsear_csv, detectar_abrangencia

FIXTURE = Path(__file__).parent / "fixtures" / "tse_amostra.csv"


def _conteudo():
    return FIXTURE.read_bytes()


def test_parseia_presidente_e_ignora_outros_cargos():
    regs = parsear_csv(_conteudo(), cargo="presidente")

    assert regs, "fixture deve conter pesquisas de presidente"
    for r in regs:
        assert r["cargo"] == "presidente"
        assert r["protocolo"].startswith("BR")
        assert r["qt_entrevistado"] > 0


def test_datas_sao_normalizadas_para_iso_curto():
    """O CSV traz '2026-03-31 00:00:00'; queremos '2026-03-31'."""
    regs = parsear_csv(_conteudo(), cargo="presidente")

    for r in regs:
        assert len(r["data_inicio"]) == 10
        assert len(r["data_fim"]) == 10
        assert r["data_inicio"][4] == "-"


def test_sentinela_nulo_vira_none():
    """NM_EMPRESA_FANTASIA == '#NULO#' não pode virar a string literal."""
    regs = parsear_csv(_conteudo(), cargo="governador_rj")

    for r in regs:
        assert r["nome_empresa"] != "#NULO#"
        assert r["nome_empresa"], "nome_empresa nunca pode ser vazio"


def test_governador_rj_filtra_por_cargo():
    regs = parsear_csv(_conteudo(), cargo="governador_rj")

    assert regs
    for r in regs:
        assert r["cargo"] == "governador_rj"
        assert r["protocolo"].startswith("RJ")


def test_detectar_abrangencia_municipal():
    metodologia = "Pesquisa realizada no município de Angra dos Reis, Estado do Rio de Janeiro."
    assert detectar_abrangencia(metodologia, "") == "municipal"


def test_detectar_abrangencia_estadual_nao_confunde_capital():
    """'município do Rio de Janeiro' é a capital, mas 'Estado do Rio' é estadual."""
    metodologia = "Amostra representativa do eleitorado do Estado do Rio de Janeiro."
    assert detectar_abrangencia(metodologia, "") == "estadual"
```

- [ ] **Step 3: Rodar o teste e confirmar que falha**

Run: `python -m pytest tests/test_tse_dataset.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'tse'`

- [ ] **Step 4: Implementar o parser**

Criar `tse/__init__.py` vazio e `tse/dataset.py`:

```python
"""Download e parsing do dataset de pesquisas eleitorais do TSE.

Este módulo não toca no banco — recebe bytes, devolve dicts. Isso mantém o
parsing testável com fixture, sem rede e sem SQLite.

Formato do arquivo (verificado em 2026-07-22): ZIP com um CSV por UF mais
BRASIL.csv, encoding latin-1, delimitador ';', sentinela '#NULO#' para campo
vazio, datas em 'YYYY-MM-DD HH:MM:SS'. O arquivo é regerado diariamente.
"""
import csv
import io
import re
import zipfile

import requests

URL_TSE = (
    "https://cdn.tse.jus.br/estatistica/sead/odsele/"
    "pesquisa_eleitoral/pesquisa_eleitoral_2026.zip"
)

ARQUIVO_PRESIDENTE = "pesquisa_eleitoral_2026_BRASIL.csv"
ARQUIVO_GOVERNADOR_RJ = "pesquisa_eleitoral_2026_RJ.csv"

_NULO = "#NULO#"

# "município de X" onde X não é a capital indica pesquisa municipal. A capital
# ("município do Rio de Janeiro") é ambígua e tratada como estadual, porque o
# custo de excluir uma pesquisa estadual válida é maior que o de incluir uma
# municipal da capital — que a curadoria manual ainda filtra.
_RE_MUNICIPIO = re.compile(r"munic[íi]pio (?:de|do|da) ([a-zà-ÿ\s]{3,40})", re.IGNORECASE)


def baixar_zip(url: str = URL_TSE) -> bytes:
    """Baixa o ZIP do TSE. Levanta requests.HTTPError se a CDN falhar."""
    resposta = requests.get(url, timeout=120)
    resposta.raise_for_status()
    return resposta.content


def extrair_csv(zip_bytes: bytes, nome: str) -> bytes:
    """Extrai um CSV de dentro do ZIP pelo nome."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        return z.read(nome)


def _limpar(valor: str | None) -> str:
    """Normaliza o sentinela '#NULO#' e espaços para string vazia."""
    if valor is None:
        return ""
    valor = valor.strip()
    return "" if valor == _NULO else valor


def _data_curta(valor: str) -> str:
    """'2026-03-31 00:00:00' -> '2026-03-31'."""
    return _limpar(valor)[:10]


def detectar_abrangencia(metodologia: str, dado_municipio: str) -> str:
    """Classifica a abrangência a partir do texto livre do registro.

    Heurística deliberadamente conservadora: só marca 'municipal' quando
    encontra menção explícita a um município que não seja a capital. Falso
    negativo (municipal classificada como estadual) apenas mantém a pesquisa na
    fila para a curadoria decidir; falso positivo a esconderia sem aviso.
    """
    texto = f"{metodologia} {dado_municipio}".lower()
    achado = _RE_MUNICIPIO.search(texto)
    if achado:
        municipio = achado.group(1).strip()
        if not municipio.startswith("rio de janeiro"):
            return "municipal"
    return "estadual"


def parsear_csv(conteudo: bytes, cargo: str) -> list[dict]:
    """Parseia o CSV do TSE e devolve os registros do cargo pedido.

    cargo: 'presidente' (exige SG_UE == 'BR') ou 'governador_rj'.
    """
    if cargo == "presidente":
        termo, exige_nacional = "Presidente", True
    elif cargo == "governador_rj":
        termo, exige_nacional = "Governador", False
    else:
        raise ValueError(f"cargo não suportado: {cargo!r}")

    texto = conteudo.decode("latin-1")
    leitor = csv.DictReader(io.StringIO(texto), delimiter=";")

    registros = []
    for linha in leitor:
        if termo not in linha.get("DS_CARGO", ""):
            continue
        if exige_nacional and linha.get("SG_UE") != "BR":
            continue

        quantidade = _limpar(linha.get("QT_ENTREVISTADO"))
        if not quantidade.isdigit() or int(quantidade) <= 0:
            continue

        fantasia = _limpar(linha.get("NM_EMPRESA_FANTASIA"))
        razao = _limpar(linha.get("NM_EMPRESA"))

        registros.append({
            "protocolo": _limpar(linha.get("NR_PROTOCOLO_REGISTRO")),
            "cargo": cargo,
            "cnpj_empresa": _limpar(linha.get("NR_CNPJ_EMPRESA")),
            "nome_empresa": fantasia or razao,
            "data_inicio": _data_curta(linha.get("DT_INICIO_PESQUISA", "")),
            "data_fim": _data_curta(linha.get("DT_FIM_PESQUISA", "")),
            "data_divulgacao": _data_curta(linha.get("DT_DIVULGACAO", "")) or None,
            "qt_entrevistado": int(quantidade),
            "abrangencia": "nacional" if cargo == "presidente" else detectar_abrangencia(
                _limpar(linha.get("DS_METODOLOGIA_PESQUISA")),
                _limpar(linha.get("DS_DADO_MUNICIPIO")),
            ),
        })

    return registros
```

- [ ] **Step 5: Rodar o teste e confirmar que passa**

Run: `python -m pytest tests/test_tse_dataset.py -v`
Expected: PASS (6 testes)

- [ ] **Step 6: Commit**

```bash
git add tse/ tests/test_tse_dataset.py tests/fixtures/tse_amostra.csv
git commit -m "feat(tse): parser do dataset de pesquisas eleitorais do TSE"
```

---

### Task 3: Sincronização idempotente em `pesquisas_tse`

**Files:**
- Create: `tse/sync.py`
- Test: `tests/test_tse_sync.py` (adicionar aos testes da Task 1)

**Interfaces:**
- Consumes: `parsear_csv` (Task 2), `aplicar_migracao` (Task 1).
- Produces: `sincronizar(conn: sqlite3.Connection, registros: list[dict]) -> dict` devolvendo `{"inseridos": int, "atualizados": int}`.

- [ ] **Step 1: Escrever o teste que falha**

Adicionar ao fim de `tests/test_tse_sync.py`:

```python
from tse.sync import sincronizar


def _conn_migrada():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE institutos (id INTEGER PRIMARY KEY, nome TEXT)")
    conn.execute("CREATE TABLE pesquisas (id INTEGER PRIMARY KEY)")
    aplicar_migracao(conn)
    return conn


def _registro(protocolo="BR000012026", **kwargs):
    base = {
        "protocolo": protocolo,
        "cargo": "presidente",
        "cnpj_empresa": "11111111000111",
        "nome_empresa": "INSTITUTO TESTE",
        "data_inicio": "2026-07-01",
        "data_fim": "2026-07-03",
        "data_divulgacao": "2026-07-05",
        "qt_entrevistado": 2000,
        "abrangencia": "nacional",
    }
    base.update(kwargs)
    return base


def test_sincronizar_insere_registros():
    conn = _conn_migrada()

    resultado = sincronizar(conn, [_registro(), _registro("BR000022026")])

    assert resultado == {"inseridos": 2, "atualizados": 0}
    assert conn.execute("SELECT COUNT(*) FROM pesquisas_tse").fetchone()[0] == 2
    conn.close()


def test_sincronizar_e_idempotente():
    """Rodar o mesmo lote duas vezes não duplica nem conta como inserção."""
    conn = _conn_migrada()

    sincronizar(conn, [_registro()])
    resultado = sincronizar(conn, [_registro()])

    assert resultado == {"inseridos": 0, "atualizados": 1}
    assert conn.execute("SELECT COUNT(*) FROM pesquisas_tse").fetchone()[0] == 1
    conn.close()


def test_sincronizar_atualiza_campo_corrigido_pelo_tse():
    """O TSE pode corrigir um registro; o upsert reflete a correção."""
    conn = _conn_migrada()
    sincronizar(conn, [_registro(qt_entrevistado=2000)])

    sincronizar(conn, [_registro(qt_entrevistado=2500)])

    linha = conn.execute(
        "SELECT qt_entrevistado FROM pesquisas_tse WHERE protocolo = ?",
        ("BR000012026",),
    ).fetchone()
    assert linha["qt_entrevistado"] == 2500
    conn.close()


def test_sincronizar_preserva_o_casamento_ja_feito():
    """Re-sincronizar não pode apagar o pesquisa_id ligado pelo matcher."""
    conn = _conn_migrada()
    conn.execute("INSERT INTO pesquisas (id) VALUES (7)")
    sincronizar(conn, [_registro()])
    conn.execute("UPDATE pesquisas_tse SET pesquisa_id = 7 WHERE protocolo = ?",
                 ("BR000012026",))
    conn.commit()

    sincronizar(conn, [_registro(qt_entrevistado=2500)])

    linha = conn.execute(
        "SELECT pesquisa_id FROM pesquisas_tse WHERE protocolo = ?",
        ("BR000012026",),
    ).fetchone()
    assert linha["pesquisa_id"] == 7, "o upsert não pode zerar o casamento"
    conn.close()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python -m pytest tests/test_tse_sync.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'tse.sync'`

- [ ] **Step 3: Implementar o sync**

Criar `tse/sync.py`:

```python
"""Upsert dos registros do TSE em `pesquisas_tse`.

O upsert é por `protocolo` (chave real do TSE) e **preserva `pesquisa_id`** —
o casamento feito pelo matcher não pode ser desfeito por uma re-sincronização
diária. Por isso o ON CONFLICT lista as colunas uma a uma em vez de usar
INSERT OR REPLACE (que apagaria a linha inteira e com ela o casamento).
"""
import logging
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)

_UPSERT = """
INSERT INTO pesquisas_tse
    (protocolo, cargo, cnpj_empresa, nome_empresa, data_inicio, data_fim,
     data_divulgacao, qt_entrevistado, abrangencia, sincronizado_em)
VALUES (:protocolo, :cargo, :cnpj_empresa, :nome_empresa, :data_inicio, :data_fim,
        :data_divulgacao, :qt_entrevistado, :abrangencia, :sincronizado_em)
ON CONFLICT(protocolo) DO UPDATE SET
    cargo            = excluded.cargo,
    cnpj_empresa     = excluded.cnpj_empresa,
    nome_empresa     = excluded.nome_empresa,
    data_inicio      = excluded.data_inicio,
    data_fim         = excluded.data_fim,
    data_divulgacao  = excluded.data_divulgacao,
    qt_entrevistado  = excluded.qt_entrevistado,
    abrangencia      = excluded.abrangencia,
    sincronizado_em  = excluded.sincronizado_em
"""


def sincronizar(conn: sqlite3.Connection, registros: list[dict]) -> dict:
    """Faz upsert dos registros e devolve {"inseridos": int, "atualizados": int}."""
    if not registros:
        return {"inseridos": 0, "atualizados": 0}

    existentes = {
        r[0] for r in conn.execute("SELECT protocolo FROM pesquisas_tse")
    }
    agora = datetime.now().isoformat(timespec="seconds")

    inseridos = 0
    atualizados = 0
    for registro in registros:
        if not registro.get("protocolo"):
            logger.warning("Registro do TSE sem protocolo, ignorado: %s",
                           registro.get("nome_empresa"))
            continue
        conn.execute(_UPSERT, {**registro, "sincronizado_em": agora})
        if registro["protocolo"] in existentes:
            atualizados += 1
        else:
            inseridos += 1

    conn.commit()
    logger.info("Sync TSE: %d inseridos, %d atualizados.", inseridos, atualizados)
    return {"inseridos": inseridos, "atualizados": atualizados}
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `python -m pytest tests/test_tse_sync.py -v`
Expected: PASS (6 testes — 2 da Task 1 + 4 novos)

- [ ] **Step 5: Commit**

```bash
git add tse/sync.py tests/test_tse_sync.py
git commit -m "feat(tse): upsert idempotente de registros preservando casamento"
```

---

### Task 4: Casador registro ↔ pesquisa coletada

**Files:**
- Create: `tse/matcher.py`
- Test: `tests/test_tse_matcher.py`

**Interfaces:**
- Consumes: `pesquisas_tse` e `institutos.cnpj` **já preenchido** por `popular_cnpjs` (Task 1, Step 7). Sem CNPJ o casamento devolve zero pares — se os testes desta task passarem mas o Step 8 da Task 8 casar nada, conferir `institutos.cnpj` antes de suspeitar da janela de datas.
- Produces: `casar(conn, cargo: str, dry_run: bool = True) -> dict` devolvendo `{"casados": [...], "ambiguos": [...], "sem_par": int}`. Cada item de `casados` é `{"protocolo": str, "pesquisa_id": int, "amostra_tse": int, "amostra_atual": int, "data_tse": str, "data_atual": str}`.

**Regra de casamento:** mesmo instituto (via `institutos.cnpj`) **e** `pesquisas.data_pesquisa` dentro de `[data_inicio - 3 dias, data_divulgacao + 3 dias]` **e** mesmo cargo. Se mais de um registro do TSE casar com a mesma pesquisa, ou mais de uma pesquisa com o mesmo registro, o par vai para `ambiguos` e **não** é gravado. `dry_run=True` é o padrão: calcula e devolve, sem escrever.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_tse_matcher.py`:

```python
import os
os.environ['TESTING'] = 'True'

import sqlite3

from scripts.migrate_pesquisas_tse import aplicar_migracao
from tse.matcher import casar


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE institutos (
        id INTEGER PRIMARY KEY, nome TEXT)""")
    conn.execute("""CREATE TABLE pesquisas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, instituto_id INTEGER, cargo TEXT,
        data_pesquisa TEXT, data_publicacao TEXT, tamanho_amostra INTEGER,
        margem_erro REAL, registro_tse TEXT UNIQUE, fonte_url TEXT)""")
    aplicar_migracao(conn)
    conn.execute("INSERT INTO institutos (id, nome, cnpj) VALUES (1, 'Quaest', '11111111000111')")
    conn.commit()
    return conn


def _tse(conn, protocolo, inicio, fim, divulgacao, amostra=1200, cnpj="11111111000111"):
    conn.execute("""INSERT INTO pesquisas_tse
        (protocolo, cargo, cnpj_empresa, nome_empresa, data_inicio, data_fim,
         data_divulgacao, qt_entrevistado, abrangencia)
        VALUES (?, 'presidente', ?, 'QUAEST', ?, ?, ?, ?, 'nacional')""",
        (protocolo, cnpj, inicio, fim, divulgacao, amostra))
    conn.commit()


def _pesquisa(conn, data, amostra=0, registro="GEN-x"):
    cur = conn.execute("""INSERT INTO pesquisas
        (instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra,
         margem_erro, registro_tse, fonte_url)
        VALUES (1, 'presidente', ?, ?, ?, 2.0, ?, 'http://x')""",
        (data, data, amostra, registro))
    conn.commit()
    return cur.lastrowid


def test_casa_pesquisa_dentro_da_janela():
    conn = _conn()
    _tse(conn, "BR000012026", "2026-07-01", "2026-07-03", "2026-07-05")
    pid = _pesquisa(conn, "2026-07-05", amostra=0)

    resultado = casar(conn, cargo="presidente")

    assert len(resultado["casados"]) == 1
    par = resultado["casados"][0]
    assert par["protocolo"] == "BR000012026"
    assert par["pesquisa_id"] == pid
    assert par["amostra_tse"] == 1200
    conn.close()


def test_dry_run_nao_grava():
    conn = _conn()
    _tse(conn, "BR000012026", "2026-07-01", "2026-07-03", "2026-07-05")
    _pesquisa(conn, "2026-07-05")

    casar(conn, cargo="presidente", dry_run=True)

    ligado = conn.execute(
        "SELECT pesquisa_id FROM pesquisas_tse WHERE protocolo = ?",
        ("BR000012026",)).fetchone()["pesquisa_id"]
    assert ligado is None, "dry_run não pode escrever no banco"
    conn.close()


def test_apply_grava_e_faz_backfill():
    conn = _conn()
    _tse(conn, "BR000012026", "2026-07-01", "2026-07-03", "2026-07-05", amostra=2004)
    pid = _pesquisa(conn, "2026-07-05", amostra=0)

    casar(conn, cargo="presidente", dry_run=False)

    tse = conn.execute("SELECT pesquisa_id FROM pesquisas_tse WHERE protocolo = ?",
                       ("BR000012026",)).fetchone()
    pesquisa = conn.execute(
        "SELECT tamanho_amostra, data_pesquisa, registro_tse FROM pesquisas WHERE id = ?",
        (pid,)).fetchone()

    assert tse["pesquisa_id"] == pid
    assert pesquisa["tamanho_amostra"] == 2004, "amostra deve vir do TSE"
    assert pesquisa["data_pesquisa"] == "2026-07-03", "data de campo = DT_FIM_PESQUISA"
    assert pesquisa["registro_tse"] == "BR000012026", "protocolo real substitui a chave GEN-"
    conn.close()


def test_ambiguidade_nao_casa():
    """Dois registros do mesmo instituto na mesma janela: não adivinhar."""
    conn = _conn()
    _tse(conn, "BR000012026", "2026-07-01", "2026-07-03", "2026-07-05")
    _tse(conn, "BR000022026", "2026-07-02", "2026-07-04", "2026-07-05")
    _pesquisa(conn, "2026-07-05")

    resultado = casar(conn, cargo="presidente", dry_run=False)

    assert resultado["casados"] == []
    assert len(resultado["ambiguos"]) >= 1
    restantes = conn.execute(
        "SELECT COUNT(*) FROM pesquisas_tse WHERE pesquisa_id IS NOT NULL").fetchone()[0]
    assert restantes == 0, "par ambíguo nunca pode ser gravado"
    conn.close()


def test_fora_da_janela_nao_casa():
    conn = _conn()
    _tse(conn, "BR000012026", "2026-07-01", "2026-07-03", "2026-07-05")
    _pesquisa(conn, "2026-06-01")

    resultado = casar(conn, cargo="presidente", dry_run=False)

    assert resultado["casados"] == []
    assert resultado["sem_par"] == 1
    conn.close()


def test_instituto_diferente_nao_casa():
    conn = _conn()
    _tse(conn, "BR000012026", "2026-07-01", "2026-07-03", "2026-07-05",
         cnpj="99999999000199")
    _pesquisa(conn, "2026-07-05")

    resultado = casar(conn, cargo="presidente", dry_run=False)

    assert resultado["casados"] == []
    conn.close()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python -m pytest tests/test_tse_matcher.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'tse.matcher'`

- [ ] **Step 3: Implementar o casador**

Criar `tse/matcher.py`:

```python
"""Casamento entre registro oficial do TSE e pesquisa já coletada.

Regra: mesmo instituto (via institutos.cnpj), mesmo cargo, e data_pesquisa da
pesquisa dentro de [data_inicio - 3 dias, data_divulgacao + 3 dias] do registro.

A folga de 3 dias absorve o fato de que hoje `data_pesquisa` é preenchida com a
data de publicação da matéria (bug que este casamento vem justamente corrigir).

**Ambiguidade nunca é resolvida por chute.** Se um registro casa com várias
pesquisas, ou várias pesquisas casam com o mesmo registro, o par é reportado em
`ambiguos` e não gravado: um falso negativo deixa um item a mais na fila de
cobertura, enquanto um falso positivo envenena a série histórica em silêncio.
"""
import logging
import sqlite3
from datetime import date, timedelta

logger = logging.getLogger(__name__)

_FOLGA_DIAS = 3


def _mais(data_iso: str, dias: int) -> str:
    return (date.fromisoformat(data_iso) + timedelta(days=dias)).isoformat()


def casar(conn: sqlite3.Connection, cargo: str, dry_run: bool = True) -> dict:
    """Casa registros do TSE com pesquisas coletadas.

    dry_run=True (padrão) apenas calcula e devolve o relatório, sem escrever.
    Devolve {"casados": [...], "ambiguos": [...], "sem_par": int}.
    """
    registros = conn.execute("""
        SELECT protocolo, cnpj_empresa, data_inicio, data_fim, data_divulgacao,
               qt_entrevistado
        FROM pesquisas_tse
        WHERE cargo = ? AND pesquisa_id IS NULL
        ORDER BY data_fim DESC
    """, (cargo,)).fetchall()

    candidatos_por_protocolo: dict[str, list] = {}
    protocolos_por_pesquisa: dict[int, list[str]] = {}

    for registro in registros:
        limite_inicio = _mais(registro["data_inicio"], -_FOLGA_DIAS)
        limite_fim = _mais(
            registro["data_divulgacao"] or registro["data_fim"], _FOLGA_DIAS
        )

        pesquisas = conn.execute("""
            SELECT p.id, p.tamanho_amostra, p.data_pesquisa
            FROM pesquisas p
            JOIN institutos i ON i.id = p.instituto_id
            WHERE p.cargo = ? AND i.cnpj = ?
              AND p.data_pesquisa BETWEEN ? AND ?
        """, (cargo, registro["cnpj_empresa"], limite_inicio, limite_fim)).fetchall()

        candidatos_por_protocolo[registro["protocolo"]] = pesquisas
        for pesquisa in pesquisas:
            protocolos_por_pesquisa.setdefault(pesquisa["id"], []).append(
                registro["protocolo"]
            )

    casados = []
    ambiguos = []
    sem_par = 0

    for registro in registros:
        protocolo = registro["protocolo"]
        pesquisas = candidatos_por_protocolo[protocolo]

        if not pesquisas:
            sem_par += 1
            continue

        if len(pesquisas) > 1:
            ambiguos.append({
                "protocolo": protocolo,
                "motivo": "registro casa com mais de uma pesquisa",
                "pesquisa_ids": [p["id"] for p in pesquisas],
            })
            continue

        pesquisa = pesquisas[0]
        if len(protocolos_por_pesquisa[pesquisa["id"]]) > 1:
            ambiguos.append({
                "protocolo": protocolo,
                "motivo": "pesquisa casa com mais de um registro",
                "pesquisa_ids": [pesquisa["id"]],
            })
            continue

        casados.append({
            "protocolo": protocolo,
            "pesquisa_id": pesquisa["id"],
            "amostra_tse": registro["qt_entrevistado"],
            "amostra_atual": pesquisa["tamanho_amostra"],
            "data_tse": registro["data_fim"],
            "data_atual": pesquisa["data_pesquisa"],
        })

    if not dry_run:
        for par in casados:
            conn.execute(
                "UPDATE pesquisas_tse SET pesquisa_id = ? WHERE protocolo = ?",
                (par["pesquisa_id"], par["protocolo"]),
            )
            conn.execute("""
                UPDATE pesquisas
                SET tamanho_amostra = ?, data_pesquisa = ?, registro_tse = ?
                WHERE id = ?
            """, (par["amostra_tse"], par["data_tse"], par["protocolo"],
                  par["pesquisa_id"]))
        conn.commit()
        logger.info("Casamento aplicado: %d pares, %d ambíguos, %d sem par.",
                    len(casados), len(ambiguos), sem_par)

    return {"casados": casados, "ambiguos": ambiguos, "sem_par": sem_par}
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `python -m pytest tests/test_tse_matcher.py -v`
Expected: PASS (6 testes)

- [ ] **Step 5: Commit**

```bash
git add tse/matcher.py tests/test_tse_matcher.py
git commit -m "feat(tse): casador registro-pesquisa com dry-run e recusa de ambiguidade"
```

---

### Task 5: Migração de deduplicação

**Files:**
- Create: `scripts/migrate_dedup_pesquisas.py`
- Modify: `db/core.py` (registrar após a migração da Task 1)
- Test: `tests/test_dedup_pesquisas.py`

**Interfaces:**
- Consumes: nada.
- Produces: `deduplicar(conn) -> dict` devolvendo `{"fundidas": int, "intencoes_movidas": int}`.

**Regra de fusão:** pesquisas com mesmo `instituto_id`, `cargo`, `data_pesquisa` e `tamanho_amostra` são a mesma pesquisa. Sobrevive a que tem **mais intenções** (a extração mais completa); empate desempata pelo maior `id`. As intenções exclusivas da perdedora migram para a sobrevivente; a perdedora é apagada.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_dedup_pesquisas.py`:

```python
import os
os.environ['TESTING'] = 'True'

import sqlite3

from scripts.migrate_dedup_pesquisas import deduplicar


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE pesquisas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, instituto_id INTEGER, cargo TEXT,
        data_pesquisa TEXT, data_publicacao TEXT, tamanho_amostra INTEGER,
        margem_erro REAL, registro_tse TEXT UNIQUE, fonte_url TEXT)""")
    conn.execute("""CREATE TABLE intencoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, pesquisa_id INTEGER,
        candidato TEXT, partido TEXT, percentual REAL, tipo TEXT)""")
    return conn


def _pesquisa(conn, registro, candidatos, amostra=2000, data="2026-07-20"):
    cur = conn.execute("""INSERT INTO pesquisas
        (instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra,
         margem_erro, registro_tse, fonte_url)
        VALUES (7, 'presidente', ?, ?, ?, 2.0, ?, ?)""",
        (data, data, amostra, registro, f"http://x/{registro}"))
    pid = cur.lastrowid
    for nome, pct in candidatos.items():
        conn.execute("""INSERT INTO intencoes (pesquisa_id, candidato, percentual, tipo)
                        VALUES (?, ?, ?, 'estimulada')""", (pid, nome, pct))
    conn.commit()
    return pid


def test_funde_duplicata_truncada_preservando_a_completa():
    """Reproduz os ids 27/28 reais: mesma pesquisa, uma extração truncada."""
    conn = _conn()
    truncada = _pesquisa(conn, "GEN-a", {"Lula": 40.0, "Flávio Bolsonaro": 33.0})
    completa = _pesquisa(conn, "GEN-b", {
        "Lula": 40.0, "Flávio Bolsonaro": 33.0, "Renan Santos": 9.0,
        "Ronaldo Caiado": 7.0, "Romeu Zema": 2.0, "Augusto Cury": 1.0})

    resultado = deduplicar(conn)

    assert resultado["fundidas"] == 1
    restantes = [r["id"] for r in conn.execute("SELECT id FROM pesquisas")]
    assert restantes == [completa], "a extração completa deve sobreviver"
    assert conn.execute("SELECT COUNT(*) FROM intencoes WHERE pesquisa_id = ?",
                        (completa,)).fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM intencoes WHERE pesquisa_id = ?",
                        (truncada,)).fetchone()[0] == 0
    conn.close()


def test_move_intencao_exclusiva_da_perdedora():
    """Se a perdedora tem um candidato que a vencedora não tem, ele migra."""
    conn = _conn()
    _pesquisa(conn, "GEN-a", {"Lula": 40.0, "Ciro Gomes": 5.0})
    vencedora = _pesquisa(conn, "GEN-b", {
        "Lula": 40.0, "Flávio Bolsonaro": 33.0, "Renan Santos": 9.0})

    deduplicar(conn)

    candidatos = {r["candidato"] for r in conn.execute(
        "SELECT candidato FROM intencoes WHERE pesquisa_id = ?", (vencedora,))}
    assert "Ciro Gomes" in candidatos
    conn.close()


def test_nao_funde_pesquisas_de_datas_diferentes():
    conn = _conn()
    _pesquisa(conn, "GEN-a", {"Lula": 40.0}, data="2026-07-20")
    _pesquisa(conn, "GEN-b", {"Lula": 41.0}, data="2026-07-25")

    resultado = deduplicar(conn)

    assert resultado["fundidas"] == 0
    assert conn.execute("SELECT COUNT(*) FROM pesquisas").fetchone()[0] == 2
    conn.close()


def test_e_idempotente():
    conn = _conn()
    _pesquisa(conn, "GEN-a", {"Lula": 40.0})
    _pesquisa(conn, "GEN-b", {"Lula": 40.0, "Flávio Bolsonaro": 33.0})

    deduplicar(conn)
    resultado = deduplicar(conn)

    assert resultado["fundidas"] == 0
    conn.close()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python -m pytest tests/test_dedup_pesquisas.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'scripts.migrate_dedup_pesquisas'`

- [ ] **Step 3: Implementar a deduplicação**

Criar `scripts/migrate_dedup_pesquisas.py`:

```python
"""
Migration: funde pesquisas duplicadas criadas pela chave sintética de
`collectors/base.py`.

A chave `GEN-{instituto}-{cargo}-{data_coleta}-{sha1(url)}` usa a URL da
matéria, então duas reportagens sobre a mesma pesquisa viravam duas linhas —
e frequentemente uma delas é uma extração truncada. Confirmado em produção nos
ids 27 e 28 (Real Time, 2026-07-20, n=2000): a cópia extra tinha 2 candidatos
contra 6 da completa.

Sobrevive a pesquisa com mais intenções (extração mais completa); empate
desempata pelo maior id. Intenções exclusivas da perdedora migram antes de ela
ser apagada.

Idempotente: rodar de novo sobre um banco já limpo não muda nada.

Uso: python scripts/migrate_dedup_pesquisas.py
"""
import logging
import sqlite3

logger = logging.getLogger(__name__)

DB_PATH = "data/pulso.db"


def deduplicar(conn: sqlite3.Connection) -> dict:
    """Funde duplicatas. Devolve {"fundidas": int, "intencoes_movidas": int}."""
    grupos = conn.execute("""
        SELECT instituto_id, cargo, data_pesquisa, tamanho_amostra,
               GROUP_CONCAT(id) AS ids
        FROM pesquisas
        GROUP BY instituto_id, cargo, data_pesquisa, tamanho_amostra
        HAVING COUNT(*) > 1
    """).fetchall()

    fundidas = 0
    movidas = 0

    for grupo in grupos:
        ids = [int(x) for x in grupo["ids"].split(",")]

        contagens = {
            pid: conn.execute(
                "SELECT COUNT(*) FROM intencoes WHERE pesquisa_id = ?", (pid,)
            ).fetchone()[0]
            for pid in ids
        }
        vencedora = max(ids, key=lambda pid: (contagens[pid], pid))

        candidatos_vencedora = {
            r[0] for r in conn.execute(
                "SELECT candidato FROM intencoes WHERE pesquisa_id = ?", (vencedora,)
            )
        }

        for perdedora in ids:
            if perdedora == vencedora:
                continue

            exclusivas = conn.execute(
                "SELECT id, candidato FROM intencoes WHERE pesquisa_id = ?",
                (perdedora,),
            ).fetchall()
            for intencao in exclusivas:
                if intencao["candidato"] in candidatos_vencedora:
                    conn.execute("DELETE FROM intencoes WHERE id = ?", (intencao["id"],))
                else:
                    conn.execute(
                        "UPDATE intencoes SET pesquisa_id = ? WHERE id = ?",
                        (vencedora, intencao["id"]),
                    )
                    candidatos_vencedora.add(intencao["candidato"])
                    movidas += 1

            conn.execute("DELETE FROM pesquisas WHERE id = ?", (perdedora,))
            fundidas += 1
            logger.info("Pesquisa %d fundida em %d (duplicata).", perdedora, vencedora)

    conn.commit()
    return {"fundidas": fundidas, "intencoes_movidas": movidas}


def aplicar_migracao(conn: sqlite3.Connection) -> None:
    """Ponto de entrada para o init_db. Idempotente."""
    deduplicar(conn)


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        resultado = deduplicar(conn)
        print(f"Deduplicação: {resultado['fundidas']} pesquisas fundidas, "
              f"{resultado['intencoes_movidas']} intenções movidas.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `python -m pytest tests/test_dedup_pesquisas.py -v`
Expected: PASS (4 testes)

- [ ] **Step 5: Rodar a deduplicação no banco local e conferir o resultado**

```bash
python scripts/migrate_dedup_pesquisas.py
```

Expected: `Deduplicação: 1 pesquisas fundidas, 0 intenções movidas.` — corresponde ao par 27/28. Conferir que sobrou a completa:

```bash
python -c "import sqlite3; c=sqlite3.connect('data/pulso.db'); print(c.execute('SELECT COUNT(*) FROM pesquisas').fetchone()[0], 'pesquisas')"
```

Expected: `13 pesquisas` (eram 14).

- [ ] **Step 6: Commit**

```bash
git add scripts/migrate_dedup_pesquisas.py tests/test_dedup_pesquisas.py
git commit -m "fix(db): funde pesquisas duplicadas pela chave sintética de URL"
```

---

### Task 6: Teto de peso na média agregada

**Files:**
- Modify: `db/pesquisas.py:250-261`
- Modify: `templates/metodologia.html`
- Test: `tests/test_agregacao.py`

**Interfaces:**
- Consumes: nada.
- Produces: `_teto_amostra(amostras: list[int]) -> int` em `db/pesquisas.py` — percentil 90 por *nearest-rank*, isto é, o elemento de índice `ceil(0.9 * n) - 1` na lista ordenada. Determinístico e testável.

**Por que:** a Vetor Arrow registrou tracking de RJ com n=14.000 contra n=1.200 do Quaest. Sem teto, um único instituto domina a média. Com poucos institutos o percentil 90 ≈ máximo, então o teto não tem efeito — ele só morde quando há um outlier real.

- [ ] **Step 1: Escrever o teste que falha**

Adicionar a `tests/test_agregacao.py`:

```python
from db.pesquisas import _teto_amostra


def test_teto_amostra_percentil_90_nearest_rank():
    """Nearest-rank: índice ceil(0.9*n)-1 na lista ordenada."""
    assert _teto_amostra([1000]) == 1000
    assert _teto_amostra([1000, 2000]) == 2000
    # n=10 -> índice ceil(9)-1 = 8 -> nono menor
    assert _teto_amostra([100, 200, 300, 400, 500, 600, 700, 800, 900, 99999]) == 900


def test_teto_amostra_lista_vazia():
    assert _teto_amostra([]) == 1000


def test_outlier_de_amostra_nao_domina_a_media():
    """Um instituto com amostra 10x maior não pode ditar a média sozinho."""
    _init_limpo()
    conn = get_conn()
    try:
        # 4 institutos comedidos concordam em ~40; o outlier diz 30.
        _seed_pesquisa(conn, "Quaest", dias_atras=1, amostra=1200,
                       candidatos={"Lula": 40.0, "Flávio Bolsonaro": 30.0})
        _seed_pesquisa(conn, "Datafolha", dias_atras=1, amostra=2000,
                       candidatos={"Lula": 40.0, "Flávio Bolsonaro": 30.0})
        _seed_pesquisa(conn, "Atlas", dias_atras=1, amostra=1500,
                       candidatos={"Lula": 40.0, "Flávio Bolsonaro": 30.0})
        _seed_pesquisa(conn, "PoderData", dias_atras=1, amostra=1800,
                       candidatos={"Lula": 40.0, "Flávio Bolsonaro": 30.0})
        _seed_pesquisa(conn, "Verita", dias_atras=1, amostra=40000,
                       candidatos={"Lula": 30.0, "Flávio Bolsonaro": 40.0})

        resultado = get_media_agregada("presidente", dias=30)
        lula = next(c for c in resultado["candidatos"] if c["candidato"] == "Lula")

        # Sem teto, o outlier de 40k puxaria a média para ~32.
        # Com teto no percentil 90, ela fica muito mais perto do consenso de 40.
        assert lula["media"] > 36.0, (
            f"outlier dominou a média: {lula['media']}"
        )
    finally:
        conn.close()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python -m pytest tests/test_agregacao.py -v -k "teto or outlier"`
Expected: FAIL com `ImportError: cannot import name '_teto_amostra'`

- [ ] **Step 3: Implementar o teto**

Em `db/pesquisas.py`, adicionar a função logo antes de `get_media_agregada` (por volta da linha 190):

```python
def _teto_amostra(amostras: list[int]) -> int:
    """Percentil 90 das amostras por nearest-rank (índice ceil(0.9*n)-1).

    Serve de teto na ponderação para que um instituto com amostra muito acima
    das demais não domine a média sozinho. Com poucos institutos o percentil 90
    tende ao máximo, então o teto só tem efeito quando há outlier real.
    """
    import math

    validas = sorted(a for a in amostras if a and a > 0)
    if not validas:
        return 1000
    indice = math.ceil(0.9 * len(validas)) - 1
    return validas[max(0, indice)]
```

Em seguida, substituir o bloco de score (linhas 250-261) por:

```python
    # 2-4. Score de cada pesquisa selecionada = peso_amostra * peso_recencia
    hoje = date.today()
    teto = _teto_amostra([polls[pid]['amostra'] for pid in pids_selecionados])
    scores: dict[int, float] = {}
    for pid in pids_selecionados:
        poll = polls[pid]
        peso_amostra = poll['amostra'] if poll['amostra'] and poll['amostra'] > 0 else 1000
        # Teto: nenhuma pesquisa pesa mais que o percentil 90 das amostras da
        # janela — evita que um tracking de amostra atípica dite o agregado.
        peso_amostra = min(peso_amostra, teto)
        try:
            dias_desde = max(0, (hoje - date.fromisoformat(poll['data'])).days)
        except (ValueError, TypeError):
            dias_desde = 0
        peso_recencia = 0.9 ** dias_desde
        scores[pid] = peso_amostra * peso_recencia
```

Atualizar também a docstring de `get_media_agregada` (linha 199), trocando o item 2 por:

```
      2. Pondera por tamanho de amostra (peso = amostra, ou 1000 se ausente),
         limitado ao percentil 90 das amostras da janela;
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `python -m pytest tests/test_agregacao.py -v`
Expected: PASS, incluindo os testes de contrato numérico que já existiam. **Se algum teste antigo de agregação quebrar, parar e investigar** — o teto não deveria mudar cenários sem outlier. Um teste antigo vermelho aqui significa que o teto está mordendo onde não devia.

- [ ] **Step 5: Atualizar a página de metodologia**

Em `templates/metodologia.html`, localizar a explicação da ponderação por amostra e acrescentar, no mesmo bloco:

```html
<p>
  Para que um único instituto com amostra atipicamente grande não determine
  sozinho o resultado, o peso de amostra de cada pesquisa é limitado ao
  percentil 90 das amostras das pesquisas consideradas naquele momento.
  Na prática, o limite só tem efeito quando há um caso destoante: quando os
  institutos têm amostras parecidas, nenhum peso é reduzido.
</p>
```

- [ ] **Step 6: Rodar a suíte inteira**

Run: `python -m pytest -q`
Expected: tudo passando.

- [ ] **Step 7: Commit**

```bash
git add db/pesquisas.py tests/test_agregacao.py templates/metodologia.html
git commit -m "feat(agregacao): teto de peso no percentil 90 da amostra"
```

---

### Task 7: Coletor deixa de reportar sucesso sem salvar

**Files:**
- Modify: `collectors/base.py:59-77`
- Test: `tests/test_collectors.py`

**Interfaces:**
- Consumes: nada.
- Produces: `BaseCollector.run()` passa a devolver `status` em `{"ok", "vazio", "parcial", "erro"}`. `"vazio"` = executou sem exceção, mas não salvou nenhuma pesquisa.

**Por que:** hoje Quaest, Atlas e Poder360 devolvem `"ok"` com zero pesquisas salvas, e o log do scheduler mostra `"ok"` nos 9 coletores. A quebra é invisível.

- [ ] **Step 1: Escrever o teste que falha**

Adicionar a `tests/test_collectors.py`:

```python
def test_run_reporta_vazio_quando_nada_e_salvo(monkeypatch):
    """Coletor que não encontra nada não pode reportar 'ok'."""
    from collectors.datafolha import DatafolhaCollector

    coletor = DatafolhaCollector(db_path=database.DB_PATH)
    monkeypatch.setattr(coletor, "fetch", lambda: [])

    resultado = coletor.run()

    assert resultado["status"] == "vazio"
    assert resultado["salvas"] == 0


def test_run_reporta_ok_quando_salva(monkeypatch):
    from collectors.datafolha import DatafolhaCollector

    coletor = DatafolhaCollector(db_path=database.DB_PATH)
    monkeypatch.setattr(coletor, "fetch", lambda: [])
    monkeypatch.setattr(
        coletor, "save",
        lambda pesquisas: {"pesquisas": 2, "intencoes": 8, "rejeicoes": 0, "falhas": []},
    )

    resultado = coletor.run()

    assert resultado["status"] == "ok"
    assert resultado["salvas"] == 2
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python -m pytest tests/test_collectors.py -v -k "vazio or reporta_ok"`
Expected: FAIL — `assert 'ok' == 'vazio'`

- [ ] **Step 3: Implementar o status**

Em `collectors/base.py`, no método `run()`, substituir a linha que calcula `status` (linha 68) por:

```python
            salvas = resultado.get("pesquisas", 0)
            if falhas:
                status = "parcial"
            elif salvas == 0:
                # Não é sucesso: o coletor rodou sem erro e não trouxe nada.
                # Antes isso virava "ok" e a quebra ficava invisível no log.
                status = "vazio"
            else:
                status = "ok"
```

E ajustar o `return` (linha 74) para usar a variável já calculada:

```python
            return {"status": status, "salvas": salvas, "falhas": falhas}
```

Atualizar a docstring de `run()` (linha 60-61):

```python
        """Executa o ciclo completo de coleta: busca, logs e persistência.
        Retorna {"status": "ok"|"vazio"|"parcial"|"erro", "salvas": int, "falhas": list}.
        "vazio" = rodou sem exceção mas não salvou nada (fonte mudou ou quebrou)."""
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `python -m pytest tests/test_collectors.py -v`
Expected: PASS. Se algum teste antigo esperava `"ok"` para lote vazio, atualizar para `"vazio"` — a mudança é intencional.

- [ ] **Step 5: Rodar a suíte inteira**

Run: `python -m pytest -q`
Expected: tudo passando. Atenção a `tests/test_app.py` e à rota `/admin/status-coletores`, que consomem esse status.

- [ ] **Step 6: Commit**

```bash
git add collectors/base.py tests/test_collectors.py
git commit -m "fix(collectors): status 'vazio' distingue coleta sem resultado de sucesso"
```

---

### Task 8: CLI de sincronização e job diário

**Files:**
- Create: `scripts/sync_tse.py`
- Modify: `app.py` (após o `scheduler.add_job` existente, linha ~152)
- Modify: `db/core.py` (registrar a migração de dedup)
- Test: `tests/test_tse_sync.py`

**Interfaces:**
- Consumes: `baixar_zip`, `extrair_csv`, `parsear_csv` (Task 2), `sincronizar` (Task 3), `casar` (Task 4).
- Produces: `sincronizar_tse(dry_run: bool = True) -> dict` devolvendo `{"presidente": {...}, "governador_rj": {...}, "casamento": {...}}`.

- [ ] **Step 1: Escrever o teste que falha**

Adicionar a `tests/test_tse_sync.py`:

```python
def test_sincronizar_tse_nao_chama_gemini(monkeypatch):
    """O sync do TSE é gratuito por contrato — nunca pode tocar no Gemini."""
    from pathlib import Path

    import scripts.sync_tse as sync_tse

    fixture = (Path(__file__).parent / "fixtures" / "tse_amostra.csv").read_bytes()
    monkeypatch.setattr(sync_tse, "baixar_zip", lambda url=None: b"zip-falso")
    monkeypatch.setattr(sync_tse, "extrair_csv", lambda zip_bytes, nome: fixture)

    def explodir(*args, **kwargs):
        raise AssertionError("sync do TSE não pode chamar o Gemini")

    monkeypatch.setattr("collectors.gemini_extractor.gerar_com_cascata", explodir)

    resultado = sync_tse.sincronizar_tse(dry_run=True)

    assert resultado["presidente"]["inseridos"] >= 0
    assert "casamento" in resultado
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python -m pytest tests/test_tse_sync.py -v -k gemini`
Expected: FAIL com `ModuleNotFoundError: No module named 'scripts.sync_tse'`

- [ ] **Step 3: Implementar a CLI**

Criar `scripts/sync_tse.py`:

```python
"""
Sincroniza o registro oficial de pesquisas do TSE e casa com o que já foi
coletado.

Diferente de `coletar.py`, este script **não chama o Gemini** — é só download
de CSV e escrita em SQLite. Por isso pode rodar diariamente sem consumir a cota
mensal que limita a coleta a 2x/semana.

Uso:
    python scripts/sync_tse.py            # dry-run: mostra o que casaria
    python scripts/sync_tse.py --aplicar  # grava casamentos e backfill
"""
import argparse
import logging
import sys

from db.core import get_conn
from tse.dataset import (ARQUIVO_GOVERNADOR_RJ, ARQUIVO_PRESIDENTE, baixar_zip,
                         extrair_csv, parsear_csv)
from tse.matcher import casar
from tse.sync import sincronizar

logger = logging.getLogger(__name__)

_CARGOS = [
    ("presidente", ARQUIVO_PRESIDENTE),
    ("governador_rj", ARQUIVO_GOVERNADOR_RJ),
]


def sincronizar_tse(dry_run: bool = True) -> dict:
    """Baixa o dataset do TSE, sincroniza e casa. Devolve o relatório."""
    zip_bytes = baixar_zip()
    resultado = {}

    conn = get_conn()
    try:
        for cargo, arquivo in _CARGOS:
            registros = parsear_csv(extrair_csv(zip_bytes, arquivo), cargo=cargo)
            resultado[cargo] = sincronizar(conn, registros)

        casamento = {}
        for cargo, _ in _CARGOS:
            casamento[cargo] = casar(conn, cargo=cargo, dry_run=dry_run)
        resultado["casamento"] = casamento
    finally:
        conn.close()

    return resultado


def main():
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    parser = argparse.ArgumentParser(description="Sincroniza pesquisas registradas no TSE")
    parser.add_argument("--aplicar", action="store_true",
                        help="grava os casamentos (sem esta flag, é dry-run)")
    args = parser.parse_args()

    resultado = sincronizar_tse(dry_run=not args.aplicar)

    for cargo, _ in _CARGOS:
        contagem = resultado[cargo]
        print(f"{cargo}: {contagem['inseridos']} inseridos, "
              f"{contagem['atualizados']} atualizados")

    for cargo, relatorio in resultado["casamento"].items():
        print(f"\n{cargo}: {len(relatorio['casados'])} casamentos, "
              f"{len(relatorio['ambiguos'])} ambíguos, "
              f"{relatorio['sem_par']} sem par")
        for par in relatorio["casados"]:
            print(f"  {par['protocolo']}: pesquisa {par['pesquisa_id']} "
                  f"amostra {par['amostra_atual']} -> {par['amostra_tse']}, "
                  f"data {par['data_atual']} -> {par['data_tse']}")
        for ambiguo in relatorio["ambiguos"]:
            print(f"  AMBÍGUO {ambiguo['protocolo']}: {ambiguo['motivo']} "
                  f"{ambiguo['pesquisa_ids']}")

    if not args.aplicar:
        print("\n(dry-run — nada foi gravado. Use --aplicar para gravar.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `python -m pytest tests/test_tse_sync.py -v`
Expected: PASS (todos)

- [ ] **Step 5: Registrar a migração de dedup no init_db**

Em `db/core.py`, logo após o registro da migração da Task 1, inserir:

```python
    # Migration idempotente: funde pesquisas duplicadas pela chave sintética
    from scripts.migrate_dedup_pesquisas import aplicar_migracao as _aplicar_dedup
    _aplicar_dedup(conn)
```

- [ ] **Step 6: Agendar o job diário**

Em `app.py`, após o `scheduler.add_job(...)` existente (linha ~152), acrescentar:

```python
def _job_sync_tse():
    """Sincroniza o registro oficial do TSE. Não consome cota do Gemini,
    por isso roda diariamente (a coleta roda 2x/semana)."""
    from scripts.sync_tse import sincronizar_tse
    try:
        # dry_run=False: o casamento recusa ambiguidade por construção, então
        # só grava par inequívoco (ver tse/matcher.py).
        resultado = sincronizar_tse(dry_run=False)
        app.logger.info("Sync TSE concluído: %s", resultado)
    except Exception:
        app.logger.exception("Falha no sync do TSE")


scheduler.add_job(
    _job_sync_tse,
    'cron',
    hour=9,
    minute=30,
    id='sync_tse',
    replace_existing=True,
    misfire_grace_time=3600,
)
```

O horário (9h30) fica depois da geração do arquivo pelo TSE, observada às 5h46, e antes da coleta das 10h — assim a coleta já encontra os registros do dia sincronizados.

- [ ] **Step 7: Rodar a suíte inteira**

Run: `python -m pytest -q`
Expected: tudo passando. O scheduler é desligado sob `TESTING=True`, então o job novo não deve interferir.

- [ ] **Step 8: Rodar o sync de verdade em dry-run**

```bash
python scripts/sync_tse.py
```

Expected: relatório com ~484 inseridos em presidente, ~30 em governador_rj, e a lista de casamentos propostos. **Conferir os pares manualmente antes de aplicar** — em especial se as datas propostas fazem sentido.

- [ ] **Step 9: Aplicar depois de conferir**

```bash
python scripts/sync_tse.py --aplicar
```

Conferir o efeito:

```bash
python -c "
import sqlite3
c = sqlite3.connect('data/pulso.db'); c.row_factory = sqlite3.Row
print('registros TSE:', c.execute('SELECT COUNT(*) FROM pesquisas_tse').fetchone()[0])
print('casados:', c.execute('SELECT COUNT(*) FROM pesquisas_tse WHERE pesquisa_id IS NOT NULL').fetchone()[0])
print('amostra zerada restante:', c.execute('SELECT COUNT(*) FROM pesquisas WHERE tamanho_amostra = 0').fetchone()[0])
"
```

- [ ] **Step 10: Commit**

```bash
git add scripts/sync_tse.py tests/test_tse_sync.py db/core.py app.py
git commit -m "feat(tse): CLI de sincronização e job diário no scheduler"
```

---

## Verificação final da onda

- [ ] `python -m pytest -q` — suíte inteira verde.
- [ ] `python scripts/sync_tse.py` roda sem erro e reporta contagens plausíveis.
- [ ] `SELECT COUNT(*) FROM pesquisas WHERE tamanho_amostra = 0` diminuiu.
- [ ] Nenhuma pesquisa duplicada: `SELECT instituto_id, cargo, data_pesquisa, tamanho_amostra, COUNT(*) FROM pesquisas GROUP BY 1,2,3,4 HAVING COUNT(*) > 1` volta vazio.
- [ ] `/metodologia` descreve o teto de peso.
- [ ] **Não dar push.** A branch fica local até o dono do produto decidir — push na `main` dispara CI → `flyctl deploy`.

## O que esta onda deliberadamente não faz

- Não cria tela de cobertura (Onda 2).
- Não cria fluxo de preenchimento manual (Onda 3).
- Não popula `contratante` — cortado do escopo por decisão do dono do produto.
- Não extrai `margem_erro` do texto livre do TSE.
- Não marca nenhum instituto como `agregar = 1`. A coluna nasce com default 0 e **ainda não é lida por nenhuma query** — a curadoria entra em vigor na Onda 2. Isso é intencional: a Onda 1 não pode mudar quem entra na média, só corrigir os números de quem já entra.
