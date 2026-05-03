import asyncio
import os
import json
from playwright.async_api import async_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(BASE_DIR, "sessao_gbg3.json")
URL_DEPOSITO = "https://www.gbg3.bet/#/Recharge"

async def gerar_pix_jogo(valor):
    if not os.path.exists(SESSION_FILE):
        return {"success": False, "message": "Sessão não encontrada. Suba o arquivo sessao_gbg3.json para o GitHub."}

    async with async_playwright() as p:
        # Lança o navegador com configurações de performance
        browser = await p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox"])
        context = await browser.new_context(storage_state=SESSION_FILE)
        page = await context.new_page()
        
        try:
            # Vai direto para a página de depósito
            await page.goto(URL_DEPOSITO, timeout=30000, wait_until="commit")
            
            # Tenta preencher o valor rápido
            input_val = await page.wait_for_selector("input[type='number'], input[placeholder*='valor']", timeout=10000)
            await input_val.fill(str(valor))
            
            # Clica no botão de depósito
            await page.click("button:has-text('Depósito'), .btn-recharge, button:has-text('Confirmar')", timeout=5000)
            
            # Espera o PIX aparecer (máximo 10 segundos)
            for _ in range(20):
                pix_text = await page.evaluate("""() => {
                    const el = document.body.innerText.match(/000201[a-zA-Z0-9]+/);
                    return el ? el[0] : '';
                }""")
                if pix_text: return {"success": True, "pix_code": pix_text}
                await asyncio.sleep(0.5)
            
            return {"success": False, "message": "O QR Code não apareceu a tempo. Tente novamente."}

        except Exception as e:
            return {"success": False, "message": f"Erro: {str(e)}"}
        finally:
            await browser.close()
