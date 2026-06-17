import asyncio
from playwright.async_api import async_playwright
import os

PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})

        errors = []
        logs = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: logs.append(f"[{m.type}] {m.text}"))

        # Login
        await page.goto("http://localhost:5080/login")
        await page.fill('input[name="username"]', "admin")
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle", timeout=10000)
        print(f"URL pós-login: {page.url}")

        if "/login" in page.url:
            print("ERRO: login falhou")
            await browser.close()
            return

        # Wait for JS init to complete
        await asyncio.sleep(4)

        # Check candidatos-toggle
        inner = await page.evaluate("document.getElementById('candidatos-toggle')?.innerHTML || 'NOT FOUND'")
        print(f"innerHTML candidatos-toggle: {inner[:300]}")

        checkboxes = await page.query_selector_all('#candidatos-toggle input[type="checkbox"]')
        print(f"Checkboxes encontrados: {len(checkboxes)}")

        # Show relevant console logs
        for log in logs:
            if any(k in log for k in ["historico", "erro", "error", "fail", "Gemini", "candidato"]):
                print(f"Console: {log}")

        if not checkboxes:
            print("Todos os logs de console:")
            for log in logs[:30]:
                print(f"  {log}")
            await browser.close()
            return

        # Verify onchange has no params
        first_cb = checkboxes[0]
        val = await first_cb.get_attribute("value")
        onchange = await first_cb.get_attribute("onchange")
        print(f"Candidato: {val} | onchange: {onchange}")
        assert onchange == "toggleCandidato()", f"ERRO: onchange inesperado: {onchange}"
        print("OK: onchange sem parâmetros")

        # Uncheck first candidate
        await first_cb.uncheck()
        await asyncio.sleep(1)
        print(f"Erros JS após uncheck: {errors or 'nenhum'}")

        # Re-check
        await first_cb.check()
        await asyncio.sleep(0.5)
        print(f"Erros JS total: {errors or 'nenhum'}")

        await browser.close()
        if errors:
            print(f"FALHA: erros JS: {errors}")
        else:
            print("TESTE OK")

asyncio.run(main())
