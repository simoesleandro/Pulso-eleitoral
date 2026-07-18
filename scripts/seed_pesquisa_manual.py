"""
INSERÇÃO MANUAL PONTUAL — NÃO FAZ PARTE DO PIPELINE DEFINITIVO.

Insere UMA pesquisa real verificada manualmente, porque o coletor
correspondente ainda não faz scraping de verdade (ex.: ParanaPesquisasCollector
em collectors/paraná_pesquisas.py tem fetch() retornando [] — parsing de PDF
fica pra uma próxima sessão). Serve pra destravar cálculos (ex.:
get_media_agregada) que dependem de dado recente enquanto o coletor real não
existe.

Quando o coletor de verdade for implementado, ele deve fazer a coleta real
dessa mesma pesquisa (ou de pesquisas futuras) — a linha inserida aqui deve
ser revalidada/substituída nesse momento, não é fonte de verdade permanente.

Reutilizável pra outras inserções pontuais: edite INSTITUTO e DADOS_PESQUISA
abaixo (não mexa na lógica de inserção).

Uso: python scripts/seed_pesquisa_manual.py
"""
import sqlite3

DB_PATH = "data/pulso.db"

# Mesmo nome/instituto_id usado por ParanaPesquisasCollector (instituto_id=6,
# name="Paraná") — reaproveita o instituto já cadastrado em vez de duplicar.
INSTITUTO = {
    "nome": "Paraná",
    "sigla": "Paraná Pesquisas",
    "site": "https://paranapesquisas.com.br/",
}

DADOS_PESQUISA = {
    "cargo": "governador_rj",
    "data_pesquisa": "2026-07-01",
    "data_publicacao": "2026-07-02",
    "tamanho_amostra": 1600,
    "margem_erro": 2.5,
    "contratante": None,  # não informado na matéria
    "registro_tse": "RJ-04259/2026",
    "fonte_url": (
        "https://paranapesquisas.com.br/pesquisas/parana-pesquisas-registra-"
        "pesquisa-no-estado-do-rio-de-janeiro-para-os-cargos-de-governador-e-"
        "senador-registro-tse-n-o-rj-04259-2026-julho-2026/"
    ),
    "tipo": "estimulada",
    "candidatos": [
        {"nome": "Eduardo Paes", "percentual": 54.2},
        {"nome": "Douglas Ruas", "percentual": 14.6},
        {"nome": "André Marinho", "percentual": 4.9},
        {"nome": "Wilson Witzel", "percentual": 3.5},
    ],
}


def _instituto_id(conn: sqlite3.Connection, nome: str, sigla: str, site: str) -> int:
    """Retorna o id do instituto pelo nome, criando se ainda não existir. Idempotente."""
    row = conn.execute("SELECT id FROM institutos WHERE nome = ?", (nome,)).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO institutos (nome, sigla, site) VALUES (?, ?, ?)",
        (nome, sigla, site)
    )
    return cur.lastrowid


def _pesquisa_ja_existe(conn: sqlite3.Connection, registro_tse: str):
    row = conn.execute("SELECT id FROM pesquisas WHERE registro_tse = ?", (registro_tse,)).fetchone()
    return row[0] if row else None


def inserir(conn: sqlite3.Connection) -> None:
    """Insere a pesquisa + intenções de DADOS_PESQUISA. Idempotente: se já
    existir uma pesquisa com o mesmo registro_tse, não faz nada."""
    instituto_id = _instituto_id(conn, INSTITUTO["nome"], INSTITUTO["sigla"], INSTITUTO["site"])

    pesquisa_id = _pesquisa_ja_existe(conn, DADOS_PESQUISA["registro_tse"])
    if pesquisa_id is not None:
        print(f"Pesquisa registro_tse={DADOS_PESQUISA['registro_tse']} já existe "
              f"(id={pesquisa_id}) — nada a fazer, idempotente.")
        return

    cur = conn.execute("""
        INSERT INTO pesquisas
        (instituto_id, cargo, data_pesquisa, data_publicacao, tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        instituto_id,
        DADOS_PESQUISA["cargo"],
        DADOS_PESQUISA["data_pesquisa"],
        DADOS_PESQUISA["data_publicacao"],
        DADOS_PESQUISA["tamanho_amostra"],
        DADOS_PESQUISA["margem_erro"],
        DADOS_PESQUISA["contratante"],
        DADOS_PESQUISA["registro_tse"],
        DADOS_PESQUISA["fonte_url"],
    ))
    pesquisa_id = cur.lastrowid

    for c in DADOS_PESQUISA["candidatos"]:
        conn.execute(
            "INSERT INTO intencoes (pesquisa_id, candidato, percentual, tipo) VALUES (?, ?, ?, ?)",
            (pesquisa_id, c["nome"], c["percentual"], DADOS_PESQUISA["tipo"])
        )

    conn.commit()
    print(f"Pesquisa inserida: id={pesquisa_id}, instituto_id={instituto_id}, "
          f"cargo={DADOS_PESQUISA['cargo']}, {len(DADOS_PESQUISA['candidatos'])} candidatos.")


def main():
    conn = sqlite3.connect(DB_PATH)
    try:
        inserir(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
