# Plan 002: Adicionar gate de testes no CI antes do deploy para o Fly.io

> **Executor instructions**: Siga o plano passo a passo. Rode cada verificação e
> confirme o resultado antes de avançar. Se algo nas "STOP conditions" ocorrer, pare
> e reporte. Ao terminar, atualize a linha de status em `plans/README.md`.
>
> **Drift check (rode primeiro)**:
> `git diff --stat 2b49ba3..HEAD -- .github/workflows/ requirements.txt`
> Se algum arquivo em escopo mudou desde `2b49ba3`, compare com os trechos de
> "Current state" antes de prosseguir.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (mexe só no workflow de CI)
- **Depends on**: `plans/001-fix-test-baseline.md` — o gate só pode entrar com a
  suíte verde; senão todo deploy passa a falhar.
- **Category**: dx / tests
- **Planned at**: commit `2b49ba3`, 2026-06-26

## Why this matters

O único workflow do repo (`.github/workflows/fly-deploy.yml`) roda
`flyctl deploy --remote-only` a cada push na `main`, **sem nenhum passo de teste**.
Código quebrado (hoje 13 testes falham) vai direto para produção sem barreira. Com
um job de `pytest` que precede o deploy, um push que quebra a suíte falha o pipeline
e não publica. Isso transforma a suíte de testes (restaurada no Plano 001) em uma
rede de segurança real de produção.

## Current state

`.github/workflows/fly-deploy.yml` (conteúdo integral hoje):
```yaml
name: Fly Deploy
on:
  push:
    branches:
      - main
jobs:
  deploy:
    name: Deploy app
    runs-on: ubuntu-latest
    concurrency: deploy-group
    steps:
      - uses: actions/checkout@v4
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - run: flyctl deploy --remote-only
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

Fatos relevantes:
- Python do projeto: **3.11+** (Dockerfile usa `python:3.11-slim`; README pede 3.11+).
- Dependências em `requirements.txt` (inclui `pytest>=8.0.0`).
- Os testes mockam Playwright e Gemini em `tests/conftest.py` (autouse), então **não
  precisam de browser real nem de chaves de API** para rodar. NÃO é necessário
  `playwright install` no CI de testes.
- A suíte leva ~1-2 min (é aceitável rodar inteira no CI).

## Commands you will need

| Propósito | Comando | Esperado |
|-----------|---------|----------|
| Validar YAML localmente | `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/fly-deploy.yml'))"` | exit 0, sem erro |
| Rodar testes localmente | `python -m pytest -q` | `0 failed`, exit 0 |

(Para validar o YAML, `pyyaml` pode não estar instalado; se faltar, pule a validação
local e confie na sintaxe — ela é simples.)

## Scope

**In scope** (único arquivo a modificar):
- `.github/workflows/fly-deploy.yml`

**Out of scope**:
- `requirements.txt`, `Dockerfile`, qualquer código de aplicação.
- Não adicione lint/typecheck aqui (é outro trabalho) — só o gate de testes.

## Git workflow

- Branch: `advisor/002-ci-test-gate`
- Commit único; mensagem estilo conventional commits, ex.:
  `ci: roda pytest como gate antes do deploy no Fly`.
- Não faça push/PR a menos que o operador peça. **Atenção**: este arquivo só tem
  efeito quando estiver na `main`; o operador controla o merge.

## Steps

### Step 1: Adicionar um job `test` e fazer `deploy` depender dele
Reescreva `.github/workflows/fly-deploy.yml` para esta forma (mantém o deploy
idêntico, só adiciona o gate):

```yaml
name: Fly Deploy
on:
  push:
    branches:
      - main
jobs:
  test:
    name: Run tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - run: python -m pytest -q

  deploy:
    name: Deploy app
    needs: test
    runs-on: ubuntu-latest
    concurrency: deploy-group
    steps:
      - uses: actions/checkout@v4
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - run: flyctl deploy --remote-only
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

Pontos-chave:
- `needs: test` no job `deploy` faz o deploy só rodar se os testes passarem.
- O job `test` não instala Playwright (os testes mockam tudo via conftest).
- `cache: 'pip'` acelera execuções subsequentes.

**Verify**:
- `python -c "import yaml; yaml.safe_load(open('.github/workflows/fly-deploy.yml'))"`
  → exit 0 (se `pyyaml` disponível).
- Inspeção visual: o job `deploy` contém `needs: test`.

### Step 2: Confirmar que a suíte passa localmente (pré-condição do gate)
**Verify**: `python -m pytest -q` → `0 failed`. Se houver falhas, o Plano 001 não foi
concluído → **STOP** (não faça merge deste gate com a suíte vermelha).

## Test plan

Sem testes de código novos. A validação é o próprio pipeline:
- Localmente: `pytest -q` verde garante que o gate não bloqueará deploys legítimos.
- No GitHub (responsabilidade do operador no merge): o primeiro push deve mostrar o
  job `test` verde seguido do `deploy`.

## Done criteria

ALL devem valer:

- [ ] `.github/workflows/fly-deploy.yml` tem um job `test` que roda `python -m pytest -q`.
- [ ] O job `deploy` tem `needs: test`.
- [ ] O YAML é válido (carrega sem erro com `yaml.safe_load`, se testável).
- [ ] `python -m pytest -q` sai com código 0 localmente.
- [ ] Nenhum arquivo fora de `.github/workflows/fly-deploy.yml` foi modificado.
- [ ] Linha de status do Plano 002 atualizada em `plans/README.md`.

## STOP conditions

Pare e reporte se:
- A suíte local ainda tem falhas (Plano 001 incompleto) — não introduza um gate que
  quebraria todo deploy.
- O conteúdo atual do workflow divergir do trecho em "Current state".
- A instalação de dependências no job exigir passos extras não óbvios (ex.: deps de
  sistema) — reporte antes de adicionar.

## Maintenance notes

- Se no futuro algum teste passar a exigir Playwright real (não mockado), o job
  `test` precisará de `playwright install chromium` — hoje NÃO precisa.
- Ao adicionar lint/format/typecheck (backlog), encaixe como passos ou jobs adicionais
  com `needs` apropriado.
- O revisor deve confirmar que o deploy continua idêntico (mesmo comando, mesma
  secret `FLY_API_TOKEN`) e que a única mudança é a dependência `needs: test`.
