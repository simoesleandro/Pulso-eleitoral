import os
import json
import logging
import time
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

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
  que ainda não declararam candidatura (Michelle Bolsonaro, Aécio Neves, etc.)
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
  ]
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

TEXTO:
{texto}
"""

MAPA_NOMES = {
    'luiz inácio lula da silva': 'Lula',
    'luiz inacio lula da silva': 'Lula',
    'lula': 'Lula',
    'flávio bolsonaro': 'Flávio Bolsonaro',
    'flavio bolsonaro': 'Flávio Bolsonaro',
    'bolsonaro': 'Flávio Bolsonaro',
    'flavio': 'Flávio Bolsonaro',
    'jair bolsonaro': None,
    'jair messias bolsonaro': None,
    'bolsonaro pai': None,
    'ronaldo caiado': 'Ronaldo Caiado',
    'romeu zema': 'Romeu Zema',
    'renan santos': 'Renan Santos',
    'renan santos (missão)': 'Renan Santos',
    'samara martins': 'Samara Martins',
    'augusto cury': 'Augusto Cury',
    'rui costa pimenta': 'Rui Costa Pimenta',
    'cabo daciolo': 'Cabo Daciolo',
    'ciro gomes': 'Ciro Gomes',
    'simone tebet': 'Simone Tebet',
    'tarcísio de freitas': 'Tarcísio de Freitas',
    'tarcisio de freitas': 'Tarcísio de Freitas',
    'eduardo paes': 'Eduardo Paes',
    'cláudio castro': 'Cláudio Castro',
    'claudio castro': 'Cláudio Castro',
    'marcelo freixo': 'Marcelo Freixo',
    'rodrigo neves': 'Rodrigo Neves',
    # Candidatos hipotéticos / não declarados — descartar
    'michelle bolsonaro': None,
    'michele bolsonaro': None,
    'michelle': None,
    'aécio neves': None,
    'aecio neves': None,
    'aldo rebelo': None,
    'eduardo bolsonaro': None,
    'camilo santana': None,
    'fernando haddad': None,
    'elmano de freitas': None,
    'acm neto': None,
    'jeronimo rodrigues': None,
    'jerônimo rodrigues': None,
    'ratinho junior': None,
    'ratinho': None,
    'carlos massa ratinho junior': None,
    'joaquim barbosa': None,
    # Abreviações comuns
    'ciro': 'Ciro Gomes',
    'simone': 'Simone Tebet',
    'tarcísio': 'Tarcísio de Freitas',
    'tarcisio': 'Tarcísio de Freitas',
}


def normalizar_nome(nome: str) -> str | None:
    """Normaliza nome do candidato para forma canônica. Retorna None para descartar."""
    chave = nome.lower().strip()
    return MAPA_NOMES.get(chave, nome)


def extrair_com_gemini(texto: str, fonte_url: str = "") -> dict:
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
        
        prompt = PROMPT_EXTRACAO.replace("{texto}", texto_truncado)
        
        MODELOS = [
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.0-flash-lite",
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
        
        candidatos = resultado.get("candidatos", [])

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
