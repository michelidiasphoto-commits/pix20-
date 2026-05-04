import os, json, time, httpx, threading, random, secrets, telebot
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn
from pymongo import MongoClient
from fastapi.responses import HTMLResponse

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- CONFIGURAÇÕES ---
TOKEN = "8618759737:AAH8JRKP_7Xm_nPXMiSxelKsPLbJMaRwM-M"
ADMIN_ID = "8084292904"

# --- MONGODB ---
MONGO_URI = "mongodb+srv://michelidiasphoto_db_user:lVN70gFWTgsecLTw@cluster0.eb7vf2i.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URI); db = client["sigilopay_db"]
col_cobrancas = db["cobrancas"]; col_users = db["users"]

bot = telebot.TeleBot(TOKEN)
JOBS = {}

class PixReq(BaseModel):
    valor: float

# --- FUNÇÕES DE APOIO ---
def gerar_cpf_aleatorio():
    c = [random.randint(0, 9) for _ in range(9)]
    for _ in range(2):
        v = sum([(len(c) + 1 - i) * val for i, val in enumerate(c)]) % 11
        c.append(11 - v if v > 1 else 0)
    return "".join(map(str, c))

# --- ROTAS API (PAINEL) ---
@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    with open("dashboard.html", "r", encoding="utf-8") as f: return f.read()

@app.post("/api/login")
async def api_login(d: dict):
    u = d.get("username"); p = d.get("password")
    if u == "admin_maisvelho" and p == "maisvelhoadmin": return {"success": True, "role": "master"}
    return {"success": False, "message": "Login inválido"}

@app.get("/api/stats")
async def get_stats():
    count = col_cobrancas.count_documents({"status": "pago"})
    return {"pago": count, "valor": count * 50.0}

@app.post("/api/gerar_pix_web")
async def gerar_pix_web(req: PixReq):
    ident = f"cashin_{int(time.time())}"
    str_cpf = gerar_cpf_aleatorio()
    payload = {
        "identifier": ident, "amount": round(req.valor, 2),
        "callbackUrl": "https://pix20.onrender.com/webhook_pagamento",
        "client": {"name": "Cliente VIP", "email": "c@e.com", "phone": "119", "document": str_cpf}
    }
    headers = {
        "x-public-key": "laispereiraphoto_2s0vatrdx6coy3pp",
        "x-secret-key": "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v",
        "Content-Type": "application/json"
    }
    async with httpx.AsyncClient(timeout=30) as cl:
        try:
            resp = await cl.post("https://app.sigilopay.com.br/api/v1/gateway/pix/receive", json=payload, headers=headers)
            data = resp.json()
            pix = data.get("pix") or data.get("order", {}).get("pix") or {}
            qrt = pix.get("code") or pix.get("payload") or data.get("qrcode") or ""
            
            # Salva no MongoDB
            col_cobrancas.insert_one({
                "transaction_id": ident, "valor": req.valor, "status": "aguardando",
                "metodo": "sigilopay", "criado_em": datetime.now()
            })
            
            return {"success": True, "qr_text": qrt}
        except: return {"success": False, "message": "Erro na API"}

# --- LÓGICA DO BOT DE TELEGRAM INTEGRADA ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    if str(message.from_user.id) != ADMIN_ID: return
    text = "👋 *Olá! SigiloPay On-line!*\\n\\nUse `/pix 50` para gerar um PIX."
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['pix'])
def bot_gerar_pix(message):
    if str(message.from_user.id) != ADMIN_ID: return
    try:
        valor = float(message.text.split()[1])
        ident = f"bot_{int(time.time())}"
        str_cpf = gerar_cpf_aleatorio()
        
        headers = {
            "x-public-key": "laispereiraphoto_2s0vatrdx6coy3pp",
            "x-secret-key": "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v",
            "Content-Type": "application/json"
        }
        payload = {
            "identifier": ident, "amount": valor,
            "callbackUrl": "https://pix20.onrender.com/webhook_pagamento",
            "client": {"name": "Bot Telegram", "email": "b@t.com", "phone": "119", "document": str_cpf}
        }
        
        with httpx.Client(timeout=30) as cl:
            resp = cl.post("https://app.sigilopay.com.br/api/v1/gateway/pix/receive", json=payload, headers=headers)
            data = resp.json()
            pix = data.get("pix") or data.get("order", {}).get("pix") or {}
            qrt = pix.get("code") or pix.get("payload") or ""
            
            if qrt:
                bot.reply_to(message, f"✅ *PIX Gerado!*\\n\\n💰 Valor: R$ {valor:.2f}\\n\\n📱 Copia e Cola:\\n`{qrt}`", parse_mode="Markdown")
            else:
                bot.reply_to(message, "❌ Erro ao gerar PIX.")
    except:
        bot.reply_to(message, "❌ Use: `/pix [valor]`")

# --- EXECUÇÃO EM PARALELO ---
def run_bot():
    print("🤖 Bot de Telegram Iniciado...")
    bot.infinity_polling()

if __name__ == "__main__":
    # Liga o Bot em segundo plano
    threading.Thread(target=run_bot, daemon=True).start()
    # Liga o Servidor Web
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
