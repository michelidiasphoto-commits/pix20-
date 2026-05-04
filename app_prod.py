import os, json, time, httpx, threading, random, secrets, telebot
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn
from pymongo import MongoClient
from fastapi.responses import HTMLResponse

# --- CONFIGURAÇÕES (AGORA COM SEU ID CORRETO) ---
TOKEN = "8618759737:AAH8JRKP_7Xm_nPXMiSxelKsPLbJMaRwM-M"
ADMIN_ID = "8215388700"  # Atualizado com o ID que apareceu no seu print

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

bot = telebot.TeleBot(TOKEN)

# --- MONGODB ---
MONGO_URI = "mongodb+srv://michelidiasphoto_db_user:lVN70gFWTgsecLTw@cluster0.eb7vf2i.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URI); db = client["sigilopay_db"]
col_cobrancas = db["cobrancas"]

class PixReq(BaseModel): valor: float

def gerar_cpf_aleatorio():
    c = [random.randint(0, 9) for _ in range(9)]
    for _ in range(2):
        v = sum([(len(c) + 1 - i) * val for i, val in enumerate(c)]) % 11
        c.append(11 - v if v > 1 else 0)
    return "".join(map(str, c))

# --- BOT TELEGRAM (LIBERADO PARA VOCÊ) ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    if str(message.from_user.id) != ADMIN_ID:
        bot.send_message(message.chat.id, f"❌ *Acesso Negado!*\nSeu ID é: `{message.from_user.id}`", parse_mode="Markdown")
        return
    text = (
        "✅ *SISTEMA VIP PIX 20% ATIVADO!*\n\n"
        "Você agora tem acesso total ao bot.\n\n"
        "💰 `/pix 50` - Gerar PIX SigiloPay\n"
        "📊 `/stats` - Ver vendas pagas\n"
        "📜 `/historico` - Ver últimas vendas"
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['pix'])
def bot_gerar_pix(message):
    if str(message.from_user.id) != ADMIN_ID: return
    try:
        args = message.text.split()
        valor = float(args[1]) if len(args) > 1 else 50.0
        bot.reply_to(message, f"⏳ Gerando PIX de R$ {valor:.2f}...")
        
        ident = f"bot_{int(time.time())}"
        payload = {"identifier": ident, "amount": valor, "callbackUrl": "https://pix20.onrender.com/webhook_pagamento", "client": {"name": "Bot", "email": "b@t.com", "phone": "119", "document": gerar_cpf_aleatorio()}}
        headers = {"x-public-key": "laispereiraphoto_2s0vatrdx6coy3pp", "x-secret-key": "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v", "Content-Type": "application/json"}
        
        with httpx.Client(timeout=30) as cl:
            resp = cl.post("https://app.sigilopay.com.br/api/v1/gateway/pix/receive", json=payload, headers=headers)
            data = resp.json()
            pix = data.get("pix") or data.get("order", {}).get("pix") or {}
            qrt = pix.get("code") or pix.get("payload") or ""
            
            if qrt:
                bot.send_message(message.chat.id, f"✅ *PIX GERADO!*\n💰 Valor: R$ {valor:.2f}\n\n📱 Copia e Cola:\n`{qrt}`", parse_mode="Markdown")
            else:
                bot.reply_to(message, "❌ Erro SigiloPay: API não retornou código.")
    except Exception as e:
        bot.reply_to(message, f"❌ Erro: {str(e)}")

@bot.message_handler(commands=['stats'])
def bot_stats(message):
    if str(message.from_user.id) != ADMIN_ID: return
    pago = col_cobrancas.count_documents({"status": "pago"})
    bot.reply_to(message, f"📊 *Estatísticas:* \n✅ Pagos: {pago}\n💰 Total: R$ {pago*50:.2f}", parse_mode="Markdown")

# --- ROTAS WEB ---
@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    with open("dashboard.html", "r", encoding="utf-8") as f: return f.read()

@app.post("/api/gerar_pix_web")
async def gerar_pix_web(req: PixReq):
    ident = f"web_{int(time.time())}"
    payload = {"identifier": ident, "amount": req.valor, "callbackUrl": "https://pix20.onrender.com/webhook_pagamento", "client": {"name": "Web", "email": "w@e.com", "phone": "119", "document": gerar_cpf_aleatorio()}}
    headers = {"x-public-key": "laispereiraphoto_2s0vatrdx6coy3pp", "x-secret-key": "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as cl:
        resp = await cl.post("https://app.sigilopay.com.br/api/v1/gateway/pix/receive", json=payload, headers=headers)
        data = resp.json()
        pix = data.get("pix") or data.get("order", {}).get("pix") or {}
        qrt = pix.get("code") or pix.get("payload") or ""
        return {"success": True, "qr_text": qrt}

@app.on_event("startup")
def startup():
    threading.Thread(target=lambda: bot.infinity_polling(), daemon=True).start()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
