import os
import json
import logging
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
- NÃO extraia aprovação de governo, apenas intenção de voto
- Cargo deve ser "presidente", "governador_rj", "governador_sp" etc
- Se o texto for sobre aprovação/rejeição de governo sem intenção de voto, retorne lista vazia

Retorne SOMENTE JSON válido, sem markdown, sem explicação:
{
  "cargo": "presidente",
  "instituto": "nome do instituto mencionado",
  "data": "YYYY-MM-DD ou null",
  "tamanho_amostra": numero ou null,
  "margem_erro": numero ou null,
  "candidatos": [
    {"nome": "Nome Candidato", "percentual": 38.0},
    {"nome": "Nome Candidato 2", "percentual": 32.0}
  ]
}

Se não encontrar intenções de voto com percentuais explícitos, retorne:
{"candidatos": []}

TEXTO:
{texto}
"""

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
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        
        raw = response.text.strip()
        start_idx = raw.find("{")
        end_idx = raw.rfind("}")
        if start_idx != -1 and end_idx != -1:
            raw = raw[start_idx:end_idx+1]
            
        resultado = json.loads(raw.strip())
        
        n = len(resultado.get("candidatos", []))
        logger.info(f"Gemini extraiu {n} candidatos de {fonte_url}")
        return resultado
        
    except json.JSONDecodeError as e:
        logger.warning(f"Gemini retornou JSON inválido: {e}")
        return {"candidatos": []}
    except Exception as e:
        logger.error(f"Gemini erro: {e}")
        return {"candidatos": []}
