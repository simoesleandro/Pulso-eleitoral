import os
import pytest
from unittest.mock import patch, MagicMock
from collectors.gemini_extractor import extrair_com_gemini

@patch('google.genai.Client')
def test_extrai_percentuais_explicitos(mock_client_class):
    """Testa que extrair_com_gemini extrai corretamente os percentuais se o JSON for válido."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    
    mock_response = MagicMock()
    mock_response.text = """
    ```json
    {
      "cargo": "presidente",
      "instituto": "Quaest",
      "data": "2026-05-06",
      "tamanho_amostra": 2000,
      "margem_erro": 2.0,
      "candidatos": [
        {"nome": "Lula", "percentual": 41.0},
        {"nome": "Bolsonaro", "percentual": 35.0},
        {"nome": "Ciro", "percentual": 8.0}
      ]
    }
    ```
    """
    mock_client.models.generate_content.return_value = mock_response
    
    # Define a chave no ambiente temporariamente
    with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy_key"}):
        texto = "Lula lidera com 41%. Bolsonaro aparece com 35%. Ciro tem 8%."
        resultado = extrair_com_gemini(texto, "http://teste.com")
        
        assert resultado["cargo"] == "presidente"
        assert resultado["instituto"] == "Quaest"
        assert len(resultado["candidatos"]) == 3
        assert resultado["candidatos"][0]["nome"] == "Lula"
        assert resultado["candidatos"][0]["percentual"] == 41.0

@patch('google.genai.Client')
def test_retorna_vazio_sem_percentuais(mock_client_class):
    """Testa que extrair_com_gemini retorna lista vazia de candidatos quando não há percentuais."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    
    mock_response = MagicMock()
    mock_response.text = '{"candidatos": []}'
    mock_client.models.generate_content.return_value = mock_response
    
    with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy_key"}):
        texto = "Aprovação do governo Lula é positiva no Nordeste"
        resultado = extrair_com_gemini(texto, "http://teste.com")
        
        assert resultado["candidatos"] == []

@patch('google.genai.Client')
def test_trata_json_invalido(mock_client_class):
    """Testa que extrair_com_gemini lida de forma graciosa com respostas inválidas (não-JSON)."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    
    mock_response = MagicMock()
    mock_response.text = "erro interno do servidor ou resposta truncada"
    mock_client.models.generate_content.return_value = mock_response
    
    with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy_key"}):
        texto = "Qualquer texto"
        resultado = extrair_com_gemini(texto, "http://teste.com")
        
        assert resultado == {"candidatos": []}

def test_trata_sem_api_key():
    """Testa que extrair_com_gemini falha imediatamente e retorna vazio se GEMINI_API_KEY não estiver definida."""
    with patch.dict(os.environ, {}, clear=True):
        resultado = extrair_com_gemini("Qualquer texto", "http://teste.com")
        assert resultado == {"candidatos": []}
