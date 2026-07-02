"""
Debug: por que a URL da Rio Mafrix falhou em /admin/coletar-url?
  1. GET simples na URL (requests, sem Playwright) e mostra os primeiros 2000 chars do HTML
  2. Verifica se o texto da notícia está no HTML estático ou se precisa de JS (Playwright)
  3. Se o texto estiver lá, mostra o texto extraído (o que seria passado pro Gemini)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from bs4 import BeautifulSoup

URL = "https://www.riomaframix.com.br/noticia/eleicoes-2026-pesquisa-aponta-diferencas-regionais-na-disputa-entre-lula-e-flavio-bolsonaro/119496"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": "https://www.google.com.br/",
}

print(f"\n[1/3] GET simples: {URL}")
try:
    resp = requests.get(URL, headers=HEADERS, timeout=15)
    print(f"      status: {resp.status_code}  |  bytes: {len(resp.content)}  |  content-type: {resp.headers.get('content-type')}")
except Exception as e:
    print(f"ERRO no GET: {e}")
    sys.exit(1)

html = resp.text
print("\n--- primeiros 2000 chars do HTML bruto ---")
print(html[:2000])
print("---")

print("\n[2/3] Verificando se o texto da notícia está no HTML estático...")
soup = BeautifulSoup(html, 'lxml')
texto = soup.get_text(separator=' ', strip=True)
print(f"      texto extraído (BeautifulSoup): {len(texto)} chars")

palavras_chave = ['lula', 'bolsonaro', 'pesquisa', 'eleitoral']
achou = [p for p in palavras_chave if p in texto.lower()]
print(f"      palavras-chave encontradas no texto: {achou or 'NENHUMA'}")

if len(texto) < 500 or not achou:
    print("      => Conteúdo real provavelmente NÃO está no HTML estático (SPA/JS). Precisa de Playwright.")
else:
    print("      => Conteúdo real ESTÁ no HTML estático. GET simples deveria bastar.")

print("\n[3/3] Texto extraído (o que seria passado pro Gemini) — primeiros 3000 chars:")
print(texto[:3000])
