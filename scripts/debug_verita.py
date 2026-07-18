"""
Debug: testa o fluxo completo do VeritaCollector numa URL específica.
  1. Playwright carrega a SPA e salva HTML em logs/verita_debug.html
  2. Extrai URL do PDF
  3. Baixa o PDF e printa os primeiros 2000 chars do texto extraído
  4. Chama _parse_release() e mostra os dados estruturados
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collectors.verita import VeritaCollector

URL = "https://eleicoes26.institutoverita.com.br/pesquisa/e13762d1-0545-4e9d-b26b-1e30b966b494"
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
HTML_OUT = os.path.join(LOG_DIR, "verita_debug.html")

collector = VeritaCollector(db_path=":memory:")

# --- Passo 1: Playwright ---
print(f"\n[1/4] Abrindo SPA com Playwright: {URL}")
html = collector._get_page(URL)

if not html:
    print("ERRO: HTML vazio — Playwright falhou.")
    sys.exit(1)

with open(HTML_OUT, "w", encoding="utf-8") as f:
    f.write(html)
print(f"      HTML salvo em {HTML_OUT} ({len(html)} chars)")

# --- Passo 2: Extrai URL do PDF ---
print("\n[2/4] Extraindo URL do PDF...")
pdf_url = collector._extract_pdf_url(html)
if not pdf_url:
    print("ERRO: URL do PDF não encontrada no HTML.")
    sys.exit(1)
print(f"      PDF: {pdf_url}")

# --- Passo 3: Baixa e extrai texto do PDF ---
print("\n[3/4] Baixando e extraindo texto do PDF...")
texto = collector._download_pdf_text(pdf_url)
if not texto:
    print("ERRO: Texto vazio extraído do PDF.")
    sys.exit(1)
print(f"      Texto extraído: {len(texto)} chars")
print("\n--- primeiros 2000 chars do PDF ---")
print(texto[:2000])
print("---")

# --- Passo 4: Parse com Gemini ---
print("\n[4/4] Chamando _parse_release()...")
dados = collector._parse_release(html, URL)
if not dados:
    print("AVISO: _parse_release() retornou lista vazia.")
else:
    print(f"      {len(dados)} registro(s) extraído(s):")
    for d in dados:
        print(f"        {d.get('candidato'):25s} {d.get('percentual')}%  [{d.get('cargo')}]")
