"""
SIGILO PAY - SISTEMA COMPLETO (1 ARQUIVO)
==========================================
Servidor FastAPI embutido + Painel Admin + Gerar PIX
Tudo em 1 EXE portátil.
"""

import sys, os, io, json, sqlite3, threading, time, base64, secrets, webbrowser, asyncio
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime

# ── dependências opcionais ───────────────────────────────────────────────────
try:
    import requests as _req; REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

try:
    from PIL import Image, ImageTk; PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    import qrcode as _qr; QR_OK = True
except ImportError:
    QR_OK = False

try:
    import pymongo; import dns; PYMONGO_OK = True
except ImportError:
    PYMONGO_OK = False

try:
    import telebot; TELEBOT_OK = True
except ImportError:
    TELEBOT_OK = False

# ── caminho base (funciona como EXE ou como .py) ────────────────────────────
BASE = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
CFG_FILE = os.path.join(BASE, "sigilopay_config.json")
DB_FILE  = os.path.join(BASE, "sigilopay.db")

# ─────────────────────────── CONFIGURAÇÃO ────────────────────────────────────
DEFAULT_CFG = {
    "public_key":  "laispereiraphoto_2s0vatrdx6coy3pp",
    "secret_key":  "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v",
    "api_base":    "https://app.sigilopay.com.br",

    "public_key_above": "laispereiraphoto_2s0vatrdx6coy3pp",
    "secret_key_above": "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v",
    "api_base_above":   "https://app.sigilopay.com.br",

    "porta":       8000,

    "webhook_url": "http://localhost:8000",
    "parceiros": {
        "admin":     "admin_master_key_123",
        "parceiro1": "chave_parceiro1_aqui"
    },
    "nome_parceiro_padrao": "admin",
    "usuarios_admin": {
        "adminmaisvelho": "maisvelhoadmin"
    },
    "telegram_token": "8618759737:AAH8JRKP_7Xm_nPXMiSxelKsPLbJMaRwM-M",
    "telegram_admin_id": "8084292904"
}

def load_cfg():
    if os.path.exists(CFG_FILE):
        try:
            with open(CFG_FILE, "r", encoding="utf-8") as f:
                c = json.load(f)
                for k, v in DEFAULT_CFG.items():
                    c.setdefault(k, v)
                return c
        except Exception:
            pass
    return dict(DEFAULT_CFG)

def save_cfg(c):
    with open(CFG_FILE, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=2, ensure_ascii=False)


CFG = load_cfg()

# ─── MONGODB USERS ───────────────────────────────────────────────────────────
MONGO_URI = "mongodb+srv://michelidiasphoto_db_user:lVN70gFWTgsecLTw@cluster0.eb7vf2i.mongodb.net/?appName=Cluster0"
MONGO_DB_NAME = "sigilopay_db"

def get_admin_users():
    default_users = CFG.get("usuarios_admin", {"adminmaisvelho": "maisvelhoadmin"})
    if not PYMONGO_OK:
        return default_users
    try:
        from pymongo import MongoClient
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
        coll = client[MONGO_DB_NAME]["users"]
        docs = list(coll.find({}))
        if not docs:
            print("MongoDB: Nenhum usuário encontrado no BD. Semeando...")
            for u, p in default_users.items():
                coll.update_one({"username": u}, {"$set": {"password": p}}, upsert=True)
            return default_users
        
        users_dict = {}
        for d in docs:
            users_dict[d["username"]] = d["password"]
        
        print(f"MongoDB: {len(users_dict)} usuários carregados.")
        # Atualiza o arquivo local pra manter síncrono
        CFG["usuarios_admin"] = users_dict
        save_cfg(CFG)
        return users_dict
    except Exception as e:
        print("Erro MongoDB get:", e)
        return default_users


def set_admin_user(usr, pwd):
    users = get_admin_users()
    users[usr] = pwd
    CFG["usuarios_admin"] = users
    save_cfg(CFG)
    if PYMONGO_OK:
        try:
            from pymongo import MongoClient
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
            coll = client[MONGO_DB_NAME]["users"]
            coll.update_one({"username": usr}, {"$set": {"password": pwd}}, upsert=True)
        except Exception as e:
            print("Erro MongoDB set:", e)

def del_admin_user(usr):
    users = get_admin_users()
    if usr in users:
        del users[usr]
    CFG["usuarios_admin"] = users
    save_cfg(CFG)
    if PYMONGO_OK:
        try:
            from pymongo import MongoClient
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
            coll = client[MONGO_DB_NAME]["users"]
            coll.delete_one({"username": usr})
        except Exception as e:
            print("Erro MongoDB del:", e)

def update_session(usr, token):
    if not PYMONGO_OK: return
    try:
        from pymongo import MongoClient
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
        coll = client[MONGO_DB_NAME]["users"]
        coll.update_one({"username": usr}, {"$set": {"session_id": token}}, upsert=True)
    except Exception as e:
        print("Erro session update:", e)

def get_session(usr):
    if not PYMONGO_OK: return None
    try:
        from pymongo import MongoClient
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
        coll = client[MONGO_DB_NAME]["users"]
        doc = coll.find_one({"username": usr})
        return doc.get("session_id") if doc else None
    except Exception:
        return None



# ─────────────────────────── BANCO DE DADOS ───────────────────────────────────
def db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    c = db()
    c.execute("""CREATE TABLE IF NOT EXISTS cobranças (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id TEXT UNIQUE,
        parceiro       TEXT,
        valor          REAL,
        status         TEXT DEFAULT 'aguardando',
        qr_code        TEXT,
        qr_text        TEXT,
        criado_em      TEXT,
        pago_em        TEXT
    )""")
    c.commit(); c.close()

def db_criar(tid, parceiro, valor, qrc, qrt):
    if PYMONGO_OK:
        try:
            from pymongo import MongoClient
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
            col = client[MONGO_DB_NAME]["cobrancas"]
            col.update_one({"transaction_id": tid}, {"$set": {
                "parceiro": parceiro, "valor": valor, "status": "aguardando",
                "qr_code": qrc, "qr_text": qrt, "criado_em": datetime.now().isoformat()
            }}, upsert=True)
            return
        except: pass
    
    c = db()
    c.execute("INSERT OR IGNORE INTO cobranças (transaction_id,parceiro,valor,status,qr_code,qr_text,criado_em) VALUES(?,?,?,'aguardando',?,?,?)",
              (tid, parceiro, valor, qrc, qrt, datetime.now().isoformat()))
    c.commit(); c.close()

def db_status(tid):
    if PYMONGO_OK:
        try:
            from pymongo import MongoClient
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
            col = client[MONGO_DB_NAME]["cobrancas"]
            res = col.find_one({"transaction_id": tid})
            if res: res.pop("_id", None); return res
        except: pass

    c = db()
    r = c.execute("SELECT * FROM cobranças WHERE transaction_id=?", (tid,)).fetchone()
    c.close()
    return dict(r) if r else None

def db_update(tid, status):
    pago = datetime.now().isoformat() if status == "pago" else None
    if PYMONGO_OK:
        try:
            from pymongo import MongoClient
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
            col = client[MONGO_DB_NAME]["cobrancas"]
            col.update_one({"transaction_id": tid}, {"$set": {"status": status, "pago_em": pago}})
            return
        except: pass

    c = db()
    c.execute("UPDATE cobranças SET status=?,pago_em=? WHERE transaction_id=?", (status, pago, tid))
    c.commit(); c.close()

def db_list(parceiro=None):
    if PYMONGO_OK:
        try:
            from pymongo import MongoClient
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
            col = client[MONGO_DB_NAME]["cobrancas"]
            query = {"parceiro": parceiro} if parceiro and parceiro != "admin" else {}
            docs = list(col.find(query).sort("criado_em", -1).limit(200))
            for d in docs: d.pop("_id", None)
            return docs
        except: pass

    c = db()
    if parceiro and parceiro != "admin":
        rows = c.execute("SELECT * FROM cobranças WHERE parceiro=? ORDER BY id DESC LIMIT 200",(parceiro,)).fetchall()
    else:
        rows = c.execute("SELECT * FROM cobranças ORDER BY id DESC LIMIT 200").fetchall()
    c.close()
    return [dict(r) for r in rows]

def db_clear(parceiro=None):
    c = db()
    if parceiro and parceiro != "admin":
        c.execute("DELETE FROM cobranças WHERE parceiro=?", (parceiro,))
    else:
        c.execute("DELETE FROM cobranças")
    c.commit(); c.close()


# ─────────────────────────── SERVIDOR FASTAPI ─────────────────────────────────
_server_started = False
_server_thread  = None

def start_server():
    global _server_started
    if _server_started:
        return
    _server_started = True

    import uvicorn
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, FileResponse
    from fastapi.security import HTTPBasic, HTTPBasicCredentials
    from pydantic import BaseModel
    from typing import Optional, List
    import httpx
    
    security = HTTPBasic()

    app = FastAPI(title="SigiloPay", docs_url="/docs")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    def sigilo_hdr(valor: float = 0):
        if valor >= 1000:
            return {
                "x-public-key": CFG.get("public_key_above", CFG["public_key"]),
                "x-secret-key": CFG.get("secret_key_above", CFG["secret_key"]),
                "Content-Type": "application/json",
                "Accept":       "application/json"
            }
        else:
            return {
                "x-public-key": CFG["public_key"],
                "x-secret-key": CFG["secret_key"],
                "Content-Type": "application/json",
                "Accept":       "application/json"
            }

    def get_api_creds(valor: float):

        if valor >= 1000:
            return {
                "x-public-key": CFG.get("public_key_above", CFG["public_key"]),
                "x-secret-key": CFG.get("secret_key_above", CFG["secret_key"]),
                "url":          CFG.get("api_base_above",   CFG["api_base"]),
                "Content-Type": "application/json",
                "Accept":       "application/json"
            }
        else:
            return {
                "x-public-key": CFG["public_key"],
                "x-secret-key": CFG["secret_key"],
                "url":          CFG["api_base"],
                "Content-Type": "application/json",
                "Accept":       "application/json"
            }


    def check_key(k):
        for nome, chave in CFG["parceiros"].items():
            if chave == k:
                return nome
        raise HTTPException(401, "Chave invalida")

    class PixReq(BaseModel):
        valor: float
        descricao: Optional[str] = "Cobranca PIX"
        nome_pagador: Optional[str] = "Cliente"

    @app.get("/health")
    def health():
        return {"status": "online"}

    @app.get("/")
    @app.get("/dashboard.html")
    async def get_dashboard():
        dash_path = os.path.join(BASE, "dashboard.html")
        if os.path.exists(dash_path):
            return FileResponse(dash_path)
        return HTMLResponse("<h1>Arquivo dashboard.html nao encontrado na pasta do servidor.</h1>", status_code=404)

    # --- NOVAS ROTAS DE COMPATIBILIDADE ---
    @app.post("/api/login")
    async def api_login(data: dict):
        u = data.get("username")
        p = data.get("password")
        # Master Admin
        if u == "admin_maisvelho" and p == "maisvelhoadmin":
            return {"success": True, "role": "master"}
        # Busca nos parceiros locais
        for nome, chave in CFG["parceiros"].items():
            if nome == u and chave == p:
                return {"success": True, "role": "user"}
        raise HTTPException(401, "Login ou senha inválidos")

    @app.get("/api/stats")
    async def api_stats(credentials: HTTPBasicCredentials = Depends(security)):
        c = db()
        rows = c.execute("SELECT * FROM cobranças").fetchall()
        c.close()
        rows = [dict(r) for r in rows]
        
        pagos = [r for r in rows if r["status"] == "pago"]
        valor = sum(r["valor"] for r in pagos)
        return {"total": len(rows), "pago": len(pagos), "valor": valor}

    @app.get("/api/financas")
    async def api_financas(credentials: HTTPBasicCredentials = Depends(security)):
        st = await api_stats(credentials)
        valor_total = st["valor"]
        return {
            "vendas_total": valor_total,
            "comissao_total": valor_total * 0.8,
            "sacado": 0,
            "disponivel": valor_total * 0.8
        }

    @app.get("/api/users")
    async def api_users_list(credentials: HTTPBasicCredentials = Depends(security)):
        users = []
        for nome, chave in CFG["parceiros"].items():
            users.append({"login": nome, "saldo_disponivel": 0})
        return {"users": users, "auto_saque": False}

    @app.post("/api/gerar_pix_web")
    async def gerar_pix(body: PixReq, x_partner_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
        # Tenta pegar a chave de um dos dois cabeçalhos
        chave = x_partner_key or authorization
        parceiro = check_key(chave)
        if body.valor <= 0:
            raise HTTPException(400, "Valor invalido")
        import secrets
        import random
        ident = f"cashin_{int(time.time())}_{secrets.token_hex(3)}"
        
        cpf = [random.randint(0, 9) for _ in range(9)]
        for _ in range(2):
            val = sum([(len(cpf) + 1 - i) * v for i, v in enumerate(cpf)]) % 11
            cpf.append(11 - val if val > 1 else 0)
        str_cpf = "".join(map(str, cpf))

        payload = {
            "identifier": ident,
            "amount": round(body.valor, 2),
            "callbackUrl": f"{CFG['webhook_url']}/webhook_pagamento",
            "client": {
                "name": body.nome_pagador or "Cliente Anonimo",
                "email": "cliente@email.com",
                "phone": "11999999999",
                "document": str_cpf
            }
        }
        creds = get_api_creds(body.valor)
        api_url = f"{creds.pop('url')}/api/v1/gateway/pix/receive"
        
        try:
            async with httpx.AsyncClient(timeout=30) as cl:
                resp = await cl.post(api_url, json=payload, headers=creds)
                try:
                    data = resp.json()
                except Exception:
                    raise HTTPException(502, f"Erro API Externa ({resp.status_code}): {resp.text[:120]}")

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(502, f"Erro Conexao: {e}")

        if resp.status_code not in (200, 201):
            raise HTTPException(resp.status_code, str(data))

        tid = data.get("transactionId") or data.get("id") or ident
        pix_node = data.get("pix") or data.get("order", {}).get("pix") or {}
        qrc = pix_node.get("base64") or pix_node.get("image") or pix_node.get("qrCodeImageUrl") or ""
        if qrc and not qrc.startswith("data:"):
            qrc = "data:image/png;base64," + qrc
        qrt = pix_node.get("code") or pix_node.get("payload") or pix_node.get("qrCodeText") or pix_node.get("emv") or pix_node.get("qrCode") or pix_node.get("qrcode") or ""


        db_criar(str(tid), parceiro, body.valor, qrc, qrt)
        return {"success": True, "transaction_id": str(tid), "valor": body.valor,
                "qr_code": qrc, "qr_text": qrt, "status": "aguardando"}

    @app.post("/api/gerar_pix_jogo")
    async def gerar_pix_jogo_api(body: PixReq, x_partner_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
        chave = x_partner_key or authorization
        parceiro = check_key(chave)
        
        print(f"🤖 [ROBÔ] Solicitação de PIX JOGO recebida. Valor: R$ {body.valor}")
        
        if body.valor <= 0:
            raise HTTPException(400, "Valor invalido")
            
        try:
            from bot_gbg3 import gerar_pix_jogo
            # Chama o robô para gerar o PIX na GBG3
            res = await gerar_pix_jogo(body.valor)
            
            if res.get("success"):
                qrt = res.get("pix_code")
                tid = f"gbg3_{int(time.time())}_{secrets.token_hex(2)}"
                # Salva no DB para histórico
                db_criar(tid, f"{parceiro}_gbg3", body.valor, "", qrt)
                
                return {
                    "success": True, 
                    "transaction_id": tid, 
                    "valor": body.valor,
                    "qr_code": "", # O robô geralmente não pega a imagem, só o texto
                    "qr_text": qrt, 
                    "status": "aguardando",
                    "metodo": "jogo"
                }
            else:
                raise HTTPException(500, res.get("message", "Erro ao gerar PIX no jogo"))
                
        except ImportError:
            raise HTTPException(500, "Modulo do robo (bot_gbg3) nao encontrado no servidor")
        except Exception as e:
            raise HTTPException(500, f"Erro interno: {str(e)}")

    @app.get("/status/{tid}")
    async def status(tid: str, x_partner_key: str = Header(...)):
        check_key(x_partner_key)
        row = db_status(tid)
        if not row:
            raise HTTPException(404, "Nao encontrado")
        if row["status"] == "pago":
            return row

        try:
            row = db_status(tid)
            v = row.get("valor", 0) if row else 0
            async with httpx.AsyncClient(timeout=10) as cl:
                resp = await cl.get(f"{CFG['api_base']}/api/v1/gateway/transactions",
                                    params={"id": tid}, headers=sigilo_hdr(v))
                if resp.status_code == 404: # Tenta sem api/v1
                    resp = await cl.get(f"{CFG['api_base']}/gateway/transactions",
                                        params={"id": tid}, headers=sigilo_hdr(v))
                data = resp.json()
            
            s = str(data.get("status") or data.get("data", {}).get("status", "")).lower()
            if s in ("paid","pago","completed","approved"):
                db_update(tid, "pago")
                if row: row["status"] = "pago"
        except Exception:
            pass
        return row

    @app.post("/webhook_pagamento")
    async def webhook(request: Request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        
        print(f"📥 Webhook recebido: {data}")
        
        tid = str(data.get("id") or data.get("transactionId") or 
               data.get("transaction_id") or data.get("data", {}).get("id") or data.get("external_id") or "")
        s = str(data.get("status") or data.get("data", {}).get("status", "")).lower()
        
        if tid and s in ("paid","pago","completed","approved", "success"):
            row = db_status(str(tid))
            if row and row.get("status") != "pago":
                db_update(str(tid), "pago")
                
                # Notificação Telegram
                if TELEBOT_OK and CFG.get("telegram_token") and CFG.get("telegram_admin_id"):
                    try:
                        bot_notify = telebot.TeleBot(CFG["telegram_token"])
                        valor = row['valor']
                        parceiro = row['parceiro']
                        texto = f"✅ *PAGAMENTO CONFIRMADO!*\\n\\n💰 *Valor:* R$ {valor}\\n👤 *Parceiro:* {parceiro}\\n🆔 *ID:* `{tid}`"
                        bot_notify.send_message(CFG["telegram_admin_id"], texto, parse_mode="Markdown")
                    except Exception as e:
                        print(f"Erro notificação Telegram: {e}")

        return {"received": True}

    try:
        if getattr(sys, "frozen", False) and sys.stdout is None:
            class DummyStream:
                def write(self, *args): pass
                def flush(self): pass
                def isatty(self): return False
            sys.stdout = DummyStream()
            sys.stderr = DummyStream()
        
        # log_config=None é uma solução extra para o uvicorn
        uvicorn.run(app, host="0.0.0.0", port=int(CFG["porta"]), log_config=None, access_log=False)
    except Exception as e:
        import traceback
        with open("server_fatal_error.log", "w") as f:
            f.write(traceback.format_exc())

# ─────────────────────────── CORES & ESTILOS ─────────────────────────────────
BG    = "#0a0e1a"
CARD  = "#141824"
BORD  = "#1e2538"
GREEN = "#00d4aa"
YELLOW= "#ffd700"
RED   = "#ff4444"
BLUE  = "#4a9eff"
TEXT  = "#e8eaf0"
GRAY  = "#8892b0"
PAID  = "#00ff88"
DARK  = "#0d1117"

# ─────────────────────────── JANELA PRINCIPAL ────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Gerador PIX")

        self.geometry("1050x700")
        self.minsize(900, 600)
        self.configure(bg=BG)

        self._srv_running = False
        self._pix_tid = None
        self._polling  = False
        self._logs = []

        init_db()
        self._login_screen()

    def _login_screen(self):
        self._login_frame = tk.Frame(self, bg=BG)
        self._login_frame.pack(fill="both", expand=True)

        card = tk.Frame(self._login_frame, bg=CARD, highlightbackground=BORD, highlightthickness=1)
        card.place(relx=0.5, rely=0.5, anchor="center", width=400, height=350)

        tk.Label(card, text="LOGIN ADMIN", font=("Segoe UI", 16, "bold"), bg=CARD, fg=GREEN).pack(pady=(30, 20))
        
        tk.Label(card, text="Usuário", font=("Segoe UI", 10), bg=CARD, fg=GRAY).pack(anchor="w", padx=30)
        self.e_user = tk.Entry(card, font=("Segoe UI", 12), bg=BORD, fg=TEXT, bd=0, insertbackground=GREEN)
        self.e_user.pack(fill="x", padx=30, pady=(4, 15), ipady=6)
        
        tk.Label(card, text="Senha", font=("Segoe UI", 10), bg=CARD, fg=GRAY).pack(anchor="w", padx=30)
        self.e_pass = tk.Entry(card, font=("Segoe UI", 12), bg=BORD, fg=TEXT, bd=0, insertbackground=GREEN, show="*")
        self.e_pass.pack(fill="x", padx=30, pady=(4, 25), ipady=6)

        tk.Button(card, text="ENTRAR", font=("Segoe UI", 12, "bold"), bg=GREEN, fg=BG, bd=0, cursor="hand2", command=self._fazer_login).pack(fill="x", padx=30, ipady=10)

        self.e_pass.bind("<Return>", lambda e: self._fazer_login())
        self.e_user.focus()

    def _fazer_login(self):
        usr = self.e_user.get().strip()
        pwd = self.e_pass.get().strip()
        users = get_admin_users()
        if usr in users and users[usr] == pwd:
            self.logged_user = usr
            self.session_token = secrets.token_hex(16)
            update_session(usr, self.session_token)
            
            self._login_frame.destroy()
            self._init_app()
            
            # Loop de checagem de sessão
            self.after(5000, self._check_session_loop)
        else:
            messagebox.showerror("Erro", "Login ou senha incorretos")

    def _check_session_loop(self):
        if not hasattr(self, "session_token") or not self.logged_user: return
        remote_token = get_session(self.logged_user)
        if remote_token and remote_token != self.session_token:
            messagebox.showwarning("Sessão Encerrada", "Outra instância fez login com este usuário.\nO aplicativo será fechado.")
            self.destroy()
            return
        self.after(10000, self._check_session_loop)


    def _init_app(self):
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(400, self._auto_start_server)
        self.after(4000, self._refresh_loop)

    # ─── AUTO-INICIA SERVIDOR ────────────────────────────────────────────────
    def _auto_start_server(self):
        self._log("Iniciando servidor automaticamente...")
        t = threading.Thread(target=self._run_server, daemon=True)
        t.start()
        
        # Inicia Bot Telegram se configurado
        if CFG.get("telegram_token") and CFG.get("telegram_admin_id"):
            self._log("Iniciando Bot Telegram...")
            threading.Thread(target=self._run_telegram_bot, daemon=True).start()

        self.after(2500, self._mark_server_on)

    def _run_telegram_bot(self):
        try:
            import subprocess
            py_cmd = sys.executable
            bot_path = os.path.join(BASE, "bot_telegram.py")
            if os.path.exists(bot_path):
                subprocess.Popen([py_cmd, bot_path], creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                self._log("Bot Telegram iniciado com sucesso!")
            else:
                self._log("Erro: Arquivo bot_telegram.py não encontrado.")
        except Exception as e:
            self._log(f"Erro ao iniciar Bot Telegram: {e}")

    def _run_server(self):
        try:
            start_server()
        except Exception as e:
            self.after(0, lambda: self._log(f"ERRO servidor: {e}"))

    def _mark_server_on(self):
        self._srv_running = True
        self.lbl_dot.config(text="  ONLINE", fg=PAID)
        self.btn_srv.config(text="Servidor ONLINE", bg=GREEN, state="disabled")

        self._log(f"Servidor rodando em http://localhost:{CFG['porta']}")
        self._log(f"Documentacao: http://localhost:{CFG['porta']}/docs")

    # ─── BUILD UI ───────────────────────────────────────────────────────────
    def _build(self):
        # SIDEBAR
        self.sb = tk.Frame(self, bg=CARD, width=210)
        self.sb.pack(side="left", fill="y")
        self.sb.pack_propagate(False)

        tk.Label(self.sb, text="GERADOR", font=("Segoe UI", 18, "bold"), bg=CARD, fg=GREEN).pack(pady=(22,0))
        tk.Label(self.sb, text="PIX", font=("Segoe UI", 12), bg=CARD, fg=TEXT).pack()

        tk.Frame(self.sb, bg=BORD, height=1).pack(fill="x", padx=12, pady=14)

        self.lbl_dot = tk.Label(self.sb, text="  Iniciando...", font=("Segoe UI",9,"bold"), bg=CARD, fg=YELLOW)
        self.lbl_dot.pack()
        self.btn_srv = tk.Button(self.sb, text="Aguarde...", font=("Segoe UI",9,"bold"),
                                  bg=YELLOW, fg=BG, bd=0, state="disabled")
        self.btn_srv.pack(fill="x", padx=14, ipady=8, pady=6)

        tk.Frame(self.sb, bg=BORD, height=1).pack(fill="x", padx=12, pady=8)

        self._pages = {}
        self._nav_btns = {}
        nav = [("pix","  Gerar PIX"), ("dash","  Dashboard"), ("cobr","  Cobranças")]
        if getattr(self, "logged_user", "") == "adminmaisvelho":
            nav.extend([("users","  Usuários"), ("cfg","  Configurações"), ("logs","  Logs")])
        for key, label in nav:
            b = tk.Button(self.sb, text=label, font=("Segoe UI",10), bd=0,
                          bg=CARD, fg=GRAY, anchor="w", cursor="hand2",
                          activebackground=BORD,
                          command=lambda k=key: self._show(k))
            b.pack(fill="x", padx=8, pady=2, ipady=8)
            self._nav_btns[key] = b

        tk.Frame(self.sb, bg=BORD, height=1).pack(fill="x", padx=12, pady=8)
        
        if getattr(self, "logged_user", "") == "adminmaisvelho":
            tk.Button(self.sb, text="Abrir Docs API", font=("Segoe UI",8),
                      bg=CARD, fg=BLUE, bd=0, cursor="hand2",
                      command=lambda: webbrowser.open(f"http://localhost:{CFG['porta']}/docs")
                      ).pack(pady=2)


        # Botão Sair / Logout
        tk.Frame(self.sb, bg=BORD, height=1).pack(fill="x", padx=12, pady=8)
        tk.Button(self.sb, text="Sair / Logout", font=("Segoe UI",9,"bold"),
                  bg=CARD, fg=RED, bd=0, cursor="hand2",
                  command=self._logout).pack(fill="x", padx=14, ipady=6, pady=4)

        # CONTEÚDO
        self._area = tk.Frame(self, bg=BG)
        self._area.pack(side="left", fill="both", expand=True)

        self._pg_pix()
        self._pg_dash()
        self._pg_cobr()
        self._pg_parc()
        self._pg_users()
        self._pg_cfg()
        self._pg_logs()
        self._show("pix")

    def _show(self, name):
        for n, f in self._pages.items():
            f.pack_forget()
        for n, b in self._nav_btns.items():
            b.config(bg=CARD if n != name else BORD, fg=GRAY if n != name else TEXT)
        self._pages[name].pack(fill="both", expand=True)
        if name in ("cobr","dash"):
            self._refresh_table()

    # ─── PÁGINA: GERAR PIX ───────────────────────────────────────────────────
    def _pg_pix(self):
        p = tk.Frame(self._area, bg=BG)
        self._pages["pix"] = p

        # Título
        tk.Label(p, text="GERAR COBRANÇA PIX", font=("Segoe UI",16,"bold"),
                 bg=BG, fg=TEXT).pack(anchor="w", padx=28, pady=(22,2))
        tk.Label(p, text="Gere cobranças instantaneamente pela SigiloPay",
                 font=("Segoe UI",9), bg=BG, fg=GRAY).pack(anchor="w", padx=28)

        # Card formulário
        fc = self._card(p)
        fc.pack(fill="x", padx=28, pady=12)

        # Valor
        tk.Label(fc, text="Valor (R$)", font=("Segoe UI",9), bg=CARD, fg=GRAY
                 ).pack(anchor="w", padx=16, pady=(14,2))
        vf = tk.Frame(fc, bg=BORD)
        vf.pack(fill="x", padx=16)
        tk.Label(vf, text="R$", font=("Segoe UI",16,"bold"), bg=BORD, fg=GREEN, width=4
                 ).pack(side="left")
        self.e_valor = tk.Entry(vf, font=("Segoe UI",20,"bold"), bg=BORD, fg=TEXT,
                                 bd=0, insertbackground=GREEN, width=14)
        self.e_valor.pack(side="left", pady=10)
        self.e_valor.insert(0, "0,00")
        self.e_valor.bind("<FocusIn>", lambda e: (self.e_valor.delete(0,"end") if self.e_valor.get() in ("0,00","") else None))
        self.e_valor.bind("<Return>", lambda e: self._gerar())

        # Descrição
        tk.Label(fc, text="Descrição", font=("Segoe UI",9), bg=CARD, fg=GRAY
                 ).pack(anchor="w", padx=16, pady=(10,2))
        self.e_desc = tk.Entry(fc, font=("Segoe UI",11), bg=BORD, fg=TEXT, bd=0, insertbackground=GREEN)
        self.e_desc.pack(fill="x", padx=16, pady=(0,14), ipady=7)
        self.e_desc.insert(0, "Cobrança PIX")

        # Selecionar parceiro (escondido)
        self.combo_parc = ttk.Combobox(fc, font=("Segoe UI",10), state="readonly")
        self._refresh_combo()

        # Botão gerar
        self.btn_gerar = tk.Button(p, text="⚡  GERAR PIX",
                                    font=("Segoe UI",13,"bold"),
                                    bg=GREEN, fg=BG, bd=0, cursor="hand2",
                                    activebackground="#00b894",
                                    command=self._gerar)
        self.btn_gerar.pack(fill="x", padx=28, pady=4, ipady=13)

        # Card QR
        qc = self._card(p)
        qc.pack(fill="x", padx=28, pady=4)

        tk.Label(qc, text="QR CODE", font=("Segoe UI",9,"bold"), bg=CARD, fg=GRAY
                 ).pack(pady=(12,0))

        self.lbl_qr = tk.Label(qc, bg=CARD, text="Nenhum QR Code gerado",
                                font=("Segoe UI",10), fg=GRAY)
        self.lbl_qr.pack(pady=20)

        # Pix copia e cola
        self._pix_cc = tk.Frame(qc, bg=CARD)
        tk.Label(self._pix_cc, text="Pix Copia e Cola (Clique no texto para copiar):", font=("Segoe UI",8, "bold"),
                 bg=CARD, fg=GRAY).pack(anchor="w", padx=10)
        self.txt_pix = tk.Entry(self._pix_cc, font=("Consolas",9), bg=BORD, fg=GREEN, bd=0, justify="center")
        self.txt_pix.pack(fill="x", padx=10, pady=(4,10), ipady=8)
        
        # Mágica do clique direto no código para copiar:
        self.txt_pix.bind("<Button-1>", lambda e: self._copiar())
        
        self.btn_copiar = tk.Button(self._pix_cc, text="📋 COPIAR PIX COPIA E COLA", font=("Segoe UI",12, "bold"),
                                     bg=GREEN, fg=BG, bd=0, cursor="hand2",
                                     activebackground="#00b894",
                                     command=self._copiar)
        self.btn_copiar.pack(fill="x", padx=10, pady=(8,10), ipady=8)
        # Status
        sc = self._card(p)
        sc.pack(fill="x", padx=28, pady=4)
        tk.Label(sc, text="STATUS", font=("Segoe UI",8,"bold"), bg=CARD, fg=GRAY
                 ).pack(pady=(10,0))
        self.lbl_status = tk.Label(sc, text="Aguardando geração...",
                                    font=("Segoe UI",13,"bold"), bg=CARD, fg=GRAY)
        self.lbl_status.pack(pady=(2,12))

        self.btn_nova = tk.Button(p, text="Nova Cobrança", font=("Segoe UI",10),
                                   bg=BORD, fg=GRAY, bd=0, cursor="hand2",
                                   command=self._nova)
        # começa escondido

    def _refresh_combo(self):
        nomes = list(CFG["parceiros"].keys())
        self.combo_parc["values"] = nomes
        padrao = CFG.get("nome_parceiro_padrao","admin")
        if padrao in nomes:
            self.combo_parc.set(padrao)
        elif nomes:
            self.combo_parc.set(nomes[0])

    def _gerar(self):
        v = self.e_valor.get().replace(",",".").replace("R$","").strip()
        try:
            valor = float(v); assert valor > 0
        except Exception:
            messagebox.showerror("Erro","Digite um valor válido."); return

        parceiro_nome = self.combo_parc.get()
        chave = CFG["parceiros"].get(parceiro_nome,"")
        if not chave:
            messagebox.showerror("Erro","Selecione um parceiro válido."); return

        desc = self.e_desc.get().strip() or "Cobrança PIX"
        self.btn_gerar.config(state="disabled", text="Gerando...", bg="#555")
        self.lbl_status.config(text="Conectando à SigiloPay...", fg=YELLOW)
        threading.Thread(target=self._req_gerar, args=(valor, desc, chave, parceiro_nome), daemon=True).start()

    def _req_gerar(self, valor, desc, chave, parceiro_nome):
        if not REQUESTS_OK:
            self.after(0, lambda: messagebox.showerror("Erro","Biblioteca 'requests' não instalada.")); return
        try:
            r = _req.post(f"http://127.0.0.1:{CFG['porta']}/gerar_pix",
                          json={"valor": valor, "descricao": desc, "nome_pagador": parceiro_nome},
                          headers={"x-partner-key": chave}, timeout=30)
            try:
                data = r.json()
            except Exception:
                self.after(0, lambda: self._erro(f"Erro Servidor ({r.status_code}): {r.text[:60]}"))
                return
        except Exception as e:
            self.after(0, lambda: self._erro(str(e))); return

        if r.status_code != 200 or not data.get("success"):
            msg = data.get("detail") or str(data)
            self.after(0, lambda: self._erro(msg)); return

        self.after(0, lambda: self._show_qr(data, chave))

    def _show_qr(self, data, chave):
        self._pix_tid = data["transaction_id"]
        qrc = data.get("qr_code","")
        qrt = data.get("qr_text","")

        shown = False
        if qrc and PIL_OK:
            try:
                b64 = qrc.split("base64,")[-1]
                img = Image.open(io.BytesIO(base64.b64decode(b64))).resize((200,200), Image.LANCZOS)
                ph = ImageTk.PhotoImage(img)
                self.lbl_qr.config(image=ph, text=""); self.lbl_qr._ph = ph; shown = True
            except Exception: pass

        if not shown and qrt and QR_OK and PIL_OK:
            try:
                img = _qr.make(qrt).resize((200,200), Image.LANCZOS)
                ph = ImageTk.PhotoImage(img)
                self.lbl_qr.config(image=ph, text=""); self.lbl_qr._ph = ph; shown = True
            except Exception: pass

        if not shown:
            self.lbl_qr.config(text="PIX gerado! Copie o codigo abaixo.", fg=GREEN, image="")

        if qrt:
            self._pix_cc.pack(fill="x", padx=10, pady=(0,8))
            self.txt_pix.config(state="normal")
            self.txt_pix.delete(0,"end")
            self.txt_pix.insert(0, qrt)
            self.txt_pix.config(state="readonly")

        self.lbl_status.config(text="Aguardando pagamento...", fg=YELLOW)
        self.btn_gerar.config(state="disabled", text="Aguardando...", bg="#555")
        self.btn_nova.pack(fill="x", padx=28, pady=4, ipady=8)

        self._polling = True
        threading.Thread(target=self._poll, args=(chave,), daemon=True).start()

    def _poll(self, chave):
        while self._polling and self._pix_tid:
            time.sleep(5)
            if not self._polling: break
            try:
                r = _req.get(f"http://127.0.0.1:{CFG['porta']}/status/{self._pix_tid}",
                             headers={"x-partner-key": chave}, timeout=10)
                if r.json().get("status") == "pago":
                    self._polling = False
                    self.after(0, self._confirmado)
            except Exception: pass

    def _confirmado(self):
        self.lbl_status.config(text="PAGAMENTO CONFIRMADO!", fg=PAID)
        self.lbl_qr.config(text="PAGO!", font=("Segoe UI",24,"bold"), fg=PAID, image="")
        if hasattr(self.lbl_qr,"_ph"): del self.lbl_qr._ph
        self.btn_gerar.config(state="normal", text="⚡  GERAR NOVO PIX", bg=GREEN)
        messagebox.showinfo("Pago!", "Pagamento PIX confirmado com sucesso!")
        self._refresh_table()

    def _erro(self, msg):
        self.lbl_status.config(text=f"Erro: {msg[:60]}", fg=RED)
        self.btn_gerar.config(state="normal", text="⚡  GERAR PIX", bg=GREEN)
        messagebox.showerror("Erro", msg)

    def _copiar(self):
        self.txt_pix.config(state="normal")
        txt = self.txt_pix.get().strip()
        self.txt_pix.config(state="readonly")
        if txt:
            self.clipboard_clear()
            self.clipboard_append(txt)
            self.update()
            
            # Animação botões
            self.btn_copiar.config(text="✔ COPIADO!", bg="#00b894")
            self.after(2000, lambda: self.btn_copiar.config(text="📋 COPIAR PIX COPIA E COLA", bg=GREEN))

    def _nova(self):
        self._polling = False; self._pix_tid = None
        self.e_valor.delete(0,"end"); self.e_valor.insert(0,"0,00")
        self.lbl_qr.config(text="Nenhum QR Code gerado", fg=GRAY, font=("Segoe UI",10), image="")
        if hasattr(self.lbl_qr,"_ph"): del self.lbl_qr._ph
        self._pix_cc.pack_forget()
        self.lbl_status.config(text="Aguardando geração...", fg=GRAY)
        self.btn_gerar.config(state="normal", text="⚡  GERAR PIX", bg=GREEN)
        self.btn_nova.pack_forget()

    # ─── PÁGINA: DASHBOARD ───────────────────────────────────────────────────
    def _pg_dash(self):
        p = tk.Frame(self._area, bg=BG)
        self._pages["dash"] = p

        tk.Label(p, text="Dashboard", font=("Segoe UI",16,"bold"),
                 bg=BG, fg=TEXT).pack(anchor="w", padx=28, pady=(22,4))

        row = tk.Frame(p, bg=BG)
        row.pack(fill="x", padx=28, pady=8)
        self.s_total = self._stat(row, "Total", "0", BLUE)
        self.s_pago  = self._stat(row, "Pagas", "0", PAID)
        self.s_agua  = self._stat(row, "Aguardando", "0", YELLOW)
        self.s_val   = self._stat(row, "Valor Total Pago", "R$ 0,00", GREEN)

        c = self._card(p, "Ultimas cobranças")
        c.pack(fill="both", expand=True, padx=28, pady=(0,20))
        cols = ("ID","Parceiro","Valor","Status","Criado em")
        self.t_dash = ttk.Treeview(c, columns=cols, show="headings", height=12)
        self._style_tree(self.t_dash, cols, [180,120,90,110,160])
        self.t_dash.pack(fill="both", expand=True, padx=8, pady=(0,8))

    def _stat(self, parent, label, val, cor):
        f = tk.Frame(parent, bg=CARD)
        f.configure(highlightbackground=cor, highlightthickness=1)
        f.pack(side="left", fill="both", expand=True, padx=4)
        tk.Label(f, text=label, font=("Segoe UI",8), bg=CARD, fg=GRAY).pack(pady=(10,2))
        lbl = tk.Label(f, text=val, font=("Segoe UI",18,"bold"), bg=CARD, fg=cor)
        lbl.pack(pady=(0,10))
        return lbl

    # ─── PÁGINA: COBRANÇAS ───────────────────────────────────────────────────
    def _clear_history(self):
        if messagebox.askyesno("Confirmar", "Deseja realmente limpar todo o histórico de cobranças?"):
            db_clear()
            self._refresh_table()
            messagebox.showinfo("Sucesso", "Histórico limpo com sucesso.")

    def _pg_cobr(self):

        p = tk.Frame(self._area, bg=BG)
        self._pages["cobr"] = p

        top = tk.Frame(p, bg=BG)
        top.pack(fill="x", padx=28, pady=(22,8))
        tk.Label(top, text="Cobranças", font=("Segoe UI",16,"bold"),
                 bg=BG, fg=TEXT).pack(side="left")
        tk.Button(top, text="Atualizar", font=("Segoe UI",9), bg=CARD, fg=GREEN,
                  bd=0, cursor="hand2", command=self._refresh_table
                  ).pack(side="right", ipady=6, ipadx=12)
        tk.Button(top, text="Limpar Histórico", font=("Segoe UI",9), bg=CARD, fg=RED,
                  bd=0, cursor="hand2", command=self._clear_history
                  ).pack(side="right", padx=10, ipady=6, ipadx=12)


        c = self._card(p)
        c.pack(fill="both", expand=True, padx=28, pady=(0,20))
        cols = ("transaction_id","Parceiro","Valor","Status","Criado em","Pago em")
        self.t_cobr = ttk.Treeview(c, columns=cols, show="headings")
        self._style_tree(self.t_cobr, cols, [200,110,80,100,150,150])
        sb2 = ttk.Scrollbar(c, orient="vertical", command=self.t_cobr.yview)
        self.t_cobr.configure(yscrollcommand=sb2.set)
        self.t_cobr.pack(side="left", fill="both", expand=True, padx=(8,0), pady=8)
        sb2.pack(side="right", fill="y", pady=8, padx=(0,8))

    def _refresh_table(self):
        rows = db_list()

        # stats
        pagos  = [r for r in rows if r.get("status")=="pago"]
        aguard = [r for r in rows if r.get("status")!="pago"]
        total_val = sum(r.get("valor",0) for r in pagos)
        self.s_total.config(text=str(len(rows)))
        self.s_pago.config(text=str(len(pagos)))
        self.s_agua.config(text=str(len(aguard)))
        self.s_val.config(text=f"R$ {total_val:,.2f}".replace(",","X").replace(".",",").replace("X","."))

        # tabela dash
        for it in self.t_dash.get_children(): self.t_dash.delete(it)
        for r in rows[:12]:
            tag = "p" if r["status"]=="pago" else "a"
            self.t_dash.insert("","end", values=(
                (r.get("transaction_id","")[:20]+"..."),
                r.get("parceiro",""), f"R$ {r.get('valor',0):.2f}",
                r.get("status","").upper(), r.get("criado_em","")[:19]
            ), tags=(tag,))
        self.t_dash.tag_configure("p", foreground=PAID)
        self.t_dash.tag_configure("a", foreground=YELLOW)

        # tabela cobranças
        for it in self.t_cobr.get_children(): self.t_cobr.delete(it)
        for r in rows:
            tag = "p" if r["status"]=="pago" else "a"
            self.t_cobr.insert("","end", values=(
                r.get("transaction_id",""), r.get("parceiro",""),
                f"R$ {r.get('valor',0):.2f}", r.get("status","").upper(),
                r.get("criado_em","")[:19], r.get("pago_em","") or "-"
            ), tags=(tag,))
        self.t_cobr.tag_configure("p", foreground=PAID)
        self.t_cobr.tag_configure("a", foreground=YELLOW)

    def _refresh_loop(self):
        self._refresh_table()
        self.after(8000, self._refresh_loop)

    # ─── PÁGINA: PARCEIROS ───────────────────────────────────────────────────
    def _pg_parc(self):
        p = tk.Frame(self._area, bg=BG)
        self._pages["parc"] = p

        top = tk.Frame(p, bg=BG)
        top.pack(fill="x", padx=28, pady=(22,4))
        tk.Label(top, text="Parceiros & Chaves", font=("Segoe UI",16,"bold"),
                 bg=BG, fg=TEXT).pack(side="left")
        tf = tk.Frame(top, bg=BG); tf.pack(side="right")
        tk.Button(tf, text="+ Novo", font=("Segoe UI",9,"bold"),
                  bg=GREEN, fg=BG, bd=0, cursor="hand2",
                  command=self._novo_parc).pack(side="left", padx=4, ipady=6, ipadx=10)
        tk.Button(tf, text="Remover", font=("Segoe UI",9),
                  bg=RED, fg=TEXT, bd=0, cursor="hand2",
                  command=self._del_parc).pack(side="left", padx=4, ipady=6, ipadx=10)

        tk.Label(p, text="Envie a chave de acesso para cada parceiro. Eles usam no app cliente.",
                 font=("Segoe UI",9), bg=BG, fg=GRAY).pack(anchor="w", padx=28, pady=(0,8))

        c = self._card(p)
        c.pack(fill="both", expand=True, padx=28, pady=(0,20))
        cols = ("Nome","Chave de Acesso","Status")
        self.t_parc = ttk.Treeview(c, columns=cols, show="headings", height=14)
        self._style_tree(self.t_parc, cols, [180,420,100])
        self.t_parc.pack(fill="both", expand=True, padx=8, pady=8)
        self._refresh_parc()

    def _refresh_parc(self):
        for it in self.t_parc.get_children(): self.t_parc.delete(it)
        for nome, chave in CFG["parceiros"].items():
            tag = "adm" if nome=="admin" else "norm"
            self.t_parc.insert("","end", values=(nome, chave, "ATIVO"), tags=(tag,))
        self.t_parc.tag_configure("adm", foreground=GREEN)
        self.t_parc.tag_configure("norm", foreground=TEXT)

    def _novo_parc(self):
        nome = simpledialog.askstring("Novo Parceiro","Nome do parceiro:", parent=self)
        if not nome or not nome.strip(): return
        nome = nome.strip()
        chave = secrets.token_hex(18)
        CFG["parceiros"][nome] = chave
        save_cfg(CFG)
        self._refresh_parc()
        self._refresh_combo()
        messagebox.showinfo("Parceiro Criado",
            f"Nome: {nome}\nChave: {chave}\n\nEnvie essa chave para o parceiro.")

    def _del_parc(self):
        sel = self.t_parc.selection()
        if not sel: messagebox.showwarning("Aviso","Selecione um parceiro."); return
        nome = self.t_parc.item(sel[0])["values"][0]
        if nome == "admin": messagebox.showerror("Erro","Não é possível remover o admin."); return
        if messagebox.askyesno("Confirmar", f"Remover '{nome}'?"):
            del CFG["parceiros"][nome]; save_cfg(CFG)
            self._refresh_parc(); self._refresh_combo()

    # ─── PÁGINA: USUÁRIOS ADMIN ──────────────────────────────────────────────
    def _pg_users(self):
        p = tk.Frame(self._area, bg=BG)
        self._pages["users"] = p

        top = tk.Frame(p, bg=BG)
        top.pack(fill="x", padx=28, pady=(22,4))
        tk.Label(top, text="Usuários do Painel", font=("Segoe UI",16,"bold"), bg=BG, fg=TEXT).pack(side="left")
        
        tf = tk.Frame(top, bg=BG); tf.pack(side="right")
        tk.Button(tf, text="+ Novo", font=("Segoe UI",9,"bold"), bg=GREEN, fg=BG, bd=0, cursor="hand2", command=self._novo_user).pack(side="left", padx=4, ipady=6, ipadx=10)

        tk.Label(p, text="Gerencie quem pode fazer login neste app.", font=("Segoe UI",9), bg=BG, fg=GRAY).pack(anchor="w", padx=28, pady=(0,8))

        card = self._card(p)
        card.pack(fill="both", expand=True, padx=28, pady=(0,20))
        self.users_container = tk.Frame(card, bg=CARD)
        self.users_container.pack(fill="both", expand=True, padx=10, pady=10)


        
        self._refresh_users()

    def _refresh_users(self):
        for widget in self.users_container.winfo_children():
            widget.destroy()

        users = get_admin_users()
        
        # Cabeçalho
        hdr = tk.Frame(self.users_container, bg=CARD)
        hdr.pack(fill="x", pady=5)
        tk.Label(hdr, text="Login do Usuário", font=("Segoe UI", 10, "bold"), bg=CARD, fg=GRAY, width=25, anchor="w").pack(side="left", padx=10)
        tk.Label(hdr, text="Senha", font=("Segoe UI", 10, "bold"), bg=CARD, fg=GRAY, width=25, anchor="w").pack(side="left", padx=10)
        tk.Frame(self.users_container, bg=BORD, height=1).pack(fill="x", pady=2)

        for usr, pwd in users.items():
            row = tk.Frame(self.users_container, bg=CARD)
            row.pack(fill="x", pady=4)
            
            tk.Label(row, text=usr, font=("Segoe UI", 10), bg=CARD, fg=TEXT, width=25, anchor="w").pack(side="left", padx=10)
            tk.Label(row, text=pwd, font=("Segoe UI", 10), bg=CARD, fg=TEXT, width=25, anchor="w").pack(side="left", padx=10)
            
            btn_del = tk.Button(row, text="🗑 Excluir", font=("Segoe UI", 9, "bold"), bg=RED, fg=TEXT, bd=0, cursor="hand2",
                                command=lambda u=usr: self._del_user(u))
            btn_del.pack(side="right", padx=10, ipady=4, ipadx=8)

    def _novo_user(self):
        usr = simpledialog.askstring("Novo Usuário", "Login do Usuário:", parent=self)
        if not usr or not usr.strip(): return
        usr = usr.strip()
        pwd = simpledialog.askstring("Novo Usuário", "Senha para o Usuário:", parent=self)
        if not pwd or not pwd.strip(): return
        
        set_admin_user(usr, pwd.strip())
        self._refresh_users()
        messagebox.showinfo("Sucesso", f"Usuário '{usr}' cadastrado com sucesso.")

    def _del_user(self, usr):
        users = get_admin_users()
        if len(users) <= 1:
            messagebox.showerror("Erro", "Você não pode remover o único usuário do sistema.")
            return
            
        if messagebox.askyesno("Confirmar", f"Tem certeza que deseja remover o usuário '{usr}'?"):
            del_admin_user(usr)
            self._refresh_users()

    # ─── PÁGINA: CONFIGURAÇÕES ───────────────────────────────────────────────
    def _pg_cfg(self):
        p = tk.Frame(self._area, bg=BG)
        self._pages["cfg"] = p

        tk.Label(p, text="Configurações", font=("Segoe UI",16,"bold"),
                 bg=BG, fg=TEXT).pack(anchor="w", padx=28, pady=(22,4))

        c = self._card(p, "Credenciais SigiloPay")
        c.pack(fill="x", padx=28, pady=8)

        self._cfg_ent = {}
        campos = [
            ("public_key",  "API < R$ 1000: Public Key"),
            ("secret_key",  "API < R$ 1000: Secret Key"),
            ("api_base",    "API < R$ 1000: URL Base"),
            ("spacer",      "--- ACIMA DE R$ 1000 ---"),
            ("public_key_above", "API >= R$ 1000: Public Key"),
            ("secret_key_above", "API >= R$ 1000: Secret Key"),
            ("api_base_above",   "API >= R$ 1000: URL Base"),
            ("spacer2",      "--- CONFIGS GERAIS ---"),
            ("webhook_url", "URL do Webhook (ngrok/dominio)"),
            ("porta",       "Porta do Servidor"),
            ("nome_parceiro_padrao", "Parceiro padrão"),
            ("spacer3",      "--- TELEGRAM BOT ---"),
            ("telegram_token", "Token do Bot (BotFather)"),
            ("telegram_admin_id", "ID do Administrador (User ID)"),
        ]
        for key, label in campos:

            if "spacer" in key:
                tk.Label(c, text=label, font=("Segoe UI", 9, "bold"), bg=CARD, fg=GREEN).pack(fill="x", padx=12, pady=(10, 2))
                continue

            row = tk.Frame(c, bg=CARD)
            row.pack(fill="x", padx=12, pady=3)
            tk.Label(row, text=label, width=36, anchor="w",
                     font=("Segoe UI",9), bg=CARD, fg=GRAY).pack(side="left")
            e = tk.Entry(row, font=("Segoe UI",10), bg=BORD, fg=TEXT, bd=0,
                         insertbackground=GREEN, width=45)
            e.pack(side="left", ipady=6, padx=4, fill="x", expand=True)
            e.insert(0, str(CFG.get(key,"")))
            if "secret_key" in key or "token" in key: e.config(show="*")
            self._cfg_ent[key] = e


        tk.Button(c, text="Salvar Configurações", font=("Segoe UI",10,"bold"),
                  bg=GREEN, fg=BG, bd=0, cursor="hand2",
                  command=self._salvar_cfg
                  ).pack(padx=12, pady=14, ipady=8, ipadx=16, anchor="w")

        info = self._card(p, "Como usar ngrok (expor servidor)")
        info.pack(fill="x", padx=28, pady=8)
        tk.Label(info,
                 text="1. Baixe ngrok em: https://ngrok.com/download\n"
                      "2. Execute: ngrok http 8000\n"
                      "3. Copie a URL (ex: https://abc123.ngrok.io)\n"
                      "4. Cole em 'URL do Webhook' acima e salve\n"
                      "5. Reinicie o servidor para aplicar",
                 font=("Consolas",9), bg=CARD, fg=GRAY, justify="left"
                 ).pack(padx=12, pady=8, anchor="w")

    def _salvar_cfg(self):
        for k, e in self._cfg_ent.items():
            v = e.get().strip()
            CFG[k] = int(v) if k == "porta" and v.isdigit() else v
        save_cfg(CFG)
        self._refresh_combo()
        messagebox.showinfo("Salvo","Configurações salvas!\nReinicie para aplicar mudanças de porta.")

    # ─── PÁGINA: LOGS ────────────────────────────────────────────────────────
    def _pg_logs(self):
        p = tk.Frame(self._area, bg=BG)
        self._pages["logs"] = p

        top = tk.Frame(p, bg=BG)
        top.pack(fill="x", padx=28, pady=(22,4))
        tk.Label(top, text="Logs do Servidor", font=("Segoe UI",16,"bold"),
                 bg=BG, fg=TEXT).pack(side="left")
        tk.Button(top, text="Limpar", font=("Segoe UI",9), bg=CARD, fg=GRAY,
                  bd=0, cursor="hand2", command=self._limpar_log
                  ).pack(side="right", ipady=6, ipadx=8)

        c = self._card(p)
        c.pack(fill="both", expand=True, padx=28, pady=(0,20))
        self.txt_log = tk.Text(c, font=("Consolas",9), bg=DARK, fg=PAID,
                                bd=0, state="disabled", insertbackground=GREEN)
        sb3 = ttk.Scrollbar(c, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=sb3.set)
        self.txt_log.pack(side="left", fill="both", expand=True, padx=(8,0), pady=8)
        sb3.pack(side="right", fill="y", pady=8, padx=(0,8))

    def _log(self, msg):
        self._logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        if len(self._logs) > 500: self._logs = self._logs[-500:]
        try:
            self.txt_log.config(state="normal")
            self.txt_log.delete("1.0","end")
            self.txt_log.insert("end", "\n".join(self._logs))
            self.txt_log.see("end")
            self.txt_log.config(state="disabled")
        except Exception: pass

    def _limpar_log(self):
        self._logs.clear()
        try:
            self.txt_log.config(state="normal")
            self.txt_log.delete("1.0","end")
            self.txt_log.config(state="disabled")
        except Exception: pass

    # ─── HELPERS ─────────────────────────────────────────────────────────────
    def _card(self, parent, title=""):
        f = tk.Frame(parent, bg=CARD)
        f.configure(highlightbackground=BORD, highlightthickness=1)
        if title:
            tk.Label(f, text=title, font=("Segoe UI",9,"bold"),
                     bg=CARD, fg=GRAY).pack(anchor="w", padx=12, pady=(10,2))
        return f

    def _style_tree(self, tree, cols, widths=None):
        s = ttk.Style()
        s.theme_use("default")
        s.configure("Treeview", background=CARD, foreground=TEXT,
                    fieldbackground=CARD, rowheight=28, font=("Segoe UI",9))
        s.configure("Treeview.Heading", background=BORD, foreground=GRAY,
                    font=("Segoe UI",9,"bold"))
        s.map("Treeview", background=[("selected", BORD)])
        for i, col in enumerate(cols):
            w = widths[i] if widths and i < len(widths) else 120
            tree.heading(col, text=col)
            tree.column(col, width=w, minwidth=50, anchor="w")

    def _close(self):
        self._polling = False
        self.destroy()

    def _logout(self):
        self._polling = False
        if hasattr(self, "sb"): self.sb.destroy()
        if hasattr(self, "_area"): self._area.destroy()
        self._login_screen()

# ─────────────────────────── ENTRY POINT ─────────────────────────────────────
if __name__ == "__main__":
    App().mainloop()
