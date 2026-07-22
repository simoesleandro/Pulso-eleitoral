"""Download e parsing do dataset de pesquisas eleitorais do TSE.

Este módulo não toca no banco — recebe bytes, devolve dicts. Isso mantém o
parsing testável com fixture, sem rede e sem SQLite.

Formato do arquivo (verificado em 2026-07-22): ZIP com um CSV por UF mais
BRASIL.csv, encoding latin-1, delimitador ';', sentinela '#NULO#' para campo
vazio, datas em 'YYYY-MM-DD HH:MM:SS'. O arquivo é regerado diariamente.
"""
import csv
import io
import re
import zipfile

import requests

URL_TSE = (
    "https://cdn.tse.jus.br/estatistica/sead/odsele/"
    "pesquisa_eleitoral/pesquisa_eleitoral_2026.zip"
)

ARQUIVO_PRESIDENTE = "pesquisa_eleitoral_2026_BRASIL.csv"
ARQUIVO_GOVERNADOR_RJ = "pesquisa_eleitoral_2026_RJ.csv"

_NULO = "#NULO#"

# "município de X" onde X não é a capital indica pesquisa municipal. A capital
# ("município do Rio de Janeiro") é ambígua e tratada como estadual, porque o
# custo de excluir uma pesquisa estadual válida é maior que o de incluir uma
# municipal da capital — que a curadoria manual ainda filtra.
_RE_MUNICIPIO = re.compile(r"munic[íi]pio (?:de|do|da) ([a-zà-ÿ\s]{3,40})", re.IGNORECASE)


def baixar_zip(url: str = URL_TSE) -> bytes:
    """Baixa o ZIP do TSE. Levanta requests.HTTPError se a CDN falhar."""
    resposta = requests.get(url, timeout=120)
    resposta.raise_for_status()
    return resposta.content


def extrair_csv(zip_bytes: bytes, nome: str) -> bytes:
    """Extrai um CSV de dentro do ZIP pelo nome."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        return z.read(nome)


def _limpar(valor: str | None) -> str:
    """Normaliza o sentinela '#NULO#' e espaços para string vazia."""
    if valor is None:
        return ""
    valor = valor.strip()
    return "" if valor == _NULO else valor


def _data_curta(valor: str) -> str:
    """'2026-03-31 00:00:00' -> '2026-03-31'."""
    return _limpar(valor)[:10]


def detectar_abrangencia(metodologia: str, dado_municipio: str) -> str:
    """Classifica a abrangência a partir do texto livre do registro.

    Heurística deliberadamente conservadora: só marca 'municipal' quando
    encontra menção explícita a um município que não seja a capital. Falso
    negativo (municipal classificada como estadual) apenas mantém a pesquisa na
    fila para a curadoria decidir; falso positivo a esconderia sem aviso.
    """
    texto = f"{metodologia} {dado_municipio}".lower()
    achado = _RE_MUNICIPIO.search(texto)
    if achado:
        municipio = achado.group(1).strip()
        if not municipio.startswith("rio de janeiro"):
            return "municipal"
    return "estadual"


def parsear_csv(conteudo: bytes, cargo: str) -> list[dict]:
    """Parseia o CSV do TSE e devolve os registros do cargo pedido.

    cargo: 'presidente' (exige SG_UE == 'BR') ou 'governador_rj'.
    """
    # `ue_exigida` não é redundante com a escolha do arquivo: se o arquivo
    # errado for passado, sem esse filtro entrariam governadores de outros
    # estados como se fossem do RJ, em silêncio.
    if cargo == "presidente":
        termo, ue_exigida = "Presidente", "BR"
    elif cargo == "governador_rj":
        termo, ue_exigida = "Governador", "RJ"
    else:
        raise ValueError(f"cargo não suportado: {cargo!r}")

    texto = conteudo.decode("latin-1")
    leitor = csv.DictReader(io.StringIO(texto), delimiter=";")

    registros = []
    for linha in leitor:
        if termo not in linha.get("DS_CARGO", ""):
            continue
        if linha.get("SG_UE") != ue_exigida:
            continue

        quantidade = _limpar(linha.get("QT_ENTREVISTADO"))
        if not quantidade.isdigit() or int(quantidade) <= 0:
            continue

        fantasia = _limpar(linha.get("NM_EMPRESA_FANTASIA"))
        razao = _limpar(linha.get("NM_EMPRESA"))

        registros.append({
            "protocolo": _limpar(linha.get("NR_PROTOCOLO_REGISTRO")),
            "cargo": cargo,
            "cnpj_empresa": _limpar(linha.get("NR_CNPJ_EMPRESA")),
            "nome_empresa": fantasia or razao,
            "data_inicio": _data_curta(linha.get("DT_INICIO_PESQUISA", "")),
            "data_fim": _data_curta(linha.get("DT_FIM_PESQUISA", "")),
            "data_divulgacao": _data_curta(linha.get("DT_DIVULGACAO", "")) or None,
            "qt_entrevistado": int(quantidade),
            "abrangencia": "nacional" if cargo == "presidente" else detectar_abrangencia(
                _limpar(linha.get("DS_METODOLOGIA_PESQUISA")),
                _limpar(linha.get("DS_DADO_MUNICIPIO")),
            ),
        })

    return registros
