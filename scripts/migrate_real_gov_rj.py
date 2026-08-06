"""
Migration idempotente para garantir a presença de pesquisas reais para Governador do RJ
(Paraná Pesquisas RJ-09303/2026 de 30/07/2026 com 7 candidatos) e sincronização do TSE.
"""
import logging
from datetime import date

logger = logging.getLogger(__name__)

def aplicar_migracao(conn) -> None:
    cur = conn.cursor()
    
    # Verifica se os institutos já foram semeados
    inst = cur.execute("SELECT id FROM institutos WHERE id=6").fetchone()
    if not inst:
        logger.info("[migracao_gov_rj] Instituto 6 ainda não existe na tabela institutos. Adiando.")
        return

    # 1. Garante que os candidatos a Governador do RJ estejam populados
    from db.candidatos import _popular_candidatos, _invalidar_cache_candidatos, get_mapa_apelidos
    _popular_candidatos(conn)
    _invalidar_cache_candidatos()
    
    # 2. Insere a pesquisa real do Paraná Pesquisas (30/07/2026 - RJ-09303/2026) se não existir
    row = cur.execute(
        "SELECT id FROM pesquisas WHERE cargo='governador_rj' AND data_pesquisa='2026-07-30' AND instituto_id=6"
    ).fetchone()
    
    if not row:
        cur.execute("""
            INSERT INTO pesquisas (
                instituto_id, cargo, data_pesquisa, data_publicacao,
                tamanho_amostra, margem_erro, contratante, registro_tse, fonte_url, coletado_em
            ) VALUES (
                6, 'governador_rj', '2026-07-30', '2026-07-31',
                1600, 2.5, 'Paraná Pesquisas', 'RJ-09303/2026',
                'https://paranapesquisas.com.br/pesquisas/parana-pesquisas-registra-pesquisa-no-estado-do-rio-de-janeiro-para-os-cargos-de-governador-e-senador-registro-tse-n-o-rj-09303-2026-julho-2026/',
                ?
            )
        """, (date.today().isoformat(),))
        pesquisa_id = cur.lastrowid
        logger.info("[migracao_gov_rj] Pesquisa real inserida com ID %d", pesquisa_id)
    else:
        pesquisa_id = row[0]
        
    candidatos_dados = [
        ("Eduardo Paes", 48.6, "PSD"),
        ("Douglas Ruas", 11.1, "PL"),
        ("Anthony Garotinho", 11.0, "REPUBLICANOS"),
        ("André Marinho", 3.4, "NOVO"),
        ("Coronel Busnello", 3.4, "PL"),
        ("Cyro Garcia", 2.0, "PSTU"),
        ("Wilson Witzel", 1.9, "PMB"),
    ]
    
    mapa_apelidos = get_mapa_apelidos()
    for cand_nome, pct, partido in candidatos_dados:
        nome_final = mapa_apelidos.get(cand_nome.lower(), cand_nome) or cand_nome
        check_i = cur.execute(
            "SELECT id FROM intencoes WHERE pesquisa_id=? AND candidato=?",
            (pesquisa_id, nome_final)
        ).fetchone()
        if not check_i:
            cur.execute("""
                INSERT INTO intencoes (pesquisa_id, candidato, partido, percentual, tipo)
                VALUES (?, ?, ?, ?, 'estimulada')
            """, (pesquisa_id, nome_final, partido, pct))
            logger.info("[migracao_gov_rj] Intenção inserida: %s (%.1f%%)", nome_final, pct)
            
    conn.commit()
