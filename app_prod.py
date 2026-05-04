import os, json, time, httpx, threading, random, secrets, telebot
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from pymongo import MongoClient
from fastapi.responses import HTMLResponse

# --- CONFIGURAÇÕES ---
TOKEN = "8618759737:AAH8JRKP_7Xm_nPXMiSxelKsPLbJMaRwM-M"
ADMIN_ID = "8084292904"

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

bot = telebot.TeleBot(TOKEN)
JOBS = {}

# --- MONGODB ---
MONGO_URI = "mongodb+srv://michelidiasphoto_db_user:lVN70gFWTgsecLTw@cluster0.eb7vf2i.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URI); db = client["sigilopay_db"]
col_cobrancas = db["cobrancas"]; col_users = db["users"]

class PixReq(BaseModel): valor: float

# --- APOIO ---
def gerar_cpf_aleatorio():
    c = [random.randint(0, 9) for _ in range(9)]; [c.append(11 - sum([(len(c) + 1 - i) * v for i, v in enumerate(c)]) % 11 if sum([(len(c) + 1 - i) * v for i, v in enumerate(c)]) % 11 > 1 else 0) for _ in range(2)]
    return "".join(map(str, c))

# --- BOT TELEGRAM (SISTEMA COMPLETO) ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    if str(message.from_user.id) != ADMIN_ID: return
    text = (
        "👋 *Bem-vindo ao Sistema VIP Pix 20%!*\\n\\n"
        "🚀 *Comandos:*\\n"
        "💰 `/pix 50` - Gerar PIX SigiloPay\\n"
        "📊 `/stats` - Ver vendas\\n"
        "📜 `/historico` - Últimas vendas"
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['pix'])
def bot_gerar_pix(message):
    if str(message.from_user.id) != ADMIN_ID: return
    try:
        valor = float(message.text.split()[1])
        ident = f"bot_{int(time.time())}"
        payload = {"identifier": ident, "amount": valor, "callbackUrl": "https://pix20.onrender.com/webhook_pagamento", "client": {"name": "Bot", "email": "b@t.com", "phone": "119", "document": gerar_cpf_aleatorio()}}
        headers = {"x-public-key": "laispereiraphoto_2s0vatrdx6coy3pp", "x-secret-key": "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v", "Content-Type": "application/json"}
        with httpx.Client(timeout=30) as cl:
            resp = cl.post("https://app.sigilopay.com.br/api/v1/gateway/pix/receive", json=payload, headers=headers)
            data = resp.json()
            pix = data.get("pix") or data.get("order", {}).get("pix") or {}
            qrt = pix.get("code") or pix.get("payload") or ""
            if qrt:
                col_cobrancas.insert_one({"transaction_id": ident, "valor": valor, "status": "aguardando", "criado_em": datetime.now()})
                bot.reply_to(message, f"✅ *PIX GERADO!*\\n💰 Valor: R$ {valor:.2f}\\n\\n📱 Copia e Cola:\\n`{qrt}`", parse_mode="Markdown")
            else: bot.reply_to(message, "❌ Erro SigiloPay")
    except: bot.reply_to(message, "Use: `/pix 50`")

@bot.message_handler(commands=['stats'])
def bot_stats(message):
    if str(message.from_user.id) != ADMIN_ID: return
    pago = col_cobrancas.count_documents({"status": "pago"})
    bot.reply_to(message, f"📊 *Estatísticas:*\\n✅ Pagos: {pago}\\n💰 Total: R$ {pago*50:.2f}", parse_mode="Markdown")

# --- ROTAS WEB ---
@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    with open("dashboard.html", "r", encoding="utf-8") as f: return f.read()

@app.get("/api/stats")
async def get_stats():
    pago = col_cobrancas.count_documents({"status": "pago"})
    return {"pago": pago, "valor": pago * 50.0}

@app.post("/api/gerar_pix_web")
async def gerar_pix_web(req: PixReq):
    ident = f"web_{int(time.time())}"
    payload = {"identifier": ident, "amount": req.valor, "callbackUrl": "https://pix20.onrender.com/webhook_pagamento", "client": {"name": "Web", "email": "w@e.com", "phone": "119", "document": gerar_cpf_aleatorio()}}
    headers = {"x-public-key": "laispereiraphoto_2s0vatrdx6coy3pp", "x-secret-key": "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as cl:
        resp = await cl.post("https://app.sigilopay.com.br/api/v1/gateway/pix/receive", json=payload, headers=headers)
        data = resp.json()
        pix = data.get("pix") or data.get("order", {}).get("pix") or {}
        qrt = pix.get("code") or pix.get("payload") or ""
        return {"success": True, "qr_text": qrt}

@app.post("/api/gerar_pix_jogo")
async def gerar_pix_jogo_api(req: PixReq, bg_tasks: BackgroundTasks):
    job_id = f"job_{int(time.time())}"
    JOBS[job_id] = {"status": "processando"}
    bg_tasks.add_task(run_bot_task, job_id, req.valor)
    return {"success": True, "job_id": job_id}

async def run_bot_task(job_id, valor):
    try:
        import bot_gbg3
        res = await bot_gbg3.gerar_pix_jogo(valor)
        if res.get("success"): JOBS[job_id] = {"status": "sucesso", "qr_text": res.get("pix_code")}
        else: JOBS[job_id] = {"status": "erro", "message": res.get("message")}
    except Exception as e: JOBS[job_id] = {"status": "erro", "message": str(e)}

@app.get("/api/status_jogo/{job_id}")
async def status_jogo(job_id: str):
    return JOBS.get(job_id, {"status": "erro", "message": "Não encontrado"})

# --- INICIALIZAÇÃO ---
def run_bot():
    bot.infinity_polling()

@app.on_event("startup")
def startup():
    threading.Thread(target=run_bot, daemon=True).start()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
