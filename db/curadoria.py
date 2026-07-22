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


def ligar(protocolo: str, pesquisa_id: int) -> dict:
    with get_db() as conn:
        return ligar_manual(conn, protocolo, pesquisa_id)


def avaliar(cnpj: str, nome_exibicao: str, aprovar: bool) -> dict:
    with get_db() as conn:
        return avaliar_instituto(conn, cnpj, nome_exibicao, aprovar)
