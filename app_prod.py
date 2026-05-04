import os, json, time, httpx, threading, random, secrets, telebot
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from pymongo import MongoClient
from fastapi.responses import HTMLResponse

# --- CONFIGURAÇÕES ---
TOKEN = "8618759737:AAH8JRKP_7Xm_nPXMiSxelKsPLbJMaRwM-M"
# Removi a trava de ADMIN_ID temporariamente para teste

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

bot = telebot.TeleBot(TOKEN)

# --- BOT DE TELEGRAM (COMANDO START LIBERADO) ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    # Agora ele vai responder para TODO MUNDO só para testarmos
    print(f"📩 Recebido /start de {message.from_user.id}")
    text = "🚀 *SIGILOPAY ATIVO!*\\n\\nO bot está rodando com sucesso no Render.\\n\\nEnvie `/pix 10` para testar a geração."
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['pix'])
def bot_gerar_pix(message):
    try:
        valor = float(message.text.split()[1])
        bot.reply_to(message, f"⏳ Gerando PIX de R$ {valor:.2f}...")
        # (A lógica de geração continua aqui igual ao anterior)
    except:
        bot.reply_to(message, "Use: `/pix 10`")

def run_bot_forever():
    while True:
        try:
            print("🤖 Iniciando Polling do Bot...")
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"❌ Bot caiu, reiniciando em 5s... Erro: {e}")
            time.sleep(5)

# --- INICIALIZAÇÃO ---
@app.on_event("startup")
def startup_event():
    # Isso garante que o bot ligue ASSIM que o servidor web estiver pronto
    threading.Thread(target=run_bot_forever, daemon=True).start()

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    with open("dashboard.html", "r", encoding="utf-8") as f: return f.read()

# ... (Mantenha o resto das rotas de stats, login e pix_web iguais)

if __name__ == "__main__":
    # Garante que a porta seja lida corretamente do Render
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
