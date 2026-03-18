
import os
import json
import time
import secrets
import random
import threading
import httpx
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn
import telebot
from telebot import types
from pymongo import MongoClient
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import qrcode
from io import BytesIO

# --- CONFIGURAÇÃO ---
def get_env(key, default):
    return os.environ.get(key, default)

def load_cfg():
    # Pega lista de IDs autorizados (separados por vírgula)
    admin_ids_raw = get_env("TELEGRAM_ADMIN_ID", "8084292904")
    admin_ids = [s.strip() for s in admin_ids_raw.split(",")]

    cfg = {
        "public_key": get_env("SIGILOPAY_PUBLIC_KEY", "laispereiraphoto_2s0vatrdx6coy3pp"),
        "secret_key": get_env("SIGILOPAY_SECRET_KEY", "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v"),
        "api_base": get_env("SIGILOPAY_API_BASE", "https://app.sigilopay.com.br"),
        "telegram_token": get_env("TELEGRAM_TOKEN", "8618759737:AAH8JRKP_7Xm_nPXMiSxelKsPLbJMaRwM-M"),
        "telegram_admin_ids": admin_ids,
        "webhook_url": get_env("WEBHOOK_URL", "https://pix20.onrender.com"),
        "parceiros": {"admin": "admin_master_key_123"},
        "auto_saque": False # Modo padrão: Manual
    }
    return cfg

CFG = load_cfg()
BASE = os.path.dirname(os.path.abspath(__file__))
MONGO_URI = get_env("MONGO_URI", "mongodb+srv://michelidiasphoto_db_user:lVN70gFWTgsecLTw@cluster0.eb7vf2i.mongodb.net/?appName=Cluster0")
DB_NAME = get_env("MONGO_DB_NAME", "sigilopay_db")

# --- MONGODB SETUP ---
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
col_cobrancas = db["cobrancas"]
col_users = db["users"]
col_saques = db["saques"]

def db_criar(tid, parceiro, valor, qrc, qrt, parceiro_login=None):
    col_cobrancas.update_one(
        {"transaction_id": tid},
        {"$set": {
            "parceiro": parceiro,
            "parceiro_login": parceiro_login,
            "valor": valor,
            "status": "aguardando",
            "qr_code": qrc,
            "qr_text": qrt,
            "criado_em": datetime.now().isoformat()
        }},
        upsert=True
    )

def db_update(tid, status):
    pago_em = datetime.now().isoformat() if status == "pago" else None
    col_cobrancas.update_one(
        {"transaction_id": tid},
        {"$set": {"status": status, "pago_em": pago_em}}
    )

def db_status(tid):
    return col_cobrancas.find_one({"transaction_id": tid})

def db_stats(parceiro_login=None):
    filter_q = {}
    if parceiro_login:
        filter_q["parceiro_login"] = parceiro_login
    
    total = col_cobrancas.count_documents(filter_q)
    paid_filter = {**filter_q, "status": "pago"}
    pago = col_cobrancas.count_documents(paid_filter)
    
    pipeline = [{"$match": paid_filter}, {"$group": {"_id": None, "total": {"$sum": "$valor"}}}]
    res = list(col_cobrancas.aggregate(pipeline))
    valor = res[0]["total"] if res else 0
    
    return {"total": total, "pago": pago, "valor": valor}

# --- GESTÃO DE USUÁRIOS NO MONGO ---
def bot_user_add(uid):
    col_users.update_one({"user_id": str(uid)}, {"$set": {"authorized": True}}, upsert=True)

def bot_user_remove(uid):
    col_users.delete_one({"user_id": str(uid)})

def bot_user_list():
    return [u["user_id"] for u in col_users.find({"authorized": True})]

def is_authorized(uid):
    uid_str = str(uid)
    # Sempre autoriza o Admin do Render
    if uid_str in CFG["telegram_admin_ids"]:
        return True
    # Verifica no MongoDB (usando o ID vinculado)
    return col_users.find_one({"telegram_id": uid_str}) is not None

# --- STATUS POLLING ---
def check_single_status(tid):
    """Consulta o status de uma transação diretamente na API da SigiloPay"""
    cobranca = db_status(tid)
    if not cobranca or cobranca.get("status") == "pago":
        return
    
    # Determina chaves corretas baseadas no valor
    valor = cobranca.get("valor", 0)
    p_key = CFG["public_key"]
    s_key = CFG["secret_key"]
    if valor >= 1000 and CFG.get("public_key_above"):
        p_key = CFG["public_key_above"]
        s_key = CFG["secret_key_above"]

    headers = {
        "x-public-key": p_key,
        "x-secret-key": s_key,
        "Content-Type": "application/json"
    }

    try:
        # Tenta com e sem /api/v1 dependendo da configuração
        url = f"{CFG['api_base']}/api/v1/gateway/transactions"
        with httpx.Client(timeout=15) as client_http:
            resp = client_http.get(url, params={"id": tid}, headers=headers)
            if resp.status_code == 404: # Tenta sem api/v1 se falhar
                url = f"{CFG['api_base']}/gateway/transactions"
                resp = client_http.get(url, params={"id": tid}, headers=headers)
            
            if resp.status_code in (200, 201):
                data = resp.json()
                # Debug se necessário: print(f"Polling {tid}: {data}")
                status_api = str(data.get("status") or data.get("data", {}).get("status", "")).lower()
                if status_api in ("paid", "pago", "completed", "approved"):
                    db_update(tid, "pago")
                    return True
    except Exception as e:
        print(f"Erro polling {tid}: {e}")
    return False

def bg_check_pending():
    """Loop de fundo para conferir todas as cobranças pendentes da última hora"""
    print("🔄 Job de conferência automática iniciado...")
    while True:
        try:
            # Pega cobranças 'aguardando' criadas nas últimas 24 horas
            uma_hora_atras = (datetime.now() - timedelta(hours=24)).isoformat()
            pendentes = list(col_cobrancas.find({
                "status": "aguardando",
                "criado_em": {"$gt": uma_hora_atras}
            }).limit(50))
            
            for p in pendentes:
                tid = p.get("transaction_id")
                if tid:
                    if check_single_status(tid):
                        print(f"✅ Pago via Polling: {tid}")
                    time.sleep(1) # Pequena pausa entre cada checagem
                    
        except Exception as e:
            print(f"Erro no loop de polling: {e}")
        
        time.sleep(60) # Roda a cada 1 minuto

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
security = HTTPBasic()

class PixReq(BaseModel):
    valor: float
    descricao: Optional[str] = "Cobrança PIX"
    nome_pagador: Optional[str] = "Cliente"

class LoginReq(BaseModel):
    username: str
    password: str
    telegram_id: Optional[str] = None

# Removendo Depends(security) da rota principal para evitar erro no Telegram
@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    with open(os.path.join(BASE, "dashboard.html"), "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/login")
async def api_login(req: LoginReq):
    # Master Admin
    if req.username == "admin_maisvelho" and req.password == "maisvelhoadmin":
        return {"success": True, "role": "master"}
    
    # Busca parceiro no banco
    user = col_users.find_one({"login": req.username, "password": req.password})
    if user:
        if user.get("expira_em"):
            expira = datetime.fromisoformat(user["expira_em"])
            if datetime.now() > expira:
                raise HTTPException(401, "Acesso expirado")
        
        # Vínculo automático com o ID do Telegram se enviado
        if req.telegram_id:
            col_users.update_one({"login": req.username}, {"$set": {"telegram_id": str(req.telegram_id)}})
            
        return {"success": True, "role": "user"}
        
    raise HTTPException(401, "Login ou senha inválidos")

@app.get("/api/stats")
async def api_stats(credentials: HTTPBasicCredentials = Depends(security)):
    # Master vê tudo, parceiro vê só o dele
    if credentials.username == "admin_maisvelho" and credentials.password == "maisvelhoadmin":
        return db_stats()
    
    user = col_users.find_one({"login": credentials.username, "password": credentials.password})
    if user:
        return db_stats(parceiro_login=credentials.username)
            
    raise HTTPException(401, "Não autorizado")

@app.get("/api/financas")
async def api_financas(credentials: HTTPBasicCredentials = Depends(security)):
    # Retorna dados financeiros específicos para o parceiro
    if credentials.username == "admin_maisvelho":
        # Master vê consolidado (opcional, vamos focar no parceiro agora)
        return {"error": "Acesso Master: use o dashboard geral"}
        
    stats = db_stats(parceiro_login=credentials.username)
    valor_total = stats["valor"]
    valor_comissao = valor_total * 0.8  # 80% como pedido
    
    # Soma saques já feitos
    pipeline = [{"$match": {"login": credentials.username, "status": "completo"}}, {"$group": {"_id": None, "total": {"$sum": "$valor"}}}]
    res_saques = list(col_saques.aggregate(pipeline))
    sacado = res_saques[0]["total"] if res_saques else 0
    
    disponivel = valor_comissao - sacado
    
    return {
        "vendas_total": valor_total,
        "comissao_total": valor_comissao,
        "sacado": sacado,
        "disponivel": disponivel
    }

@app.post("/api/saque")
async def api_saque(data: dict, credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username == "admin_maisvelho": raise HTTPException(400, "Admin não faz saque aqui")
    
    chave = data.get("pix_key")
    valor_pedir = float(data.get("valor", 0))
    
    if not chave or valor_pedir <= 0:
        raise HTTPException(400, "Dados inválidos")

    if valor_pedir < 100:
        raise HTTPException(400, "O valor mínimo para saque é de R$ 100,00.")

    # PREVENÇÃO DE DUPLICATAS: Verifica se já tem saque pendente
    pendente = col_saques.find_one({"login": credentials.username, "status": "pendente"})
    if pendente:
        raise HTTPException(400, "Você já possui um pedido de saque aguardando aprovação.")
        
    fin = await api_financas(credentials)
    if valor_pedir > fin["disponivel"]:
        raise HTTPException(400, "Saldo insuficiente para o saque")
        
    saque_doc = {
        "login": credentials.username,
        "valor": valor_pedir,
        "pix_key": chave,
        "status": "pendente",
        "criado_em": datetime.now().isoformat()
    }
    
    # Tenta saque AUTOMÁTICO se estiver ligado
    if CFG.get("auto_saque"):
        try:
            payout_payload = {
                "amount": valor_pedir,
                "key": chave
            }
            payout_headers = {
                "x-public-key": CFG["public_key"],
                "x-secret-key": CFG["secret_key"],
                "Content-Type": "application/json"
            }
            async with httpx.AsyncClient(timeout=30) as cl:
                payout_resp = await cl.post(f"{CFG['api_base']}/api/v1/gateway/pix/payout", json=payout_payload, headers=payout_headers)
                payout_data = payout_resp.json()
                
            if payout_resp.status_code in (200, 201):
                saque_doc["status"] = "completo"
                saque_doc["payout_id"] = payout_data.get("id") or "auto"
            else:
                saque_doc["status"] = "erro"
                saque_doc["erro_api"] = payout_data.get("message", "Erro na API")
        except Exception as e:
            saque_doc["status"] = "erro"
            saque_doc["erro_api"] = str(e)

    col_saques.insert_one(saque_doc)
    
    # Notifica Admin Principal
    status_emoji = "✅ AUTOMÁTICO" if saque_doc["status"] == "completo" else "⏳ PENDENTE (MANUAL)"
    if saque_doc["status"] == "erro": status_emoji = f"⚠️ ERRO AUTO: {saque_doc.get('erro_api')}"
    
    notif = f"💰 *PEDIDO DE SAQUE*\n👤 Usuário: `{credentials.username}`\n💵 Valor: R$ {valor_pedir:.2f}\n🔑 Chave: `{chave}`\n📌 Status: {status_emoji}"
    for admin_id in CFG["telegram_admin_ids"]:
        try: bot.send_message(admin_id, notif, parse_mode="Markdown")
        except: pass
        
    return {"success": True, "message": "Pedido de saque enviado com sucesso", "status": saque_doc["status"]}

@app.get("/api/saques/meus")
async def api_meus_saques(credentials: HTTPBasicCredentials = Depends(security)):
    # Retorna o histórico de saques do parceiro logado
    saques = list(col_saques.find({"login": credentials.username}).sort("criado_em", -1).limit(10))
    for s in saques: s["_id"] = str(s["_id"])
    return {"saques": saques}

@app.get("/api/users")
async def api_users(credentials: HTTPBasicCredentials = Depends(security)):
    # Somente o Master vê a lista de gestão e config
    if credentials.username == "admin_maisvelho" and credentials.password == "maisvelhoadmin":
        users = list(col_users.find({}, {"_id": 0, "password": 0}))
        
        # Adiciona o saldo disponível para cada usuário
        for u in users:
            if u.get("login"):
                st = db_stats(u["login"])
                # 80% do total vendido
                v_comissao = st["valor"] * 0.8
                # Soma saques completos
                pip = [{"$match": {"login": u["login"], "status": "completo"}}, {"$group": {"_id": None, "total": {"$sum": "$valor"}}}]
                res_s = list(col_saques.aggregate(pip))
                v_sacado = res_s[0]["total"] if res_s else 0
                u["saldo_disponivel"] = v_comissao - v_sacado
            else:
                u["saldo_disponivel"] = 0
                
        return {"users": users, "auto_saque": CFG["auto_saque"]}
    raise HTTPException(401, "Apenas o Admin Master pode gerir usuários")

@app.get("/api/admin/saques")
async def api_admin_list_saques(credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username != "admin_maisvelho": raise HTTPException(401)
    # Lista saques pendentes ou erro (para revisão)
    saques = list(col_saques.find({"status": {"$in": ["pendente", "erro"]}}).sort("criado_em", -1))
    for s in saques: s["_id"] = str(s["_id"])
    return {"saques": saques}

@app.post("/api/admin/saques/{saque_id}/confirmar")
async def api_admin_confirm_saque(saque_id: str, credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username != "admin_maisvelho": raise HTTPException(401)
    from bson import ObjectId
    col_saques.update_one({"_id": ObjectId(saque_id)}, {"$set": {"status": "completo", "pago_em": datetime.now().isoformat()}})
    return {"success": True}

@app.post("/api/admin/config")
async def api_admin_config(data: dict, credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username != "admin_maisvelho": raise HTTPException(401)
    if "auto_saque" in data:
        CFG["auto_saque"] = bool(data["auto_saque"])
    return {"success": True, "auto_saque": CFG["auto_saque"]}

@app.post("/api/users")
async def api_create_user(data: dict, credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username != "admin_maisvelho": raise HTTPException(401)
    
    login = data.get("login")
    senha = data.get("password")
    dias = int(data.get("validade", 30))
    
    expira_em = (datetime.now() + timedelta(days=dias)).isoformat()
    
    col_users.update_one(
        {"login": login},
        {"$set": {
            "password": senha,
            "expira_em": expira_em,
            "criado_em": datetime.now().isoformat()
        }},
        upsert=True
    )
    return {"success": True}

@app.delete("/api/users/{login}")
async def api_delete_user(login: str, credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username != "admin_maisvelho": raise HTTPException(401)
    col_users.delete_one({"login": login})
    # Opcional: também limpa dados ao deletar usuário
    col_cobrancas.delete_many({"parceiro_login": login})
    col_saques.delete_many({"login": login})
    return {"success": True}

@app.post("/api/admin/users/{login}/zerar")
async def api_reset_user(login: str, credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username != "admin_maisvelho": raise HTTPException(401)
    # Limpa cobranças e saques do usuário para fins de teste/reset
    col_cobrancas.delete_many({"parceiro_login": login})
    col_saques.delete_many({"login": login})
    print(f"♻️ Dados do usuário {login} foram resetados pelo administrador.")
    return {"success": True}

@app.post("/api/gerar_pix_web")
async def gerar_pix_web(req: PixReq, credentials: HTTPBasicCredentials = Depends(security)):
    # Valida se o usuário logado existe e não expirou
    is_master = credentials.username == "admin_maisvelho" and credentials.password == "maisvelhoadmin"
    valid_user = False
    
    if not is_master:
        u = col_users.find_one({"login": credentials.username, "password": credentials.password})
        if u:
            exp = datetime.fromisoformat(u["expira_em"]) if u.get("expira_em") else None
            if not exp or datetime.now() < exp:
                valid_user = True
    
    if is_master or valid_user:
        res = await gerar_pix(req, CFG["parceiros"].get("admin", "admin_master_key_123"), parceiro_login=credentials.username)
        return res
    
    raise HTTPException(401, "Não autorizado ou expirado")

@app.post("/gerar_pix")
async def gerar_pix(body: PixReq, x_partner_key: str = Header(...), parceiro_login=None):
    # Valida parceiro
    parceiro = None
    for n, k in CFG.get("parceiros", {}).items():
        if k == x_partner_key:
            parceiro = n; break
    if not parceiro: raise HTTPException(401, "Chave inválida")
    
    ident = f"prod_{int(time.time())}_{secrets.token_hex(3)}"
    
    # Payload simplificado (mesma lógica do bot)
    payload = {
        "identifier": ident,
        "amount": round(body.valor, 2),
        "callbackUrl": f"{CFG.get('webhook_url')}/webhook_pagamento",
        "client": {
            "name": body.nome_pagador,
            "email": "cliente@email.com",
            "phone": "11999999999",
            "document": "12345678909" # CPF fixo para teste/prod simplificado
        }
    }
    
    creds = {
        "x-public-key": CFG["public_key"],
        "x-secret-key": CFG["secret_key"],
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    async with httpx.AsyncClient(timeout=30) as cl:
        resp = await cl.post(f"{CFG['api_base']}/api/v1/gateway/pix/receive", json=payload, headers=creds)
        data = resp.json()
    
    if resp.status_code not in (200, 201):
        raise HTTPException(resp.status_code, str(data))
    
    tid = data.get("transactionId") or data.get("id") or ident
    pix_node = data.get("pix") or data.get("order", {}).get("pix") or {}
    qrt = pix_node.get("code") or pix_node.get("payload") or pix_node.get("qrCodeText") or ""
    
    db_criar(str(tid), parceiro, body.valor, "", qrt, parceiro_login=parceiro_login)
    return {"success": True, "transaction_id": str(tid), "qr_text": qrt}

@app.post("/webhook_pagamento")
async def webhook(request: Request):
    try:
        data = await request.json()
    except:
        return {"error": "Invalid JSON"}
        
    print(f"📥 Webhook recebido: {data}")
    
    tid = str(data.get("id") or data.get("transactionId") or data.get("data", {}).get("id") or data.get("external_id") or "")
    status = str(data.get("status") or data.get("data", {}).get("status", "")).lower()
    
    if tid and status in ("paid", "pago", "completed", "approved", "success"):
        cobranca = db_status(tid)
        if cobranca and cobranca.get("status") != "pago":
            db_update(tid, "pago")
            
            # Notifica no Telegram (todos os admins)
            valor = cobranca.get('valor', '???')
            parceiro = cobranca.get('parceiro_login') or cobranca.get('parceiro') or "Web"
            msg_notif = f"✅ *PAGAMENTO RECEBIDO!*\n💰 Valor: R$ {valor}\n🆔 ID: `{tid}`\n👤 Parceiro: `{parceiro}`"
            for admin_id in CFG["telegram_admin_ids"]:
                try:
                    bot.send_message(admin_id, msg_notif, parse_mode="Markdown")
                except: pass
        
    return {"received": True}

# --- TELEGRAM BOT ---
bot = telebot.TeleBot(CFG["telegram_token"])

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    # URL real do seu Render para o Mini App abrir corretamente
    web_app = types.WebAppInfo(url="https://pix20.onrender.com") 
    btn_web = types.KeyboardButton("🚀 Abrir Painel Web", web_app=web_app)
    markup.add(btn_web)
    return markup

@bot.message_handler(commands=['start', 'help'])
def bot_welcome(message):
    # Todos podem dar /start
    welcome_msg = "👋 *Bem-vindo ao Painel VIP Pix 20%!*\n\n"
    
    if is_authorized(message.from_user.id):
        welcome_msg += "Você já está autorizado! Use o menu abaixo para gerenciar suas vendas."
    else:
        welcome_msg += "Para acessar as funções, abra o Painel Web e faça login com suas credenciais."
        
    bot.send_message(message.chat.id, welcome_msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda m: m.text == "📊 Estatísticas")
@bot.message_handler(commands=['stats'])
def bot_stats_reply(message):
    if not is_authorized(message.from_user.id): return
    s = db_stats()
    text = f"📊 *Resumo Geral*\n\nTotal Cobranças: {s['total']}\nConfirmadas: {s['pago']}\nTotal: *R$ {s['valor']:.2f}*"
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['add'])
def bot_add_user(message):
    # Só o Admin do Render pode adicionar outros
    if str(message.from_user.id) not in CFG["telegram_admin_ids"]: return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Use: `/add [ID]`")
        return
    bot_user_add(parts[1])
    bot.reply_to(message, f"✅ Usuário `{parts[1]}` liberado!")

@bot.message_handler(commands=['remove'])
def bot_del_user(message):
    if str(message.from_user.id) not in CFG["telegram_admin_ids"]: return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Use: `/remove [ID]`")
        return
    bot_user_remove(parts[1])
    bot.reply_to(message, f"❌ Usuário `{parts[1]}` removido!")

@bot.message_handler(commands=['list'])
def bot_list_users(message):
    if str(message.from_user.id) not in CFG["telegram_admin_ids"]: return
    users = bot_user_list()
    if not users:
        bot.reply_to(message, "Nenhum usuário extra cadastrado.")
        return
    texto = "👥 *Usuários Liberados:*\n\n" + "\n".join([f"• `{u}`" for u in users])
    bot.send_message(message.chat.id, texto, parse_mode="Markdown")

@bot.message_handler(commands=['pix'])
def bot_pix(message):
    if not is_authorized(message.from_user.id): return
    
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "❌ *Erro!* Use: `/pix [valor]`\nExemplo: `/pix 50.00`", parse_mode="Markdown")
        return

    try:
        valor_str = parts[1].replace(',', '.')
        valor = float(valor_str)
        if valor < 1.0:
            bot.reply_to(message, "⚠️ O valor mínimo é R$ 1,00")
            return
    except:
        bot.reply_to(message, "❌ Valor inválido! Use números (ex: 10.50)")
        return

    bot.send_chat_action(message.chat.id, 'typing')
    msg_espera = bot.reply_to(message, "⏳ Gerando PIX, aguarde...")

    try:
        ident = f"bot_{int(time.time())}_{secrets.token_hex(2)}"
        
        # Escolhe as chaves baseadas no valor (mesma lógica do painel)
        p_key = CFG["public_key"]
        s_key = CFG["secret_key"]
        if valor >= 1000 and CFG.get("public_key_above"):
            p_key = CFG["public_key_above"]
            s_key = CFG["secret_key_above"]

        payload = {
            "identifier": ident,
            "amount": round(valor, 2),
            "callbackUrl": f"{CFG.get('webhook_url')}/webhook_pagamento",
            "client": {
                "name": "Cliente Bot",
                "email": "cliente@bot.com",
                "phone": "11999999999",
                "document": "12345678909"
            }
        }
        
        headers = {
            "x-public-key": p_key,
            "x-secret-key": s_key,
            "Content-Type": "application/json"
        }

        with httpx.Client(timeout=30) as client_http:
            resp = client_http.post(f"{CFG['api_base']}/api/v1/gateway/pix/receive", json=payload, headers=headers)
            data = resp.json()

        if resp.status_code not in (200, 201):
            bot.edit_message_text(f"❌ *Erro na API:* {data.get('message', 'Erro desconhecido')}", message.chat.id, msg_espera.message_id, parse_mode="Markdown")
            return

        tid = data.get("transactionId") or data.get("id")
        pix_node = data.get("pix") or data.get("order", {}).get("pix") or {}
        qrt = pix_node.get("code") or pix_node.get("payload") or ""

        # Salva no MongoDB
        db_criar(str(tid), "Telegram Bot", valor, "", qrt)

        # Gera imagem do QR Code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qrt)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Salva em memória
        bio = BytesIO()
        bio.name = 'qrcode.png'
        img.save(bio, 'PNG')
        bio.seek(0)

        # Resposta final para o usuário
        texto_final = (
            f"✅ *PIX GERADO COM SUCESSO!*\n\n"
            f"💰 *Valor:* R$ {valor:.2f}\n"
            f"🆔 *ID:* `{tid}`\n\n"
            f"👇 *Copia e Cola:*"
        )
        
        # Remove mensagem de espera e envia Foto + Texto
        bot.delete_message(message.chat.id, msg_espera.message_id)
        bot.send_photo(message.chat.id, bio, caption=texto_final, parse_mode="Markdown")
        bot.send_message(message.chat.id, f"`{qrt}`", parse_mode="Markdown")

    except Exception as e:
        bot.edit_message_text(f"❌ *Erro interno:* {str(e)}", message.chat.id, msg_espera.message_id, parse_mode="Markdown")

# --- EXECUÇÃO ---
def run_bot():
    print("🤖 Bot Iniciado...")
    bot.infinity_polling()

if __name__ == "__main__":
    # Inicia Bot em Thread separada
    threading.Thread(target=run_bot, daemon=True).start()
    
    # Inicia conferência automática das cobranças pendentes
    threading.Thread(target=bg_check_pending, daemon=True).start()
    
    # Inicia Servidor (Porta 8000 é o padrão do Render se não definida)
    port = int(os.environ.get("PORT", 8000))
    print(f"🌐 Servidor rodando na porta {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
