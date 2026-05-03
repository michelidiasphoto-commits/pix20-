
import telebot
import json
import os
import sqlite3
import time
import secrets
import random
import httpx
from datetime import datetime
from telebot import types

# --- CONFIGURAÇÃO ---
BASE = os.path.dirname(os.path.abspath(__file__))
CFG_FILE = os.path.join(BASE, "sigilopay_config.json")
DB_FILE  = os.path.join(BASE, "sigilopay.db")

def load_cfg():
    if os.path.exists(CFG_FILE):
        try:
            with open(CFG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {}

CFG = load_cfg()
TOKEN = CFG.get("telegram_token", "8618759737:AAH8JRKP_7Xm_nPXMiSxelKsPLbJMaRwM-M")
ADMIN_ID = CFG.get("telegram_admin_id", "8084292904")

bot = telebot.TeleBot(TOKEN)

# --- BANCO DE DADOS (Copia minimalista do SigiloPay_Tudo) ---
def db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def db_criar(tid, parceiro, valor, qrc, qrt):
    c = db()
    c.execute("INSERT OR IGNORE INTO cobranças (transaction_id,parceiro,valor,status,qr_code,qr_text,criado_em) VALUES(?,?,?,'aguardando',?,?,?)",
              (tid, parceiro, valor, qrc, qrt, datetime.now().isoformat()))
    c.commit(); c.close()

def db_list():
    c = db()
    rows = c.execute("SELECT * FROM cobranças ORDER BY id DESC LIMIT 10").fetchall()
    c.close()
    return [dict(r) for r in rows]

def db_stats():
    c = db()
    total = c.execute("SELECT COUNT(*) FROM cobranças").fetchone()[0]
    pago = c.execute("SELECT COUNT(*) FROM cobranças WHERE status='pago'").fetchone()[0]
    valor_total = c.execute("SELECT SUM(valor) FROM cobranças WHERE status='pago'").fetchone()[0] or 0
    c.close()
    return {"total": total, "pago": pago, "valor": valor_total}

# --- HELPERS ---
def check_admin(message):
    if str(message.from_user.id) != str(ADMIN_ID):
        bot.reply_to(message, "❌ *Acesso Negado.*\nApenas o administrador pode usar este bot.")
        return False
    return True

# --- COMANDOS ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if not check_admin(message): return
    
    welcome_text = (
        "👋 *Olá, Bem-vindo ao SigiloPay Bot!*\\n\\n"
        "Com este bot você pode gerenciar suas cobranças PIX diretamente pelo Telegram.\\n\\n"
        "🚀 *Comandos disponíveis:*\\n"
        "💰 `/pix [valor]` - Gera um novo QR Code PIX (Ex: `/pix 50.00`)\\n"
        "📊 `/stats` - Resumo de vendas e status\\n"
        "📜 `/historico` - Lista as últimas 10 cobranças\\n"
        "⚙️ `/config` - Ver configurações atuais"
    )
    bot.send_message(message.chat.id, welcome_text, parse_mode="Markdown")

@bot.message_handler(commands=['stats'])
def stats(message):
    if not check_admin(message): return
    s = db_stats()
    text = (
        "📊 *Estatísticas Atuais*\\n\\n"
        f"🔹 *Total de Cobranças:* {s['total']}\\n"
        f"✅ *Pagas:* {s['pago']}\\n"
        f"⏳ *Aguardando:* {s['total'] - s['pago']}\\n\\n"
        f"💵 *Total Recebido:* `R$ {s['valor']:.2f}`"
    )
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['historico'])
def historico(message):
    if not check_admin(message): return
    rows = db_list()
    if not rows:
        bot.reply_to(message, "📭 Nenhuma cobrança encontrada.")
        return
    
    text = "📜 *Últimas 10 Cobranças:*\\n\\n"
    for r in rows:
        status_icon = "✅" if r['status'] == 'pago' else "⏳"
        text += f"{status_icon} `R$ {r['valor']:.2f}` - _{r['transaction_id'][:8]}..._\\n"
    
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['pix'])
def gerar_pix_cmd(message):
    if not check_admin(message): return
    
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "❌ *Erro:* Use o formato `/pix [valor]`. Ex: `/pix 19.90`")
            return
        
        valor_str = args[1].replace(",", ".")
        valor = float(valor_str)
        if valor <= 0: raise ValueError
    except:
        bot.reply_to(message, "❌ *Erro:* Valor inválido. Digite um número positivo.")
        return

    msg = bot.reply_to(message, "⏳ *Gerando PIX...* Aguarde.")
    
    # Lógica de geração PIX (copiada do painel)
    try:
        ident = f"bot_{int(time.time())}_{secrets.token_hex(3)}"
        
        # CPF fake para API
        cpf_list = [random.randint(0, 9) for _ in range(9)]
        for _ in range(2):
            val = sum([(len(cpf_list) + 1 - i) * v for i, v in enumerate(cpf_list)]) % 11
            cpf_list.append(11 - val if val > 1 else 0)
        str_cpf = "".join(map(str, cpf_list))

        payload = {
            "identifier": ident,
            "amount": round(valor, 2),
            "callbackUrl": f"{CFG.get('webhook_url', 'http://localhost:8000')}/webhook_pagamento",
            "client": {
                "name": "Cliente Telegram",
                "email": "telegram@cliente.com",
                "phone": "11999999999",
                "document": str_cpf
            }
        }

        # Credenciais
        is_high = valor >= 1000
        creds = {
            "x-public-key": CFG.get("public_key_above" if is_high else "public_key", CFG.get("public_key")),
            "x-secret-key": CFG.get("secret_key_above" if is_high else "secret_key", CFG.get("secret_key")),
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        api_base = CFG.get("api_base_above" if is_high else "api_base", CFG.get("api_base", "https://app.sigilopay.com.br"))
        api_url = f"{api_base}/api/v1/gateway/pix/receive"

        with httpx.Client(timeout=30) as cl:
            resp = cl.post(api_url, json=payload, headers=creds)
            data = resp.json()

        if resp.status_code not in (200, 201):
            bot.edit_message_text(f"❌ *Erro API:* {data}", message.chat.id, msg.message_id)
            return

        tid = data.get("transactionId") or data.get("id") or ident
        pix_node = data.get("pix") or data.get("order", {}).get("pix") or {}
        qrt = pix_node.get("code") or pix_node.get("payload") or pix_node.get("qrCodeText") or pix_node.get("emv") or ""
        
        # Salva no DB
        db_criar(str(tid), "telegram_bot", valor, "", qrt)

        text_final = (
            f"✅ *PIX Gerado com Sucesso!*\\n\\n"
            f"💰 *Valor:* `R$ {valor:.2f}`\\n"
            f"🆔 *ID:* `{tid}`\\n\\n"
            f"📱 *Copia e Cola:*\\n`{qrt}`"
        )
        
        bot.delete_message(message.chat.id, msg.message_id)
        bot.send_message(message.chat.id, text_final, parse_mode="Markdown")
        
    except Exception as e:
        bot.edit_message_text(f"❌ *Erro Inesperado:* {str(e)}", message.chat.id, msg.message_id)

@bot.message_handler(commands=['config'])
def show_config(message):
    if not check_admin(message): return
    text = (
        "⚙️ *Configurações Atuais*\\n\\n"
        f"🔑 *Public Key:* `{CFG.get('public_key', 'Não definida')[:10]}...`\\n"
        f"🌐 *Webhook URL:* `{CFG.get('webhook_url', 'Não definida')}`\\n"
        f"🤖 *Bot Token:* `{TOKEN[:10]}...`\\n"
        f"👤 *Admin ID:* `{ADMIN_ID}`"
    )
    bot.reply_to(message, text, parse_mode="Markdown")

# --- EXECUÇÃO ---
if __name__ == "__main__":
    print(f"🤖 Bot iniciado (Admin: {ADMIN_ID})...")
    bot.infinity_polling()
