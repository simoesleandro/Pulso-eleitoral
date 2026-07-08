import os
import pytest
from unittest.mock import patch, MagicMock
from collectors.gemini_extractor import (
    extrair_com_gemini, PROMPT_EXTRACAO, PROMPT_EXTRACAO_REGIONAL,
)


def test_prompts_compostos_contem_ancoras_chave():
    """Âncora permanente pós-composição (plano 012): os prompts compostos a
    partir da base compartilhada precisam conter os marcadores-chave que o
    parsing e a extração dependem — regressão aqui indica que a composição
    dos deltas (escopo/rejeições) quebrou."""
    for prompt in (PROMPT_EXTRACAO, PROMPT_EXTRACAO_REGIONAL):
        assert "REGRAS CRÍTICAS" in prompt
        assert "{lista_ignorar}" in prompt
        assert "pct_pode_mudar_voto" in prompt
        assert "{texto}" in prompt
    # Delta específico do nacional: bloco de rejeições só existe no não-regional.
    assert "EXTRAÇÃO DE REJEIÇÃO" in PROMPT_EXTRACAO
    assert "EXTRAÇÃO DE REJEIÇÃO" not in PROMPT_EXTRACAO_REGIONAL

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


@patch('google.genai.Client')
def test_candidato_sem_nome_nao_descarta_pesquisa_inteira(mock_client_class):
    """Um candidato sem a chave 'nome' no meio da lista deve ser ignorado
    individualmente — a pesquisa não deve virar {"candidatos": []}."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    mock_response = MagicMock()
    mock_response.text = """
    {
      "candidatos": [
        {"nome": "Lula", "percentual": 40},
        {"percentual": 30},
        {"nome": "Ciro", "percentual": 10}
      ]
    }
    """
    mock_client.models.generate_content.return_value = mock_response

    with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy_key"}):
        resultado = extrair_com_gemini("texto qualquer", "http://teste.com")

        # O candidato sem "nome" (percentual 30) é descartado; os outros dois
        # sobrevivem — checagem por percentual evita depender da normalização
        # de nomes (fora do escopo deste plano).
        percentuais = {c["percentual"] for c in resultado["candidatos"]}
        assert percentuais == {40.0, 10.0}


@patch('google.genai.Client')
def test_percentual_string_com_simbolo_e_coagido(mock_client_class):
    """'percentual': '38%' deve ser coagido para float 38.0."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    mock_response = MagicMock()
    mock_response.text = '{"candidatos": [{"nome": "Lula", "percentual": "38%"}]}'
    mock_client.models.generate_content.return_value = mock_response

    with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy_key"}):
        resultado = extrair_com_gemini("texto qualquer", "http://teste.com")

        assert len(resultado["candidatos"]) == 1
        assert resultado["candidatos"][0]["percentual"] == 38.0


@patch('google.genai.Client')
def test_percentual_nao_numerico_e_ignorado(mock_client_class):
    """'percentual': 'abc' (não coercível) deve descartar só esse candidato."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    mock_response = MagicMock()
    mock_response.text = """
    {
      "candidatos": [
        {"nome": "Lula", "percentual": "abc"},
        {"nome": "Bolsonaro", "percentual": 35}
      ]
    }
    """
    mock_client.models.generate_content.return_value = mock_response

    with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy_key"}):
        resultado = extrair_com_gemini("texto qualquer", "http://teste.com")

        # Só o candidato com percentual coercível sobrevive.
        assert len(resultado["candidatos"]) == 1
        assert resultado["candidatos"][0]["percentual"] == 35.0


@patch('google.genai.Client')
def test_percentual_fora_da_faixa_e_ignorado(mock_client_class):
    """'percentual': 150 (fora de [0,100]) deve descartar só esse candidato."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    mock_response = MagicMock()
    mock_response.text = """
    {
      "candidatos": [
        {"nome": "Lula", "percentual": 150},
        {"nome": "Bolsonaro", "percentual": 35}
      ]
    }
    """
    mock_client.models.generate_content.return_value = mock_response

    with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy_key"}):
        resultado = extrair_com_gemini("texto qualquer", "http://teste.com")

        # Só o candidato dentro da faixa [0,100] sobrevive.
        assert len(resultado["candidatos"]) == 1
        assert resultado["candidatos"][0]["percentual"] == 35.0


@patch('google.genai.Client')
def test_item_nao_dict_na_lista_e_ignorado_sem_excecao(mock_client_class):
    """Um item que não é dict na lista de candidatos não deve gerar exceção."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    mock_response = MagicMock()
    mock_response.text = """
    {
      "candidatos": [
        "not_a_dict",
        {"nome": "Lula", "percentual": 40}
      ]
    }
    """
    mock_client.models.generate_content.return_value = mock_response

    with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy_key"}):
        resultado = extrair_com_gemini("texto qualquer", "http://teste.com")

        nomes = {c["nome"] for c in resultado["candidatos"]}
        assert nomes == {"Lula"}
