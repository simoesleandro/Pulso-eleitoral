import os
os.environ['TESTING'] = 'True'

import socket

import httpx
import pytest
import requests

import collectors.gemini_extractor as gemini_extractor
import collectors.playwright_base as playwright_base


def _confirma_bloqueio(registro, trecho: str):
    """Confere que a tentativa foi registrada e a reconhece (limpa), senão a
    própria fixture reprovaria este teste no teardown."""
    assert any(trecho in t for t in registro.tentativas), registro.tentativas
    registro.tentativas.clear()


def test_requests_real_levanta_erro_explicito(bloqueio_de_rede):
    with pytest.raises(Exception, match="Teste tentou acessar a rede: https://exemplo.invalid/x"):
        requests.get("https://exemplo.invalid/x", timeout=1)
    _confirma_bloqueio(bloqueio_de_rede, "https://exemplo.invalid/x")


def test_httpx_real_levanta_erro_explicito(bloqueio_de_rede):
    with pytest.raises(Exception, match="Teste tentou acessar a rede: https://exemplo.invalid/y"):
        httpx.get("https://exemplo.invalid/y")
    _confirma_bloqueio(bloqueio_de_rede, "https://exemplo.invalid/y")


def test_socket_cru_levanta_erro_explicito(bloqueio_de_rede):
    """Rede de segurança para qualquer biblioteca fora de requests/httpx."""
    with pytest.raises(Exception, match="Teste tentou acessar a rede: exemplo.invalid"):
        socket.create_connection(("exemplo.invalid", 80), timeout=1)
    _confirma_bloqueio(bloqueio_de_rede, "exemplo.invalid")


def test_playwright_real_levanta_erro_explicito(bloqueio_de_rede):
    with pytest.raises(Exception, match="Teste tentou acessar a rede: playwright"):
        playwright_base.sync_playwright()
    _confirma_bloqueio(bloqueio_de_rede, "playwright")


def test_cliente_real_do_gemini_levanta_erro_explicito(bloqueio_de_rede):
    from google import genai
    with pytest.raises(Exception, match="Teste tentou acessar a rede: .*Gemini"):
        genai.Client(api_key="qualquer")
    _confirma_bloqueio(bloqueio_de_rede, "Gemini")


def test_tentativa_engolida_pelo_codigo_ainda_e_registrada(bloqueio_de_rede, monkeypatch):
    """fetch_with_retry captura qualquer exceção e devolve "" — a tentativa
    tem de ficar registrada mesmo assim (a fixture reprova no teardown)."""
    from collectors import utils
    monkeypatch.setattr(utils.time, "sleep", lambda s: None)
    assert utils.fetch_with_retry("https://exemplo.invalid/z", headers={}, max_retries=1) == ""
    _confirma_bloqueio(bloqueio_de_rede, "https://exemplo.invalid/z")


def test_extratores_gemini_de_governador_e_regional_estao_mockados(bloqueio_de_rede, monkeypatch):
    """Mesmo com chave configurada, os extratores não chegam no cliente real:
    o conftest os troca por fakes, como já fazia com extrair_com_gemini."""
    monkeypatch.setenv("GEMINI_API_KEY", "chave-fake")
    assert gemini_extractor.extrair_governador_rj("Eduardo Paes tem 40%") == {"candidatos": []}
    assert gemini_extractor.extrair_regional_multiestado("SP: Lula 40%") == []
    assert bloqueio_de_rede.tentativas == []


@pytest.mark.network
def test_marker_network_desliga_o_bloqueio(bloqueio_de_rede):
    """Testes marcados como network (fora da suíte padrão) não passam pelo
    bloqueio — rodam de propósito contra a rede real, com pytest -m network."""
    assert bloqueio_de_rede is None
