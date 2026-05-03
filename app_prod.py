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
    "webhook_url": get_env("WEBHOOK_URL", "https://pix20.onrender.com")
}

client = MongoClient(get_env("MONGO_URI", "...")); db = client[get_env("MONGO_DB_NAME", "sigilopay_db")]
col_cobrancas = db["cobrancas"]; col_users = db["users"]

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
security = HTTPBasic()

class PixReq(BaseModel):
    valor: float
    nome_pagador: Optional[str] = "Cliente"

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    with open(os.path.join(os.path.dirname(__file__), "dashboard.html"), "r", encoding="utf-8") as f: return f.read()

# 🎰 ROTA DO JOGO (CORRIGIDA)
@app.post("/api/gerar_pix_jogo")
async def gerar_pix_jogo_api(req: PixReq, c: HTTPBasicCredentials = Depends(security)):
    try:
        import bot_gbg3
        res = await bot_gbg3.gerar_pix_jogo(req.valor)
        if res.get("success") and res.get("pix_code"):
            qrt = res.get("pix_code")
            return {"success": True, "qr_text": qrt, "transaction_id": f"game_{int(time.time())}"}
        return {"success": False, "message": res.get("message") or "Erro ao capturar PIX no jogo"}
    except Exception as e:
        return {"success": False, "message": f"Erro no robô: {str(e)}"}

# 💳 ROTA SIGILOPAY (RESTAURADA)
@app.post("/api/gerar_pix_web")
async def gerar_pix_web(req: PixReq, c: HTTPBasicCredentials = Depends(security)):
    ident = f"web_{int(time.time())}"
    payload = {
        "identifier": ident, "amount": round(req.valor, 2),
        "callbackUrl": f"{CFG['webhook_url']}/webhook_pagamento",
        "client": {"name": req.nome_pagador, "email": "c@e.com", "phone": "11999999999", "document": "12345678909"}
    }
    headers = {"x-public-key": CFG["public_key"], "x-secret-key": CFG["secret_key"], "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as cl:
        resp = await cl.post(f"{CFG['api_base']}/api/v1/gateway/pix/receive", json=payload, headers=headers)
        data = resp.json()
    pix = data.get("pix") or data.get("order", {}).get("pix") or {}
    qrt = pix.get("code") or pix.get("payload") or ""
    return {"success": True, "qr_text": qrt}

# ... resto das funções de login e webhook ...
