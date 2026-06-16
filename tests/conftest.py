import pytest

@pytest.fixture(autouse=True)
def mock_playwright(monkeypatch):
    """
    Impede Playwright de rodar em testes.
    Retorna string vazia simulando falha de conexão.
    """
    monkeypatch.setattr(
        'collectors.playwright_base.PlaywrightCollector._get_page_playwright',
        lambda self, url, **kwargs: ""
    )

@pytest.fixture(autouse=True)
def mock_gemini(request, monkeypatch):
    """Impede chamadas reais ao Gemini nos testes, exceto nos testes unitários do extrator."""
    if "test_gemini_extractor" in request.node.nodeid:
        return

    def fake_extrair(texto, fonte_url=""):
        # Mini-parser simulando o Gemini para os outros testes passarem
        candidatos = []
        if "Lula" in texto:
            pct = 38.0
            if "41%" in texto:
                pct = 41.0
            candidatos.append({"nome": "Lula", "percentual": pct})
        if "Bolsonaro" in texto:
            pct = 32.0
            if "35%" in texto:
                pct = 35.0
            candidatos.append({"nome": "Bolsonaro", "percentual": pct})
        if "Ciro" in texto:
            pct = 8.0
            candidatos.append({"nome": "Ciro", "percentual": pct})
        if "Outros" in texto:
            pct = 30.0
            if "16%" in texto:
                pct = 16.0
            candidatos.append({"nome": "Outros", "percentual": pct})
            
        cargo = "presidente"
        if "governador" in texto or "governador" in (fonte_url or "").lower():
            cargo = "governador_rj"
            
        return {
            "cargo": cargo,
            "instituto": "Quaest" if "Quaest" in texto else ("Atlas" if "Atlas" in texto else "Datafolha"),
            "data": "2026-06-15" if "15 de junho" in texto else ("2026-06-10" if "10 de junho" in texto else "2026-05-06"),
            "tamanho_amostra": 2000,
            "margem_erro": 2.0,
            "candidatos": candidatos
        }
        
    monkeypatch.setattr(
        'collectors.gemini_extractor.extrair_com_gemini',
        fake_extrair
    )
