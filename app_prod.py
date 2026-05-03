import os, json, time, secrets, random, threading, httpx
from datetime import datetime
from fastapi import FastAPI, HTTPException, Header, Request, Depends, BackgroundTasks
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
    "webhook_url": get_env("WEBHOOK_URL", "https://pix20.onrender.com"),
    "telegram_token": get_env("TELEGRAM_TOKEN", "8618759737:AAH8JRKP_7Xm_nPXMiSxelKsPLbJMaRwM-M")
}
MONGO_URI = get_env("MONGO_URI", "mongodb+srv://michelidiasphoto_db_user:lVN70gFWTgsecLTw@cluster0.eb7vf2i.mongodb.net/?appName=Cluster0")
client = MongoClient(MONGO_URI); db = client[get_env("MONGO_DB_NAME", "sigilopay_db")]
col_cobrancas = db["cobrancas"]; col_users = db["users"]

# Armazenamento temporário dos PIX do jogo
GAME_PIX_CACHE = {}

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
security = HTTPBasic()

class PixReq(BaseModel): valor: float; nome_pagador: Optional[str] = "Cliente"

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    with open(os.path.join(os.path.dirname(__file__), "dashboard.html"), "r", encoding="utf-8") as f: return f.read()

@app.post("/api/login")
async def api_login(d: dict):
    if d.get("username") == "admin_maisvelho" and d.get("password") == "maisvelhoadmin": return {"success": True, "role": "master"}
    u = col_users.find_one({"login": d.get("username"), "password": d.get("password")})
    if u: return {"success": True, "role": "user"}
    raise HTTPException(401, "Erro")

# 🎰 ROTA DO JOGO (COM ESPERA INTELIGENTE)
@app.post("/api/gerar_pix_jogo")
async def gerar_pix_jogo_api(req: PixReq, bg_tasks: BackgroundTasks, c: HTTPBasicCredentials = Depends(security)):
    request_id = f"job_{int(time.time())}_{secrets.token_hex(2)}"
    GAME_PIX_CACHE[request_id] = {"status": "processando"}
    
    # Executa o robô em segundo plano para não travar a conexão
    bg_tasks.add_task(rodar_robo_bg, request_id, req.valor, c.username)
    return {"success": True, "request_id": request_id}

async def rodar_robo_bg(rid, valor, username):
    try:
        import bot_gbg3
        res = await bot_gbg3.gerar_pix_jogo(valor)
        if res.get("success"):
            GAME_PIX_CACHE[rid] = {"status": "sucesso", "qr_text": res.get("pix_code")}
        else:
            GAME_PIX_CACHE[rid] = {"status": "erro", "message": res.get("message")}
    except Exception as e:
        GAME_PIX_CACHE[rid] = {"status": "erro", "message": str(e)}

@app.get("/api/status_jogo/{request_id}")
async def status_jogo(request_id: str):
    return GAME_PIX_CACHE.get(request_id, {"status": "nao_encontrado"})

@app.post("/api/gerar_pix_web")
async def gerar_pix_web(req: PixReq, c: HTTPBasicCredentials = Depends(security)):
    payload = {"identifier": f"sig_{int(time.time())}", "amount": round(req.valor, 2), "callbackUrl": f"{CFG['webhook_url']}/webhook_pagamento", "client": {"name": req.nome_pagador, "email": "c@e.com", "phone": "119", "document": "12345678909"}}
    headers = {"x-public-key": get_env("SIGILOPAY_PUBLIC_KEY", "laispereiraphoto_2s0vatrdx6coy3pp"), "x-secret-key": get_env("SIGILOPAY_SECRET_KEY", "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v"), "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as cl:
        resp = await cl.post("https://app.sigilopay.com.br/api/v1/gateway/pix/receive", json=payload, headers=headers)
        data = resp.json()
    pix = data.get("pix") or data.get("order", {}).get("pix") or {}
    return {"success": True, "qr_text": pix.get("code") or ""}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
