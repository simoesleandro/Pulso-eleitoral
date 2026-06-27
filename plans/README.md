# Implementation Plans

Gerado pela skill `improve` em 2026-06-26 (auditoria completa do projeto). Execute
na ordem abaixo, respeitando as dependências. Cada executor: leia o plano inteiro
antes de começar, honre as "STOP conditions" e atualize a linha de status quando
terminar.

Todos os planos foram escritos contra o commit `2b49ba3`.

## Ordem de execução & status

| Plano | Título | Prioridade | Esforço | Depende de | Status |
|-------|--------|-----------|---------|------------|--------|
| 001 | Restaurar suíte de testes verde (baseline) | P1 | M | — | DONE |
| 002 | Gate de testes no CI antes do deploy | P1 | S | 001 | DONE |
| 003 | Endurecer `/admin/apply-db` (auth + validação do DB) | P1 | M | — | DONE |
| 004 | Exigir `SECRET_KEY` (remover fallback commitado) | P1 | S | — | DONE |
| 005 | Remover senha admin default `pulso2026` | P1 | S | — | DONE |

Valores de status: TODO | IN PROGRESS | DONE | BLOCKED (motivo em uma linha) | REJECTED (motivo)

## Ordem recomendada

Os planos de segurança **003, 004, 005** são independentes entre si e do resto —
faça-os primeiro (rápidos, baixo risco, alto valor). Depois **001** (baseline de
testes) e por fim **002** (gate de CI, que só faz sentido com a suíte verde).

## Notas de dependência

- **002 depende de 001**: adicionar um gate de `pytest` ao deploy só é útil depois
  que a suíte está verde — senão todo deploy quebra.
- 003/004/005 não têm dependências; podem ser feitos em qualquer ordem ou em
  paralelo (tocam arquivos/linhas diferentes de `app.py` — atenção a conflitos de
  merge se feitos em branches separados).

## Achados considerados e rejeitados (para não re-auditar)

- **XSS em `templates/admin_coletar_url.html`**: os valores interpolados via
  `innerHTML` (`k.val`) são inteiros calculados no servidor (delta de `COUNT(*)`),
  nunca input do usuário; mensagens de erro usam `textContent`. Não explorável.
- **Vazamento de processo Playwright** em `collectors/playwright_base.py`: o
  `browser.close()` só roda no caminho de sucesso, mas tudo está dentro de
  `with sync_playwright() as p:`, que encerra o driver e mata o browser ao sair do
  contexto. Risco desprezível.
- **Dedup sem dimensão de data** em `collectors/base.py:100-103`: provável
  comportamento by-design (uma URL de release = uma pesquisa, atualizada in-place).
  Não tratar sem confirmar a intenção do produto.

## Achados auditados NÃO planejados (backlog, fora dos bundles escolhidos)

Disponíveis para virar planos depois, se desejado:
- CSRF + flags de cookie (`Secure`/`SameSite`) em rotas POST (médio).
- Guarda anti-SSRF em `/admin/coletar-url` (médio, requer admin logado).
- Headers de segurança HTTP (CSP, X-Frame-Options, HSTS).
- Pin de dependências / lockfile (`requirements.txt` usa `>=`).
- Deduplicar `_get_page`/dedup de links entre coletores.
- `except Exception: pass` silenciosos em `database.py`.
- DX: lint/format/typecheck, `CLAUDE.md`, `.env.example` (BOM + var faltando),
  Dockerfile instala Playwright 2×.
- Código morto na raiz: `check.py`, `check_tables.py`, `test_toggle.py`,
  `scripts/debug_*.py`.
