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
col_cobrancas = db["cobrancas"]; col_users = db["users"]

class PixReq(BaseModel): valor: float
class UserData(BaseModel): username: str; password: str

def gerar_cpf_real():
    c = [random.randint(0, 9) for _ in range(9)]; [c.append(11 - sum([(len(c) + 1 - i) * v for i, v in enumerate(c)]) % 11 if sum([(len(c) + 1 - i) * v for i, v in enumerate(c)]) % 11 > 1 else 0) for _ in range(2)]
    return "".join(map(str, c))

# --- LOGIN ---
@app.post("/api/login")
async def api_login(d: dict):
    u = d.get("username"); p = d.get("password")
    if u == "adminmaisvelho" and p == "maisvelhoadmin": return {"success": True, "role": "admin"}
    if col_users.find_one({"username": u, "password": p}): return {"success": True, "role": "user"}
    return {"success": False}

@app.get("/api/users")
async def list_users(): return list(col_users.find({}, {"_id": 0}))

@app.post("/api/users/add")
async def add_user(user: UserData):
    if col_users.find_one({"username": user.username}): return {"success": False}
    col_users.insert_one({"username": user.username, "password": user.password, "criado_em": datetime.now().strftime("%d/%m/%Y")})
    return {"success": True}

@app.delete("/api/users/{username}")
async def delete_user(username: str):
    col_users.delete_one({"username": username}); return {"success": True}

# --- BOT TELEGRAM ---
@bot.message_handler(commands=['start', 'painel'])
def send_welcome(message):
    if str(message.from_user.id) != ADMIN_ID: return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="📱 ABRIR PAINEL", web_app=WebAppInfo(url=WEBAPP_URL)))
    bot.send_message(message.chat.id, "✅ *SISTEMA ATIVO!*", parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=['pix'])
def bot_gerar_pix(message):
    if str(message.from_user.id) != ADMIN_ID: return
    try:
        valor = float(message.text.split()[1])
        ident = f"bot_{int(time.time())}"
        c_data = {"name": "Bot User", "email": "b@t.com", "phone": "11999999999", "document": gerar_cpf_real()}
        payload = {"identifier": ident, "amount": valor, "callbackUrl": f"{WEBAPP_URL}/webhook", "client": c_data, "customer": c_data}
        headers = {"x-public-key": "laispereiraphoto_2s0vatrdx6coy3pp", "x-secret-key": "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v", "Content-Type": "application/json"}
        with httpx.Client(timeout=30) as cl:
            resp = cl.post("https://app.sigilopay.com.br/api/v1/gateway/pix/receive", json=payload, headers=headers)
            data = resp.json()
            pix = data.get("pix") or data.get("order", {}).get("pix") or {}
            qrt = pix.get("code") or pix.get("payload") or ""
            if qrt:
                col_cobrancas.insert_one({"transaction_id": ident, "valor": valor, "status": "aguardando", "criado_em": datetime.now()})
                bot.reply_to(message, f"✅ *PIX GERADO!*\n`{qrt}`", parse_mode="Markdown")
            else: bot.reply_to(message, f"❌ Erro SigiloPay: {data.get('message') or 'Resposta vazia'}")
    except Exception as e: bot.reply_to(message, f"❌ Erro Interno: {str(e)}")

# --- ROTAS WEB ---
@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    with open("dashboard.html", "r", encoding="utf-8") as f: return f.read()

@app.get("/api/stats")
async def get_stats():
    pago = col_cobrancas.count_documents({"status": "pago"})
    total = sum([c.get("valor", 0) for c in col_cobrancas.find({"status": "pago"})])
    return {"pago": pago, "valor": total}

@app.post("/api/gerar_pix_web")
async def gerar_pix_web(req: PixReq):
    ident = f"web_{int(time.time())}"
    str_cpf = gerar_cpf_real()
    c_data = {"name": "Web VIP", "email": "w@e.com", "phone": "11999999999", "document": str_cpf}
    payload = {"identifier": ident, "amount": round(req.valor, 2), "callbackUrl": f"{WEBAPP_URL}/webhook", "client": c_data, "customer": c_data}
    headers = {"x-public-key": "laispereiraphoto_2s0vatrdx6coy3pp", "x-secret-key": "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v", "Content-Type": "application/json", "Accept": "application/json"}
    
    async with httpx.AsyncClient(timeout=30) as cl:
        try:
            resp = await cl.post("https://app.sigilopay.com.br/api/v1/gateway/pix/receive", json=payload, headers=headers)
            data = resp.json()
            pix = data.get("pix") or data.get("order", {}).get("pix") or {}
            qrt = pix.get("code") or pix.get("payload") or pix.get("qrCodeText") or ""
            if qrt:
                col_cobrancas.insert_one({"transaction_id": ident, "valor": req.valor, "status": "aguardando", "criado_em": datetime.now()})
                return {"success": True, "qr_text": qrt}
            
            # MOSTRA O ERRO REAL DA SIGILOPAY
            msg = data.get("message") or data.get("details") or str(data)
            return {"success": False, "message": f"SigiloPay diz: {msg}"}
        except Exception as e:
            return {"success": False, "message": f"Erro de Conexão: {str(e)}"}

@app.on_event("startup")
def startup(): threading.Thread(target=lambda: bot.infinity_polling(), daemon=True).start()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
