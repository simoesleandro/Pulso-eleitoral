# URL Base: https://eleicoes26.institutoverita.com.br
# Listing URL: https://eleicoes26.institutoverita.com.br/
#
# Estratégia de extração:
#   1. Playwright carrega a SPA e extrai a URL do PDF embutida na página
#   2. requests baixa o PDF do Supabase
#   3. pdfplumber extrai o texto do PDF
#   4. Nacional: _parse_com_gemini(). Governador RJ: _recorte_governador()
#      manda só a tabela estimulada (percentual sobre o total) para
#      extrair_governador_rj().
#
# A listagem é filtrada pelo título do card antes de abrir cada página: só
# nacionais e RJ com governador. PDFs de outros estados são ignorados, e PDFs
# do RJ sem pergunta de governador (pesquisas de presidente no RJ) também.

import io
import re
import time
import unicodedata
from datetime import date
import requests
import pdfplumber
from bs4 import BeautifulSoup
from .base import BaseCollector, logger
from .playwright_base import PlaywrightCollector

BASE_URL = "https://eleicoes26.institutoverita.com.br"
LISTING_URL = "https://eleicoes26.institutoverita.com.br/"
INSTITUTO_ID = 9

URLS_CONHECIDAS = [
    "https://eleicoes26.institutoverita.com.br/pesquisa/e13762d1-0545-4e9d-b26b-1e30b966b494",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/pdf,*/*",
    "Referer": BASE_URL,
}


def _is_pdf_nacional(pdf_url: str) -> bool:
    filename = pdf_url.split('/')[-1].lower()
    return 'brasil' in filename or 'nacional' in filename


def _norm(texto: str) -> str:
    """Minúsculas e sem acento: toda busca em texto de PDF/listagem passa por aqui."""
    return unicodedata.normalize('NFKD', (texto or '').lower()).encode('ascii', 'ignore').decode('ascii')


# RJ no nome do arquivo ou no título do card: nome por extenso ou "rj" como token.
_RJ_RE = re.compile(r"rio[\s_-]+de[\s_-]+janeiro|(?<![a-z])rj(?![a-z])")


def _card_relevante(titulo: str) -> bool:
    """Card da listagem que pode ter PDF nacional ou de governador do RJ.
    Sem título não dá para decidir: abre (perder pesquisa é pior que abrir
    uma página a mais)."""
    t = _norm(titulo)
    if not t:
        return True
    if 'brasil' in t or 'nacional' in t:
        return True
    return bool(_RJ_RE.search(t)) and 'governador' in t


# --- Recorte da tabela de governador (relatórios SPSS do Verita) ---
# O relatório traz, por pergunta, Frequência | Porcentual (sobre o total) |
# Porcentagem válida | acumulativa, seguido de um gráfico só com a válida.
# O extrator recebe só o cabeçalho da pesquisa e, da pergunta estimulada de
# governador, "Nome Frequência Porcentual" de cada candidato: o Pulso usa o
# percentual sobre o total (ver /metodologia). Se a estrutura não for
# reconhecida, o PDF é pulado — nunca vai texto bruto, que traria a válida.

_PERGUNTA_RE = re.compile(r"^\s*pergunta\s+\d+", re.IGNORECASE | re.MULTILINE)
_PCT = r"\d{0,3},\d"
_LINHA_COMPLETA_RE = re.compile(
    rf"^(?P<nome>.*[^\d\s])\s+(?P<n>\d+)\s+(?P<pct>{_PCT})\s+{_PCT}\s+{_PCT}$")
_LINHA_NUMEROS_RE = re.compile(rf"^(?P<n>\d+)\s+(?P<pct>{_PCT})\s+{_PCT}\s+{_PCT}$")
_LINHA_TOTAL_RE = re.compile(rf"^total\s+(?P<n>\d+)\s+{_PCT}\s+100,0$", re.IGNORECASE)
_VALIDO_RE = re.compile(r"^v[aá]lido\b\s*", re.IGNORECASE)
_METADADOS = ('registro:', 'periodo:', 'amostra:', 'margem de erro:')


class TabelaNaoReconhecida(Exception):
    """A pergunta de governador existe, mas a tabela não tem a estrutura esperada."""


def _e_estimulada_governador(enunciado: str) -> bool:
    e = _norm(enunciado)
    return ('governador' in e
            and any(m in e for m in ('estes fossem os candidatos',
                                     'esses fossem os candidatos', 'estimulada'))
            and 'nao votaria' not in e and 'segunda' not in e and 'segundo turno' not in e)


def _linhas_candidatos(linhas: list[str]) -> list[tuple[str, int, str]]:
    """Linhas da tabela entre o cabeçalho de colunas e o Total. Aceita o nome
    quebrado em volta dos números ("NOME -" / "95 4,7 4,8 94,7" / "PARTIDO").
    Qualquer linha que não se encaixe derruba a tabela inteira."""
    try:
        inicio = next(i for i, l in enumerate(linhas) if 'acumulativa' in _norm(l)) + 1
    except StopIteration:
        raise TabelaNaoReconhecida("sem cabeçalho de colunas")
    cabecalho = _norm(' '.join(linhas[:inicio]))
    if 'frequencia' not in cabecalho or 'porcentual' not in cabecalho:
        raise TabelaNaoReconhecida("cabeçalho sem Frequência/Porcentual")

    linhas_tab, pendente, aguarda_sufixo, total = [], [], False, None
    for bruta in linhas[inicio:]:
        linha = _VALIDO_RE.sub('', bruta.strip()).strip()
        if not linha:
            continue
        m_total = _LINHA_TOTAL_RE.match(linha)
        if m_total:
            total = int(m_total.group('n'))
            break
        m = _LINHA_COMPLETA_RE.match(linha)
        if m:
            if pendente:
                raise TabelaNaoReconhecida(f"nome solto antes de {linha!r}")
            linhas_tab.append([m.group('nome').strip(), int(m.group('n')), m.group('pct')])
            aguarda_sufixo = False
            continue
        m = _LINHA_NUMEROS_RE.match(linha)
        if m:
            if not pendente:
                raise TabelaNaoReconhecida(f"números sem nome: {linha!r}")
            linhas_tab.append([' '.join(pendente), int(m.group('n')), m.group('pct')])
            pendente, aguarda_sufixo = [], True
            continue
        if re.search(r"\d", linha):
            raise TabelaNaoReconhecida(f"linha fora do formato: {linha!r}")
        if aguarda_sufixo:
            linhas_tab[-1][0] += ' ' + linha
            aguarda_sufixo = False
        else:
            pendente.append(linha)

    if total is None:
        raise TabelaNaoReconhecida("sem linha de Total")
    if pendente:
        raise TabelaNaoReconhecida("nome sem números no fim da tabela")
    if len(linhas_tab) < 2:
        raise TabelaNaoReconhecida("menos de 2 candidatos")
    if sum(n for _, n, _ in linhas_tab) != total:
        raise TabelaNaoReconhecida("soma das frequências não bate com o Total")
    return [tuple(l) for l in linhas_tab]


def _recorte_governador(texto: str) -> str | None:
    """Cabeçalho da pesquisa + "Nome Frequência Porcentual" da pergunta
    estimulada de governador. None se o PDF não tem pergunta de governador;
    TabelaNaoReconhecida se tem, mas a tabela não pôde ser lida."""
    marcas = list(_PERGUNTA_RE.finditer(texto))
    for i, m in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        linhas = texto[m.start():fim].splitlines()
        corte = next((j for j, l in enumerate(linhas)
                      if 'porcentagem' in _norm(l) or 'frequencia' in _norm(l)), len(linhas))
        enunciado = ' '.join(l.strip() for l in linhas[1:corte])
        if not _e_estimulada_governador(enunciado):
            continue
        candidatos = _linhas_candidatos(linhas[corte:])
        antes = texto[:marcas[0].start()].splitlines()
        metadados = [l.strip() for l in antes if any(k in _norm(l) for k in _METADADOS)]
        return "\n".join(
            metadados
            + [f"Pergunta: {enunciado}",
               "Tabela: candidato, frequência (entrevistados) e porcentual sobre o total de entrevistados"]
            + [f"{nome} {n} {pct}" for nome, n, pct in candidatos]
        )
    if 'governador' in _norm(texto):
        raise TabelaNaoReconhecida("pergunta estimulada de governador não encontrada")
    return None


# --- Infraestrutura futura: pesquisas_regionais presidenciais por UF ---
# Os PDFs estaduais do Verita cobrem governador/senador, não presidente.
# Quando o Verita publicar pesquisas presidenciais por UF, descomentar abaixo.
#
# import sqlite3
#
# ESTADO_UF = {
#     'Acre': 'AC', 'Alagoas': 'AL', 'Amapa': 'AP', 'Amazonas': 'AM',
#     'Bahia': 'BA', 'Ceara': 'CE', 'Distrito_Federal': 'DF',
#     'Espirito_Santo': 'ES', 'Goias': 'GO', 'Maranhao': 'MA',
#     'Mato_Grosso_do_Sul': 'MS', 'Mato_Grosso': 'MT', 'Minas_Gerais': 'MG',
#     'Para': 'PA', 'Paraiba': 'PB', 'Parana': 'PR', 'Pernambuco': 'PE',
#     'Piaui': 'PI', 'Rio_de_Janeiro': 'RJ', 'Rio_Grande_do_Norte': 'RN',
#     'Rio_Grande_do_Sul': 'RS', 'Rondonia': 'RO', 'Roraima': 'RR',
#     'Santa_Catarina': 'SC', 'Sao_Paulo': 'SP', 'Sergipe': 'SE',
#     'Tocantins': 'TO',
# }
# # Ordenados longest-first: Mato_Grosso_do_Sul antes de Mato_Grosso,
# # Rio_de_Janeiro antes de Janeiro (confundido como mês pelo regex).
# _ESTADO_LIST = sorted(ESTADO_UF.keys(), key=len, reverse=True)
#
# def _detectar_uf_verita(pdf_url: str) -> str | None:
#     filename = pdf_url.split('/')[-1]
#     if 'Brasil' in filename or 'Nacional' in filename:
#         return None
#     for estado in _ESTADO_LIST:
#         if estado in filename:
#             return ESTADO_UF[estado]
#     return None
#
# def _salvar_regional(self, dados: list[dict], uf: str) -> None:
#     if not dados:
#         return
#     try:
#         conn = sqlite3.connect(self.db_path)
#         for d in dados:
#             conn.execute(
#                 "INSERT OR REPLACE INTO pesquisas_regionais "
#                 "(instituto_id, data_pesquisa, uf, candidato, percentual) "
#                 "VALUES (?, ?, ?, ?, ?)",
#                 (d.get('instituto_id', self.instituto_id),
#                  d.get('data_pesquisa', ''),
#                  uf, d['candidato'], d['percentual'])
#             )
#         conn.commit()
#         conn.close()
#         self.logger.info("[Verita] Regional %s: %d intenções salvas", uf, len(dados))
#     except Exception as e:
#         self.logger.error("[Verita] Erro ao salvar regional %s: %s", uf, e)
# --- fim infraestrutura futura ---


class VeritaCollector(PlaywrightCollector, BaseCollector):
    @property
    def name(self) -> str:
        return "Verita"

    @property
    def instituto_id(self) -> int:
        return INSTITUTO_ID

    def _get_page(self, url: str, wait_selector=None) -> str:
        """SPA React — sempre usa Playwright; nunca tenta requests."""
        return self._get_page_playwright(
            url,
            wait_selector=wait_selector or "main",
            wait_seconds=5,
        )

    def _extract_links(self, html: str) -> list[str]:
        """Extrai links /pesquisa/{uuid} da listagem, só dos cards que podem ter
        PDF nacional ou de governador do RJ: cada link custa uma página
        Playwright, e a listagem passa de 90 pesquisas de todos os estados."""
        if not html:
            return []
        try:
            soup = BeautifulSoup(html, 'lxml')
            titulos: dict[str, list[str]] = {}
            for a in soup.find_all('a', href=True):
                href = a['href']
                if '/pesquisa/' in href:
                    url = href if href.startswith('http') else BASE_URL + href
                    # Cada card tem mais de um <a>; junta os textos por URL.
                    titulos.setdefault(url, []).append(a.get_text(' ', strip=True))
            unique = [u for u, t in titulos.items() if _card_relevante(' '.join(t))]
            self.logger.info("[Verita] %d de %d pesquisas da listagem podem ter PDF "
                             "nacional ou de governador RJ", len(unique), len(titulos))
            return unique
        except Exception as e:
            self.logger.warning("[Verita] Erro ao extrair links: %s", e)
            return []

    def _extract_pdf_url(self, html: str) -> str | None:
        """Extrai a URL do PDF da página de pesquisa individual."""
        try:
            soup = BeautifulSoup(html, 'lxml')
            for a in soup.find_all('a', href=True):
                if '/pesquisas/pdfs/' in a['href']:
                    return a['href']
        except Exception as e:
            self.logger.warning("[Verita] Erro ao extrair URL do PDF: %s", e)
        return None

    def _download_pdf_text(self, pdf_url: str) -> str:
        """Baixa o PDF e retorna o texto extraído com pdfplumber."""
        try:
            resp = requests.get(pdf_url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                partes = [page.extract_text() or "" for page in pdf.pages]
            return "\n".join(partes).strip()
        except Exception as e:
            self.logger.error("[Verita] Falha ao baixar/extrair PDF %s: %s", pdf_url, e)
            return ""

    def _build_items_gov(self, resultado: dict, url: str) -> list[dict]:
        candidatos = resultado.get("candidatos") or []
        if not candidatos:
            return []
        hoje = date.today().isoformat()
        data_real = resultado.get("data")
        tipo = resultado.get("tipo", "estimulada")
        return [
            {
                "instituto_id": self.instituto_id,
                "cargo": "governador_rj",
                "candidato": c["nome"],
                "percentual": c["percentual"],
                "tipo": tipo,
                "data_pesquisa": data_real or hoje,
                "data_coleta": hoje,
                "data_divulgacao": data_real,
                "tamanho_amostra": resultado.get("tamanho_amostra"),
                "margem_erro": resultado.get("margem_erro"),
                "fonte_url": url,
                "metodologia": "Espontânea" if tipo == "espontanea" else "Estimulada",
            }
            for c in candidatos
            if c.get("nome") and c.get("percentual") is not None
        ]

    def _parse_release(self, html: str, url: str) -> list[dict]:
        pdf_url = self._extract_pdf_url(html)
        if not pdf_url:
            self.logger.warning("[Verita] PDF não encontrado em %s", url)
            return []

        filename = pdf_url.split('/')[-1]
        is_rj = bool(_RJ_RE.search(_norm(filename)))

        if not _is_pdf_nacional(pdf_url) and not is_rj:
            return []

        texto = self._download_pdf_text(pdf_url)
        if not texto:
            self.logger.warning("[Verita] Texto vazio do PDF em %s", pdf_url)
            return []

        if is_rj:
            # O nome do arquivo só diz que é do RJ, não que é de governador:
            # há PDFs do RJ só de presidente (BR-02698, BR-09535), que não são
            # nacionais nem de governador e ficam de fora.
            try:
                recorte = _recorte_governador(texto)
            except TabelaNaoReconhecida as e:
                self.logger.warning(
                    "[Verita] PDF do RJ pulado: tabela de governador não reconhecida (%s): %s",
                    e, filename)
                return []
            if recorte is None:
                self.logger.info("[Verita] PDF do RJ sem pergunta de governador, pulado: %s", filename)
                return []
            self.logger.info("[Verita] PDF Governador RJ: %s (%d chars recortados)", filename, len(recorte))
            from .gemini_extractor import extrair_governador_rj
            res_gov = extrair_governador_rj(recorte, fonte_url=url)
            return self._build_items_gov(res_gov, url)

        self.logger.info("[Verita] PDF nacional: %s", filename)
        return self._parse_com_gemini(texto, url, instituto_id=self.instituto_id)

    def fetch(self) -> list[dict]:
        html_listing = self._get_page(LISTING_URL, wait_selector="a[href*='/pesquisa/']")
        links = self._extract_links(html_listing)

        seen = set(links)
        for url in URLS_CONHECIDAS:
            if url not in seen:
                links.append(url)
                seen.add(url)

        resultados = []
        for idx, link in enumerate(links):
            self.logger.info("[Verita] Pesquisa %d/%d: %s", idx + 1, len(links), link)
            # Falha num PDF não pode derrubar os outros (nem o nacional):
            # registra, conta no resumo do run() e segue para o próximo.
            try:
                html = self._get_page(link)
                resultados.extend(self._parse_release(html, link))
            except Exception as e:
                self._registrar_falha_coleta(link, e)
            time.sleep(2)

        self.logger.info("[Verita] %d registros de %d pesquisas", len(resultados), len(links))
        return resultados
