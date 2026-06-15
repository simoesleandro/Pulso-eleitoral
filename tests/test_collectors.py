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
        assert hasattr(collector, "_parse") or hasattr(collector, "_parse_release")

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
    
    conn = sqlite3.connect(db_file)
    schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    conn.executescript(schema_sql)
    conn.close()

    for collector_cls in ALL_COLLECTORS:
        collector = collector_cls(str(db_file))
        # Chamada direta ao save com array vazio
        collector.save([])
