"""Laudo de microdados enviados por upload (CSV linha-a-linha de questionários).

Processamento 100% em memória — o arquivo NUNCA é gravado em disco/banco
(microdados podem conter dados pessoais, LGPD). O upload é um trust boundary:
toda validação de formato é explícita, sem assumir nada do cliente.
"""
import csv
import io
import math
from collections import Counter

from db.estatistica import (
    N_MIN_BENFORD,
    N_MIN_DIGITO_FINAL,
    divergencia_kl,
    teste_benford,
    teste_digito_final,
    teste_qui_quadrado,
)

LIMITE_LINHAS = 200_000
LIMITE_COLUNAS = 100
LIMITE_BYTES = 2 * 1024 * 1024  # espelha app.config['MAX_CONTENT_LENGTH']


class ErroMicrodados(ValueError):
    """Erro de validação do arquivo — vira HTTP 400 na rota, nunca 500."""


def _decodificar(dados: bytes) -> str:
    if not dados:
        raise ErroMicrodados("arquivo vazio")
    if len(dados) > LIMITE_BYTES:
        raise ErroMicrodados(f"arquivo maior que o limite de {LIMITE_BYTES // 1024} KB")
    if b"\x00" in dados[:4096]:
        raise ErroMicrodados("arquivo não parece ser texto (bytes nulos detectados)")
    for codec in ("utf-8-sig", "latin-1"):
        try:
            return dados.decode(codec)
        except UnicodeDecodeError:
            continue
    raise ErroMicrodados("não foi possível decodificar o arquivo (esperado UTF-8 ou Latin-1)")


def _parse_numero(texto: str) -> float | None:
    texto = texto.strip()
    if not texto:
        return None
    try:
        return float(texto.replace(",", ".") if "," in texto and "." not in texto else texto)
    except ValueError:
        return None


def _ler_linhas(texto: str) -> tuple[list[str], list[list[str]]]:
    try:
        amostra = texto[:4096]
        delimitador = csv.Sniffer().sniff(amostra, delimiters=",;\t|").delimiter
    except csv.Error:
        delimitador = ","

    leitor = csv.reader(io.StringIO(texto), delimiter=delimitador)
    try:
        cabecalho = next(leitor)
    except StopIteration:
        raise ErroMicrodados("arquivo sem cabeçalho")
    if not cabecalho or all(not c.strip() for c in cabecalho):
        raise ErroMicrodados("cabeçalho vazio")
    if len(cabecalho) > LIMITE_COLUNAS:
        raise ErroMicrodados(f"mais de {LIMITE_COLUNAS} colunas — provavelmente delimitador errado")

    linhas = []
    for i, linha in enumerate(leitor):
        if i >= LIMITE_LINHAS:
            raise ErroMicrodados(f"mais de {LIMITE_LINHAS} linhas — envie uma amostra")
        if len(linha) != len(cabecalho):
            continue  # linha malformada isolada não derruba o arquivo inteiro
        linhas.append(linha)

    if not linhas:
        raise ErroMicrodados("nenhuma linha de dados válida encontrada")

    return cabecalho, linhas


def _tipar_coluna(valores: list[str]) -> tuple[str, list]:
    """Numérica se >=90% das células não-vazias parseiam como float."""
    nao_vazios = [v for v in valores if v.strip()]
    if not nao_vazios:
        return "vazia", []
    numeros = [_parse_numero(v) for v in nao_vazios]
    validos = [n for n in numeros if n is not None]
    if len(validos) / len(nao_vazios) >= 0.9:
        return "numerica", validos
    return "categorica", nao_vazios


def _analisar_coluna(nome: str, tipo: str, valores: list,
                      referencia_col: dict | None) -> dict:
    resultado = {"nome": nome, "tipo": tipo, "n_validos": len(valores),
                 "benford": None, "digito_final": None, "aderencia": None, "kl": None}

    if tipo == "numerica":
        resultado["benford"] = teste_benford(valores)
        # dígito final só faz sentido em valores com casas decimais reais
        if any(abs(v - round(v)) > 1e-9 for v in valores):
            resultado["digito_final"] = teste_digito_final(valores)

    if tipo == "categorica" and referencia_col:
        contagem = Counter(valores)
        categorias = sorted(set(contagem) | set(referencia_col))
        observados = [contagem.get(c, 0) for c in categorias]
        total = sum(observados)
        esperados = [total * (referencia_col.get(c, 0) / 100.0) for c in categorias]
        if all(e > 0 for e in esperados):
            resultado["aderencia"] = teste_qui_quadrado(observados, esperados)
        try:
            kl = divergencia_kl(dict(contagem), referencia_col)
            resultado["kl"] = None if math.isinf(kl) else round(kl, 4)
        except ValueError:
            resultado["kl"] = None

    return resultado


def analisar_csv(dados: bytes, proporcoes_referencia: dict | None = None) -> dict:
    """Laudo de perícia sobre um CSV de microdados.

    `proporcoes_referencia`: {"coluna": {"categoria": percentual}} opcional,
    usado para aderência (qui-quadrado) e divergência KL de colunas categóricas.
    """
    texto = _decodificar(dados)
    cabecalho, linhas = _ler_linhas(texto)
    proporcoes_referencia = proporcoes_referencia or {}

    delimitador = ","
    try:
        delimitador = csv.Sniffer().sniff(texto[:4096], delimiters=",;\t|").delimiter
    except csv.Error:
        pass

    contagem_linhas = Counter(tuple(l) for l in linhas)
    duplicados = [(linha, n) for linha, n in contagem_linhas.items() if n > 1]
    linhas_duplicadas = sum(n for _, n in duplicados)

    colunas_resultado = []
    avisos = []
    for idx, nome_col in enumerate(cabecalho):
        valores_brutos = [linha[idx] for linha in linhas]
        tipo, valores = _tipar_coluna(valores_brutos)
        if tipo == "vazia":
            avisos.append(f'coluna "{nome_col}" está vazia — ignorada')
            continue
        if tipo == "numerica" and len(valores) < N_MIN_BENFORD and len(valores) < N_MIN_DIGITO_FINAL:
            avisos.append(f'coluna "{nome_col}": N insuficiente para testes numéricos')
        colunas_resultado.append(
            _analisar_coluna(nome_col, tipo, valores, proporcoes_referencia.get(nome_col)))

    for nome_ref in proporcoes_referencia:
        if nome_ref not in cabecalho:
            avisos.append(f'proporção de referência para "{nome_ref}" ignorada: coluna não existe no CSV')

    return {
        "resumo": {"linhas": len(linhas), "colunas": len(cabecalho), "delimitador": delimitador},
        "colunas": colunas_resultado,
        "duplicatas": {
            "grupos": len(duplicados),
            "linhas_duplicadas": linhas_duplicadas,
            "pct": round(linhas_duplicadas / len(linhas) * 100, 1) if linhas else 0.0,
        },
        "avisos": avisos,
    }
