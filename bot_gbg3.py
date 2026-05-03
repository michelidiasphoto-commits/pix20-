import asyncio
import os
import json
from playwright.async_api import async_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(BASE_DIR, "sessao_gbg3.json")
URL_DEPOSITO = "https://www.gbg3.bet/#/Recharge"

async def gerar_pix_jogo(valor):
    if not os.path.exists(SESSION_FILE):
        return {"success": False, "message": "Sessão não encontrada."}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(storage_state=SESSION_FILE)
        page = await context.new_page()
        
        try:
            await page.goto(URL_DEPOSITO, timeout=40000)
            
            # Preenche o valor
            input_val = await page.wait_for_selector("input[type='number'], input[placeholder*='valor']", timeout=15000)
            await input_val.fill("")
            await input_val.type(str(valor))
            
            # Clica no botão de depósito
            await page.click("button:has-text('Depósito'), .btn-recharge, button:has-text('Confirmar')", timeout=5000)
            
            # Espera e busca o código PIX de forma agressiva
            pix_code = ""
            for _ in range(30): # Tenta por 15 segundos
                pix_code = await page.evaluate("""() => {
                    // Busca em todos os inputs e textos o código que começa com 000201
                    const bodyText = document.body.innerText;
                    const match = bodyText.match(/000201[^\s]+/);
                    if (match) return match[0];
                    
                    const inputs = Array.from(document.querySelectorAll('input, textarea'));
                    for (let i of inputs) {
                        if (i.value.startsWith('000201')) return i.value;
                    }
                    return '';
                }""")
                if pix_code: break
                await asyncio.sleep(0.5)
            
            if pix_code:
                return {"success": True, "pix_code": pix_code}
            return {"success": False, "message": "Código PIX não encontrado na tela."}

        except Exception as e:
            return {"success": False, "message": str(e)}
        finally:
            await browser.close()
