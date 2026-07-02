"""
Debug: investiga a chamada ao Gemini para a URL riomaframix (pesquisa BTG/Nexus
por macrorregião: Sul, Sudeste, Nordeste, Norte/Centro-Oeste).

Reproduz exatamente o caminho de produção:
  GazetaDoPovoColetor._get_page -> _parse_com_gemini -> extrair_com_gemini(PROMPT_EXTRACAO)

  1. Mostra o texto exato enviado no prompt (o extraído da notícia)
  2. Mostra a resposta bruta do Gemini
  3. Analisa se PROMPT_EXTRACAO reconhece dados por macrorregião
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from bs4 import BeautifulSoup
from collectors.gemini_extractor import _montar_prompt, PROMPT_EXTRACAO, extrair_com_gemini

URL = "https://www.riomaframix.com.br/noticia/eleicoes-2026-pesquisa-aponta-diferencas-regionais-na-disputa-entre-lula-e-flavio-bolsonaro/119496"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": "https://www.google.com.br/",
}

print(f"[1/3] Fetch: {URL}")
resp = requests.get(URL, headers=HEADERS, timeout=15)
html = resp.text

# Mesma limpeza de _parse_com_gemini (base.py)
soup = BeautifulSoup(html, 'lxml')
for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
    tag.decompose()
texto = soup.get_text(separator=' ', strip=True)
texto_truncado = texto[:8000]

print(f"      texto limpo: {len(texto)} chars (truncado p/ Gemini: {len(texto_truncado)} chars)")

prompt = _montar_prompt(PROMPT_EXTRACAO, texto_truncado)

out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(out_dir, exist_ok=True)
prompt_path = os.path.join(out_dir, "riomaframix_prompt.txt")
with open(prompt_path, "w", encoding="utf-8") as f:
    f.write(prompt)
print(f"      prompt completo salvo em {prompt_path}")

print("\n--- TEXTO EXATO ENVIADO (texto_truncado, sem o template do prompt) ---")
print(texto_truncado)
print("--- fim do texto ---")

print("\n[2/3] Chamando extrair_com_gemini(permite_regional=False) — caminho de produção...")
resultado = extrair_com_gemini(texto, fonte_url=URL, permite_regional=False)
print("\n--- RESPOSTA (dict já parseado) ---")
import json
print(json.dumps(resultado, ensure_ascii=False, indent=2))

print(f"\n[3/3] candidatos extraídos: {len(resultado.get('candidatos', []))}")
if not resultado.get("candidatos"):
    print("      => Gemini retornou lista vazia. Isso bate com PROMPT_EXTRACAO, que instrui:")
    print('         "IGNORE pesquisas estaduais/regionais — apenas âmbito nacional"')
    print('         "Se o texto mencionar um estado específico como contexto principal, retorne []"')
