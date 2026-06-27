# Plan 001: Restaurar a suíte de testes para verde (baseline de verificação)

> **Executor instructions**: Siga o plano passo a passo. Rode cada comando de
> verificação e confirme o resultado esperado antes de avançar. Se algo na seção
> "STOP conditions" ocorrer, pare e reporte — não improvise. Ao terminar, atualize
> a linha de status deste plano em `plans/README.md`.
>
> **Drift check (rode primeiro)**:
> `git diff --stat 2b49ba3..HEAD -- tests/ seed.sql templates/dashboard.html app.py collectors/`
> Se algum arquivo em escopo mudou desde `2b49ba3`, compare os trechos de "Current
> state" com o código vivo antes de prosseguir; em divergência, trate como STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (mexe só em testes/conftest; nenhuma mudança de produção)
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `2b49ba3`, 2026-06-26

## Why this matters

`python -m pytest -q` retorna hoje **13 failed, 71 passed**. O README anuncia "61
testes" verdes — falso. Sem uma suíte verde não há rede de segurança: qualquer
refatoração (incluindo os outros planos) avança às cegas, e o Plano 002 (gate de
CI) é impossível enquanto o deploy quebraria a cada push. A maioria das falhas é
**drift de teste** (o seed cresceu de 9 → 14 institutos, o template mudou de caixa,
a API ganhou a chave `tipo`), além de **um bug real no mock do conftest**. Ao fim
deste plano, `pytest` sai com código 0.

## Current state

As 13 falhas, agrupadas por causa-raiz:

### Causa A — mock do conftest com assinatura desatualizada (4 falhas)
`tests/conftest.py:20` define o fake do Gemini sem o parâmetro `permite_regional`:
```python
def fake_extrair(texto, fonte_url=""):
```
Mas `collectors/base.py:218` chama o real com esse kwarg:
```python
resultado = extrair_com_gemini(texto, fonte_url=url, permite_regional=permite_regional)
```
→ `TypeError: fake_extrair() got an unexpected keyword argument 'permite_regional'`.
Falhas: `test_atlas.py::test_parse_release`, `test_poder360.py::test_parse_release`,
`test_poder360.py::test_parse_instituto_correto`, `test_quaest.py::test_parse_release`.

### Causa B — seed cresceu de 9 para 14 institutos (2 falhas)
`seed.sql:5` insere hoje **14** institutos (Datafolha, Ibope/IPEC, Quaest,
Genial/Quaest, Atlas, Paraná, Real Time, Nexus/BTG Pactual, Verita, Futura
Inteligência, PoderData, Meio/Ideia, Vox Populi, Instituto Gerp). Dois testes ainda
esperam 9:
- `tests/test_database.py:76` — `assert len(institutos) == 9` (docstring diz "7",
  lista 7 nomes em `:77-80`; tudo desatualizado).
- `tests/test_dashboard.py:106` — `assert len(data['institutos']) == 9`.

### Causa C — template do dashboard mudou de caixa (1 falha)
`templates/dashboard.html:37` usa `Pulso Eleitoral` (mixed case); o título em `:6`
é `Dashboard — Pulso Eleitoral`. O teste `tests/test_dashboard.py:51` ainda checa o
texto em caixa alta:
```python
assert b"PULSO ELEITORAL" in response.data
```

### Causa D — endpoint governador-rj agora retorna a chave `tipo` (1 falha)
`app.py:509-516` (branch de banco vazio) retorna o dict **com** `"tipo": None`. O
teste `tests/test_dashboard.py:132-138` ainda espera o dict **sem** `tipo`:
```python
assert res_gov.json == {
    "candidatos": [], "percentuais": [], "data_coleta": None,
    "instituto": None, "margem_erro": None
}   # falta "tipo": None
```
(O branch de presidente em `app.py:483-489` NÃO tem `tipo`, e o teste de presidente
em `:121-127` está correto — não mexa nele.)

### Causa E — `media_agregada` retorna 0 por janela de data relativa ao relógio (1 falha)
`tests/test_dashboard.py:199` — `assert len(data['candidatos']) > 0` recebe 0.
`get_media_agregada` (em `database.py`, ~linha 275) filtra
`data_pesquisa >= date.today() - 30 dias`. A data mais recente no seed é
**2026-06-10**. Quando o relógio do sistema está a mais de ~30 dias dessa data, a
janela exclui todo o seed → 0 candidatos. É **fragilidade de teste** (depende do
relógio), não bug de produção.

### Causa F — testes de fetch de coletor retornam 0 registros (3 falhas) — INVESTIGAR
`test_atlas.py::test_fetch_with_mock_requests`, `test_quaest.py::test_fetch_with_mock_requests`,
`test_poder360.py::test_fetch_com_mock` falham com `assert 0 == N`. O log mostra
`Texto muito curto ... 0 chars`, indicando que `_get_page` devolveu vazio no
release. Parte pode resolver junto com a Causa A (o `TypeError` no mock fazia o
parse retornar []). **Reavalie estes 3 testes SÓ DEPOIS de aplicar o passo 1.**

### Causa G — instanciação de coletores (1 falha) — INVESTIGAR
`test_collectors.py::test_concrete_collectors_instantiation` falha com
`AssertionError`. Pode ser lista de coletores esperados desatualizada. Diagnostique
no passo 6.

### Convenções do repo
- Testes em `tests/test_*.py`, pytest, fixtures `autouse` em `tests/conftest.py`.
- `TESTING=True` é setado no topo dos arquivos de teste (ex.: `test_dashboard.py:3`).
- Banco de teste é recriado por teste via `init_db(force_seed=True)` /
  `setup_db_with_seed()`.

## Commands you will need

| Propósito | Comando | Esperado no sucesso |
|-----------|---------|---------------------|
| Suíte completa | `python -m pytest -q` | `0 failed`, exit 0 |
| Um arquivo | `python -m pytest tests/test_dashboard.py -q` | todos passam |
| Um teste | `python -m pytest tests/test_quaest.py::test_parse_release -q` | passa |
| Ver causa | `python -m pytest tests/test_atlas.py -q -x --tb=short` | traceback curto |

(O projeto não tem lint/typecheck configurado — não há gate além do pytest.)

## Scope

**In scope** (únicos arquivos a modificar):
- `tests/conftest.py`
- `tests/test_database.py`
- `tests/test_dashboard.py`
- `tests/test_atlas.py`, `tests/test_quaest.py`, `tests/test_poder360.py`
  (apenas se a investigação dos passos 5/6 confirmar drift de teste)
- `tests/test_collectors.py` (idem)

**Out of scope** (NÃO toque, mesmo parecendo relacionado):
- `app.py`, `database.py`, `collectors/*.py` (lógica de produção) — exceto se um STOP
  for acionado e o problema for um bug real; nesse caso **pare e reporte**, não
  conserte produção por conta própria.
- `seed.sql`, `schema.sql` — o seed com 14 institutos é o estado correto; alinhe os
  testes a ele, não o contrário.
- `templates/dashboard.html` — "Pulso Eleitoral" (mixed case) é o estado correto.

## Git workflow

- Branch: `advisor/001-fix-test-baseline`
- Um commit por causa-raiz (A–G) ou um commit único coeso. Estilo de mensagem do
  repo (conventional commits), ex.: `fix(tests): alinha conftest e asserts ao estado atual`.
- Não faça push nem abra PR a menos que o operador peça.

## Steps

### Step 1: Corrigir a assinatura do mock no conftest (Causa A)
Em `tests/conftest.py:20`, adicione o parâmetro `permite_regional=False` à função:
```python
def fake_extrair(texto, fonte_url="", permite_regional=False):
```
Nada mais muda — o corpo não usa o parâmetro (o fake é determinístico).

**Verify**: `python -m pytest tests/test_atlas.py::test_parse_release tests/test_poder360.py::test_parse_release tests/test_poder360.py::test_parse_instituto_correto tests/test_quaest.py::test_parse_release -q`
→ os 4 passam (0 failed).

### Step 2: Alinhar contagem/nomes de institutos (Causa B)
Em `tests/test_database.py`:
- Linha 76: troque `== 9` por `== 14`.
- Linhas 77-80 (`nomes_esperados`): substitua pela lista completa e na ordem do
  seed: `'Datafolha', 'Ibope/IPEC', 'Quaest', 'Genial/Quaest', 'Atlas', 'Paraná',
  'Real Time', 'Nexus/BTG Pactual', 'Verita', 'Futura Inteligência', 'PoderData',
  'Meio/Ideia', 'Vox Populi', 'Instituto Gerp'`.
- Atualize a docstring em `:66` ("7 institutos" → "14 institutos").

Em `tests/test_dashboard.py:106`: troque `== 9` por `== 14`.

**Verify**: `python -m pytest tests/test_database.py::test_seed_inserts_institutos tests/test_dashboard.py::test_api_institutos -q`
→ ambos passam.

> Antes de editar, confirme a contagem real:
> `grep -cE "^\([0-9]" <(awk '/INSERT INTO institutos/{f=1} f{print} /;/{if(f)exit}' seed.sql)`
> Deve imprimir `14`. Se imprimir outro número, use ESSE número e a ordem real do
> seed (STOP se divergir muito do descrito aqui).

### Step 3: Corrigir o texto do dashboard (Causa C)
Em `tests/test_dashboard.py:51`, troque para a caixa real do template:
```python
assert b"Pulso Eleitoral" in response.data
```

**Verify**: `python -m pytest tests/test_dashboard.py::test_dashboard_route -q` → passa.

### Step 4: Adicionar a chave `tipo` no dict esperado de governador-rj (Causa D)
Em `tests/test_dashboard.py:132-138`, adicione `"tipo": None` ao dict esperado do
`res_gov` (para casar com `app.py:509-516`). **Não** altere o dict de presidente em
`:121-127`.

**Verify**: `python -m pytest tests/test_dashboard.py::test_empty_database_handling -q` → passa.

### Step 5: Tornar `test_api_media_agregada` independente do relógio (Causa E)
O problema é a janela de 30 dias relativa a `date.today()` contra um seed com data
máxima `2026-06-10`. **Não** mude `database.py` nem `seed.sql`. Em vez disso, em
`tests/test_dashboard.py::test_api_media_agregada` (`:191-210`), torne o teste
robusto inserindo uma pesquisa com data recente ANTES da chamada, OU passando uma
janela larga via querystring se o endpoint aceitar (`/api/media-agregada?cargo=presidente&dias=N`).

Verifique o contrato do endpoint: `app.py:552-558` mostra que ele aceita
`?dias=<int>` (default 30). A correção mínima e robusta é pedir uma janela que
sempre cubra o seed — calcule os dias entre a data máxima do seed e hoje:
```python
import datetime
dias = (datetime.date.today() - datetime.date(2026, 6, 10)).days + 30
response = client.get(f'/api/media-agregada?cargo=presidente&dias={max(dias, 30)}')
```
Isso mantém o teste verde independentemente do relógio do sistema.

**Verify**: `python -m pytest tests/test_dashboard.py::test_api_media_agregada -q` → passa.

> Se `get_media_agregada` ignorar o parâmetro `dias` e ainda retornar 0, é sinal de
> que o endpoint/ função tem um bug real de produção → **STOP e reporte** (não
> conserte `database.py` aqui).

### Step 6: Diagnosticar e corrigir os testes de fetch e instanciação (Causas F, G)
Agora que o Step 1 corrigiu o mock, rode os testes restantes e diagnostique:
```
python -m pytest tests/test_quaest.py tests/test_atlas.py tests/test_poder360.py tests/test_collectors.py -q --tb=short
```
Para CADA falha remanescente, decida com este critério:
- Se o teste codifica uma **expectativa desatualizada** (lista de coletores, nº de
  registros que o mock produz, nomes) → atualize o teste para o comportamento atual.
- Se o coletor realmente **deixou de extrair** dados que deveria (bug de produção em
  `collectors/*.py`) → **STOP e reporte** com o nome do teste e o traceback. Não
  altere `collectors/*.py` neste plano.

**Verify**: `python -m pytest tests/test_quaest.py tests/test_atlas.py tests/test_poder360.py tests/test_collectors.py -q` → todos passam (ou STOP reportado).

### Step 7: Rodar a suíte inteira
**Verify**: `python -m pytest -q` → `0 failed`, exit 0.

## Test plan

Nenhum teste novo — este plano **conserta** testes existentes. Cobertura por causa:
- A: 4 testes de parse de coletor voltam a exercitar o caminho Gemini-mockado.
- B/C/D: asserts de dashboard/seed alinhados ao estado atual.
- E: `media_agregada` deixa de depender do relógio.
- F/G: fetch/instanciação corrigidos ou escalados como bug real.
- Padrão estrutural a seguir: os próprios testes vizinhos no mesmo arquivo.

## Done criteria

ALL devem valer:

- [ ] `python -m pytest -q` sai com código 0 e reporta `0 failed`.
- [ ] Nenhum arquivo fora de `tests/` foi modificado (`git status --short` mostra só
      `tests/`).
- [ ] `grep -rn "PULSO ELEITORAL" tests/` não retorna nada.
- [ ] `grep -rn "== 9" tests/test_database.py tests/test_dashboard.py` não retorna
      asserts de institutos (podem existir outros `== 9` legítimos; confira o
      contexto).
- [ ] Linha de status do Plano 001 atualizada em `plans/README.md`.

## STOP conditions

Pare e reporte (não improvise) se:
- Os trechos de "Current state" não baterem com o código vivo (drift desde `2b49ba3`).
- A verificação de um passo falhar duas vezes após uma tentativa razoável de correção.
- Uma falha de fetch (F) ou de `media_agregada` (E) revelar-se bug real de produção
  em `app.py`/`database.py`/`collectors/*.py` — o conserto de produção é outro
  trabalho.
- A contagem de institutos no seed não for 14.

## Maintenance notes

- Testes que dependem de "últimos N dias" contra um seed de datas fixas voltarão a
  quebrar conforme o relógio avança. O Step 5 mitiga `media_agregada`; ao adicionar
  novos testes com janela temporal, prefira inserir dados com datas relativas a
  `date.today()` em vez de confiar no seed estático.
- Sempre que `seed.sql` ganhar/perder institutos, `test_database.py` e
  `test_dashboard.py::test_api_institutos` precisam acompanhar a contagem.
- Atualize o README do projeto ("61 testes") para o número real após este plano.
- O revisor deve checar que NENHUM arquivo de produção foi tocado.
