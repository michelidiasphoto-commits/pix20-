import os, json, time, secrets, random, threading, httpx
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn, telebot
from telebot import types
from pymongo import MongoClient
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

# --- CONFIGURAÇÃO ---
def get_env(k, d): return os.environ.get(k, d)

CFG = {
    "public_key": get_env("SIGILOPAY_PUBLIC_KEY", "laispereiraphoto_2s0vatrdx6coy3pp"),
    "secret_key": get_env("SIGILOPAY_SECRET_KEY", "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v"),
    "api_base": get_env("SIGILOPAY_API_BASE", "https://app.sigilopay.com.br"),
    "telegram_token": get_env("TELEGRAM_TOKEN", "8618759737:AAH8JRKP_7Xm_nPXMiSxelKsPLbJMaRwM-M"),
    "webhook_url": get_env("WEBHOOK_URL", "https://pix20.onrender.com"),
    "parceiros": {"admin": "admin_master_key_123"}
}

# SENHA DO BANCO CORRIGIDA:
MONGO_URI = "mongodb+srv://michelidiasphoto_db_user:lVN70gFWTgsecLTw@cluster0.eb7vf2i.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URI)
db = client[get_env("MONGO_DB_NAME", "sigilopay_db")]
col_cobrancas = db["cobrancas"]; col_users = db["users"]

def db_criar(tid, parceiro, valor, qrc, qrt, p_login=None):
    col_cobrancas.update_one({"transaction_id": tid}, {"$set": {"parceiro": parceiro, "parceiro_login": p_login, "valor": valor, "status": "aguardando", "qr_code": qrc, "qr_text": qrt, "criado_em": datetime.now().isoformat()}}, upsert=True)

def db_stats(p_login=None):
    f = {"parceiro_login": p_login} if p_login else {}
    t = col_cobrancas.count_documents(f)
    pf = {**f, "status": "pago"}
    p = col_cobrancas.count_documents(pf)
    res = list(col_cobrancas.aggregate([{"$match": pf}, {"$group": {"_id": None, "total": {"$sum": "$valor"}}}]))
    v = res[0]["total"] if res else 0
    return {"total": t, "pago": p, "valor": v}

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
security = HTTPBasic()

class PixReq(BaseModel):
    valor: float
    nome_pagador: Optional[str] = "Cliente"

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    try:
        with open(os.path.join(os.path.dirname(__file__), "dashboard.html"), "r", encoding="utf-8") as f: return f.read()
    except: return "Erro ao ler dashboard.html"

@app.post("/api/login")
async def api_login(d: dict):
    if d.get("username") == "admin_maisvelho" and d.get("password") == "maisvelhoadmin": return {"success": True, "role": "master"}
    u = col_users.find_one({"login": d.get("username"), "password": d.get("password")})
    if u: return {"success": True, "role": "user"}
    raise HTTPException(401, "Erro")

@app.get("/api/stats")
async def api_stats(c: HTTPBasicCredentials = Depends(security)):
    return db_stats(p_login=None if c.username == "admin_maisvelho" else c.username)

@app.get("/api/financas")
async def api_financas(c: HTTPBasicCredentials = Depends(security)):
    s = db_stats(p_login=c.username)
    return {"vendas_total": s["valor"], "comissao_total": s["valor"] * 0.8, "disponivel": s["valor"] * 0.8}

@app.post("/api/gerar_pix_web")
async def gerar_pix_web(req: PixReq, c: HTTPBasicCredentials = Depends(security)):
    ident = f"sig_{int(time.time())}"
    payload = {"identifier": ident, "amount": round(req.valor, 2), "callbackUrl": f"{CFG['webhook_url']}/webhook_pagamento", "client": {"name": req.nome_pagador, "email": "c@e.com", "phone": "11999999999", "document": "12345678909"}}
    headers = {"x-public-key": CFG["public_key"], "x-secret-key": CFG["secret_key"], "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as cl:
        resp = await cl.post(f"{CFG['api_base']}/api/v1/gateway/pix/receive", json=payload, headers=headers)
        data = resp.json()
    pix = data.get("pix") or data.get("order", {}).get("pix") or {}
    qrt = pix.get("code") or pix.get("payload") or ""
    db_criar(data.get("transactionId") or ident, "Web", req.valor, "", qrt, p_login=c.username)
    return {"success": True, "qr_text": qrt}

@app.post("/api/gerar_pix_jogo")
async def gerar_pix_jogo_api(req: PixReq, c: HTTPBasicCredentials = Depends(security)):
    try:
        import bot_gbg3
        res = await bot_gbg3.gerar_pix_jogo(req.valor)
        if res.get("success"):
            qrt = res.get("pix_code"); tid = f"gbg3_{int(time.time())}"
            db_criar(tid, f"{c.username}_gbg3", req.valor, "", qrt, p_login=c.username)
            return {"success": True, "qr_text": qrt}
        return {"success": False, "message": res.get("message")}
    except Exception as e:
        return {"success": False, "message": f"Erro no robô: {e}"}

@app.post("/webhook_pagamento")
async def webhook(r: Request):
    d = await r.json()
    t = str(d.get("id") or d.get("transactionId") or "")
    if t: col_cobrancas.update_one({"transaction_id": t}, {"$set": {"status": "pago", "pago_em": datetime.now().isoformat()}})
    return {"ok": True}

# --- TELEGRAM BOT ---
bot = telebot.TeleBot(CFG["telegram_token"])
@bot.message_handler(commands=['start'])
def welcome(m): bot.send_message(m.chat.id, "🚀 Painel Pix 20%", reply_markup=types.ReplyKeyboardMarkup().add(types.KeyboardButton("Abrir Painel", web_app=types.WebAppInfo(url=CFG["webhook_url"]))))

if __name__ == "__main__":
    threading.Thread(target=lambda: bot.infinity_polling(), daemon=True).start()
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
