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
    client = MongoClient("mongodb+srv://michelidiasphoto_db_user:lVN70gFWTgsecLTw@cluster0.eb7vf2i.mongodb.net/?appName=Cluster0", serverSelectionTimeoutMS=5000)
    db = client["sigilopay_db"]
    col_cobrancas = db["cobrancas"]; col_users = db["users"]; col_saques = db["saques"]
except Exception as e:
    print(f"Erro Conexão MongoDB: {e}")

class PixReq(BaseModel): valor: float; username: str
class SaqueReq(BaseModel): valor: float; username: str; pix_key: str
class UserData(BaseModel): username: str; password: str

def gerar_cpf_real():
    c = [random.randint(0, 9) for _ in range(9)]
    for _ in range(2):
        v = sum([(len(c) + 1 - i) * val for i, val in enumerate(c)]) % 11
        c.append(11 - v if v > 1 else 0)
    return "".join(map(str, c))

# --- ROTAS DO PAINEL ---
@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    try:
        with open("dashboard.html", "r", encoding="utf-8") as f: return f.read()
    except: return "dashboard.html ausente."

# --- API DE GESTÃO (COM PROTEÇÃO CONTRA ERRO 500) ---
@app.get("/api/users")
async def list_users():
    try:
        users_raw = list(col_users.find({}, {"_id": 0}))
        processed_users = []
        for u in users_raw:
            try:
                name = u.get("username", "Desconhecido")
                # Filtra cobranças pagas desse usuário com segurança
                pago_u = list(col_cobrancas.find({"status": "pago", "criado_por": name}))
                total_v = sum([float(c.get("valor", 0)) for c in pago_u])
                
                u['total_vendas'] = total_v
                u['saldo_disponivel'] = total_v * 0.8
                u['username'] = name
                processed_users.append(u)
            except Exception as e:
                print(f"Erro ao processar usuário {u}: {e}")
                continue # Pula o usuário com erro e vai para o próximo
        return processed_users
    except Exception as e:
        print(f"Erro Fatal na Lista: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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

@app.post("/api/users/add")
async def add_user(user: UserData):
    if col_users.find_one({"username": user.username}): return {"success": False}
    col_users.insert_one({"username": user.username, "password": user.password, "criado_em": datetime.now()})
    return {"success": True}

@app.delete("/api/users/{username}")
async def delete_user(username: str):
    col_users.delete_one({"username": username}); return {"success": True}

@app.post("/api/saque")
async def api_saque(req: SaqueReq):
    try:
        col_saques.insert_one({"username": req.username, "valor": req.valor, "chave_pix": req.pix_key, "data": datetime.now(), "status": "pendente"})
        bot.send_message(ADMIN_ID, f"💸 *SAQUE:* `{req.username}` | `R$ {req.valor:.2f}` | `{req.pix_key}`", parse_mode="Markdown")
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

def run_bot():
    bot.remove_webhook(); time.sleep(2); bot.infinity_polling(timeout=60)

@app.on_event("startup")
def startup():
    threading.Thread(target=run_bot, daemon=True).start()
    try: bot.send_message(ADMIN_ID, "🚀 *PAINEL ESTABILIZADO!* Pode abrir a Gestão.")
    except: pass

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
