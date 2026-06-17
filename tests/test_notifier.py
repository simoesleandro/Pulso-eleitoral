import pytest
from unittest.mock import patch, MagicMock
from notifier import send_telegram, montar_mensagem_coleta, montar_mensagem_alerta

def test_send_telegram_sem_config():
    """Testa que send_telegram retorna False e não crasha se não houver token ou chat id configurados."""
    with patch('notifier.BOT_TOKEN', None), patch('notifier.CHAT_ID', None):
        res = send_telegram("Mensagem de teste")
        assert res is False

    with patch('notifier.BOT_TOKEN', "token"), patch('notifier.CHAT_ID', None):
        res = send_telegram("Mensagem de teste")
        assert res is False

    with patch('notifier.BOT_TOKEN', None), patch('notifier.CHAT_ID', "chat_id"):
        res = send_telegram("Mensagem de teste")
        assert res is False

@patch('notifier.requests.post')
def test_send_telegram_mock(mock_post):
    """Testa que send_telegram retorna True quando a requisição POST retorna 200."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_post.return_value = mock_response

    with patch('notifier.BOT_TOKEN', "token"), patch('notifier.CHAT_ID', "chat_id"):
        res = send_telegram("Mensagem de teste")
        assert res is True
        mock_post.assert_called_once_with(
            "https://api.telegram.org/bottoken/sendMessage",
            json={"chat_id": "chat_id", "text": "Mensagem de teste", "parse_mode": "HTML"},
            timeout=10
        )

@patch('notifier.requests.post')
def test_send_telegram_erro_http(mock_post):
    """Testa que send_telegram retorna False quando a requisição POST retorna erro HTTP (ex: 500)."""
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mock_post.return_value = mock_response

    with patch('notifier.BOT_TOKEN', "token"), patch('notifier.CHAT_ID', "chat_id"):
        res = send_telegram("Mensagem de teste")
        assert res is False

def test_montar_mensagem_com_novidades():
    """Testa que a mensagem contém as novidades formatadas se pesquisas_novas > 0."""
    resultados = [
        {"coletor": "QuaestCollector", "status": "ok"},
        {"coletor": "AtlasCollector", "status": "ok"}
    ]
    msg = montar_mensagem_coleta(resultados, pesquisas_novas=2, intencoes_novas=16)
    
    assert "🗳️ <b>2 nova(s) pesquisa(s)</b>" in msg
    assert "📊 Intenções salvas: 16" in msg
    assert "✅ Coletores OK: Quaest, Atlas" in msg

def test_montar_mensagem_sem_novidades():
    """Testa que a mensagem indica 'Sem novidades' se pesquisas_novas == 0."""
    resultados = [
        {"coletor": "QuaestCollector", "status": "ok"}
    ]
    msg = montar_mensagem_coleta(resultados, pesquisas_novas=0, intencoes_novas=0)
    
    assert "⚪ Sem novidades" in msg
    assert "📊 Intenções salvas: 0" in msg

def test_montar_mensagem_alerta_com_dados():
    """Testa que montar_mensagem_alerta formata corretamente um alerta de queda."""
    alertas = [
        {
            'candidato': 'Lula',
            'percentual_atual': 36.0,
            'percentual_anterior': 40.0,
            'variacao': -4.0,
            'direcao': 'down',
            'data_atual': '2026-06-15',
            'data_anterior': '2026-06-08',
            'instituto_atual': 'Quaest',
            'instituto_anterior': 'Datafolha',
        }
    ]
    msg = montar_mensagem_alerta(alertas)
    assert '🚨' in msg
    assert 'Lula' in msg
    assert '40.0%' in msg
    assert '36.0%' in msg
    assert '-4.0pp' in msg
    assert '📉' in msg
    assert 'pulso-eleitoral.fly.dev' in msg

def test_montar_mensagem_alerta_vazio():
    """Testa que montar_mensagem_alerta retorna string vazia para lista vazia."""
    msg = montar_mensagem_alerta([])
    assert msg == ""

def test_montar_mensagem_com_erro():
    """Testa que a mensagem reporta erros se algum coletor falhar."""
    resultados = [
        {"coletor": "QuaestCollector", "status": "ok"},
        {"coletor": "AtlasCollector", "status": "erro", "msg": "Timeout"}
    ]
    msg = montar_mensagem_coleta(resultados, pesquisas_novas=0, intencoes_novas=0)
    
    assert "❌ Erros: Atlas" in msg
    assert "✅ Coletores OK: Quaest" in msg
