import os
import json
import time
import secrets
import random
import threading
import httpx
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn
import telebot
from telebot import types
from pymongo import MongoClient
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
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
        "parceiros": {"admin": "admin_master_key_123"},
        "auto_saque": False # Modo padrão: Manual
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
col_saques = db["saques"]

def db_criar(tid, parceiro, valor, qrc, qrt, parceiro_login=None):
    col_cobrancas.update_one(
        {"transaction_id": tid},
        {"$set": {
            "parceiro": parceiro,
            "parceiro_login": parceiro_login,
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

def db_stats(parceiro_login=None):
    filter_q = {}
    if parceiro_login:
        filter_q["parceiro_login"] = parceiro_login
    
    total = col_cobrancas.count_documents(filter_q)
    paid_filter = {**filter_q, "status": "pago"}
    pago = col_cobrancas.count_documents(paid_filter)
    
    pipeline = [{"$match": paid_filter}, {"$group": {"_id": None, "total": {"$sum": "$valor"}}}]
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
    if uid_str in CFG["telegram_admin_ids"]:
        return True
    return col_users.find_one({"telegram_id": uid_str}) is not None

# --- STATUS POLLING ---
def check_single_status(tid):
    cobranca = db_status(tid)
    if not cobranca or cobranca.get("status") == "pago":
        return
    
    valor = cobranca.get("valor", 0)
    p_key = CFG["public_key"]
    s_key = CFG["secret_key"]
    if valor >= 1000 and CFG.get("public_key_above"):
        p_key = CFG["public_key_above"]
        s_key = CFG["secret_key_above"]

    headers = {
        "x-public-key": p_key,
        "x-secret-key": s_key,
        "Content-Type": "application/json"
    }

    try:
        url = f"{CFG['api_base']}/api/v1/gateway/transactions"
        with httpx.Client(timeout=15) as client_http:
            resp = client_http.get(url, params={"id": tid}, headers=headers)
            if resp.status_code == 404:
                url = f"{CFG['api_base']}/gateway/transactions"
                resp = client_http.get(url, params={"id": tid}, headers=headers)
            
            if resp.status_code in (200, 201):
                data = resp.json()
                status_api = str(data.get("status") or data.get("data", {}).get("status", "")).lower()
                if status_api in ("paid", "pago", "completed", "approved"):
                    db_update(tid, "pago")
                    return True
    except Exception as e:
        print(f"Erro polling {tid}: {e}")
    return False

def bg_check_pending():
    while True:
        try:
            uma_hora_atras = (datetime.now() - timedelta(hours=24)).isoformat()
            pendentes = list(col_cobrancas.find({
                "status": "aguardando",
                "criado_em": {"$gt": uma_hora_atras}
            }).limit(50))
            for p in pendentes:
                tid = p.get("transaction_id")
                if tid:
                    check_single_status(tid)
                    time.sleep(1)
        except Exception as e:
            print(f"Erro no loop de polling: {e}")
        time.sleep(60)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
security = HTTPBasic()

class PixReq(BaseModel):
    valor: float
    descricao: Optional[str] = "Cobrança PIX"
    nome_pagador: Optional[str] = "Cliente"

class LoginReq(BaseModel):
    username: str
    password: str
    telegram_id: Optional[str] = None

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    with open(os.path.join(BASE, "dashboard.html"), "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/login")
async def api_login(req: LoginReq):
    if req.username == "admin_maisvelho" and req.password == "maisvelhoadmin":
        return {"success": True, "role": "master"}
    user = col_users.find_one({"login": req.username, "password": req.password})
    if user:
        if user.get("expira_em"):
            expira = datetime.fromisoformat(user["expira_em"])
            if datetime.now() > expira: raise HTTPException(401, "Acesso expirado")
        if req.telegram_id:
            col_users.update_one({"login": req.username}, {"$set": {"telegram_id": str(req.telegram_id)}})
        return {"success": True, "role": "user"}
    raise HTTPException(401, "Login ou senha inválidos")

@app.get("/api/stats")
async def api_stats(credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username == "admin_maisvelho" and credentials.password == "maisvelhoadmin":
        return db_stats()
    user = col_users.find_one({"login": credentials.username, "password": credentials.password})
    if user: return db_stats(parceiro_login=credentials.username)
    raise HTTPException(401, "Não autorizado")

@app.get("/api/financas")
async def api_financas(credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username == "admin_maisvelho": return {"error": "Acesso Master"}
    stats = db_stats(parceiro_login=credentials.username)
    valor_total = stats["valor"]
    valor_comissao = valor_total * 0.8
    pipeline = [{"$match": {"login": credentials.username, "status": "completo"}}, {"$group": {"_id": None, "total": {"$sum": "$valor"}}}]
    res_saques = list(col_saques.aggregate(pipeline))
    sacado = res_saques[0]["total"] if res_saques else 0
    disponivel = valor_comissao - sacado
    return {"vendas_total": valor_total, "comissao_total": valor_comissao, "sacado": sacado, "disponivel": disponivel}

@app.post("/api/saque")
async def api_saque(data: dict, credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username == "admin_maisvelho": raise HTTPException(400, "Admin não faz saque")
    chave = data.get("pix_key"); valor_pedir = float(data.get("valor", 0))
    if not chave or valor_pedir < 100: raise HTTPException(400, "Dados inválidos ou valor mínimo R$ 100")
    fin = await api_financas(credentials)
    if valor_pedir > fin["disponivel"]: raise HTTPException(400, "Saldo insuficiente")
    saque_doc = {"login": credentials.username, "valor": valor_pedir, "pix_key": chave, "status": "pendente", "criado_em": datetime.now().isoformat()}
    col_saques.insert_one(saque_doc)
    return {"success": True}

@app.get("/api/saques/meus")
async def api_meus_saques(credentials: HTTPBasicCredentials = Depends(security)):
    saques = list(col_saques.find({"login": credentials.username}).sort("criado_em", -1).limit(10))
    for s in saques: s["_id"] = str(s["_id"])
    return {"saques": saques}

@app.post("/api/gerar_pix_web")
async def gerar_pix_web(req: PixReq, credentials: HTTPBasicCredentials = Depends(security)):
    is_master = credentials.username == "admin_maisvelho" and credentials.password == "maisvelhoadmin"
    valid_user = False
    if not is_master:
        u = col_users.find_one({"login": credentials.username, "password": credentials.password})
        if u: valid_user = True
    if is_master or valid_user:
        return await gerar_pix(req, CFG["parceiros"].get("admin", "admin_master_key_123"), parceiro_login=credentials.username)
    raise HTTPException(401, "Não autorizado")

# 🎰 ROTA NOVA DO JOGO GBG3
@app.post("/api/gerar_pix_jogo")
async def gerar_pix_jogo_api(req: PixReq, credentials: HTTPBasicCredentials = Depends(security)):
    is_master = credentials.username == "admin_maisvelho" and credentials.password == "maisvelhoadmin"
    valid_user = False
    if not is_master:
        u = col_users.find_one({"login": credentials.username, "password": credentials.password})
        if u: valid_user = True
    if is_master or valid_user:
        try:
            from bot_gbg3 import gerar_pix_jogo
            res = await gerar_pix_jogo(req.valor)
            if res.get("success"):
                qrt = res.get("pix_code")
                tid = f"gbg3_{int(time.time())}_{secrets.token_hex(2)}"
                db_criar(tid, f"{credentials.username}_gbg3", req.valor, "", qrt, parceiro_login=credentials.username)
                return {"success": True, "transaction_id": tid, "qr_text": qrt, "metodo": "jogo"}
            else:
                raise HTTPException(500, res.get("message", "Erro no robô"))
        except Exception as e:
            raise HTTPException(500, f"Erro interno: {str(e)}")
    raise HTTPException(401, "Não autorizado")

@app.post("/gerar_pix")
async def gerar_pix(body: PixReq, x_partner_key: str = Header(...), parceiro_login=None):
    parceiro = None
    for n, k in CFG.get("parceiros", {}).items():
        if k == x_partner_key: parceiro = n; break
    if not parceiro: raise HTTPException(401, "Chave inválida")
    ident = f"prod_{int(time.time())}_{secrets.token_hex(3)}"
    payload = {"identifier": ident, "amount": round(body.valor, 2), "callbackUrl": f"{CFG['webhook_url']}/webhook_pagamento", "client": {"name": body.nome_pagador, "email": "c@c.com", "phone": "119", "document": "12345678909"}}
    creds = {"x-public-key": CFG["public_key"], "x-secret-key": CFG["secret_key"], "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as cl:
        resp = await cl.post(f"{CFG['api_base']}/api/v1/gateway/pix/receive", json=payload, headers=creds)
        data = resp.json()
    tid = data.get("transactionId") or data.get("id") or ident
    pix_node = data.get("pix") or data.get("order", {}).get("pix") or {}
    qrt = pix_node.get("code") or pix_node.get("payload") or ""
    db_criar(str(tid), parceiro, body.valor, "", qrt, parceiro_login=parceiro_login)
    return {"success": True, "transaction_id": str(tid), "qr_text": qrt}

@app.post("/webhook_pagamento")
async def webhook(request: Request):
    data = await request.json()
    tid = str(data.get("id") or data.get("transactionId") or "")
    status = str(data.get("status") or "").lower()
    if tid and status in ("paid", "pago", "completed", "approved", "success"):
        cobranca = db_status(tid)
        if cobranca and cobranca.get("status") != "pago":
            db_update(tid, "pago")
            valor = cobranca.get('valor', '???'); parceiro = cobranca.get('parceiro_login') or "Web"
            msg = f"✅ *PAGAMENTO RECEBIDO!*\n💰 Valor: R$ {valor}\n👤 Parceiro: `{parceiro}`"
            for admin_id in CFG["telegram_admin_ids"]:
                try: bot.send_message(admin_id, msg, parse_mode="Markdown")
                except: pass
    return {"received": True}

# --- TELEGRAM BOT ---
bot = telebot.TeleBot(CFG["telegram_token"])

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    web_app = types.WebAppInfo(url=CFG["webhook_url"]) 
    markup.add(types.KeyboardButton("🚀 Abrir Painel Web", web_app=web_app))
    return markup

@bot.message_handler(commands=['start', 'help'])
def bot_welcome(message):
    bot.send_message(message.chat.id, "👋 *Bem-vindo ao Painel VIP Pix 20%!*", parse_mode="Markdown", reply_markup=get_main_keyboard())

@bot.message_handler(commands=['pix'])
def bot_pix(message):
    if not is_authorized(message.from_user.id): return
    parts = message.text.split()
    if len(parts) < 2: return
    try:
        valor = float(parts[1].replace(',', '.'))
        ident = f"bot_{int(time.time())}_{secrets.token_hex(2)}"
        payload = {"identifier": ident, "amount": round(valor, 2), "callbackUrl": f"{CFG['webhook_url']}/webhook_pagamento", "client": {"name": "Bot", "email": "c@b.com", "phone": "119", "document": "12345678909"}}
        headers = {"x-public-key": CFG["public_key"], "x-secret-key": CFG["secret_key"], "Content-Type": "application/json"}
        with httpx.Client(timeout=30) as cl:
            resp = cl.post(f"{CFG['api_base']}/api/v1/gateway/pix/receive", json=payload, headers=headers)
            data = resp.json()
        qrt = data.get("pix", {}).get("code") or ""
        bot.send_message(message.chat.id, f"✅ *PIX GERADO!*\n💰 R$ {valor:.2f}\n\n`{qrt}`", parse_mode="Markdown")
    except: pass

if __name__ == "__main__":
    threading.Thread(target=lambda: bot.infinity_polling(), daemon=True).start()
    threading.Thread(target=bg_check_pending, daemon=True).start()
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
