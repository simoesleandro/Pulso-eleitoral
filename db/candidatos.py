"""Candidatos: fonte única de verdade para normalização de nomes, espectro
político e cores (tabela `candidatos`, populada no init_db, cacheada em
memória por processo).

O cache (`_cache_candidatos`) continua vivendo como atributo do módulo
`database.py` (o façade), não aqui — `tests/test_apply_db.py` e
`tests/test_database.py` fazem `database._cache_candidatos = ...` e esperam
que `_invalidar_cache_candidatos()`/`_carregar_candidatos_cache()` leiam e
escrevam nesse mesmo global. Por isso as funções abaixo acessam
`database._cache_candidatos` via `import database` (live attribute lookup)
em vez de um cache local neste módulo.
"""
import json

import database

# Roster canônico que popula a tabela `candidatos`. Cada item:
# (nome_canonico, [apelidos...], espectro, cor_hex, is_presidencial, ativo)
# ativo=0 → menções devem ser descartadas (hipotéticos / inelegíveis / não declarados).
_CANDIDATOS_SEED = [
    # Presidenciais ativos
    ("Lula", ["luiz inácio lula da silva", "luiz inacio lula da silva", "lula", "lula da silva"], "esquerda", "#0A2240", 1, 1),
    ("Flávio Bolsonaro", ["flávio bolsonaro", "flavio bolsonaro", "bolsonaro", "flavio", "flávio"], "direita", "#C0392B", 1, 1),
    ("Ronaldo Caiado", ["ronaldo caiado", "caiado"], "direita", "#5a7184", 1, 1),
    ("Romeu Zema", ["romeu zema", "zema"], "direita", "#B4B2A9", 1, 1),
    ("Renan Santos", ["renan santos", "renan santos (missão)"], "direita", "#1D9E75", 1, 1),
    ("Tarcísio de Freitas", ["tarcísio de freitas", "tarcisio de freitas", "tarcísio", "tarcisio"], "direita", None, 1, 1),
    ("Pablo Marçal", ["pablo marçal", "pablo marcal"], "direita", None, 1, 1),
    ("Ciro Gomes", ["ciro gomes", "ciro"], "centro", None, 1, 1),
    ("Simone Tebet", ["simone tebet", "simone"], "centro", None, 1, 1),
    ("Augusto Cury", ["augusto cury"], "centro", None, 1, 1),
    ("Rui Costa Pimenta", ["rui costa pimenta"], "esquerda", None, 1, 1),
    ("Samara Martins", ["samara martins"], "esquerda", None, 1, 1),
    ("Cabo Daciolo", ["cabo daciolo"], "direita", None, 1, 1),
    ("Edmilson Costa", ["edmilson costa"], "esquerda", None, 1, 1),
    ("Hertz Dias", ["hertz dias"], "esquerda", None, 1, 1),
    # Governador RJ (não presidenciais)
    ("Eduardo Paes", ["eduardo paes"], "centro", None, 0, 1),
    ("Cláudio Castro", ["cláudio castro", "claudio castro"], "direita", None, 0, 1),
    ("Marcelo Freixo", ["marcelo freixo"], "esquerda", None, 0, 1),
    ("Rodrigo Neves", ["rodrigo neves"], "centro", None, 0, 1),
    # Descartar (hipotéticos / inelegíveis / não declarados)
    ("Jair Bolsonaro", ["jair bolsonaro", "jair messias bolsonaro", "bolsonaro pai"], None, None, 1, 0),
    ("Michelle Bolsonaro", ["michelle bolsonaro", "michele bolsonaro", "michelle"], None, None, 1, 0),
    ("Aécio Neves", ["aécio neves", "aecio neves"], None, None, 1, 0),
    ("Aldo Rebelo", ["aldo rebelo"], None, None, 1, 0),
    ("Eduardo Bolsonaro", ["eduardo bolsonaro"], None, None, 1, 0),
    ("Camilo Santana", ["camilo santana"], None, None, 1, 0),
    ("Fernando Haddad", ["fernando haddad"], None, None, 1, 0),
    ("Elmano de Freitas", ["elmano de freitas"], None, None, 1, 0),
    ("ACM Neto", ["acm neto"], None, None, 1, 0),
    ("Jerônimo Rodrigues", ["jerônimo rodrigues", "jeronimo rodrigues"], None, None, 0, 0),
    ("Ratinho Junior", ["ratinho junior", "ratinho", "carlos massa ratinho junior"], None, None, 0, 0),
    ("Joaquim Barbosa", ["joaquim barbosa"], None, None, 1, 0),
]


def _popular_candidatos(conn) -> None:
    """Insere o roster canônico na tabela candidatos se ela estiver vazia (idempotente)."""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM candidatos")
    if cur.fetchone()[0] > 0:
        return
    for nome, apelidos, espectro, cor, is_pres, ativo in _CANDIDATOS_SEED:
        cur.execute(
            "INSERT INTO candidatos (nome_canonico, apelidos, espectro, cor_hex, is_presidencial, ativo) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (nome, json.dumps(apelidos, ensure_ascii=False), espectro, cor, is_pres, ativo)
        )
    conn.commit()
    _invalidar_cache_candidatos()


def _invalidar_cache_candidatos() -> None:
    database._cache_candidatos = None


def _carregar_candidatos_cache() -> dict:
    """Carrega (e memoiza) os mapas derivados da tabela candidatos.

    Retorna dict com:
      - mapa: {alias/canonico_lower -> nome_canonico | None}  (None = descartar)
      - espectro: {nome_canonico -> 'esquerda'|'centro'|'direita'}  (só ativos)
      - cores: {nome_canonico -> cor_hex}
      - presidenciais: set de chaves minúsculas (apelidos+canonico) de presidenciais ativos
      - presidenciais_canonicos: [nome_canonico, ...] presidenciais ativos
      - ignorar: [nome_canonico, ...] com ativo=0
    """
    if database._cache_candidatos is not None:
        return database._cache_candidatos

    mapa, espectro, cores = {}, {}, {}
    presidenciais, presidenciais_canonicos, ignorar = set(), [], []
    try:
        with database.get_db() as conn:
            rows = conn.execute(
                "SELECT nome_canonico, apelidos, espectro, cor_hex, is_presidencial, ativo FROM candidatos"
            ).fetchall()
        for r in rows:
            nome = r["nome_canonico"]
            ativo = r["ativo"]
            try:
                apelidos = json.loads(r["apelidos"]) if r["apelidos"] else []
            except Exception:
                apelidos = []
            chaves = {a.lower().strip() for a in apelidos}
            chaves.add(nome.lower().strip())
            destino = nome if ativo else None
            for k in chaves:
                mapa[k] = destino
            if ativo:
                if r["espectro"]:
                    espectro[nome] = r["espectro"]
                if r["cor_hex"]:
                    cores[nome] = r["cor_hex"]
                if r["is_presidencial"]:
                    presidenciais.update(chaves)
                    presidenciais_canonicos.append(nome)
            else:
                ignorar.append(nome)
        database._cache_candidatos = {
            "mapa": mapa, "espectro": espectro, "cores": cores,
            "presidenciais": presidenciais, "presidenciais_canonicos": presidenciais_canonicos,
            "ignorar": ignorar,
        }
    except Exception:
        # DB ainda sem a tabela/dados (ou falha transitória): devolve mapas vazios
        # SEM memoizar — a próxima chamada tenta carregar de novo. Memoizar o vazio
        # aqui envenenaria a normalização para sempre num erro transitório (ex.:
        # banco travado durante a troca de volume do apply-db).
        return {
            "mapa": {}, "espectro": {}, "cores": {},
            "presidenciais": set(), "presidenciais_canonicos": [], "ignorar": [],
        }
    return database._cache_candidatos


def get_mapa_apelidos() -> dict:
    """{alias/nome minúsculo -> nome_canonico ou None}. Fonte para normalizar_nome."""
    return _carregar_candidatos_cache()["mapa"]


def get_cores_candidatos() -> dict:
    """{nome_canonico -> cor_hex} dos candidatos com cor definida."""
    return _carregar_candidatos_cache()["cores"]


def get_candidatos_por_espectro(espectros) -> set:
    """Nomes canônicos cujo espectro está no conjunto pedido (ex.: {'esquerda','centro'})."""
    esp = _carregar_candidatos_cache()["espectro"]
    return {nome for nome, e in esp.items() if e in espectros}


def get_nomes_presidenciais() -> set:
    """Conjunto de chaves minúsculas (apelidos + canônicos) de presidenciais ativos."""
    return _carregar_candidatos_cache()["presidenciais"]


def get_presidenciais_canonicos() -> list:
    """Lista de nomes canônicos presidenciais ativos (para injeção em prompts)."""
    return _carregar_candidatos_cache()["presidenciais_canonicos"]


def get_candidatos_ignorar() -> list:
    """Lista de nomes canônicos a descartar (para injeção em prompts)."""
    return _carregar_candidatos_cache()["ignorar"]
