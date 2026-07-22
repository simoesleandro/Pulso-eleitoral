"""Façade de compatibilidade: re-exporta tudo que os 19 call-sites existentes
(app.py, coletar.py, collectors/*, cronos/tasks/monitor_pesquisas.py,
scripts/rodar_parana.py, e 13 arquivos em tests/) importavam de `database`
antes da divisão em `db/*` (plano 029). Nenhuma lógica vive mais aqui —
apenas estado de módulo (BASE_DIR/DATA_DIR/DB_PATH/_cache_candidatos, ver
comentários abaixo) e imports.
"""
import os

# Definindo o caminho do banco de dados (data/pulso.db ou data/pulso_test.db em testes)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Em produção (Fly.io): /data/pulso.db
# Em local: data/pulso.db
if os.path.exists('/data'):
    DATA_DIR = '/data'
else:
    DATA_DIR = os.path.join(BASE_DIR, 'data')

DB_NAME = 'pulso_test.db' if os.getenv('TESTING') == 'True' else 'pulso.db'
DB_PATH = os.path.join(DATA_DIR, DB_NAME)

# Façade: get_conn/get_db/init_db/limpar_cache_analises/salvar_log_scheduler/
# buscar_ultimo_log vivem em db/core.py, que lê DATA_DIR/DB_PATH/BASE_DIR
# daqui via `import database` (live attribute lookup) — não copiar esses
# nomes por valor aqui em cima, senão o monkeypatch de database.DB_PATH nos
# testes (tests/test_collectors.py, tests/test_variacoes.py) para de
# propagar para as conexões reais. Ver db/core.py para detalhes.
from db.core import get_conn, get_db, init_db, limpar_cache_analises, salvar_log_scheduler, buscar_ultimo_log

# ─── Candidatos: fonte única de verdade ────────────────────────────────────
# _CANDIDATOS_SEED, _popular_candidatos, _invalidar_cache_candidatos,
# _carregar_candidatos_cache e os getters derivados vivem em db/candidatos.py.
# `_cache_candidatos` continua sendo um atributo deste módulo (o façade) —
# db/candidatos.py lê/escreve nele via `import database` (live attribute
# lookup), porque tests/test_apply_db.py e tests/test_database.py fazem
# `database._cache_candidatos = ...` diretamente e esperam que
# _invalidar_cache_candidatos()/_carregar_candidatos_cache() enxerguem essa
# mesma variável (ver db/candidatos.py para detalhes).
_cache_candidatos = None

from db.candidatos import (
    _popular_candidatos, _invalidar_cache_candidatos, _carregar_candidatos_cache,
    get_mapa_apelidos, get_cores_candidatos, get_candidatos_por_espectro,
    get_nomes_presidenciais, get_presidenciais_canonicos, get_candidatos_ignorar,
)

# ─── Eventos da campanha (F4 do PRD: marcadores no gráfico) ────────────────
from db.cobertura import (agendadas, contar_fila, em_campo_hoje,
                          fila_de_trabalho, institutos_para_descobrir)
from db.eventos import listar_eventos, criar_evento, remover_evento

# ─── Pesquisas: comparativos, poll-of-polls, house effects, séries ─────────
from db.pesquisas import (
    get_comparativo_candidato, get_pesquisas_mais_recentes, detectar_variacoes_bruscas,
    get_media_agregada, get_house_effects, get_historico_multi, get_historico_candidato,
    get_top_candidatos, get_institutos_com_totais, get_dados_regionais, _e_candidato,
    get_pesquisa_por_id,
)

# ─── KPIs analíticos avançados e visão geral ───────────────────────────────
from db.kpis import get_kpis_avancados, get_visao_geral, _media_intervalo

# ─── Motor de Monte Carlo (genérico, qualquer cargo) + 2º turno ────────────
from db.monte_carlo import (
    fator_volatilidade, _redistribuir_indecisos, prob_vitoria_primeiro_turno,
    _margens_por_candidato, _pct_mudar_voto_recente, _pct_indecisos_medio,
    _simular_cenario, simular_monte_carlo_cenarios, _contagem_pesquisas_por_candidato,
    _aviso_amostra_limitada, simular_prob_vitoria_1_turno,
    simular_monte_carlo_cargo, get_simulacao_monte_carlo,
    get_confronto_2turno_real, get_simulacao_segundo_turno,
)

# ─── Usuários (login/admin) ────────────────────────────────────────────────
from db.usuarios import criar_usuario, verificar_usuario, listar_usuarios, remover_usuario, toggle_usuario
