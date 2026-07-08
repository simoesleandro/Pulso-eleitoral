import os
import json
import logging
import time
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _to_pct(valor) -> float | None:
    """Coage percentual vindo do LLM: aceita int/float e strings '38', '38%',
    '38,5'. Retorna None se não for coercível ou estiver fora de [0, 100]."""
    if valor is None:
        return None
    if isinstance(valor, bool):
        return None
    try:
        if isinstance(valor, str):
            valor = valor.strip().replace('%', '').replace(',', '.').strip()
        pct = float(valor)
    except (ValueError, TypeError):
        return None
    return pct if 0.0 <= pct <= 100.0 else None

PROMPT_EXTRACAO = """
Você é um extrator de dados de pesquisas eleitorais brasileiras.
Analise o texto abaixo e extraia APENAS intenções de voto com percentuais EXPLÍCITOS.

REGRAS CRÍTICAS:
- Extraia SOMENTE quando houver percentual numérico explícito (ex: "38%", "38 por cento")
- NÃO invente percentuais — se não há número claro, não inclua o candidato
- Extraia SOMENTE intenções de voto no 1º turno NACIONAL
- IGNORE percentuais de 2º turno (geralmente acima de 50% em confronto direto)
- IGNORE pesquisas estaduais/regionais — apenas âmbito nacional
- IGNORE aprovação/rejeição de governo
- Se o release apresentar múltiplos cenários de 1º turno, escolha o cenário
  com MAIS candidatos listados
- Se o release misturar 1º e 2º turno, extraia APENAS o cenário de 1º turno
- IGNORE: cenários de 2º turno, cenários hipotéticos com candidatos
  que ainda não declararam candidatura ({lista_ignorar})
- Percentuais válidos para presidente: entre 1% e 60% por candidato
- A soma dos percentuais dos candidatos deve ser <= 100%
- Se a soma ultrapassar 100%, os percentuais provavelmente são de
  cenários diferentes — retorne {"candidatos": []}
- Se a soma for maior que 120%, provavelmente são cenários de 2º turno — retorne []
- Cargo deve ser "presidente", "governador_rj", "governador_sp" etc
- Se o texto for sobre aprovação/rejeição de governo sem intenção de voto, retorne lista vazia
- IGNORE pesquisas estaduais — só extraia se for âmbito NACIONAL (Brasil inteiro)
- Se o texto mencionar um estado específico como contexto principal da pesquisa,
  retorne {"candidatos": []}
- Pesquisas nacionais geralmente mencionam "todo o Brasil", "nível nacional",
  "eleitorado brasileiro" ou não mencionam estado nenhum

EXTRAÇÃO DE "% PODE MUDAR DE VOTO":
- Se o texto mencionar EXPLICITAMENTE o percentual de eleitores que podem
  mudar de voto / ainda podem trocar de candidato / não têm voto decidido
  até a eleição (ex.: "34% dos eleitores podem mudar de voto até outubro"),
  capture esse número em "pct_pode_mudar_voto"
- Se não houver menção clara e explícita desse dado no texto, retorne
  "pct_pode_mudar_voto": null — NUNCA infira, estime ou calcule esse valor
  a partir de indecisos/outros/nulos

DETERMINAÇÃO DO CAMPO "tipo":
Retorne "espontanea" ou "estimulada" com base nas pistas abaixo:

  "espontanea" quando:
  - O texto usa palavras como "espontânea", "sem lista", "sem apresentação de nomes",
    "de cabeça", "citou espontaneamente", "mencionou sem estímulo"
  - Os candidatos principais (Lula, Flávio Bolsonaro) aparecem com percentuais
    anormalmente baixos para corrida bipolar: Flávio abaixo de 25% e/ou
    muitos candidatos menores com 1–5% cada
  - REGRA FORTE: se Flávio Bolsonaro aparecer abaixo de 25% em corrida presidencial
    2026, classifique como "espontanea" — EXCETO se o texto usar explicitamente
    as palavras "estimulada", "com lista" ou "ao ouvir os nomes"
  - A soma dos percentuais é notavelmente baixa (abaixo de 70%), indicando
    alto percentual de "não sabe / não respondeu" implícito

  "estimulada" quando:
  - O texto usa explicitamente palavras como "estimulada", "com lista",
    "ao ouvir os nomes", "escolheria entre", "ao ser apresentada lista"
  - Os candidatos principais estão acima de 25% cada em corrida bipolar

  Na dúvida, analise os percentuais: soma abaixo de 80% ou candidato principal
  abaixo de 25% indica "espontanea"; caso contrário, use "estimulada".

Retorne SOMENTE JSON válido, sem markdown, sem explicação:
{
  "cargo": "presidente",
  "tipo": "espontanea",
  "instituto": "nome do instituto mencionado",
  "data": "YYYY-MM-DD ou null",
  "tamanho_amostra": numero ou null,
  "margem_erro": extraia de expressões como:
    - "margem de erro de X pontos percentuais"
    - "margem de erro é de X%"
    - "erro amostral de X pontos"
    - "intervalo de confiança de 95%, margem de X pp"
    Se não encontrar, retorne null — nunca retorne 0,
  "candidatos": [
    {"nome": "Nome Candidato", "percentual": 38.0},
    {"nome": "Nome Candidato 2", "percentual": 32.0}
  ],
  "rejeicoes": [
    {"nome": "Nome Candidato", "percentual": 46.0}
  ],
  "pct_pode_mudar_voto": numero ou null
}

EXTRAÇÃO DE REJEIÇÃO:
- Se o release incluir seção de rejeição / voto negativo / "não votaria de jeito nenhum" /
  "rejeitam votar", extraia em "rejeicoes" os candidatos com percentual explícito.
- Exemplos de frases que indicam rejeição:
  - "48% dizem que não votariam de jeito nenhum no senador"
  - "46% rejeitam votar no atual presidente"
  - "Fulano tem rejeição de 23%"
- Se não houver seção de rejeição no texto, retorne "rejeicoes": []
- NÃO confunda rejeição de candidato com aprovação/rejeição de governo

EXTRAÇÃO DE NOMES DE CANDIDATOS:
- Extraia o nome completo e correto
- Exemplos de nomes brasileiros frequentes:
  - "Rui Costa Pimenta" (não "ii Costa Pimenta")
  - "Flávio Bolsonaro" (com acento)
  - "Ronaldo Caiado"
- Se o nome aparecer truncado ou com erro, corrija com base no contexto
- Nunca retorne nome com menos de 3 caracteres

Se não encontrar intenções de voto com percentuais explícitos, retorne:
{"candidatos": [], "rejeicoes": []}

Ano de referência: 2026. Se o texto mencionar apenas mês e dia sem ano, assuma 2026.

TEXTO:
{texto}
"""

PROMPT_EXTRACAO_REGIONAL = """
Você é um extrator de dados de pesquisas eleitorais brasileiras.
Analise o texto abaixo e extraia APENAS intenções de voto com percentuais EXPLÍCITOS.

REGRAS CRÍTICAS:
- Extraia SOMENTE quando houver percentual numérico explícito (ex: "38%", "38 por cento")
- NÃO invente percentuais — se não há número claro, não inclua o candidato
- Extraia intenções de voto no 1º turno (nacional ou estadual)
- IGNORE percentuais de 2º turno (geralmente acima de 50% em confronto direto)
- IGNORE aprovação/rejeição de governo
- Se o release apresentar múltiplos cenários de 1º turno, escolha o cenário
  com MAIS candidatos listados
- Se o release misturar 1º e 2º turno, extraia APENAS o cenário de 1º turno
- IGNORE: cenários de 2º turno, cenários hipotéticos com candidatos
  que ainda não declararam candidatura ({lista_ignorar})
- Percentuais válidos para presidente: entre 1% e 60% por candidato
- A soma dos percentuais dos candidatos deve ser <= 100%
- Se a soma ultrapassar 100%, os percentuais provavelmente são de
  cenários diferentes — retorne {"candidatos": []}
- Se a soma for maior que 120%, provavelmente são cenários de 2º turno — retorne []
- Cargo deve ser "presidente", "governador_rj", "governador_sp" etc
- Se o texto for sobre aprovação/rejeição de governo sem intenção de voto, retorne lista vazia

EXTRAÇÃO DE "% PODE MUDAR DE VOTO":
- Se o texto mencionar EXPLICITAMENTE o percentual de eleitores que podem
  mudar de voto / ainda podem trocar de candidato / não têm voto decidido
  até a eleição (ex.: "34% dos eleitores podem mudar de voto até outubro"),
  capture esse número em "pct_pode_mudar_voto"
- Se não houver menção clara e explícita desse dado no texto, retorne
  "pct_pode_mudar_voto": null — NUNCA infira, estime ou calcule esse valor
  a partir de indecisos/outros/nulos

DETERMINAÇÃO DO CAMPO "tipo":
Retorne "espontanea" ou "estimulada" com base nas pistas abaixo:

  "espontanea" quando:
  - O texto usa palavras como "espontânea", "sem lista", "sem apresentação de nomes",
    "de cabeça", "citou espontaneamente", "mencionou sem estímulo"
  - Os candidatos principais (Lula, Flávio Bolsonaro) aparecem com percentuais
    anormalmente baixos para corrida bipolar: Flávio abaixo de 25% e/ou
    muitos candidatos menores com 1–5% cada
  - REGRA FORTE: se Flávio Bolsonaro aparecer abaixo de 25% em corrida presidencial
    2026, classifique como "espontanea" — EXCETO se o texto usar explicitamente
    as palavras "estimulada", "com lista" ou "ao ouvir os nomes"
  - A soma dos percentuais é notavelmente baixa (abaixo de 70%), indicando
    alto percentual de "não sabe / não respondeu" implícito

  "estimulada" quando:
  - O texto usa explicitamente palavras como "estimulada", "com lista",
    "ao ouvir os nomes", "escolheria entre", "ao ser apresentada lista"
  - Os candidatos principais estão acima de 25% cada em corrida bipolar

  Na dúvida, analise os percentuais: soma abaixo de 80% ou candidato principal
  abaixo de 25% indica "espontanea"; caso contrário, use "estimulada".

Retorne SOMENTE JSON válido, sem markdown, sem explicação:
{
  "cargo": "presidente",
  "tipo": "espontanea",
  "instituto": "nome do instituto mencionado",
  "data": "YYYY-MM-DD ou null",
  "tamanho_amostra": numero ou null,
  "margem_erro": extraia de expressões como:
    - "margem de erro de X pontos percentuais"
    - "margem de erro é de X%"
    - "erro amostral de X pontos"
    - "intervalo de confiança de 95%, margem de X pp"
    Se não encontrar, retorne null — nunca retorne 0,
  "candidatos": [
    {"nome": "Nome Candidato", "percentual": 38.0},
    {"nome": "Nome Candidato 2", "percentual": 32.0}
  ],
  "pct_pode_mudar_voto": numero ou null
}

EXTRAÇÃO DE NOMES DE CANDIDATOS:
- Extraia o nome completo e correto
- Exemplos de nomes brasileiros frequentes:
  - "Rui Costa Pimenta" (não "ii Costa Pimenta")
  - "Flávio Bolsonaro" (com acento)
  - "Ronaldo Caiado"
- Se o nome aparecer truncado ou com erro, corrija com base no contexto
- Nunca retorne nome com menos de 3 caracteres

Se não encontrar intenções de voto com percentuais explícitos, retorne:
{"candidatos": []}

Ano de referência: 2026. Se o texto mencionar apenas mês e dia sem ano, assuma 2026.

TEXTO:
{texto}
"""

# MAPA_NOMES, CANDIDATOS_PRESIDENCIAIS_2026 e as listas de nomes nos prompts
# foram unificados na tabela `candidatos` (fonte única de verdade). Os acessores
# abaixo leem dela via database (com cache). Se o banco ainda não tiver a tabela,
# os fallbacks deixam a normalização como no-op (nome cru) — comportamento seguro.

def _mapa_nomes() -> dict:
    """{alias minúsculo -> nome_canonico | None}. Vazio se a tabela não existir."""
    try:
        from database import get_mapa_apelidos
        return get_mapa_apelidos()
    except Exception:
        return {}


def _presidenciais() -> set:
    """Conjunto de chaves minúsculas de candidatos presidenciais ativos."""
    try:
        from database import get_nomes_presidenciais
        return get_nomes_presidenciais()
    except Exception:
        return set()


def _montar_prompt(template: str, texto: str) -> str:
    """Injeta no template o texto e as listas de candidatos vindas da tabela."""
    try:
        from database import get_presidenciais_canonicos, get_candidatos_ignorar
        presidenciais = ", ".join(get_presidenciais_canonicos())
        ignorar = ", ".join(get_candidatos_ignorar())
    except Exception:
        presidenciais, ignorar = "", ""
    if not presidenciais:
        presidenciais = "Lula, Flávio Bolsonaro, Tarcísio de Freitas, Ronaldo Caiado, Romeu Zema"
    if not ignorar:
        ignorar = "Michelle Bolsonaro, Aécio Neves"
    return (template
            .replace("{lista_presidenciais}", presidenciais)
            .replace("{lista_ignorar}", ignorar)
            .replace("{texto}", texto))

PROMPT_MULTIESTADO = """
Você é um extrator de dados de pesquisas eleitorais brasileiras por estado.
Analise o texto abaixo e extraia intenções de voto de 1º turno para PRESIDENTE DA REPÚBLICA, agrupadas por estado.

REGRA FUNDAMENTAL — CARGO:
- Extraia EXCLUSIVAMENTE dados de PRESIDENTE DA REPÚBLICA (eleição presidencial nacional de 2026)
- IGNORE COMPLETAMENTE qualquer dado de governador, senador, deputado federal, deputado estadual,
  prefeito ou qualquer outro cargo que não seja presidente da república
- Se o texto misturar presidente e governador, extraia APENAS os dados presidenciais
- Candidatos a GOVERNADOR nunca devem aparecer no resultado — mesmo que tenham percentuais explícitos

CANDIDATOS PRESIDENCIAIS CONHECIDOS (extraia apenas estes e outros claramente presidenciais):
{lista_presidenciais}

CANDIDATOS A GOVERNADOR — NUNCA EXTRAIR (exemplos de nomes a ignorar):
Juliana Brizola, Luciano Zucco, Eduardo Leite, Ratinho Jr., Raquel Lyra,
Jerônimo Rodrigues, Adriana Accorsi, Marconi Perillo, Eduardo Paes (governador),
Cláudio Castro, qualquer candidato identificado como candidato a governador estadual

REGRAS ADICIONAIS:
- Extraia SOMENTE percentuais de 1º turno com valor numérico explícito (ex: "38%", "38 por cento")
- NÃO invente percentuais — se não há número claro, não inclua
- IGNORE percentuais de 2º turno: confronto direto entre 2 candidatos onde um aparece > 50%
  e outro em torno de 30-48% somando ~100%; frases como "venceria com X% a Y%"
- IGNORE "Cenários alternativos" ou "Cenário com [nome]" — esses blocos são projeções, não intenções reais
- IGNORE aprovação/rejeição de governo, avaliação de mandato, margens de vantagem (ex: "+20 pontos")
- IGNORE dados históricos de eleições passadas (2018, 2022) — extraia APENAS o cenário atual (2026)
- Use SEMPRE o nome do candidato, nunca o nome do partido (ex: se o texto disser "PT tem 42%", extraia como Lula)
- Percentuais válidos por candidato presidencial no 1º turno: entre 1% e 80%
- Use a sigla de UF em maiúsculas: SP, MG, RJ, BA, RS, PR, GO, CE, PE, PA, DF, SC, etc.

Retorne SOMENTE JSON válido, sem markdown, sem explicação:
{
  "data": "YYYY-MM-DD ou null",
  "estados": [
    {
      "uf": "SP",
      "candidatos": [
        {"nome": "Nome Candidato Presidencial", "percentual": 45.0},
        {"nome": "Nome Candidato Presidencial 2", "percentual": 40.0}
      ]
    }
  ]
}

Se não encontrar dados presidenciais estaduais com percentuais explícitos, retorne:
{"data": null, "estados": []}

Ano de referência: 2026.

TEXTO:
{texto}
"""


def normalizar_nome(nome: str) -> str | None:
    """Normaliza nome do candidato para forma canônica usando a tabela candidatos.

    Retorna o nome canônico se o apelido for conhecido, None se for um candidato
    marcado para descarte (hipotético/inelegível), ou o próprio nome se desconhecido.
    """
    if not nome:
        return None
    chave = nome.lower().strip()
    mapa = _mapa_nomes()
    if chave in mapa:
        return mapa[chave]  # nome_canonico ou None (descartar)
    return nome


def extrair_regional_multiestado(texto: str, fonte_url: str = "") -> list[dict]:
    """
    Extrai intenções de voto de 1º turno agrupadas por estado a partir de texto
    que cobre múltiplos estados numa mesma página.

    Returns:
        Lista de dicts: {"uf": "SP", "candidato": "Lula", "percentual": 45.0, "data": "YYYY-MM-DD"}
        Em caso de erro ou sem dados: []
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY não configurada")
        return []

    try:
        client = genai.Client(api_key=api_key)
        texto_truncado = texto[:8000]
        prompt = _montar_prompt(PROMPT_MULTIESTADO, texto_truncado)
        presidenciais = _presidenciais()

        MODELOS = [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
        ]

        raw = None
        modelo_usado = None

        for modelo in MODELOS:
            for tentativa in range(2):
                try:
                    response = client.models.generate_content(model=modelo, contents=prompt)
                    raw = response.text.strip()
                    modelo_usado = modelo
                    break
                except Exception as e:
                    if '503' in str(e) and tentativa == 0:
                        time.sleep(5)
                    else:
                        logger.warning(f"Falha no modelo {modelo} tentativa {tentativa+1}: {e}")
                        break
            if raw is not None:
                break

        if raw is None:
            logger.error("extrair_regional_multiestado: todos os modelos falharam")
            return []

        start_idx = raw.find("{")
        end_idx = raw.rfind("}")
        if start_idx == -1 or end_idx == -1:
            return []
        resultado = json.loads(raw[start_idx:end_idx + 1])

        data_pesquisa = resultado.get("data") or ""
        estados = resultado.get("estados", [])

        registros = []
        descartados = []
        for estado in estados:
            uf = (estado.get("uf") or "").upper().strip()
            if not uf or len(uf) != 2:
                continue
            for c in estado.get("candidatos", []):
                if not isinstance(c, dict):
                    continue
                nome_raw = c.get("nome", "")
                percentual = _to_pct(c.get("percentual"))
                if not nome_raw or percentual is None:
                    continue
                nome = normalizar_nome(nome_raw)
                if nome is None:
                    continue
                if not (1.0 <= percentual <= 80.0):
                    continue
                # Filtro de segurança: aceita só candidatos presidenciais conhecidos
                nome_check_raw = nome_raw.lower().strip()
                nome_check_norm = (nome or "").lower().strip()
                if nome_check_raw not in presidenciais and \
                   nome_check_norm not in presidenciais:
                    descartados.append(f"{nome_raw} ({uf})")
                    continue
                registros.append({
                    "uf": uf,
                    "candidato": nome,
                    "percentual": percentual,
                    "data": data_pesquisa,
                })

        if descartados:
            logger.warning(f"extrair_regional_multiestado: descartados {len(descartados)} não-presidenciais: {descartados[:10]}")
        logger.info(f"extrair_regional_multiestado: {len(registros)} registros de {len(estados)} estados via {modelo_usado}")
        return registros

    except json.JSONDecodeError as e:
        logger.warning(f"extrair_regional_multiestado JSON inválido: {e}")
        return []
    except Exception as e:
        logger.error(f"extrair_regional_multiestado erro: {e}")
        return []


def extrair_com_gemini(texto: str, fonte_url: str = "", permite_regional: bool = False) -> dict:
    """
    Usa Gemini Flash para extrair dados estruturados de texto de pesquisa eleitoral.
    
    Returns:
        dict com chaves: cargo, instituto, data, tamanho_amostra,
                         margem_erro, candidatos (lista)
        Em caso de erro: {"candidatos": []}
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY não configurada")
        return {"candidatos": []}
    
    try:
        client = genai.Client(api_key=api_key)
        
        # Limita texto para evitar tokens excessivos
        texto_truncado = texto[:8000]

        template = PROMPT_EXTRACAO_REGIONAL if permite_regional else PROMPT_EXTRACAO
        prompt = _montar_prompt(template, texto_truncado)
        
        MODELOS = [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
        ]
        
        raw = None
        modelo_usado = None
        
        for modelo in MODELOS:
            max_retries = 2
            sucesso_modelo = False
            for tentativa in range(max_retries):
                try:
                    response = client.models.generate_content(
                        model=modelo,
                        contents=prompt
                    )
                    raw = response.text.strip()
                    modelo_usado = modelo
                    sucesso_modelo = True
                    break  # sucesso, sai do loop do modelo
                except Exception as e:
                    if '503' in str(e) and tentativa < max_retries - 1:
                        wait = 5 * (tentativa + 1)
                        logger.warning(f"Gemini 503 para {modelo}, tentativa {tentativa+1}/{max_retries}, aguardando {wait}s")
                        time.sleep(wait)
                    else:
                        logger.warning(f"Falha no modelo {modelo} na tentativa {tentativa+1}/{max_retries}: {e}")
                        break  # passa para o próximo modelo
            if sucesso_modelo:
                break
                
        if raw is None:
            logger.error("Todos os modelos em cascata falharam.")
            return {"candidatos": []}
        
        start_idx = raw.find("{")
        end_idx = raw.rfind("}")
        if start_idx != -1 and end_idx != -1:
            raw = raw[start_idx:end_idx+1]
            
        resultado = json.loads(raw.strip())
        resultado.setdefault("pct_pode_mudar_voto", None)

        candidatos_brutos = resultado.get("candidatos", [])

        # Saneamento: candidato sem nome/percentual coercível é ignorado
        # individualmente, sem descartar a pesquisa inteira.
        candidatos = []
        for c in candidatos_brutos:
            if not isinstance(c, dict):
                logger.warning(f"Candidato malformado ignorado: {c!r}")
                continue
            nome = c.get("nome")
            pct = _to_pct(c.get("percentual"))
            if not nome or pct is None:
                logger.warning(f"Candidato malformado ignorado: {c!r}")
                continue
            c["percentual"] = pct
            candidatos.append(c)

        # Cenário multipolar (1º turno): percentuais > 50% são inválidos
        if len(candidatos) > 2:
            candidatos = [c for c in candidatos if c.get("percentual", 0) <= 50]

        # Descarta candidatos com nome mapeado para None (hipotéticos / não declarados)
        candidatos = [c for c in candidatos if normalizar_nome(c["nome"]) is not None]

        # Normaliza nomes para forma canônica
        for c in candidatos:
            c["nome"] = normalizar_nome(c["nome"])

        # Remove duplicatas após normalização (mesmo nome → mantém maior percentual)
        vistos = {}
        for c in candidatos:
            nome = c["nome"]
            if nome not in vistos or c["percentual"] > vistos[nome]["percentual"]:
                vistos[nome] = c
        candidatos = list(vistos.values())

        resultado["candidatos"] = candidatos
        
        n = len(resultado.get("candidatos", []))
        logger.info(f"Gemini extraiu {n} candidatos usando {modelo_usado}")
        return resultado
        
    except json.JSONDecodeError as e:
        logger.warning(f"Gemini retornou JSON inválido: {e}")
        return {"candidatos": []}
    except Exception as e:
        logger.error(f"Gemini erro: {e}")
        return {"candidatos": []}
