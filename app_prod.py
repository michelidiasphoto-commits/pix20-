import os, json, time, httpx, threading, telebot
from fastapi import FastAPI
import uvicorn

TOKEN = "8618759737:AAH8JRKP_7Xm_nPXMiSxelKsPLbJMaRwM-M"
bot = telebot.TeleBot(TOKEN)
app = FastAPI()

def check_token():
    try:
        me = bot.get_me()
        print(f"✅ BOT CONECTADO: @{me.username}")
        return True
    except Exception as e:
        print(f"❌ ERRO DE TOKEN: O Token pode estar inválido ou expirado. Erro: {e}")
        return False

@bot.message_handler(func=lambda m: True)
def reply_all(message):
    print(f"💬 Mensagem recebida: {message.text}")
    bot.reply_to(message, "ESTOU VIVO! O bot está funcionando.")

def run_bot():
    if check_token():
        bot.infinity_polling()

@app.on_event("startup")
def startup():
    threading.Thread(target=run_bot, daemon=True).start()

@app.get("/bot_status")
def bot_status():
    try:
        me = bot.get_me()
        return {"status": "online", "bot_username": me.username}
    except Exception as e:
        return {"status": "offline", "error": str(e)}

@app.get("/")
def home():
    return {"message": "Servidor Online. Acesse /bot_status para ver o bot."}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
