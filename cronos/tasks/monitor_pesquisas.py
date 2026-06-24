"""
Monitor de novas pesquisas eleitorais via Google News RSS.
Roda 3x/dia (09h, 14h, 19h, seg-sex) via Windows Task Scheduler.

Fluxo:
  1. Busca RSS do Google News para cada termo de busca
  2. Filtra resultados das últimas 24h
  3. Filtra por relevância (título deve conter termo eleitoral explícito)
  4. Deduplica contra tabela monitor_urls_vistas (7 dias) no SQLite
  5. Agrupa todos os novos relevantes e envia UMA mensagem por execução
  6. Se 0 relevantes → silencioso
"""
import os
import sys
import sqlite3
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, '.env'))

import database
from notifier import send_telegram

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log_path = os.path.join(BASE_DIR, 'logs', 'monitor_pesquisas.log')
os.makedirs(os.path.join(BASE_DIR, 'logs'), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_path, encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
RSS_BASE = "https://news.google.com/rss/search?q={query}&hl=pt-BR&gl=BR&ceid=BR:pt-419"

TERMOS_BUSCA = [
    'pesquisa eleitoral 2026 presidente',
    'intenção de voto presidente 2026',
    'Datafolha eleições 2026 presidente',
    'Quaest eleições 2026 presidente',
    'Real Time Big Data eleições 2026',
    'Verita pesquisa 2026 presidente',
    'Gerp pesquisa presidente 2026',
    'Futura Inteligência pesquisa 2026',
    'Paraná Pesquisas 2026 presidente',
    'Vox Populi pesquisa 2026',
    'Atlas pesquisa eleitoral 2026',
]

# Mapeamento de keywords no título/fonte → nome canônico do instituto
INSTITUTOS_KEYWORDS: list[tuple[str, list[str]]] = [
    ('Datafolha',            ['datafolha']),
    ('Quaest',               ['quaest']),
    ('Real Time Big Data',   ['real time', 'realtime', 'real-time']),
    ('Verita',               ['verita']),
    ('Instituto Gerp',       ['gerp']),
    ('Futura Inteligência',  ['futura inteligência', 'futura inteligencia', 'futura']),
    ('Paraná Pesquisas',     ['paraná pesquisas', 'parana pesquisas']),
    ('Vox Populi',           ['vox populi']),
    ('Atlas',                ['atlas intel', 'atlas polítika', 'atlas politika', 'atlas']),
    ('Nexus',                ['nexus']),
    ('PoderData',            ['poderdata']),
    ('Ipespe',               ['ipespe']),
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/rss+xml, text/xml, */*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9',
}

JANELA_HORAS = 24          # janela RSS: só busca artigos das últimas 24h
JANELA_DEDUP_DIAS = 7      # dedup: ignora GUIDs vistos nos últimos 7 dias

TERMOS_RELEVANCIA = [
    'intenção de voto',
    'pesquisa eleitoral',
    'pesquisa presidencial',
    'presidente da república',
    '1º turno',
    '2º turno',
    'primeiro turno',
    'segundo turno',
]

# ---------------------------------------------------------------------------
# Banco — tabela de deduplicação
# ---------------------------------------------------------------------------
CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS monitor_urls_vistas (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    guid      TEXT NOT NULL UNIQUE,
    url       TEXT,
    titulo    TEXT,
    termo     TEXT,
    visto_em  TEXT DEFAULT (datetime('now', 'localtime'))
)
"""


def _init_tabela(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_TABLE)
    conn.commit()


def _ja_visto(conn: sqlite3.Connection, guid: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM monitor_urls_vistas WHERE guid = ? "
        "AND visto_em >= datetime('now', 'localtime', ?)",
        (guid, f'-{JANELA_DEDUP_DIAS} days'),
    ).fetchone() is not None


def _relevante(titulo: str) -> bool:
    """Retorna True se o título contém ao menos um termo eleitoral explícito."""
    titulo_lower = titulo.lower()
    return any(t in titulo_lower for t in TERMOS_RELEVANCIA)


def _registrar(conn: sqlite3.Connection, guid: str, url: str, titulo: str, termo: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO monitor_urls_vistas (guid, url, titulo, termo) VALUES (?, ?, ?, ?)",
        (guid, url, titulo, termo),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# RSS
# ---------------------------------------------------------------------------
def _buscar_rss(termo: str) -> list[dict]:
    """Faz GET no Google News RSS e retorna lista de items como dicts."""
    url = RSS_BASE.format(query=quote_plus(termo))
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            logger.warning("RSS HTTP %d para termo '%s'", r.status_code, termo)
            return []
        return _parse_rss(r.content, termo)
    except Exception as e:
        logger.warning("Erro ao buscar RSS para '%s': %s", termo, e)
        return []


def _parse_rss(content: bytes, termo: str) -> list[dict]:
    try:
        root = ET.fromstring(content)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        items = []
        for item in root.findall('.//item'):
            titulo  = (item.findtext('title') or '').strip()
            link    = (item.findtext('link') or '').strip()
            guid    = (item.findtext('guid') or link).strip()
            pub     = (item.findtext('pubDate') or '').strip()
            fonte_el = item.find('source')
            fonte   = fonte_el.text.strip() if fonte_el is not None and fonte_el.text else ''
            items.append({
                'titulo': titulo,
                'link':   link,
                'guid':   guid,
                'pub':    pub,
                'fonte':  fonte,
                'termo':  termo,
            })
        return items
    except Exception as e:
        logger.warning("Erro ao parsear RSS (termo '%s'): %s", termo, e)
        return []


def _recente(pub_str: str, horas: int = JANELA_HORAS) -> bool:
    """Retorna True se pubDate está dentro das últimas `horas` horas."""
    if not pub_str:
        return False
    try:
        pub_dt = parsedate_to_datetime(pub_str)
        limite = datetime.now(timezone.utc) - timedelta(hours=horas)
        return pub_dt >= limite
    except Exception:
        return False


def _resolver_url(google_link: str) -> str:
    """Segue o redirect do Google News para obter a URL real do artigo."""
    try:
        r = requests.get(google_link, headers=HEADERS, timeout=10, allow_redirects=True)
        return r.url
    except Exception:
        return google_link


# ---------------------------------------------------------------------------
# Detecção de instituto
# ---------------------------------------------------------------------------
def _detectar_instituto(titulo: str, fonte: str) -> str:
    combinado = (titulo + ' ' + fonte).lower()
    for nome, keywords in INSTITUTOS_KEYWORDS:
        if any(kw in combinado for kw in keywords):
            return nome
    return '—'


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
def _montar_mensagem_agrupada(novos: list[dict]) -> str:
    n = len(novos)
    header = f"🔍 <b>{n} nova{'s' if n > 1 else ''} pesquisa{'s' if n > 1 else ''} detectada{'s' if n > 1 else ''}</b>\n"
    linhas = [header]
    for i, it in enumerate(novos, 1):
        titulo_curto = it['titulo'][:80] + ('…' if len(it['titulo']) > 80 else '')
        instituto = it['instituto']
        label = f"{instituto} — {titulo_curto}" if instituto != '—' else titulo_curto
        linhas.append(f"{i}. {label}")
        linhas.append(f"   🔗 {it['url']}")
        if i < len(novos):
            linhas.append('')
    return '\n'.join(linhas)


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------
def run() -> None:
    logger.info("=== Monitor pesquisas iniciado ===")

    conn = sqlite3.connect(database.DB_PATH)
    _init_tabela(conn)

    novos: list[dict] = []
    vistos_sessao: set[str] = set()

    for termo in TERMOS_BUSCA:
        items = _buscar_rss(termo)
        recentes = [it for it in items if _recente(it['pub'])]
        relevantes = [it for it in recentes if _relevante(it['titulo'])]
        logger.info(
            "Termo '%s': %d items | %d recentes (24h) | %d relevantes",
            termo, len(items), len(recentes), len(relevantes),
        )

        for it in relevantes:
            guid = it['guid']
            if guid in vistos_sessao:
                continue
            if _ja_visto(conn, guid):
                continue

            vistos_sessao.add(guid)

            url_real = _resolver_url(it['link']) if it['link'] else it['guid']
            instituto = _detectar_instituto(it['titulo'], it['fonte'])

            novos.append({
                'titulo':    it['titulo'],
                'instituto': instituto,
                'fonte':     it['fonte'],
                'url':       url_real,
                'guid':      guid,
                'termo':     termo,
            })

    # Registra todos no banco antes de enviar (evita re-envio se Telegram falhar parcialmente)
    for it in novos:
        _registrar(conn, it['guid'], it['url'], it['titulo'], it['termo'])
    conn.close()

    if not novos:
        logger.info("=== Monitor finalizado: nenhum resultado relevante novo ===")
        return

    logger.info("=== %d novo(s) relevante(s) encontrado(s) ===", len(novos))
    for it in novos:
        logger.info("[NOVO] %s | %s", it['instituto'], it['titulo'][:70])

    msg = _montar_mensagem_agrupada(novos)
    enviado = send_telegram(msg)
    status = "✓ Telegram enviado" if enviado else "⚠ Telegram falhou"
    logger.info("=== Monitor finalizado: %d novo(s) | %s ===", len(novos), status)


if __name__ == '__main__':
    run()
