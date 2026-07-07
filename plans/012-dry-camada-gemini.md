# Plan 012: Unificar prompts e cascata de modelos da camada Gemini

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b3b92ef..HEAD -- collectors/gemini_extractor.py app.py tests/test_gemini_extractor.py`
> ATENÇÃO: o plano 007 edita `gemini_extractor.py` de propósito (deve estar
> DONE antes deste). Divergência além do esperado pelo 007 = comparar excertos
> e, em dúvida, STOP.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED — prompt é carga útil do modelo; qualquer reescrita de texto muda extração
- **Depends on**: plans/007-validacao-saida-gemini.md
- **Category**: tech-debt
- **Planned at**: commit `b3b92ef`, 2026-07-07

## Why this matters

A lógica "tentar modelos em cascata com retry de 503" existe em **três**
cópias divergentes: `extrair_com_gemini` (backoff crescente 5s/10s),
`extrair_regional_multiestado` (sleep fixo 5s, 2 tentativas) e
`api_visao_geral_analise` em `app.py` (lista de modelos diferente — inclui
`gemini-2.5-flash-8b` — e **sem** retry). Corrigir um model-id ruim ou o
backoff exige editar três lugares. Os prompts `PROMPT_EXTRACAO` (linhas
13–123) e `PROMPT_EXTRACAO_REGIONAL` (125–216) são ~90 linhas quase idênticas
que **já divergiram** (o regional omite o bloco de extração de rejeições) —
cada ajuste de prompt precisa ser aplicado à mão nos dois. Este é o item #7 do
roadmap de auditoria de junho/2026.

## Current state

- `collectors/gemini_extractor.py`:
  - `PROMPT_EXTRACAO` (13–123) e `PROMPT_EXTRACAO_REGIONAL` (125–216): idênticos
    nas seções "REGRAS CRÍTICAS", "% PODE MUDAR DE VOTO", "DETERMINAÇÃO DO tipo",
    schema JSON e "EXTRAÇÃO DE NOMES"; divergem em ~6 linhas — escopo
    (só-nacional vs nacional-ou-estadual) e o bloco `rejeicoes` (ausente no regional).
  - `PROMPT_MULTIESTADO` — prompt distinto (tabela por UF), NÃO participa da
    unificação de texto; só usa a cascata.
  - Cascata em `extrair_com_gemini` (`app.py` não — ver abaixo), linhas 451–485:

```python
        MODELOS = [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
        ]
        raw = None
        modelo_usado = None
        for modelo in MODELOS:
            max_retries = 2
            sucesso_modelo = False
            for tentativa in range(max_retries):
                try:
                    response = client.models.generate_content(model=modelo, contents=prompt)
                    raw = response.text.strip()
                    ...
                except Exception as e:
                    if '503' in str(e) and tentativa < max_retries - 1:
                        wait = 5 * (tentativa + 1)
                        ...time.sleep(wait)
```

  - Cascata em `extrair_regional_multiestado`, linhas 348–370 (variante: sleep
    fixo `time.sleep(5)` só na 1ª tentativa).
  - `_montar_prompt(template, texto)` já existe e interpola `{lista_ignorar}` +
    o texto — reutilizar.
- `app.py:474-491` — terceira cascata em `api_visao_geral_analise`: modelos
  `["gemini-2.5-flash", "gemini-2.5-flash-8b", "gemini-2.5-pro"]`, sem retry,
  para no primeiro texto não-vazio.
- Testes: `tests/test_gemini_extractor.py` mocka `genai.Client` — é o contrato
  de regressão.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Testes do extrator | `python -m pytest tests/test_gemini_extractor.py -q` | exit 0 |
| Suíte | `python -m pytest -q` | exit 0 |

## Scope

**In scope**:
- `collectors/gemini_extractor.py` (helper de cascata + composição dos prompts)
- `app.py` (apenas `api_visao_geral_analise`, para usar o helper)
- `tests/test_gemini_extractor.py` (testes do helper)

**Out de scope** (NÃO tocar):
- `PROMPT_MULTIESTADO` (texto).
- Qualquer **reescrita semântica** dos prompts — a composição deve produzir
  strings **byte-idênticas** às atuais (exceção deliberada: ver Step 3).
- O saneamento por candidato do plano 007.

## Git workflow

- Commits em português, ex.: `refactor(gemini): extrai cascata de modelos única e compõe prompts de base compartilhada`.

## Steps

### Step 1: Helper único de cascata

Em `gemini_extractor.py`, criar:

```python
def gerar_com_cascata(client, prompt: str, modelos: list[str] | None = None,
                      max_retries: int = 2) -> tuple[str | None, str | None]:
    """Tenta cada modelo em ordem; retry com backoff (5s, 10s) apenas em 503.
    Retorna (texto, modelo_usado) ou (None, None) se todos falharem."""
```

Comportamento: o de `extrair_com_gemini` hoje (backoff crescente `5*(tentativa+1)`),
que é o mais robusto dos três. `modelos=None` usa o default
`["gemini-2.5-flash", "gemini-2.5-pro"]`. Migrar `extrair_com_gemini` e
`extrair_regional_multiestado` para ele (o regional passa a ganhar o backoff
crescente — mudança de comportamento benigna e desejada; anotar no commit).

**Verify**: `python -m pytest tests/test_gemini_extractor.py -q` → exit 0.

### Step 2: `app.py` usa o helper

Em `api_visao_geral_analise`, substituir o loop de modelos por
`from collectors.gemini_extractor import gerar_com_cascata` e
`analise_texto, _ = gerar_com_cascata(client, prompt, modelos=["gemini-2.5-flash", "gemini-2.5-flash-8b", "gemini-2.5-pro"])`.
A lista de modelos própria (com o flash-8b) é preservada explicitamente.

**Verify**: `python -m pytest tests/test_dashboard.py -q` → exit 0.

### Step 3: Compor os prompts de uma base única

1. Extrair as seções comuns para constantes de módulo (ex.: `_REGRAS_CRITICAS`,
   `_BLOco_PCT_MUDAR`, `_BLOCO_TIPO`, `_BLOCO_NOMES`, `_SCHEMA_JSON`) copiando o
   texto **byte a byte** do `PROMPT_EXTRACAO` atual.
2. Reconstruir `PROMPT_EXTRACAO = _CABECALHO + _ESCOPO_NACIONAL + _REGRAS... + _BLOCO_REJEICOES + ...`
   e `PROMPT_EXTRACAO_REGIONAL = _CABECALHO + _ESCOPO_REGIONAL + _REGRAS... + ...`.
3. **Gate de equivalência**: ANTES de deletar os literais antigos, renomeá-los
   (`_PROMPT_EXTRACAO_LEGADO`, `_PROMPT_EXTRACAO_REGIONAL_LEGADO`) e adicionar
   um teste que asserte `PROMPT_EXTRACAO == _PROMPT_EXTRACAO_LEGADO` (idem
   regional). Rodar. Só então remover os legados E o teste de equivalência,
   mantendo um teste mais fraco (as âncoras-chave presentes: "REGRAS CRÍTICAS",
   "{lista_ignorar}", "pct_pode_mudar_voto").
4. Decisão deliberada a tomar com o operador se surgir: o regional NÃO ganha o
   bloco de rejeições neste plano (restaurar a paridade de features muda o
   comportamento de extração — fica registrado como follow-up).

**Verify**: durante o passo 3, `python -m pytest tests/test_gemini_extractor.py -q`
com o teste de equivalência byte-a-byte passando; ao final, suíte inteira:
`python -m pytest -q` → exit 0.

## Test plan

- Teste do helper: mock de client cujo `generate_content` lança `Exception("503 ...")`
  na 1ª chamada e responde na 2ª → retorna o texto (com `time.sleep` mockado);
  mock que sempre falha → `(None, None)`; modelo 1 falha com erro não-503 →
  pula direto pro modelo 2 sem retry.
- Teste de equivalência dos prompts (temporário, byte-a-byte) + teste
  permanente de âncoras.
- Padrão: `tests/test_gemini_extractor.py` existente.

## Done criteria

- [ ] `grep -n "for modelo in MODELOS" collectors/gemini_extractor.py app.py` → sem resultado (só o helper contém o loop)
- [ ] `python -m pytest -q` exit 0
- [ ] Prompts compostos; nenhum bloco de texto duplicado entre os dois templates (as seções comuns existem uma única vez no arquivo)
- [ ] Nenhum arquivo fora do escopo modificado (`git status`)
- [ ] Linha de status atualizada em `plans/README.md`

## STOP conditions

- Plano 007 não está DONE.
- O teste de equivalência byte-a-byte falhar e a diferença não for whitespace
  trivial de f-string/concatenação — NÃO "aproximar" o texto; reportar.
- Qualquer tentação de melhorar/reescrever frases do prompt: fora de escopo.

## Maintenance notes

- Follow-up registrado: decidir se `PROMPT_EXTRACAO_REGIONAL` deve ganhar o
  bloco de rejeições (paridade) — mudança de comportamento, requer validação
  com releases reais.
- Ajustes de prompt agora são feitos uma vez na seção compartilhada; revisor de
  PRs futuros deve desconfiar de edições que toquem só um dos templates.
