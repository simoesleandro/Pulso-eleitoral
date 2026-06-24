"""
Debug: testa o fluxo do UolColetor na listing page.
  1. Playwright carrega noticias.uol.com.br/eleicoes/ e salva HTML em /tmp/uol_debug.html
  2. Imprime os primeiros 2000 chars do body
  3. Extrai e lista os links com "real-time" encontrados
  4. Tenta fetch do primeiro link encontrado e mostra o que o Gemini extrai
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from collectors.uol import UolColetor

HTML_OUT = "/tmp/uol_debug.html"

collector = UolColetor(db_path=":memory:")

# --- Passo 1 & 2: Playwright + print body ---
print(f"\n[1/3] Abrindo listing via Playwright: {collector.__class__.__module__}.LISTING_URL")
html = collector.debug_listing(html_out=HTML_OUT)

if not html:
    print("ERRO: HTML vazio — Playwright falhou.")
    sys.exit(1)

print(f"\n      HTML completo: {len(html)} chars | salvo em {HTML_OUT}")

# --- Passo 3: Extrai links ---
print("\n[2/3] Extraindo links 'real-time'...")
links = collector._extract_links(html)
if not links:
    print("      Nenhum link encontrado.")
else:
    print(f"      {len(links)} link(s):")
    for lnk in links:
        print(f"        {lnk}")

# --- Passo 4: Primeira release ---
if links:
    first = links[0]
    print(f"\n[3/3] Buscando primeira release: {first}")
    html_rel = collector._get_page(first)
    if not html_rel:
        print("      ERRO: HTML vazio na release.")
    else:
        print(f"      HTML release: {len(html_rel)} chars")
        dados = collector._parse_release(html_rel, first)
        if not dados:
            print("      _parse_release() retornou lista vazia (pode ser regional — salvo em pesquisas_regionais).")
        else:
            print(f"      {len(dados)} registro(s) extraído(s):")
            for d in dados:
                print(f"        {d.get('candidato', '?'):25s} {d.get('percentual')}%  [{d.get('cargo')}]")
else:
    print("\n[3/3] Pulado — nenhum link para testar.")
