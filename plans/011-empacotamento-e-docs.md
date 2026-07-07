# Plan 011: Corrigir empacotamento (playwright, pytest config, lockfile) e docs que mentem

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b3b92ef..HEAD -- requirements.txt .github/workflows/fly-deploy.yml README.md Dockerfile`
> Divergência com os excertos abaixo = STOP.

## Status

- **Priority**: P2
- **Effort**: S–M
- **Risk**: LOW (Steps 1–3) / MED (Step 4, lockfile)
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `b3b92ef`, 2026-07-07

## Why this matters

`pip install -r requirements.txt` produz um ambiente quebrado: 7 módulos de
coletores importam `playwright` no load, mas ele não está no requirements — o
CI compensa com um `pip install playwright` ad-hoc comentado no workflow. O
README documenta `pytest --cov` (falha: `pytest-cov` não é dependência) e diz
"61 testes" em três lugares (a suíte tem ~139 funções de teste). Não há
`pyproject.toml`: cada arquivo de teste seta `TESTING=True` à mão. E com tudo
em `>=` sem lockfile, o deploy resolve dependências diferentes do último run
verde. Baixo esforço, remove atrito para todo agente/contribuidor.

## Current state

- `requirements.txt` (13 linhas, todas `>=`):

```
flask>=3.0.0
waitress>=3.0.0
beautifulsoup4>=4.12.0
requests>=2.31.0
apscheduler>=3.10.0
google-genai>=1.0.0
pdfplumber>=0.10.0
python-dotenv>=1.0.0
lxml>=5.0.0
pytest>=8.0.0
bcrypt>=4.0.0
flask-caching>=2.3.0
flask-wtf>=1.2.0
```

- `.github/workflows/fly-deploy.yml` — job `test`:

```yaml
      - run: pip install -r requirements.txt
      # Os coletores importam playwright.sync_api no load do módulo (mesmo com o
      # browser mockado nos testes), e playwright não está em requirements.txt.
      # Só o pacote é necessário — não o binário do Chromium.
      - run: pip install playwright
      - run: python -m pytest -q
```

- `README.md` — "61 testes"/"61 tests" nas linhas ~147, ~221 e ~260; e nas
  linhas ~253–254: `pytest --cov=. --cov-report=term-missing`.
- Não existem `pyproject.toml`, `pytest.ini`, `setup.cfg` (verificado).
- `Dockerfile:8-10`: `pip install playwright` + `playwright install chromium` +
  `playwright install-deps chromium`.
- Python consistente em 3.11 (local, Dockerfile, CI).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Suíte | `python -m pytest -q` | exit 0, 0 failed |
| Instalação limpa (opcional, em venv descartável) | `pip install -r requirements.txt && python -c "import playwright"` | exit 0 |

## Scope

**In scope**:
- `requirements.txt`
- `.github/workflows/fly-deploy.yml` (remoção do install ad-hoc)
- `pyproject.toml` (criar)
- `README.md` (contagem de testes + comando de cobertura)
- `requirements.lock` (criar, Step 4)
- `Dockerfile` (apenas se o Step 4 apontar o lockfile; NÃO remover o Chromium — ver Out of scope)

**Out of scope** (NÃO tocar):
- Remover `playwright install chromium` do Dockerfile — há hipótese de a rota
  `/admin/coletar-url` em produção precisar do browser; investigação separada.
- Adicionar lint/ruff — decisão de tooling à parte (ver Maintenance notes).
- `tests/*.py` (não remover os `os.environ['TESTING']` existentes — redundância
  inofensiva).

## Git workflow

- Commits em português, ex.: `chore(deps): declara playwright, cria pyproject e corrige docs de teste`.

## Steps

### Step 1: Declarar playwright

Adicionar `playwright>=1.40.0` ao `requirements.txt`. Remover do
`.github/workflows/fly-deploy.yml` a linha `- run: pip install playwright` e o
comentário de 3 linhas acima dela (a explicação deixa de ser verdadeira).
No `Dockerfile`, se a linha 8 for exatamente `pip install playwright`, ela pode
permanecer ou ser removida (o `pip install -r requirements.txt` anterior já
cobre) — remover apenas se o requirements for instalado ANTES dela no Dockerfile;
confira a ordem real das camadas antes.

**Verify**: `python -m pytest -q` → exit 0. `grep -n "pip install playwright" .github/workflows/fly-deploy.yml` → sem resultado.

### Step 2: `pyproject.toml` com config do pytest

Criar na raiz:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

Não adicionar seção `[project]`/build — o repo não é um pacote instalável e
transformá-lo em um muda o comportamento do pip.

**Verify**: `python -m pytest` → exit 0, coleta os mesmos testes de antes
(comparar o total exibido com o do Step 1).

### Step 3: README verdadeiro

- Trocar as três ocorrências de "61 testes"/"61 tests" pelo número real
  coletado (rodar `python -m pytest --collect-only -q | tail -1` e usar esse
  total) — ou pela forma sem número "suíte pytest cobrindo ...", que não apodrece.
- Cobertura: adicionar `pytest-cov>=5.0` ao `requirements.txt` (mantendo o
  comando documentado) — alternativa: apagar o snippet `--cov` do README.
  Escolher a primeira opção (o comando documentado passa a funcionar).

**Verify**: `python -m pytest --cov=. --cov-report=term-missing -q` → exit 0 com
relatório de cobertura. `grep -n "61 test" README.md` → sem resultado.

### Step 4: Lockfile (reprodutibilidade)

1. `pip install pip-tools`
2. `pip-compile requirements.txt --output-file requirements.lock` (gera pins exatos)
3. No workflow, trocar `pip install -r requirements.txt` por
   `pip install -r requirements.lock`.
4. No `Dockerfile`, trocar o install do requirements pelo lock (manter o
   `COPY` correspondente).
5. Rodar a suíte com o ambiente resolvido pelo lock.

O `requirements.txt` permanece como manifesto de intenção (ranges); o `.lock`
é o que CI/produção instalam.

**Verify**: `python -m pytest -q` → exit 0 com as versões do lock;
`grep -n "requirements.lock" .github/workflows/fly-deploy.yml Dockerfile` →
1 resultado em cada.

## Test plan

Sem testes novos — os gates são a própria suíte rodando em cada step e os
greps de verificação.

## Done criteria

- [ ] `pip install -r requirements.txt` instala `playwright` (presente no arquivo)
- [ ] Workflow sem install ad-hoc de playwright
- [ ] `pyproject.toml` com `[tool.pytest.ini_options]` existe
- [ ] `grep -n "61 test" README.md` vazio; comando de cobertura do README executa
- [ ] `requirements.lock` existe e é usado por CI e Dockerfile
- [ ] `python -m pytest -q` exit 0
- [ ] Linha de status atualizada em `plans/README.md`

## STOP conditions

- `pip-compile` resolver uma versão que quebra a suíte e o fix não for óbvio
  (ex.: pin de uma major anterior) — reportar o conflito em vez de forçar.
- O Dockerfile tiver ordem de camadas diferente da assumida no Step 1.
- Qualquer step exigir mudar código de produção (`app.py`, `collectors/`).

## Maintenance notes

- Renovar o lock: `pip-compile --upgrade` conscientemente, com suíte verde.
- Decisão deferida: adotar `ruff` (lint+format) — recomendado como follow-up,
  mas é escolha de tooling do dono do repo; se adotar, pendurar no mesmo
  `pyproject.toml` e no job `test` do workflow.
- O plano 014 (CLAUDE.md) documenta essas convenções — executá-lo depois deste
  deixa o CLAUDE.md já correto.
