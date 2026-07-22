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


def _tem_coluna(conn: sqlite3.Connection, tabela: str, coluna: str) -> bool:
    return any(r[1] == coluna for r in conn.execute(f"PRAGMA table_info({tabela})"))


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


def aplicar_migracao(conn: sqlite3.Connection) -> None:
    """Cria pesquisas_tse e as colunas de curadoria em institutos. Idempotente.

    **Não** popula os CNPJs: em banco novo esta migração roda antes do
    seed.sql carregar os institutos, e o UPDATE não acharia nenhuma linha.
    Quem chama é responsável por invocar `popular_cnpjs` depois do seed —
    `db/core.py::init_db` faz exatamente isso.
    """
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
        preenchidos = popular_cnpjs(conn)
        print(f"Migração aplicada: `pesquisas_tse` + institutos.cnpj/agregar "
              f"({preenchidos} CNPJ(s) preenchido(s)).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
