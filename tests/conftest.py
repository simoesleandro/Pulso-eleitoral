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
    # Os extratores de governador RJ e regional multiestado também chamam o
    # Gemini — sem fake, qualquer coletor exercitado num teste (Paraná,
    # Verita, Datafolha, QuaestRegional) iria ao modelo real.
    monkeypatch.setattr(
        'collectors.gemini_extractor.extrair_governador_rj',
        lambda texto, fonte_url="": {"candidatos": []}
    )
    monkeypatch.setattr(
        'collectors.gemini_extractor.extrair_regional_multiestado',
        lambda texto, fonte_url="": []
    )


# ─── Bloqueio de rede ─────────────────────────────────────────────────────
class RedeBloqueadaEmTeste(RuntimeError):
    """Um teste da suíte padrão tentou acessar a rede real."""


class _RegistroDeRede:
    """Guarda as tentativas de acesso à rede de um teste. Muito código de
    produção engole exceções (fetch_with_retry, BaseCollector.run, os
    extratores do Gemini), então levantar não basta: a fixture reprova o
    teste no teardown se sobrou qualquer tentativa registrada. Um teste que
    provoca a tentativa de propósito limpa `tentativas` depois de conferir."""

    def __init__(self):
        self.tentativas: list[str] = []

    def bloquear(self, alvo):
        alvo = str(alvo)
        self.tentativas.append(alvo)
        raise RedeBloqueadaEmTeste(f"Teste tentou acessar a rede: {alvo}")


_HOSTS_LOCAIS = {"localhost", "127.0.0.1", "::1"}


def _host_local(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode()
    return host is None or host in _HOSTS_LOCAIS


@pytest.fixture(autouse=True)
def bloqueio_de_rede(request, monkeypatch):
    """Qualquer acesso real à rede num teste da suíte padrão levanta
    RedeBloqueadaEmTeste ("Teste tentou acessar a rede: <URL>") e reprova o
    teste. Testes marcados com @pytest.mark.network (fora da suíte padrão,
    rodam com `pytest -m network`) não passam pelo bloqueio."""
    if request.node.get_closest_marker("network"):
        yield None
        return

    import socket

    import httpx
    import requests
    from google import genai

    import collectors.playwright_base as playwright_base

    registro = _RegistroDeRede()

    def requests_bloqueado(self, method, url, *args, **kwargs):
        registro.bloquear(url)

    def httpx_bloqueado(self, req, *args, **kwargs):
        registro.bloquear(req.url)

    async def httpx_async_bloqueado(self, req, *args, **kwargs):
        registro.bloquear(req.url)

    monkeypatch.setattr(requests.sessions.Session, "request", requests_bloqueado)
    monkeypatch.setattr(httpx.Client, "send", httpx_bloqueado)
    monkeypatch.setattr(httpx.AsyncClient, "send", httpx_async_bloqueado)

    # Rede de segurança para bibliotecas fora de requests/httpx (inclui a
    # resolução DNS de app._url_segura). Loopback continua liberado.
    getaddrinfo_original = socket.getaddrinfo
    connect_original = socket.socket.connect
    connect_ex_original = socket.socket.connect_ex

    def getaddrinfo_bloqueado(host, *args, **kwargs):
        if _host_local(host):
            return getaddrinfo_original(host, *args, **kwargs)
        registro.bloquear(host)

    def _alvo_externo(sock, endereco):
        if sock.family == getattr(socket, "AF_UNIX", None) or not isinstance(endereco, tuple):
            return None
        host, porta = endereco[0], endereco[1]
        return None if _host_local(host) else f"{host}:{porta}"

    def connect_bloqueado(self, endereco):
        alvo = _alvo_externo(self, endereco)
        if alvo:
            registro.bloquear(alvo)
        return connect_original(self, endereco)

    def connect_ex_bloqueado(self, endereco):
        alvo = _alvo_externo(self, endereco)
        if alvo:
            registro.bloquear(alvo)
        return connect_ex_original(self, endereco)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo_bloqueado)
    monkeypatch.setattr(socket.socket, "connect", connect_bloqueado)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex_bloqueado)

    # Playwright: guarda atrás do mock de _get_page_playwright (mock_playwright).
    monkeypatch.setattr(playwright_base, "sync_playwright",
                        lambda *a, **k: registro.bloquear("playwright (navegador real)"))
    # Gemini: o cliente real nunca é instanciado. Testes que precisam dele
    # usam @patch('google.genai.Client'), que sobrepõe este bloqueio.
    monkeypatch.setattr(genai, "Client",
                        lambda *a, **k: registro.bloquear("cliente real do Gemini (google.genai.Client)"))

    yield registro

    if registro.tentativas:
        pytest.fail(
            "Teste tentou acessar a rede (a exceção pode ter sido engolida pelo "
            f"código): {registro.tentativas}",
            pytrace=False,
        )
