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
        "auto_saque": False
    }
    return cfg

CFG = load_cfg()
BASE = os.path.dirname(os.path.abspath(__file__))
MONGO_URI = get_env("MONGO_URI", "mongodb+srv://michelidiasphoto_db_user:lVN70gFWTgsecLTw@cluster0.eb7vf2i.mongodb.net/?appName=Cluster0")
DB_NAME = get_env("MONGO_DB_NAME", "sigilopay_db")

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
col_cobrancas = db["cobrancas"]
col_users = db["users"]
col_saques = db["saques"]

def db_criar(tid, parceiro, valor, qrc, qrt, parceiro_login=None):
    col_cobrancas.update_one({"transaction_id": tid}, {"$set": {"parceiro": parceiro, "parceiro_login": parceiro_login, "valor": valor, "status": "aguardando", "qr_code": qrc, "qr_text": qrt, "criado_em": datetime.now().isoformat()}}, upsert=True)

def db_update(tid, status):
    pago_em = datetime.now().isoformat() if status == "pago" else None
    col_cobrancas.update_one({"transaction_id": tid}, {"$set": {"status": status, "pago_em": pago_em}})

def db_status(tid): return col_cobrancas.find_one({"transaction_id": tid})

def db_stats(parceiro_login=None):
    filter_q = {"parceiro_login": parceiro_login} if parceiro_login else {}
    total = col_cobrancas.count_documents(filter_q)
    paid_filter = {**filter_q, "status": "pago"}
    pago = col_cobrancas.count_documents(paid_filter)
    pipeline = [{"$match": paid_filter}, {"$group": {"_id": None, "total": {"$sum": "$valor"}}}]
    res = list(col_cobrancas.aggregate(pipeline))
    valor = res[0]["total"] if res else 0
    return {"total": total, "pago": pago, "valor": valor}

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
    with open(os.path.join(BASE, "dashboard.html"), "r", encoding="utf-8") as f: return f.read()

@app.post("/api/login")
async def api_login(req: LoginReq):
    if req.username == "admin_maisvelho" and req.password == "maisvelhoadmin": return {"success": True, "role": "master"}
    user = col_users.find_one({"login": req.username, "password": req.password})
    if user: return {"success": True, "role": "user"}
    raise HTTPException(401, "Login inválido")

@app.get("/api/stats")
async def api_stats(credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username == "admin_maisvelho": return db_stats()
    return db_stats(parceiro_login=credentials.username)

@app.get("/api/financas")
async def api_financas(credentials: HTTPBasicCredentials = Depends(security)):
    stats = db_stats(parceiro_login=credentials.username)
    v_total = stats["valor"]
    return {"vendas_total": v_total, "comissao_total": v_total * 0.8, "disponivel": v_total * 0.8}

@app.post("/api/gerar_pix_web")
async def gerar_pix_web(req: PixReq, credentials: HTTPBasicCredentials = Depends(security)):
    # Rota da SigiloPay Original
    return await gerar_pix(req, CFG["parceiros"].get("admin", "admin_master_key_123"), parceiro_login=credentials.username)

@app.post("/api/gerar_pix_jogo")
async def gerar_pix_jogo_api(req: PixReq, credentials: HTTPBasicCredentials = Depends(security)):
    try:
        # Importa apenas na hora de usar para não travar o resto do site
        import bot_gbg3
        res = await bot_gbg3.gerar_pix_jogo(req.valor)
        if res.get("success"):
            qrt = res.get("pix_code")
            tid = f"gbg3_{int(time.time())}"
            db_criar(tid, f"{credentials.username}_gbg3", req.valor, "", qrt, parceiro_login=credentials.username)
            return {"success": True, "transaction_id": tid, "qr_text": qrt}
        else:
            return {"success": False, "message": res.get("message")}
    except Exception as e:
        return {"success": False, "message": f"Robô não configurado no servidor: {e}"}

@app.post("/gerar_pix")
async def gerar_pix(body: PixReq, x_partner_key: str = Header(...), parceiro_login=None):
    ident = f"prod_{int(time.time())}_{secrets.token_hex(3)}"
    payload = {"identifier": ident, "amount": round(body.valor, 2), "callbackUrl": f"{CFG['webhook_url']}/webhook_pagamento", "client": {"name": body.nome_pagador, "document": "12345678909"}}
    headers = {"x-public-key": CFG["public_key"], "x-secret-key": CFG["secret_key"], "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as cl:
        resp = await cl.post(f"{CFG['api_base']}/api/v1/gateway/pix/receive", json=payload, headers=headers)
        data = resp.json()
    pix = data.get("pix") or data.get("order", {}).get("pix") or {}
    qrt = pix.get("code") or pix.get("payload") or ""
    db_criar(data.get("transactionId") or ident, "Web", body.valor, "", qrt, parceiro_login=parceiro_login)
    return {"success": True, "qr_text": qrt}

@app.post("/webhook_pagamento")
async def webhook(request: Request):
    data = await request.json()
    tid = str(data.get("id") or data.get("transactionId") or "")
    if tid: db_update(tid, "pago")
    return {"received": True}

bot = telebot.TeleBot(CFG["telegram_token"])
@bot.message_handler(commands=['start'])
def welcome(m): bot.send_message(m.chat.id, "🚀 Painel Pix 20%", reply_markup=types.ReplyKeyboardMarkup().add(types.KeyboardButton("Abrir Painel", web_app=types.WebAppInfo(url=CFG["webhook_url"]))))

if __name__ == "__main__":
    threading.Thread(target=lambda: bot.infinity_polling(), daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
