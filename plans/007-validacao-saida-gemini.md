# Plan 007: Validar a saída do Gemini com tolerância — um candidato malformado não descarta a pesquisa

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b3b92ef..HEAD -- collectors/gemini_extractor.py collectors/base.py tests/test_gemini_extractor.py`
> Se algum arquivo in-scope mudou desde a escrita do plano, comparar os
> excertos de "Current state" com o código vivo; divergência = STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none (recomendado após 006 — mesmo `collectors/base.py`)
- **Category**: bug
- **Planned at**: commit `b3b92ef`, 2026-07-07

## Why this matters

A saída do LLM é entrada não-confiável, mas o pós-processamento indexa os
dicts diretamente. Um único candidato sem a chave `nome` gera `KeyError`,
capturado pelo `except Exception` amplo que retorna `{"candidatos": []}` — a
**pesquisa inteira** (válida nos demais candidatos) é descartada em silêncio.
E um `percentual` string (`"38%"`, `"38,0"`) passa pelo extrator mas explode em
`float()` dentro de `base.py`, abortando o coletor. Depois deste plano: entradas
malformadas são puladas individualmente com log; percentuais em formatos comuns
são coagidos; o resto da pesquisa é aproveitado.

## Current state

- `collectors/gemini_extractor.py` — `extrair_com_gemini()` (linhas 428–527);
  o pós-processamento problemático está nas linhas 495–520.
- `collectors/base.py` — `_parse_com_gemini()` (linhas 199–283); a compreensão
  de lista nas linhas 256–273 já filtra `c.get("nome")`/`c.get("percentual") is not None`,
  mas `float(c["percentual"])` (linha 261) e `float(pct_rej)` (linha 254)
  lançam `ValueError` para strings não-numéricas.

Excerto de `collectors/gemini_extractor.py:495-514` (hoje):

```python
        candidatos = resultado.get("candidatos", [])

        # Cenário multipolar (1º turno): percentuais > 50% são inválidos
        if len(candidatos) > 2:
            candidatos = [c for c in candidatos if c.get("percentual", 0) <= 50]

        # Descarta candidatos com nome mapeado para None (hipotéticos / não declarados)
        candidatos = [c for c in candidatos if normalizar_nome(c["nome"]) is not None]

        # Normaliza nomes para forma canônica
        for c in candidatos:
            c["nome"] = normalizar_nome(c["nome"])

        # Remove duplicatas após normalização (mesmo nome → mantém maior percentual)
        vistos = {}
        for c in candidatos:
            nome = c["nome"]
            if nome not in vistos or c["percentual"] > vistos[nome]["percentual"]:
                vistos[nome] = c
```

Problemas concretos nesse trecho:
- `c["nome"]` (linha 502) → `KeyError` se o LLM omitir a chave → `except` da
  linha 525 devolve `{"candidatos": []}`.
- `c.get("percentual", 0) <= 50` (linha 499) → `TypeError` se percentual for
  string → mesmo efeito.
- Nenhuma coerção: `"38%"` passa adiante e quebra depois em `base.py:261`.

Convenções: logs em português via `logger` de módulo; testes unitários do
extrator em `tests/test_gemini_extractor.py` mockam `genai.Client` (o
`conftest.py` isenta esse arquivo do mock global — ver
`tests/conftest.py:17-18`).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Testes do extrator | `python -m pytest tests/test_gemini_extractor.py -q` | exit 0 |
| Suíte completa | `python -m pytest -q` | exit 0, 0 failed |

## Scope

**In scope**:
- `collectors/gemini_extractor.py` (novo helper + pós-processamento de `extrair_com_gemini` e o loop de candidatos de `extrair_regional_multiestado`, linhas 391–413)
- `collectors/base.py` (usar o helper nas conversões `float()` das linhas 254 e 261)
- `tests/test_gemini_extractor.py` (novos testes)

**Out of scope** (NÃO tocar):
- Os textos dos prompts (`PROMPT_EXTRACAO`, `PROMPT_EXTRACAO_REGIONAL`,
  `PROMPT_MULTIESTADO`) — o plano 012 cuida da unificação; qualquer mudança de
  prompt altera o comportamento do modelo.
- A cascata de modelos/retry — também é do plano 012.
- `tests/conftest.py` (o mini-parser fake é usado pelos outros testes).

## Git workflow

- Commit em português, ex.: `fix(gemini): valida e coage saída do LLM por candidato, sem descartar a pesquisa inteira`
- Sem push/PR sem instrução.

## Steps

### Step 1: Helper de coerção de percentual

Em `collectors/gemini_extractor.py`, criar (nível de módulo, perto do topo):

```python
def _to_pct(valor) -> float | None:
    """Coage percentual vindo do LLM: aceita int/float e strings '38', '38%',
    '38,5'. Retorna None se não for coercível ou estiver fora de [0, 100]."""
    if valor is None:
        return None
    if isinstance(valor, bool):
        return None
    try:
        if isinstance(valor, str):
            valor = valor.strip().replace('%', '').replace(',', '.').strip()
        pct = float(valor)
    except (ValueError, TypeError):
        return None
    return pct if 0.0 <= pct <= 100.0 else None
```

**Verify**: `python -c "from collectors.gemini_extractor import _to_pct; assert _to_pct('38%')==38.0; assert _to_pct('38,5')==38.5; assert _to_pct('abc') is None; assert _to_pct(150) is None; print('ok')"` → `ok`

### Step 2: Saneamento por candidato em `extrair_com_gemini`

Substituir o bloco das linhas 495–514 por um único loop de saneamento **antes**
das regras existentes: para cada `c` em `resultado.get("candidatos", [])`
(pular se não for `dict`), extrair `nome = c.get("nome")` e
`pct = _to_pct(c.get("percentual"))`; se `nome` falsy ou `pct is None`, logar
`logger.warning(f"Candidato malformado ignorado: {c!r}")` e pular; caso
contrário reescrever `c["percentual"] = pct` e manter. Depois do saneamento,
aplicar as regras existentes **na mesma ordem** (filtro >50 em multipolar,
descarte de `normalizar_nome(...) is None`, normalização, dedup por maior
percentual) — agora seguras porque todo item tem `nome` e `percentual` float.

**Verify**: `python -m pytest tests/test_gemini_extractor.py -q` → exit 0.

### Step 3: Mesmo saneamento no loop regional

Em `extrair_regional_multiestado` (linhas 391–413), trocar
`float(percentual)` das linhas 399 e 411 pelo resultado de `_to_pct` (pular o
candidato se `None`). A checagem de faixa `1.0 <= pct <= 80.0` existente
permanece.

**Verify**: `python -m pytest -q` → exit 0.

### Step 4: Blindar as conversões em `base.py`

Em `collectors/base.py` `_parse_com_gemini`: importar `_to_pct` junto do
`normalizar_nome` já importado (linha 247) e usar nas duas conversões:
rejeições (linha 254: `pct_rej_f = _to_pct(pct_rej)`; incluir só se não-None) e
intenções (linha 261 + filtro da linha 272: trocar
`c.get("percentual") is not None` por `_to_pct(c.get("percentual")) is not None`
e `float(c["percentual"])` por `_to_pct(c["percentual"])`). Obs.: após o Step 2
o extrator já entrega floats — esta é uma segunda linha de defesa (o
`conftest.py` substitui `extrair_com_gemini` inteiro nos testes, então valores
crus podem chegar aqui).

**Verify**: `python -m pytest tests/test_collectors.py -q` → exit 0.

## Test plan

Novos testes em `tests/test_gemini_extractor.py`, seguindo o padrão dos
existentes (mock de `genai.Client` retornando JSON controlado):

1. Candidato sem `nome` no meio da lista → os demais candidatos são retornados
   (a pesquisa NÃO vira `{"candidatos": []}`).
2. `"percentual": "38%"` → retornado como `38.0`.
3. `"percentual": "abc"` → candidato pulado, demais preservados.
4. `"percentual": 150` → candidato pulado (fora da faixa).
5. Item não-dict na lista de candidatos → pulado sem exceção.

Verificação: `python -m pytest tests/test_gemini_extractor.py -q` → todos
passam, incluindo os 5 novos.

## Done criteria

- [ ] `python -m pytest -q` exit 0
- [ ] `_to_pct` existe e é usado em `extrair_com_gemini`, `extrair_regional_multiestado` e `base.py._parse_com_gemini`
- [ ] Nenhum acesso `c["nome"]`/`c["percentual"]` sem `.get()` no pós-processamento de `extrair_com_gemini`
- [ ] Nenhum arquivo fora do escopo modificado (`git status`)
- [ ] Linha de status atualizada em `plans/README.md`

## STOP conditions

- Excertos de "Current state" não batem (drift — ex.: plano 012 executado antes).
- Um teste existente assume que pesquisa com um candidato malformado é
  totalmente descartada (comportamento antigo) — reportar em vez de mudar o teste.
- A mudança parecer exigir tocar nos textos dos prompts.

## Maintenance notes

- O plano 012 (DRY Gemini) refatora o mesmo arquivo — executar este primeiro.
- Revisor: conferir que a ordem das regras pós-saneamento não mudou (o filtro
  multipolar >50 roda sobre a lista saneada — mesmo efeito prático).
- Follow-up deferido: telemetria de quantos candidatos são descartados por
  saneamento (hoje só `logger.warning`).
