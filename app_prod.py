import os, json, time, httpx, threading, random, secrets, telebot
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn
from pymongo import MongoClient
from fastapi.responses import HTMLResponse
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

# --- CONFIGURAÇÕES ---
TOKEN = "8618759737:AAH8JRKP_7Xm_nPXMiSxelKsPLbJMaRwM-M"
ADMIN_ID = "8215388700"
WEBAPP_URL = "https://pix20.onrender.com"

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

bot = telebot.TeleBot(TOKEN)

# --- MONGODB ---
MONGO_URI = "mongodb+srv://michelidiasphoto_db_user:lVN70gFWTgsecLTw@cluster0.eb7vf2i.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URI); db = client["sigilopay_db"]
col_cobrancas = db["cobrancas"]

class PixReq(BaseModel): valor: float

# --- BOT TELEGRAM (COM BOTÃO WEBAPP) ---
@bot.message_handler(commands=['start', 'painel'])
def send_welcome(message):
    if str(message.from_user.id) != ADMIN_ID: return
    
    markup = InlineKeyboardMarkup()
    # Criando o botão que abre o Painel Web direto no Telegram
    web_button = InlineKeyboardButton(text="📱 ABRIR PAINEL WEB", web_app=WebAppInfo(url=WEBAPP_URL))
    markup.add(web_button)
    
    text = (
        "✅ *SISTEMA PIX 20% ATIVO!*\n\n"
        "Você pode gerar cobranças por aqui ou usar o nosso Painel Web exclusivo dentro do Telegram.\n\n"
        "💰 `/pix 50` - Gerar no chat\n"
        "📊 `/stats` - Ver vendas"
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=['pix'])
def bot_gerar_pix(message):
    if str(message.from_user.id) != ADMIN_ID: return
    try:
        valor = float(message.text.split()[1])
        ident = f"bot_{int(time.time())}"
        payload = {"identifier": ident, "amount": valor, "callbackUrl": f"{WEBAPP_URL}/webhook_pagamento", "client": {"name": "Bot", "email": "b@t.com", "phone": "119", "document": "12345678909"}}
        headers = {"x-public-key": "laispereiraphoto_2s0vatrdx6coy3pp", "x-secret-key": "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v", "Content-Type": "application/json"}
        with httpx.Client(timeout=30) as cl:
            resp = cl.post("https://app.sigilopay.com.br/api/v1/gateway/pix/receive", json=payload, headers=headers)
            pix = resp.json().get("pix") or {}
            qrt = pix.get("code") or pix.get("payload") or ""
            if qrt: bot.reply_to(message, f"✅ *PIX GERADO!*\n💰 R$ {valor:.2f}\n\n`{qrt}`", parse_mode="Markdown")
    except: pass

# --- ROTAS WEB ---
@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    with open("dashboard.html", "r", encoding="utf-8") as f: return f.read()

@app.post("/api/login")
async def api_login(d: dict):
    if d.get("username") == "admin_maisvelho" and d.get("password") == "maisvelhoadmin": return {"success": True}
    return {"success": False}

@app.get("/api/stats")
async def get_stats():
    pago = col_cobrancas.count_documents({"status": "pago"})
    return {"pago": pago, "valor": pago * 50.0}

@app.post("/api/gerar_pix_web")
async def gerar_pix_web(req: PixReq):
    ident = f"web_{int(time.time())}"
    payload = {"identifier": ident, "amount": req.valor, "callbackUrl": f"{WEBAPP_URL}/webhook_pagamento", "client": {"name": "Web", "email": "w@e.com", "phone": "119", "document": "12345678909"}}
    headers = {"x-public-key": "laispereiraphoto_2s0vatrdx6coy3pp", "x-secret-key": "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as cl:
        resp = await cl.post("https://app.sigilopay.com.br/api/v1/gateway/pix/receive", json=payload, headers=headers)
        pix = resp.json().get("pix") or {}
        return {"success": True, "qr_text": pix.get("code") or pix.get("payload") or ""}

@app.on_event("startup")
def startup(): threading.Thread(target=lambda: bot.infinity_polling(), daemon=True).start()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
