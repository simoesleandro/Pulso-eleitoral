import os
os.environ['TESTING'] = 'True'

import pytest
import sqlite3
from collectors.base import BaseCollector
from collectors import ALL_COLLECTORS

def test_base_collector_is_abc():
    """Verifica que BaseCollector é uma classe abstrata (ABC) e não pode ser instanciada diretamente."""
    with pytest.raises(TypeError):
        BaseCollector("dummy_path")

def test_concrete_collectors_instantiation(tmp_path):
    """Verifica que todos os coletores concretos podem ser instanciados com caminhos de banco."""
    db_file = tmp_path / "test_collectors.db"
    for collector_cls in ALL_COLLECTORS:
        collector = collector_cls(str(db_file))
        assert collector.db_path == str(db_file)
        assert collector.name is not None
        assert isinstance(collector.instituto_id, int)
        assert hasattr(collector, "fetch")
        assert hasattr(collector, "save")
        assert (hasattr(collector, "_parse")
                or hasattr(collector, "_parse_release")
                or hasattr(collector, "_parse_page"))

def test_coletores_disponiveis_cumprem_contrato_get_page_parse_release(tmp_path):
    """A rota /admin/coletar-url chama coletor._get_page(url) e
    coletor._parse_release(html, url) em qualquer classe resolvida via
    app._COLETORES_DISPONIVEIS. Este teste transforma o AttributeError de
    request-time em falha de CI caso um coletor novo (ou reaproveitado) não
    implemente o contrato."""
    import importlib
    from app import _COLETORES_DISPONIVEIS

    db_file = tmp_path / "test_collectors_contrato.db"
    for chave, (modulo_path, classe_nome) in _COLETORES_DISPONIVEIS.items():
        modulo = importlib.import_module(modulo_path)
        collector_cls = getattr(modulo, classe_nome)
        collector = collector_cls(str(db_file))
        assert callable(getattr(collector, "_get_page", None)), (
            f"{classe_nome} ({chave}) não implementa _get_page"
        )
        assert callable(getattr(collector, "_parse_release", None)), (
            f"{classe_nome} ({chave}) não implementa _parse_release"
        )

def test_run_does_not_crash_on_empty_fetch(tmp_path):
    """Verifica que o método run() não crasha quando o fetch() retorna uma lista vazia []."""
    db_file = tmp_path / "test_collectors.db"
    
    # Cria a estrutura do banco temporário
    conn = sqlite3.connect(db_file)
    schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    conn.executescript(schema_sql)
    conn.close()

    for collector_cls in ALL_COLLECTORS:
        collector = collector_cls(str(db_file))
        # Executa o run() que chama fetch() e depois save()
        # Não deve levantar exceções mesmo com retorno vazio de fetch()
        collector.run()

def test_save_empty_list_does_not_error(tmp_path):
    """Verifica que o método save() com lista vazia não gera erros ou exceções no banco."""
    db_file = tmp_path / "test_collectors.db"
    
    import database
    original_db_path = database.DB_PATH
    try:
        database.DB_PATH = str(db_file)
        database.init_db(force_seed=False)
    finally:
        database.DB_PATH = original_db_path

    for collector_cls in ALL_COLLECTORS:
        collector = collector_cls(str(db_file))
        # Chamada direta ao save com array vazio
        collector.save([])

def test_save_normalizado(tmp_path):
    """Verifica se o save() normaliza e insere corretamente as pesquisas e intenções."""
    db_file = tmp_path / "test_collectors_save.db"
    
    # Inicializa banco temporário com schema completo
    import database
    original_db_path = database.DB_PATH
    try:
        database.DB_PATH = str(db_file)
        database.init_db(force_seed=False)
    finally:
        database.DB_PATH = original_db_path
    
    # Limpa dados do seed para garantir que o banco esteja vazio
    # e insere o instituto 3 na tabela de institutos para respeitar a FK
    conn = sqlite3.connect(str(db_file))
    conn.execute("DELETE FROM intencoes")
    conn.execute("DELETE FROM pesquisas")
    conn.execute("DELETE FROM institutos")
    conn.execute("INSERT OR REPLACE INTO institutos (id, nome) VALUES (3, 'Quaest')")
    conn.commit()
    conn.close()
    
    from collectors.quaest import QuaestCollector
    collector = QuaestCollector(str(db_file))
    
    # Lista de 3 dicts com mesmo levantamento
    dados = [
        {
            "instituto_id": 3,
            "cargo": "presidente",
            "candidato": "Lula",
            "percentual": 38.0,
            "data_coleta": "2026-06-15",
            "data_divulgacao": "2026-06-16",
            "tamanho_amostra": 2000,
            "margem_erro": 2.0,
            "fonte_url": "https://quaest.com.br/release-1",
            "metodologia": "Espontânea"
        },
        {
            "instituto_id": 3,
            "cargo": "presidente",
            "candidato": "Bolsonaro",
            "percentual": 32.0,
            "data_coleta": "2026-06-15",
            "data_divulgacao": "2026-06-16",
            "tamanho_amostra": 2000,
            "margem_erro": 2.0,
            "fonte_url": "https://quaest.com.br/release-1",
            "metodologia": "Espontânea"
        },
        {
            "instituto_id": 3,
            "cargo": "presidente",
            "candidato": "Ciro",
            "percentual": 10.0,
            "data_coleta": "2026-06-15",
            "data_divulgacao": "2026-06-16",
            "tamanho_amostra": 2000,
            "margem_erro": 2.0,
            "fonte_url": "https://quaest.com.br/release-1",
            "metodologia": "Espontânea"
        }
    ]
    
    # Chama save() com os dados
    collector.save(dados)
    
    # Verifica pesquisas e intencoes
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM pesquisas")
    assert cursor.fetchone()[0] == 1
    
    cursor.execute("SELECT COUNT(*) FROM intencoes")
    assert cursor.fetchone()[0] == 3
    conn.close()
    
    # Chama save() novamente com os mesmos dados
    collector.save(dados)

    # Verifica que não duplicou pesquisas e que as intencoes foram inseridas (ou substituídas)
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM pesquisas")
    assert cursor.fetchone()[0] == 1

    cursor.execute("SELECT COUNT(*) FROM intencoes")
    assert cursor.fetchone()[0] == 3
    conn.close()


def test_save_falha_parcial_nao_derruba_lote(tmp_path):
    """Um release com dado inválido (percentual NULL, viola NOT NULL) não deve
    impedir que o outro release do mesmo lote seja salvo — commit é por grupo."""
    db_file = tmp_path / "test_collectors_falha_parcial.db"

    import database
    original_db_path = database.DB_PATH
    try:
        database.DB_PATH = str(db_file)
        database.init_db(force_seed=False)
    finally:
        database.DB_PATH = original_db_path

    conn = sqlite3.connect(str(db_file))
    conn.execute("DELETE FROM intencoes")
    conn.execute("DELETE FROM pesquisas")
    conn.execute("DELETE FROM institutos")
    conn.execute("INSERT OR REPLACE INTO institutos (id, nome) VALUES (3, 'Quaest')")
    conn.commit()
    conn.close()

    from collectors.quaest import QuaestCollector
    collector = QuaestCollector(str(db_file))

    dados = [
        {
            "instituto_id": 3,
            "cargo": "presidente",
            "candidato": "Lula",
            "percentual": 38.0,
            "data_coleta": "2026-06-15",
            "tamanho_amostra": 2000,
            "margem_erro": 2.0,
            "fonte_url": "https://quaest.com.br/release-ok",
        },
        {
            "instituto_id": 3,
            "cargo": "presidente",
            "candidato": "Bolsonaro",
            "percentual": None,  # viola NOT NULL em intencoes.percentual
            "data_coleta": "2026-06-15",
            "tamanho_amostra": 2000,
            "margem_erro": 2.0,
            "fonte_url": "https://quaest.com.br/release-quebrado",
        },
    ]

    resultado = collector.save(dados)

    assert resultado["pesquisas"] == 1
    assert len(resultado["falhas"]) == 1
    assert resultado["falhas"][0][0] == "https://quaest.com.br/release-quebrado"

    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("SELECT fonte_url FROM pesquisas")
    urls = [r[0] for r in cursor.fetchall()]
    conn.close()
    assert urls == ["https://quaest.com.br/release-ok"]


def test_save_sucesso_total_sem_falhas(tmp_path):
    """save() com todos os releases válidos retorna falhas vazia."""
    db_file = tmp_path / "test_collectors_sucesso.db"

    import database
    original_db_path = database.DB_PATH
    try:
        database.DB_PATH = str(db_file)
        database.init_db(force_seed=False)
    finally:
        database.DB_PATH = original_db_path

    conn = sqlite3.connect(str(db_file))
    conn.execute("DELETE FROM intencoes")
    conn.execute("DELETE FROM pesquisas")
    conn.execute("DELETE FROM institutos")
    conn.execute("INSERT OR REPLACE INTO institutos (id, nome) VALUES (3, 'Quaest')")
    conn.commit()
    conn.close()

    from collectors.quaest import QuaestCollector
    collector = QuaestCollector(str(db_file))

    dados = [
        {
            "instituto_id": 3,
            "cargo": "presidente",
            "candidato": "Lula",
            "percentual": 38.0,
            "data_coleta": "2026-06-15",
            "tamanho_amostra": 2000,
            "margem_erro": 2.0,
            "fonte_url": "https://quaest.com.br/release-2",
        },
    ]

    resultado = collector.save(dados)
    assert resultado["falhas"] == []
    assert resultado["pesquisas"] == 1
    assert resultado["intencoes"] == 1

    # Contrato usado por run(): sem falhas => status "ok"
    status = "parcial" if resultado["falhas"] else "ok"
    assert status == "ok"


def test_save_lote_vazio_retorna_dict_zerado():
    """save([]) deve retornar o dict com contadores zerados e falhas vazia, não None."""
    from collectors.quaest import QuaestCollector
    collector = QuaestCollector("dummy_path_nao_usado.db")

    resultado = collector.save([])
    assert resultado == {"pesquisas": 0, "intencoes": 0, "rejeicoes": 0, "falhas": []}
