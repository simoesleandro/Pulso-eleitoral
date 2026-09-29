"""
Migration: unifica séries do mesmo candidato gravadas com grafias diferentes.

`intencoes.candidato` guarda o nome em texto (não há chave estrangeira para
`candidatos`). A normalização acontece só na gravação (`normalizar_nome`),
contra o roster do momento. Enquanto o roster de produção não tinha
"Anthony Garotinho", as intenções entraram como "Garotinho" e ficaram numa
série separada. Esta migração renomeia os nomes gravados para o canônico,
pelo mapa de apelidos da tabela `candidatos` do próprio banco.

Regras:
- Só renomeia nome que o mapa conhece e que aponta para candidato ativo.
  Nome fora do mapa não é tocado. Nome de candidato inativo (`ativo = 0`,
  que `normalizar_nome` descartaria) também não: esta migração não apaga
  linha.
- Se renomear deixaria o mesmo candidato duas vezes na mesma pesquisa e
  tipo, as linhas ficam como estão e saem em `conflitos`. Escolher um dos
  percentuais seria chute.
- Idempotente: numa segunda execução não há o que renomear.

Precisa do roster completo (FIX 1, `_popular_candidatos` no init_db). Se o
banco estiver atrás do seed, o relatório lista os ausentes em
`faltam_no_roster` — o dry-run não diz que está tudo certo quando não sabe.

Uso (dry-run é o padrão; nada é gravado sem --aplicar):
    python scripts/migrate_unificar_apelidos.py --db /data/pulso.db
    python scripts/migrate_unificar_apelidos.py --db /data/pulso.db --aplicar
"""
import argparse
import json
import logging
import os
import sqlite3
import sys
from collections import Counter

# Rodar `python scripts/...` coloca scripts/ no sys.path, não a raiz do repo.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Entra pela façade `database` (importar db.* direto dispara import circular).
import database  # noqa: E402,F401
from db.candidatos import _CANDIDATOS_SEED  # noqa: E402

logger = logging.getLogger(__name__)


def _mapa_apelidos(conn: sqlite3.Connection) -> dict:
    """{chave minúscula -> nome_canonico, ou None se inativo}.

    Mesma semântica de `_carregar_candidatos_cache`, mas lida da conexão
    recebida — o script roda contra qualquer banco, não só o do processo.
    """
    mapa = {}
    for nome, apelidos_json, ativo in conn.execute(
            "SELECT nome_canonico, apelidos, ativo FROM candidatos"):
        try:
            apelidos = json.loads(apelidos_json) if apelidos_json else []
        except ValueError:
            apelidos = []
        for chave in [nome, *apelidos]:
            mapa[chave.lower().strip()] = nome if ativo else None
    return mapa


def unificar_apelidos(conn: sqlite3.Connection, aplicar: bool = False) -> dict:
    """Renomeia intenções para o nome canônico. Sem `aplicar`, só reporta.

    Retorna {"mudancas": [{"de", "para", "linhas"}], "total": int,
             "conflitos": [{"de", "para", "pesquisa_id", "tipo"}],
             "faltam_no_roster": [nome, ...], "aplicado": bool}.
    """
    mapa = _mapa_apelidos(conn)
    no_roster = {r[0] for r in conn.execute("SELECT nome_canonico FROM candidatos")}
    faltam = [nome for nome, *_ in _CANDIDATOS_SEED if nome not in no_roster]

    linhas = conn.execute(
        "SELECT id, pesquisa_id, tipo, candidato FROM intencoes ORDER BY id").fetchall()

    def alvo(candidato):
        return mapa.get(candidato.lower().strip()) or candidato

    ocupacao = Counter((pid, tipo, alvo(nome)) for _, pid, tipo, nome in linhas)

    renomear, conflitos = [], []
    for id_, pid, tipo, nome in linhas:
        para = alvo(nome)
        if para == nome:
            continue
        if ocupacao[(pid, tipo, para)] > 1:
            conflitos.append({"de": nome, "para": para, "pesquisa_id": pid, "tipo": tipo})
        else:
            renomear.append((id_, nome, para))

    contagem = Counter((de, para) for _, de, para in renomear)
    mudancas = [{"de": de, "para": para, "linhas": n}
                for (de, para), n in sorted(contagem.items())]

    if aplicar and renomear:
        conn.executemany("UPDATE intencoes SET candidato = ? WHERE id = ?",
                         [(para, id_) for id_, _, para in renomear])
        conn.commit()
        for m in mudancas:
            logger.info("Unificado: %s -> %s (%d linha(s))", m["de"], m["para"], m["linhas"])
    for c in conflitos:
        logger.warning("Conflito, não unificado: %s -> %s na pesquisa %d (%s)",
                       c["de"], c["para"], c["pesquisa_id"], c["tipo"])

    return {"mudancas": mudancas, "total": len(renomear), "conflitos": conflitos,
            "faltam_no_roster": faltam, "aplicado": bool(aplicar)}


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    parser = argparse.ArgumentParser(
        description="Unifica intenções gravadas com apelido no nome canônico")
    parser.add_argument("--db", default=database.DB_PATH,
                        help=f"banco SQLite (padrão: {database.DB_PATH})")
    parser.add_argument("--aplicar", action="store_true",
                        help="grava as mudanças (sem esta flag, é dry-run)")
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        parser.error(f"banco não encontrado: {args.db}")

    conn = sqlite3.connect(args.db)
    try:
        relatorio = unificar_apelidos(conn, aplicar=args.aplicar)
    finally:
        conn.close()

    if relatorio["faltam_no_roster"]:
        print(f"ATENÇÃO: {len(relatorio['faltam_no_roster'])} candidato(s) do seed "
              f"fora do roster deste banco: {', '.join(relatorio['faltam_no_roster'])}. "
              "Rode o init_db (deploy do FIX 1) antes; sem eles o mapa está incompleto.")
    for m in relatorio["mudancas"]:
        print(f"{m['de']} -> {m['para']}: {m['linhas']} linha(s)")
    for c in relatorio["conflitos"]:
        print(f"CONFLITO {c['de']} -> {c['para']}: pesquisa {c['pesquisa_id']} "
              f"({c['tipo']}) já tem o nome canônico — não unificado")
    print(f"Total: {relatorio['total']} linha(s), {len(relatorio['conflitos'])} conflito(s).")

    if not args.aplicar:
        print("(dry-run — nada foi gravado. Use --aplicar para gravar.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
