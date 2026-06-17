from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import logging
import time

class PlaywrightCollector:
    """
    Mixin base para coletores que precisam de browser real.
    Herda junto com BaseCollector.
    """
    
    def _get_page_playwright(self, url: str, wait_selector = None,
                              wait_seconds: int = 3) -> str:
        """
        Abre URL com Chromium headless, aguarda renderização JS,
        retorna HTML completo da página renderizada.
        
        Args:
            url: URL a acessar
            wait_selector: seletor CSS (ou lista de seletores) para aguardar antes de capturar HTML
                          (ex: '.resultado', 'table', '#dados')
            wait_seconds: segundos extras de espera após carregamento
        
        Returns:
            HTML renderizado como string, ou "" em caso de erro
        """
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-blink-features=AutomationControlled'
                    ]
                )
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    locale='pt-BR',
                    timezone_id='America/Sao_Paulo'
                )
                page = context.new_page()
                
                # Bloqueia recursos desnecessários (imagens, fonts, media)
                # para acelerar carregamento
                page.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,mp4,mp3}",
                           lambda route: route.abort())
                
                page.goto(url, timeout=30000, wait_until='domcontentloaded')
                
                # Tenta aceitar cookies se banner aparecer
                try:
                    # Complianz (usado pelo Quaest)
                    accept_btn = page.locator('button.cmplz-accept, .cmplz-btn-accept, button:has-text("OK"), button:has-text("Aceitar"), button:has-text("Accept"), button:has-text("Concordo")')
                    if accept_btn.count() > 0:
                        accept_btn.first.click()
                        time.sleep(1)
                        self.logger.info("Cookie banner dispensado")
                except Exception:
                    pass  # Se não achar botão, continua mesmo assim
                
                # Aguarda seletor específico se fornecido
                if wait_selector:
                    selectors = [wait_selector] if isinstance(wait_selector, str) else wait_selector
                    for sel in selectors:
                        try:
                            page.wait_for_selector(sel, timeout=10000)
                            break
                        except PlaywrightTimeout:
                            self.logger.warning(f"Seletor '{sel}' não encontrado em {url}")
                
                # Espera extra para JS dinâmico
                if wait_seconds > 0:
                    time.sleep(wait_seconds)
                
                html = page.content()
                browser.close()
                return html
                
        except Exception as e:
            self.logger.error(f"Playwright erro em {url}: {e}")
            return ""
