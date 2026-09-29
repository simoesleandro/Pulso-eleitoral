import os
os.environ['TESTING'] = 'True'

from pathlib import Path

import dotenv

# Importa os módulos que chamam load_dotenv() no import — se o .env real
# vazasse para a suíte, seria por aqui.
import app  # noqa: F401
import collectors.gemini_extractor  # noqa: F401
import notifier  # noqa: F401

RAIZ = Path(__file__).resolve().parent.parent

CHAVES_SENSIVEIS = (
    "GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    "ADMIN_PASS", "SECRET_KEY", "FLY_API_TOKEN",
)


def _parece_segredo(nome: str) -> bool:
    return nome in CHAVES_SENSIVEIS or nome.endswith(("_API_KEY", "_TOKEN", "_SECRET"))


def test_nenhuma_chave_sensivel_visivel_dentro_de_um_teste():
    visiveis = sorted(n for n in os.environ if _parece_segredo(n))
    assert visiveis == [], f"chaves sensíveis visíveis na suíte: {visiveis}"


def test_valores_do_env_real_nao_aparecem_no_ambiente():
    """Mesmo sob outro nome, nenhum valor sensível do .env real pode estar
    no ambiente. A mensagem de falha lista só nomes, nunca valores."""
    env_real = RAIZ / ".env"
    if not env_real.exists():  # CI não tem .env
        return
    segredos = {k: v for k, v in dotenv.dotenv_values(env_real).items()
                if v and _parece_segredo(k)}
    vazados = sorted(k for k, v in segredos.items() if v in os.environ.values())
    assert vazados == [], f"valores do .env real visíveis na suíte: {vazados}"


def test_load_dotenv_nao_carrega_o_env_real_sob_testes():
    dotenv.load_dotenv(RAIZ / ".env")
    dotenv.load_dotenv()
    # Compara só nomes: `x not in os.environ` faria o pytest imprimir o
    # ambiente inteiro (com valores) na mensagem de falha.
    nomes = set(os.environ)
    assert "GEMINI_API_KEY" not in nomes
    assert "ADMIN_PASS" not in nomes
