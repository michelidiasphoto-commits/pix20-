import os, json, time, httpx, threading, random, telebot
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
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

# --- API E GESTÃO ---
@app.get("/api/users")
async def list_users():
    try:
        users_raw = list(col_users.find({}, {"_id": 0}))
        res = []
        for u in users_raw:
            try:
                name = u.get("username", "Desconhecido")
                pago_u = list(col_cobrancas.find({"status": "pago", "criado_por": name}))
                total_v = sum([float(c.get("valor", 0)) for c in pago_u])
                u['total_vendas'] = total_v; u['saldo_disponivel'] = total_v * 0.8; u['username'] = name
                res.append(u)
            except: continue
        return res
    except: return []

@app.post("/api/login")
async def api_login(d: dict):
    u = d.get("username"); p = d.get("password")
    if u == "adminmaisvelho" and p == "maisvelhoadmin": return {"success": True, "role": "admin"}
    user = col_users.find_one({"username": u, "password": p})
    return {"success": True, "role": "user"} if user else {"success": False}

@app.get("/api/stats/{username}")
async def get_user_stats(username: str):
    q = {"status": "pago"} if username == "adminmaisvelho" else {"status": "pago", "criado_por": username}
    pago_list = list(col_cobrancas.find(q))
    total = sum([float(c.get("valor", 0)) for c in pago_list])
    return {"pago": len(pago_list), "total": total, "saldo": total * 0.8}

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

# --- BOT TELEGRAM (MODO DIAGNÓSTICO) ---
@bot.message_handler(commands=['start', 'painel'])
def send_welcome(message):
    uid = str(message.from_user.id)
    print(f"✅ Bot ouviu um comando de {uid}")
    if uid != ADMIN_ID:
        bot.send_message(message.chat.id, f"🚫 ID {uid} não autorizado.")
        return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="📱 ABRIR PAINEL", web_app=WebAppInfo(url=WEBAPP_URL)))
    bot.send_message(message.chat.id, "✅ *SISTEMA REATIVADO!*", parse_mode="Markdown", reply_markup=markup)

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    with open("dashboard.html", "r", encoding="utf-8") as f: return f.read()

def run_bot():
    print("🧹 Resetando conexões do Telegram...")
    bot.remove_webhook()
    time.sleep(2)
    print("🤖 Bot ouvindo...")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)

@app.on_event("startup")
def startup():
    threading.Thread(target=run_bot, daemon=True).start()
    try: bot.send_message(ADMIN_ID, "🟢 *ROBÔ ONLINE!* Pode testar o /start agora.")
    except: pass

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
