
import asyncio
import os
import json
from playwright.async_api import async_playwright

# Configurações
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(BASE_DIR, "sessao_gbg3.json")
URL_BASE = "https://www.gbg3.bet/#/Index"
URL_DEPOSITO = "https://www.gbg3.bet/#/Recharge"

async def conectar_jogo():
    """
    Abre o navegador para o usuário logar manualmente e resolver o CAPTCHA.
    Salva a sessão após o login bem-sucedido.
    """
    print("\n🔍 [1/4] Iniciando motor do robô...")
    async with async_playwright() as p:
        print("🌐 [2/4] Abrindo navegador Chrome...")
        args = ["--disable-blink-features=AutomationControlled"]
        
        try:
            browser = await p.chromium.launch(headless=False, args=args)
            context = await browser.new_context(viewport={'width': 1280, 'height': 720})
            page = await context.new_page()
            
            print(f"🚀 [3/4] Navegando para o site: {URL_BASE}")
            await page.goto(URL_BASE, timeout=60000)
            
            print("\n" + "="*50)
            print("✅ [4/4] PÁGINA CARREGADA!")
            print("POR FAVOR, FAÇA O LOGIN E RESOLVA O CAPTCHA AGORA.")
            print("Assim que você estiver logado, volte aqui no terminal.")
            print("="*50 + "\n")
            
            # Espera o usuário
            await asyncio.get_event_loop().run_in_executor(None, input, "Pressione ENTER aqui DEPOIS de estar logado no site...")
            
            # Salva o estado da sessão
            await context.storage_state(path=SESSION_FILE)
            print(f"\n✨ SUCESSO! Sessão salva em: {SESSION_FILE}")
            print("Pode fechar o navegador agora.")
            
        except Exception as e:
            print(f"\n❌ OCORREU UM ERRO: {e}")
            await asyncio.sleep(5)
        finally:
            await browser.close()

async def gerar_pix_jogo(valor):
    """
    Usa a sessão salva para gerar um PIX de depósito na GBG3.
    """
    if not os.path.exists(SESSION_FILE):
        return {"success": False, "message": "Sessão não encontrada. Conecte o jogo primeiro."}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=SESSION_FILE)
        page = await context.new_page()
        
        try:
            print(f"🤖 [ROBÔ] Entrando na página de recarga...")
            await page.goto(URL_DEPOSITO, timeout=60000)
            await page.wait_for_load_state("networkidle")
            
            # Tenta encontrar o campo de valor de várias formas
            print(f"💰 [ROBÔ] Preenchendo valor: R$ {valor}")
            input_selectors = [
                "input[type='number']", 
                "input[placeholder*='valor']", 
                "input[placeholder*='Valor']",
                ".recharge-input",
                "input[maxlength='10']"
            ]
            
            success_fill = False
            for selector in input_selectors:
                try:
                    el = await page.wait_for_selector(selector, timeout=3000)
                    if el:
                        await el.fill("") # Limpa
                        await el.type(str(valor))
                        success_fill = True
                        break
                except: continue
            
            if not success_fill:
                # Tenta clicar no botão de valor fixo se não achou o input
                await page.click(f"text='{int(valor)}'", timeout=3000)

            # Tenta clicar no botão de confirmar de várias formas
            print(f"👆 [ROBÔ] Clicando em confirmar depósito...")
            btn_selectors = [
                "button:has-text('Depósito')", 
                "button:has-text('Recarga')", 
                "button:has-text('Confirmar')",
                ".btn-recharge",
                ".confirm-btn",
                "text='Depósito'",
                "button.recharge-btn"
            ]
            
            for btn in btn_selectors:
                try:
                    await page.click(btn, timeout=3000)
                    break
                except: continue
            
            await asyncio.sleep(10) # Tempo extra para o QR Code carregar
            
            # Captura o código PIX de várias formas
            print(f"📸 [ROBÔ] Capturando código PIX...")
            pix_text = ""
            
            # Tenta pegar de inputs de "copia e cola"
            pix_text = await page.evaluate("""() => {
                const inputs = Array.from(document.querySelectorAll('input, textarea'));
                for (let i of inputs) {
                    if (i.value.includes('000201') && i.value.length > 50) return i.value;
                }
                return '';
            }""")
            
            if not pix_text:
                # Tenta pegar de elementos de texto
                elements = await page.query_selector_all("text, div, span, p")
                for el in elements:
                    try:
                        text = await el.inner_text()
                        if "000201" in text and len(text) > 50:
                            pix_text = text; break
                    except: pass
            
            if pix_text:
                print(f"✅ [ROBÔ] PIX Capturado com sucesso!")
                return {"success": True, "pix_code": pix_text}
            else:
                return {"success": False, "message": "O robô não encontrou o código PIX na tela. Verifique se o valor é permitido."}

        except Exception as e:
            return {"success": False, "message": f"Erro no robô: {str(e)}"}
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(conectar_jogo())
