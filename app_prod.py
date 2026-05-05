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

class PixReq(BaseModel): valor: float; username: str
class UserData(BaseModel): username: str; password: str

def gerar_cpf_real():
    c = [random.randint(0, 9) for _ in range(9)]; [c.append(11 - sum([(len(c) + 1 - i) * v for i, v in enumerate(c)]) % 11 if sum([(len(c) + 1 - i) * v for i, v in enumerate(c)]) % 11 > 1 else 0) for _ in range(2)]
    return "".join(map(str, c))

# --- LOGIN E STATS ---
@app.post("/api/login")
async def api_login(d: dict):
    u = d.get("username"); p = d.get("password")
    if u == "adminmaisvelho" and p == "maisvelhoadmin": return {"success": True, "role": "admin"}
    if col_users.find_one({"username": u, "password": p}): return {"success": True, "role": "user"}
    return {"success": False}

@app.get("/api/stats/{username}")
async def get_user_stats(username: str):
    # Se for o admin, ele vê o total geral do sistema
    if username == "adminmaisvelho":
        pago_list = list(col_cobrancas.find({"status": "pago"}))
    else:
        # Se for usuário, ele só vê o que ele vendeu
        pago_list = list(col_cobrancas.find({"status": "pago", "criado_por": username}))
    
    total = sum([c.get("valor", 0) for c in pago_list])
    return {
        "pago": len(pago_list),
        "total": total,
        "saldo": total * 0.8  # 80% do valor total
    }

@app.get("/api/users")
async def list_users():
    users = list(col_users.find({}, {"_id": 0}))
    for u in users:
        pago_u = list(col_cobrancas.find({"status": "pago", "criado_por": u['username']}))
        total_u = sum([c.get("valor", 0) for c in pago_u])
        u['total_vendas'] = total_u
        u['saldo_disponivel'] = total_u * 0.8
    return users

@app.post("/api/users/add")
async def add_user(user: UserData):
    if col_users.find_one({"username": user.username}): return {"success": False}
    col_users.insert_one({"username": user.username, "password": user.password, "criado_em": datetime.now()})
    return {"success": True}

@app.delete("/api/users/{username}")
async def delete_user(username: str):
    col_users.delete_one({"username": username}); return {"success": True}

# --- GERAÇÃO DE PIX COM RASTREIO ---
@app.post("/api/gerar_pix_web")
async def gerar_pix_web(req: PixReq):
    ident = f"web_{int(time.time())}"
    payload = {"identifier": ident, "amount": round(req.valor, 2), "callbackUrl": f"{WEBAPP_URL}/webhook", "client": {"name": "Web VIP", "email": "w@e.com", "phone": "119", "document": gerar_cpf_real()}, "customer": {"name": "Web VIP", "email": "w@e.com", "phone": "119", "document": gerar_cpf_real()}}
    headers = {"x-public-key": "laispereiraphoto_2s0vatrdx6coy3pp", "x-secret-key": "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as cl:
        try:
            resp = await cl.post("https://app.sigilopay.com.br/api/v1/gateway/pix/receive", json=payload, headers=headers)
            data = resp.json(); pix = data.get("pix") or data.get("order", {}).get("pix") or {}
            qrt = pix.get("code") or pix.get("payload") or ""
            if qrt:
                # SALVA QUEM CRIOU O PIX
                col_cobrancas.insert_one({"transaction_id": ident, "valor": req.valor, "status": "aguardando", "criado_por": req.username, "criado_em": datetime.now()})
                return {"success": True, "qr_text": qrt}
            return {"success": False, "message": data.get("message")}
        except Exception as e: return {"success": False, "message": str(e)}

@app.post("/webhook")
async def webhook_sigilopay(request: Request):
    try:
        data = await request.json(); tid = data.get("identifier") or data.get("transactionId")
        if data.get("status") in ["pago", "paid"]:
            col_cobrancas.update_one({"transaction_id": tid}, {"$set": {"status": "pago", "pago_em": datetime.now()}})
            c = col_cobrancas.find_one({"transaction_id": tid})
            bot.send_message(ADMIN_ID, f"💰 *PAGAMENTO RECEBIDO!*\n🆔 ID: `{tid}`\n👤 Por: `{c.get('criado_por', 'Admin')}`\n✅ Status: PAGO", parse_mode="Markdown")
        return {"success": True}
    except: return {"success": False}

@app.on_event("startup")
def startup(): threading.Thread(target=lambda: bot.infinity_polling(), daemon=True).start()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
