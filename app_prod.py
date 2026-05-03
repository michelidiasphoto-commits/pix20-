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
MONGO_URI = "mongodb+srv://michelidiasphoto_db_user:lVN70gFWTgsecLTw@cluster0.eb7vf2i.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URI); db = client["sigilopay_db"]
col_cobrancas = db["cobrancas"]; col_users = db["users"]

# Cache para o robô não dar timeout
JOBS = {}

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

# 🎰 NOVO SISTEMA DO JOGO (PARA NÃO DAR TIMEOUT)
@app.post("/api/gerar_pix_jogo")
async def gerar_pix_jogo_api(req: PixReq, bg_tasks: BackgroundTasks, c: HTTPBasicCredentials = Depends(security)):
    job_id = f"job_{int(time.time())}"
    JOBS[job_id] = {"status": "processando"}
    bg_tasks.add_task(run_bot_task, job_id, req.valor)
    return {"success": True, "job_id": job_id}

async def run_bot_task(job_id, valor):
    try:
        import bot_gbg3
        res = await bot_gbg3.gerar_pix_jogo(valor)
        if res.get("success"):
            JOBS[job_id] = {"status": "sucesso", "qr_text": res.get("pix_code")}
        else:
            JOBS[job_id] = {"status": "erro", "message": res.get("message")}
    except Exception as e:
        JOBS[job_id] = {"status": "erro", "message": str(e)}

@app.get("/api/status_jogo/{job_id}")
async def status_jogo(job_id: str):
    return JOBS.get(job_id, {"status": "erro", "message": "Não encontrado"})

@app.post("/api/gerar_pix_web")
async def gerar_pix_web(req: PixReq, c: HTTPBasicCredentials = Depends(security)):
    # Rota SigiloPay normal
    ident = f"sig_{int(time.time())}"
    payload = {"identifier": ident, "amount": round(req.valor, 2), "callbackUrl": "https://pix20.onrender.com/webhook_pagamento", "client": {"name": req.nome_pagador, "email": "c@e.com", "phone": "119", "document": "12345678909"}}
    headers = {"x-public-key": "laispereiraphoto_2s0vatrdx6coy3pp", "x-secret-key": "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as cl:
        resp = await cl.post("https://app.sigilopay.com.br/api/v1/gateway/pix/receive", json=payload, headers=headers)
        data = resp.json()
    pix = data.get("pix") or data.get("order", {}).get("pix") or {}
    return {"success": True, "qr_text": pix.get("code") or ""}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
