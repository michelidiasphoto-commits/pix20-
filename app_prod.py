import os, json, time, httpx, threading, random, telebot
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from bson import ObjectId
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
try:
    client = MongoClient("mongodb+srv://michelidiasphoto_db_user:lVN70gFWTgsecLTw@cluster0.eb7vf2i.mongodb.net/?appName=Cluster0")
    db = client["sigilopay_db"]; col_cobrancas = db["cobrancas"]; col_users = db["users"]; col_saques = db["saques"]
except: pass

class PixReq(BaseModel): valor: float; username: str
class SaqueReq(BaseModel): valor: float; username: str; pix_key: str
class UserData(BaseModel): username: str; password: str

def gerar_cpf_real():
    c = [random.randint(0, 9) for _ in range(9)]
    for _ in range(2):
        v = sum([(len(c) + 1 - i) * val for i, val in enumerate(c)]) % 11
        c.append(11 - v if v > 1 else 0)
    return "".join(map(str, c))

# --- API DE GESTÃO ---
@app.get("/api/users")
async def list_users():
    try:
        users_raw = list(col_users.find({}))
        res = []
        for u in users_raw:
            try:
                uid = str(u["_id"]); name = u.get("username", "Desconhecido")
                # SÓ CONTA O QUE ESTÁ COM STATUS 'pago'
                pago_u = list(col_cobrancas.find({"status": "pago", "criado_por": name}))
                total_v = sum([float(c.get("valor", 0)) for c in pago_u])
                res.append({"id": uid, "username": name, "total_vendas": total_v, "saldo_disponivel": total_v * 0.8})
            except: continue
        return res
    except: return []

@app.post("/api/users/reset/{username}")
async def reset_user_balance(username: str):
    try:
        # Muda o status de 'pago' para 'arquivado' para zerar o saldo atual
        col_cobrancas.update_many(
            {"status": "pago", "criado_por": username},
            {"$set": {"status": "arquivado", "zerado_em": datetime.now()}}
        )
        return {"success": True}
    except:
        return {"success": False}

@app.delete("/api/users/{user_id}")
async def delete_user(user_id: str):
    try:
        col_users.delete_one({"_id": ObjectId(user_id)})
        return {"success": True}
    except: return {"success": False}

@app.post("/api/users/add")
async def add_user(user: UserData):
    if col_users.find_one({"username": user.username}): return {"success": False}
    col_users.insert_one({"username": user.username, "password": user.password, "criado_em": datetime.now()})
    return {"success": True}

# --- RESTANTE DAS APIs ---
@app.post("/api/login")
async def api_login(d: dict):
    u = d.get("username"); p = d.get("password")
    if u == "adminmaisvelho" and p == "maisvelhoadmin": return {"success": True, "role": "admin"}
    user = col_users.find_one({"username": u, "password": p})
    return {"success": True, "role": "user"} if user else {"success": False}

@app.get("/api/stats/{username}")
async def get_user_stats(username: str):
    try:
        q = {"status": "pago"} if username == "adminmaisvelho" else {"status": "pago", "criado_por": username}
        pago_list = list(col_cobrancas.find(q))
        total = sum([float(c.get("valor", 0)) for c in pago_list])
        return {"pago": len(pago_list), "total": total, "saldo": total * 0.8}
    except: return {"pago": 0, "total": 0, "saldo": 0}

@app.post("/api/saque")
async def api_saque(req: SaqueReq):
    try:
        col_saques.insert_one({"username": req.username, "valor": req.valor, "chave_pix": req.pix_key, "data": datetime.now(), "status": "pendente"})
        bot.send_message(ADMIN_ID, f"💸 *SAQUE:* `{req.username}` | `R$ {req.valor:.2f}`", parse_mode="Markdown")
        return {"success": True}
    except: return {"success": False}

@app.post("/api/gerar_pix_web")
async def gerar_pix_web(req: PixReq):
    ident = f"web_{int(time.time())}"
    payload = {"identifier": ident, "amount": float(req.valor), "callbackUrl": f"{WEBAPP_URL}/webhook", "client": {"name": "Web VIP", "email": "w@e.com", "phone": "11999999999", "document": gerar_cpf_real()}}
    headers = {"x-public-key": "laispereiraphoto_2s0vatrdx6coy3pp", "x-secret-key": "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as cl:
        try:
            resp = await cl.post("https://app.sigilopay.com.br/api/v1/gateway/pix/receive", json=payload, headers=headers)
            pix = resp.json().get("pix") or resp.json().get("order", {}).get("pix") or {}
            qrt = pix.get("code") or pix.get("payload") or ""
            if qrt:
                col_cobrancas.insert_one({"transaction_id": ident, "valor": req.valor, "status": "aguardando", "criado_por": req.username, "criado_em": datetime.now()})
                return {"success": True, "qr_text": qrt}
            return {"success": False}
        except: return {"success": False}

@app.post("/webhook")
async def webhook_sigilopay(request: Request):
    try:
        data = await request.json(); tid = data.get("identifier") or data.get("transactionId")
        if data.get("status") in ["pago", "paid"]:
            col_cobrancas.update_one({"transaction_id": tid}, {"$set": {"status": "pago", "pago_em": datetime.now()}})
            c = col_cobrancas.find_one({"transaction_id": tid})
            if c: bot.send_message(ADMIN_ID, f"💰 *PAGO!* De: `{c.get('criado_por')}`", parse_mode="Markdown")
        return {"success": True}
    except: return {"success": False}

@bot.message_handler(commands=['start', 'painel'])
def send_welcome(message):
    if str(message.from_user.id) != ADMIN_ID: return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="📱 ABRIR PAINEL", web_app=WebAppInfo(url=WEBAPP_URL)))
    bot.send_message(message.chat.id, "✅ *SISTEMA ON!*", parse_mode="Markdown", reply_markup=markup)

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    with open("dashboard.html", "r", encoding="utf-8") as f: return f.read()

def run_bot():
    bot.remove_webhook(); time.sleep(2); bot.infinity_polling(timeout=60)

@app.on_event("startup")
def startup():
    threading.Thread(target=run_bot, daemon=True).start()
    try: bot.send_message(ADMIN_ID, "🚀 *TUDO PRONTO!* Agora você pode zerar saldos de parceiros.")
    except: pass

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
