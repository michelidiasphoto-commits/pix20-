
import os
import json
import time
import secrets
import random
import threading
import httpx
from datetime import datetime
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn
import telebot
from telebot import types
from pymongo import MongoClient
from fastapi.responses import HTMLResponse

# --- CONFIGURAÇÃO ---
# No Render, as variáveis de ambiente são preferíveis, mas manteremos o fallback para seu JSON
MONGO_URI = "mongodb+srv://michelidiasphoto_db_user:lVN70gFWTgsecLTw@cluster0.eb7vf2i.mongodb.net/?appName=Cluster0"
DB_NAME = "sigilopay_db"

# Tenta carregar do config local se existir, senão usa padrões
BASE = os.path.dirname(os.path.abspath(__file__))
CFG_FILE = os.path.join(BASE, "sigilopay_config.json")

def load_cfg():
    if os.path.exists(CFG_FILE):
        try:
            with open(CFG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {
        "public_key": "laispereiraphoto_2s0vatrdx6coy3pp",
        "secret_key": "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v",
        "api_base": "https://app.sigilopay.com.br",
        "telegram_token": "8618759737:AAH8JRKP_7Xm_nPXMiSxelKsPLbJMaRwM-M",
        "telegram_admin_id": "8084292904",
        "webhook_url": "http://localhost:8000", # Será atualizado pelo Render
        "parceiros": {"admin": "admin_master_key_123"}
    }

CFG = load_cfg()

# --- MONGODB SETUP ---
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
col_cobrancas = db["cobrancas"]
col_users = db["users"]

def db_criar(tid, parceiro, valor, qrc, qrt):
    col_cobrancas.update_one(
        {"transaction_id": tid},
        {"$set": {
            "parceiro": parceiro,
            "valor": valor,
            "status": "aguardando",
            "qr_code": qrc,
            "qr_text": qrt,
            "criado_em": datetime.now().isoformat()
        }},
        upsert=True
    )

def db_update(tid, status):
    pago_em = datetime.now().isoformat() if status == "pago" else None
    col_cobrancas.update_one(
        {"transaction_id": tid},
        {"$set": {"status": status, "pago_em": pago_em}}
    )

def db_status(tid):
    return col_cobrancas.find_one({"transaction_id": tid})

def db_stats():
    total = col_cobrancas.count_documents({})
    pago = col_cobrancas.count_documents({"status": "pago"})
    pipeline = [{"$match": {"status": "pago"}}, {"$group": {"_id": None, "total": {"$sum": "$valor"}}}]
    res = list(col_cobrancas.aggregate(pipeline))
    valor = res[0]["total"] if res else 0
    return {"total": total, "pago": pago, "valor": valor}

# --- FASTAPI SERVER ---
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class PixReq(BaseModel):
    valor: float
    descricao: Optional[str] = "Cobrança PIX"
    nome_pagador: Optional[str] = "Cliente"

# --- ENDPOINTS WEB APP ---

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    with open(os.path.join(BASE, "dashboard.html"), "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/stats")
async def api_stats():
    return db_stats()

@app.post("/api/gerar_pix_web")
async def gerar_pix_web(req: PixReq):
    # Simula chamada interna do bot
    res = await gerar_pix(req, CFG["parceiros"].get("admin", "admin_master_key_123"))
    return res

@app.post("/gerar_pix")
async def gerar_pix(body: PixReq, x_partner_key: str = Header(...)):
    # Valida parceiro
    parceiro = None
    for n, k in CFG.get("parceiros", {}).items():
        if k == x_partner_key:
            parceiro = n; break
    if not parceiro: raise HTTPException(401, "Chave inválida")
    
    ident = f"prod_{int(time.time())}_{secrets.token_hex(3)}"
    
    # Payload simplificado (mesma lógica do bot)
    payload = {
        "identifier": ident,
        "amount": round(body.valor, 2),
        "callbackUrl": f"{CFG.get('webhook_url')}/webhook_pagamento",
        "client": {
            "name": body.nome_pagador,
            "email": "cliente@email.com",
            "phone": "11999999999",
            "document": "12345678909" # CPF fixo para teste/prod simplificado
        }
    }
    
    creds = {
        "x-public-key": CFG["public_key"],
        "x-secret-key": CFG["secret_key"],
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    async with httpx.AsyncClient(timeout=30) as cl:
        resp = await cl.post(f"{CFG['api_base']}/api/v1/gateway/pix/receive", json=payload, headers=creds)
        data = resp.json()
    
    if resp.status_code not in (200, 201):
        raise HTTPException(resp.status_code, str(data))
    
    tid = data.get("transactionId") or data.get("id") or ident
    pix_node = data.get("pix") or data.get("order", {}).get("pix") or {}
    qrt = pix_node.get("code") or pix_node.get("payload") or pix_node.get("qrCodeText") or ""
    
    db_criar(str(tid), parceiro, body.valor, "", qrt)
    return {"success": True, "transaction_id": str(tid), "qr_text": qrt}

@app.post("/webhook_pagamento")
async def webhook(request: Request):
    data = await request.json()
    tid = str(data.get("id") or data.get("transactionId") or data.get("data", {}).get("id"))
    status = data.get("status") or data.get("data", {}).get("status", "")
    
    if tid and status.lower() in ("paid", "pago", "completed", "approved"):
        db_update(tid, "pago")
        
        # Notifica no Telegram
        bot.send_message(CFG["telegram_admin_id"], f"✅ *PAGAMENTO RECEBIDO!*\\n💰 Valor: R$ {db_status(tid).get('valor')}\\n🆔 ID: `{tid}`", parse_mode="Markdown")
        
    return {"received": True}

# --- TELEGRAM BOT ---
bot = telebot.TeleBot(CFG["telegram_token"])

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    # URL real do seu Render para o Mini App abrir corretamente
    web_app = types.WebAppInfo(url="https://pix20.onrender.com") 
    btn_web = types.KeyboardButton("🚀 Abrir Painel Web", web_app=web_app)
    btn_stats = types.KeyboardButton("📊 Estatísticas")
    btn_help = types.KeyboardButton("❓ Ajuda")
    markup.add(btn_web)
    markup.add(btn_stats, btn_help)
    return markup

@bot.message_handler(commands=['start', 'help'])
def bot_welcome(message):
    if str(message.from_user.id) != str(CFG["telegram_admin_id"]): return
    bot.send_message(message.chat.id, "👋 *Bem-vindo ao Painel VIP SigiloPay!*\\n\\nAgora você tem um **Web App** dentro do Telegram para gerenciar tudo.", 
                     parse_mode="Markdown", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda m: m.text == "📊 Estatísticas")
@bot.message_handler(commands=['stats'])
def bot_stats_reply(message):
    if str(message.from_user.id) != str(CFG["telegram_admin_id"]): return
    s = db_stats()
    text = f"📊 *Resumo Geral*\\n\\nTotal Cobranças: {s['total']}\\nConfirmadas: {s['pago']}\\nTotal: *R$ {s['valor']:.2f}*"
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['pix'])
def bot_pix(message):
    if str(message.from_user.id) != str(CFG["telegram_admin_id"]): return
    
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "❌ *Erro!* Use: `/pix [valor]`\nExemplo: `/pix 50.00`", parse_mode="Markdown")
        return

    try:
        valor_str = parts[1].replace(',', '.')
        valor = float(valor_str)
        if valor < 1.0:
            bot.reply_to(message, "⚠️ O valor mínimo é R$ 1,00")
            return
    except:
        bot.reply_to(message, "❌ Valor inválido! Use números (ex: 10.50)")
        return

    bot.send_chat_action(message.chat.id, 'typing')
    msg_espera = bot.reply_to(message, "⏳ Gerando PIX, aguarde...")

    try:
        ident = f"bot_{int(time.time())}_{secrets.token_hex(2)}"
        
        # Escolhe as chaves baseadas no valor (mesma lógica do painel)
        p_key = CFG["public_key"]
        s_key = CFG["secret_key"]
        if valor >= 1000 and CFG.get("public_key_above"):
            p_key = CFG["public_key_above"]
            s_key = CFG["secret_key_above"]

        payload = {
            "identifier": ident,
            "amount": round(valor, 2),
            "callbackUrl": f"{CFG.get('webhook_url')}/webhook_pagamento",
            "client": {
                "name": "Cliente Bot",
                "email": "cliente@bot.com",
                "phone": "11999999999",
                "document": "12345678909"
            }
        }
        
        headers = {
            "x-public-key": p_key,
            "x-secret-key": s_key,
            "Content-Type": "application/json"
        }

        with httpx.Client(timeout=30) as client_http:
            resp = client_http.post(f"{CFG['api_base']}/api/v1/gateway/pix/receive", json=payload, headers=headers)
            data = resp.json()

        if resp.status_code not in (200, 201):
            bot.edit_message_text(f"❌ *Erro na API:* {data.get('message', 'Erro desconhecido')}", message.chat.id, msg_espera.message_id, parse_mode="Markdown")
            return

        tid = data.get("transactionId") or data.get("id")
        pix_node = data.get("pix") or data.get("order", {}).get("pix") or {}
        qrt = pix_node.get("code") or pix_node.get("payload") or ""

        # Salva no MongoDB
        db_criar(str(tid), "Telegram Bot", valor, "", qrt)

        # Resposta final para o usuário
        texto_final = (
            f"✅ *PIX GERADO COM SUCESSO!*\\n\\n"
            f"💰 *Valor:* R$ {valor:.2f}\\n"
            f"🆔 *ID:* `{tid}`\\n\\n"
            f"👇 *Copia e Cola:*\\n"
            f"`{qrt}`"
        )
        bot.edit_message_text(texto_final, message.chat.id, msg_espera.message_id, parse_mode="Markdown")

    except Exception as e:
        bot.edit_message_text(f"❌ *Erro interno:* {str(e)}", message.chat.id, msg_espera.message_id, parse_mode="Markdown")

# --- EXECUÇÃO ---
def run_bot():
    print("🤖 Bot Iniciado...")
    bot.infinity_polling()

if __name__ == "__main__":
    # Inicia Bot em Thread separada
    threading.Thread(target=run_bot, daemon=True).start()
    
    # Inicia Servidor (Porta 8000 é o padrão do Render se não definida)
    port = int(os.environ.get("PORT", 8000))
    print(f"🌐 Servidor rodando na porta {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
