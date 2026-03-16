
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
import qrcode
from io import BytesIO

# --- CONFIGURAÇÃO ---
def get_env(key, default):
    return os.environ.get(key, default)

def load_cfg():
    # Pega lista de IDs autorizados (separados por vírgula)
    admin_ids_raw = get_env("TELEGRAM_ADMIN_ID", "8084292904")
    admin_ids = [s.strip() for s in admin_ids_raw.split(",")]

    cfg = {
        "public_key": get_env("SIGILOPAY_PUBLIC_KEY", "laispereiraphoto_2s0vatrdx6coy3pp"),
        "secret_key": get_env("SIGILOPAY_SECRET_KEY", "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v"),
        "api_base": get_env("SIGILOPAY_API_BASE", "https://app.sigilopay.com.br"),
        "telegram_token": get_env("TELEGRAM_TOKEN", "8618759737:AAH8JRKP_7Xm_nPXMiSxelKsPLbJMaRwM-M"),
        "telegram_admin_ids": admin_ids,
        "webhook_url": get_env("WEBHOOK_URL", "https://pix20.onrender.com"),
        "parceiros": {"admin": "admin_master_key_123"}
    }
    return cfg

CFG = load_cfg()
BASE = os.path.dirname(os.path.abspath(__file__))
MONGO_URI = get_env("MONGO_URI", "mongodb+srv://michelidiasphoto_db_user:lVN70gFWTgsecLTw@cluster0.eb7vf2i.mongodb.net/?appName=Cluster0")
DB_NAME = get_env("MONGO_DB_NAME", "sigilopay_db")

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

# --- GESTÃO DE USUÁRIOS NO MONGO ---
def bot_user_add(uid):
    col_users.update_one({"user_id": str(uid)}, {"$set": {"authorized": True}}, upsert=True)

def bot_user_remove(uid):
    col_users.delete_one({"user_id": str(uid)})

def bot_user_list():
    return [u["user_id"] for u in col_users.find({"authorized": True})]

def is_authorized(uid):
    uid_str = str(uid)
    # Sempre autoriza o Admin do Render
    if uid_str in CFG["telegram_admin_ids"]:
        return True
    # Verifica no MongoDB
    return col_users.find_one({"user_id": uid_str, "authorized": True}) is not None

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

@app.get("/api/users")
async def api_users():
    return {"users": bot_user_list()}

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
        
        # Notifica no Telegram (todos os admins)
        msg_notif = f"✅ *PAGAMENTO RECEBIDO!*\n💰 Valor: R$ {db_status(tid).get('valor')}\n🆔 ID: `{tid}`"
        for admin_id in CFG["telegram_admin_ids"]:
            try:
                bot.send_message(admin_id, msg_notif, parse_mode="Markdown")
            except: pass
        
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
    if not is_authorized(message.from_user.id): return
    
    texto = "👋 *Bem-vindo ao Painel VIP SigiloPay!*\n\n"
    texto += "Comandos disponíveis:\n"
    texto += "• `/pix [valor]` - Gerar cobrança\n"
    texto += "• `📊 Estatísticas` - Ver resumo de vendas\n"
    
    # Comandos extras para o Admin Principal
    if str(message.from_user.id) in CFG["telegram_admin_ids"]:
        texto += "\n*🔧 Gestão de Usuários:*\n"
        texto += "• `/add [ID]` - Liberar acesso a um usuário\n"
        texto += "• `/remove [ID]` - Bloquear acesso\n"
        texto += "• `/list` - Ver usuários liberados"
        
    bot.send_message(message.chat.id, texto, parse_mode="Markdown", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda m: m.text == "📊 Estatísticas")
@bot.message_handler(commands=['stats'])
def bot_stats_reply(message):
    if not is_authorized(message.from_user.id): return
    s = db_stats()
    text = f"📊 *Resumo Geral*\n\nTotal Cobranças: {s['total']}\nConfirmadas: {s['pago']}\nTotal: *R$ {s['valor']:.2f}*"
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['add'])
def bot_add_user(message):
    # Só o Admin do Render pode adicionar outros
    if str(message.from_user.id) not in CFG["telegram_admin_ids"]: return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Use: `/add [ID]`")
        return
    bot_user_add(parts[1])
    bot.reply_to(message, f"✅ Usuário `{parts[1]}` liberado!")

@bot.message_handler(commands=['remove'])
def bot_del_user(message):
    if str(message.from_user.id) not in CFG["telegram_admin_ids"]: return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Use: `/remove [ID]`")
        return
    bot_user_remove(parts[1])
    bot.reply_to(message, f"❌ Usuário `{parts[1]}` removido!")

@bot.message_handler(commands=['list'])
def bot_list_users(message):
    if str(message.from_user.id) not in CFG["telegram_admin_ids"]: return
    users = bot_user_list()
    if not users:
        bot.reply_to(message, "Nenhum usuário extra cadastrado.")
        return
    texto = "👥 *Usuários Liberados:*\n\n" + "\n".join([f"• `{u}`" for u in users])
    bot.send_message(message.chat.id, texto, parse_mode="Markdown")

@bot.message_handler(commands=['pix'])
def bot_pix(message):
    if not is_authorized(message.from_user.id): return
    
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

        # Gera imagem do QR Code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qrt)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Salva em memória
        bio = BytesIO()
        bio.name = 'qrcode.png'
        img.save(bio, 'PNG')
        bio.seek(0)

        # Resposta final para o usuário
        texto_final = (
            f"✅ *PIX GERADO COM SUCESSO!*\n\n"
            f"💰 *Valor:* R$ {valor:.2f}\n"
            f"🆔 *ID:* `{tid}`\n\n"
            f"👇 *Copia e Cola:*"
        )
        
        # Remove mensagem de espera e envia Foto + Texto
        bot.delete_message(message.chat.id, msg_espera.message_id)
        bot.send_photo(message.chat.id, bio, caption=texto_final, parse_mode="Markdown")
        bot.send_message(message.chat.id, f"`{qrt}`", parse_mode="Markdown")

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
