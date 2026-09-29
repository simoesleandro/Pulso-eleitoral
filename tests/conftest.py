import os

import dotenv
import pytest

# ─── Isolamento do ambiente ───────────────────────────────────────────────
# O .env real (chaves do Gemini, Telegram, Fly, ADMIN_PASS) nunca entra na
# suíte. Os módulos do app fazem `from dotenv import load_dotenv` e chamam no
# import (app.py, notifier.py, gemini_extractor.py, sync_db.py, ...); este
# conftest é importado antes de todos eles, então trocar o atributo do pacote
# aqui neutraliza todas as chamadas — inclusive as de módulos futuros.
def _load_dotenv_desligado(*args, **kwargs):
    return False


dotenv.load_dotenv = _load_dotenv_desligado

_CHAVES_SENSIVEIS = (
    "GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    "ADMIN_PASS", "SECRET_KEY", "FLY_API_TOKEN",
)


def _e_chave_sensivel(nome: str) -> bool:
    return nome in _CHAVES_SENSIVEIS or nome.endswith(("_API_KEY", "_TOKEN", "_SECRET"))


# Remove já no import: leituras feitas no import dos módulos (antes de
# qualquer fixture) também não podem ver chave herdada do shell/CI.
for _nome in [n for n in os.environ if _e_chave_sensivel(n)]:
    del os.environ[_nome]


@pytest.fixture(autouse=True)
def sem_chaves_de_api(monkeypatch):
    """Garante, a cada teste, que nenhuma chave de API está no ambiente —
    mesmo que um teste anterior tenha escrito em os.environ direto. Quem
    precisa de uma chave fake usa monkeypatch.setenv no próprio teste."""
    for nome in [n for n in os.environ if _e_chave_sensivel(n)]:
        monkeypatch.delenv(nome, raising=False)


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

    def fake_extrair(texto, fonte_url="", permite_regional=False):
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
            "tipo": "espontanea",
            "candidatos": candidatos
        }
        
    monkeypatch.setattr(
        'collectors.gemini_extractor.extrair_com_gemini',
        fake_extrair
    )
