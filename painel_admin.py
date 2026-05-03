"""
SIGILO PAY - PAINEL ADMINISTRATIVO (EXE)
=========================================
Interface grafica completa para o dono do sistema.
Roda o servidor FastAPI internamente, sem precisar de terminal.

Funcionalidades:
  - Ligar/Desligar servidor com 1 clique
  - Ver logs ao vivo
  - Ver todas as cobranças em tempo real
  - Gerenciar chaves de parceiros
  - Configurar credenciais SigiloPay
  - Configurar URL do servidor (ngrok etc.)
"""

import sys
import os
import threading
import time
import json
import sqlite3
import subprocess
import socket
import webbrowser
import io
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime

# Adiciona pasta do servidor ao path se rodando como EXE
BASE_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
SERVER_DIR = os.path.join(BASE_DIR, "servidor")
if os.path.exists(SERVER_DIR):
    sys.path.insert(0, SERVER_DIR)
else:
    sys.path.insert(0, BASE_DIR)

CONFIG_FILE = os.path.join(BASE_DIR, "painel_config.json")

# ─── CONFIGURAÇÃO PADRÃO ─────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "public_key":  "laispereiraphoto_2s0vatrdx6coy3pp",
    "secret_key":  "kqkjdw66o0hv37gz2w4n15m5thp0w2jv6txe1k4ss7354169260wdpqegta7en2v",
    "api_base":    "https://app.sigilopay.com.br",
    "porta":       8000,
    "webhook_url": "http://localhost:8000",
    "parceiros": {
        "admin":     "admin_master_key_123",
        "parceiro1": "chave_parceiro1_aqui",
        "parceiro2": "chave_parceiro2_aqui"
    }
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
                # Garante que todas as chaves existam
                for k, v in DEFAULT_CONFIG.items():
                    cfg.setdefault(k, v)
                return cfg
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

# ─── CORES ───────────────────────────────────────────────────────────────────
C_BG        = "#0a0e1a"
C_CARD      = "#141824"
C_BORDER    = "#1e2538"
C_GREEN     = "#00d4aa"
C_YELLOW    = "#ffd700"
C_RED       = "#ff4444"
C_BLUE      = "#4a9eff"
C_TEXT      = "#e8eaf0"
C_GRAY      = "#8892b0"
C_DARKGRAY  = "#1e2538"
C_PAID      = "#00ff88"

# ─── SERVIDOR THREAD ─────────────────────────────────────────────────────────
_server_process = None
_server_running = False

def _write_server_files(cfg):
    """Gera os arquivos do servidor dinamicamente com as configs atuais."""
    os.makedirs(SERVER_DIR, exist_ok=True)

    config_py = f'''# AUTO-GERADO PELO PAINEL - NAO EDITE MANUALMENTE
SIGILO_PUBLIC_KEY = "{cfg["public_key"]}"
SIGILO_SECRET_KEY = "{cfg["secret_key"]}"
SIGILO_API_BASE   = "{cfg["api_base"]}"
WEBHOOK_BASE_URL  = "{cfg["webhook_url"]}"
PARTNER_KEYS      = {json.dumps(cfg["parceiros"], indent=4)}
DATABASE_URL      = "sqlite:///./sigilo_pay.db"
'''
    with open(os.path.join(SERVER_DIR, "config.py"), "w", encoding="utf-8") as f:
        f.write(config_py)


# ─── APP PRINCIPAL ───────────────────────────────────────────────────────────
class PainelAdmin(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SigiloPay - Painel Admin")
        self.geometry("1000x680")
        self.minsize(900, 600)
        self.configure(bg=C_BG)

        self.cfg = load_config()
        self._server_proc = None
        self._server_running = False
        self._log_lines = []

        self._build_ui()
        self._check_db_path()
        self.after(500, self._atualizar_lista)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─────────────────────────────────────────────────────────────────────────
    def _check_db_path(self):
        """Define onde fica o banco de dados."""
        self.db_path = os.path.join(SERVER_DIR, "sigilo_pay.db")

    def _get_cobranças(self):
        if not os.path.exists(self.db_path):
            return []
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM 'cobran\u00e7as' ORDER BY id DESC LIMIT 200")
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        except Exception:
            return []

    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # === SIDEBAR ===
        sidebar = tk.Frame(self, bg=C_CARD, width=200)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="SIGILO", font=("Segoe UI", 16, "bold"),
                 bg=C_CARD, fg=C_GREEN).pack(pady=(20, 0))
        tk.Label(sidebar, text="PAY ADMIN", font=("Segoe UI", 10),
                 bg=C_CARD, fg=C_GRAY).pack(pady=(0, 20))

        tk.Frame(sidebar, bg=C_BORDER, height=1).pack(fill="x", padx=12)

        # Status do servidor
        self.lbl_srv_dot = tk.Label(sidebar, text="  SERVIDOR OFF",
                                     font=("Segoe UI", 9, "bold"),
                                     bg=C_CARD, fg=C_RED)
        self.lbl_srv_dot.pack(pady=(16, 4))

        self.btn_servidor = tk.Button(
            sidebar, text="LIGAR SERVIDOR",
            font=("Segoe UI", 10, "bold"),
            bg=C_GREEN, fg=C_BG, bd=0, cursor="hand2",
            activebackground="#00b894",
            command=self._toggle_servidor
        )
        self.btn_servidor.pack(fill="x", padx=16, ipady=10)

        tk.Frame(sidebar, bg=C_BORDER, height=1).pack(fill="x", padx=12, pady=16)

        # Navegação
        self.nav_buttons = {}
        for nome, label in [("dash", "  Dashboard"), ("cobranças", "  Cobranças"), 
                              ("parceiros", "  Parceiros"), ("config", "  Configuracoes"),
                              ("logs", "  Logs")]:
            btn = tk.Button(sidebar, text=label,
                            font=("Segoe UI", 10), bd=0, cursor="hand2",
                            bg=C_CARD, fg=C_GRAY, anchor="w",
                            activebackground=C_BORDER,
                            command=lambda n=nome: self._show_page(n))
            btn.pack(fill="x", padx=8, pady=2, ipady=8)
            self.nav_buttons[nome] = btn

        # Porta
        tk.Frame(sidebar, bg=C_BORDER, height=1).pack(fill="x", padx=12, pady=8)
        self.lbl_porta = tk.Label(sidebar, text=f"Porta: {self.cfg['porta']}",
                                   font=("Segoe UI", 8), bg=C_CARD, fg=C_GRAY)
        self.lbl_porta.pack()
        tk.Button(sidebar, text="Abrir no Browser", font=("Segoe UI", 8),
                  bg=C_CARD, fg=C_BLUE, bd=0, cursor="hand2",
                  command=lambda: webbrowser.open(f"http://localhost:{self.cfg['porta']}/docs")
                  ).pack(pady=4)

        # === CONTEÚDO PRINCIPAL ===
        self.main_area = tk.Frame(self, bg=C_BG)
        self.main_area.pack(side="left", fill="both", expand=True)

        # Páginas
        self.pages = {}
        self._build_page_dash()
        self._build_page_cobranças()
        self._build_page_parceiros()
        self._build_page_config()
        self._build_page_logs()

        self._show_page("dash")

    # ─────────────────────────── PAGES ───────────────────────────────────────

    def _show_page(self, name):
        for n, frame in self.pages.items():
            frame.pack_forget()
        for n, btn in self.nav_buttons.items():
            btn.config(bg=C_CARD if n != name else C_BORDER, fg=C_GRAY if n != name else C_TEXT)
        self.pages[name].pack(fill="both", expand=True)
        if name == "cobranças":
            self._atualizar_lista()
        if name == "logs":
            self._refresh_logs()

    def _card(self, parent, title="", **kwargs):
        f = tk.Frame(parent, bg=C_CARD, **kwargs)
        f.configure(highlightbackground=C_BORDER, highlightthickness=1)
        if title:
            tk.Label(f, text=title, font=("Segoe UI", 9, "bold"),
                     bg=C_CARD, fg=C_GRAY).pack(anchor="w", padx=12, pady=(10, 2))
        return f

    # --- DASHBOARD ---
    def _build_page_dash(self):
        page = tk.Frame(self.main_area, bg=C_BG)
        self.pages["dash"] = page

        tk.Label(page, text="Dashboard", font=("Segoe UI", 16, "bold"),
                 bg=C_BG, fg=C_TEXT).pack(anchor="w", padx=24, pady=(20, 4))
        tk.Label(page, text="Resumo das operacoes em tempo real",
                 font=("Segoe UI", 9), bg=C_BG, fg=C_GRAY).pack(anchor="w", padx=24)

        # Cards de estatísticas
        stats_row = tk.Frame(page, bg=C_BG)
        stats_row.pack(fill="x", padx=24, pady=16)

        self.stat_total   = self._stat_card(stats_row, "Total de Cobranças", "0", C_BLUE)
        self.stat_pago    = self._stat_card(stats_row, "Pagas", "0", C_PAID)
        self.stat_aguard  = self._stat_card(stats_row, "Aguardando", "0", C_YELLOW)
        self.stat_valor   = self._stat_card(stats_row, "Valor Total Pago", "R$ 0,00", C_GREEN)

        # Últimas cobranças (mini tabela)
        card = self._card(page, "Ultimas cobranças")
        card.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        cols = ("ID", "Parceiro", "Valor", "Status", "Criado em")
        self.tree_dash = ttk.Treeview(card, columns=cols, show="headings", height=10)
        self._estilizar_tree(self.tree_dash, cols, [80, 120, 100, 120, 160])
        self.tree_dash.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.after(3000, self._auto_refresh_dash)

    def _stat_card(self, parent, label, value, color):
        f = tk.Frame(parent, bg=C_CARD)
        f.configure(highlightbackground=color, highlightthickness=1)
        f.pack(side="left", fill="both", expand=True, padx=4)
        tk.Label(f, text=label, font=("Segoe UI", 8), bg=C_CARD, fg=C_GRAY).pack(pady=(10, 2))
        lbl = tk.Label(f, text=value, font=("Segoe UI", 18, "bold"), bg=C_CARD, fg=color)
        lbl.pack(pady=(0, 10))
        return lbl

    def _auto_refresh_dash(self):
        self._update_dash_stats()
        self.after(5000, self._auto_refresh_dash)

    def _update_dash_stats(self):
        rows = self._get_cobranças()
        total = len(rows)
        pagos = [r for r in rows if r.get("status") == "pago"]
        aguard = [r for r in rows if r.get("status") != "pago"]
        valor_total = sum(r.get("valor", 0) for r in pagos)

        self.stat_total.config(text=str(total))
        self.stat_pago.config(text=str(len(pagos)))
        self.stat_aguard.config(text=str(len(aguard)))
        self.stat_valor.config(text=f"R$ {valor_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

        # Atualiza mini tabela
        for item in self.tree_dash.get_children():
            self.tree_dash.delete(item)
        for r in rows[:10]:
            tag = "pago" if r.get("status") == "pago" else "aguard"
            self.tree_dash.insert("", "end", values=(
                r.get("transaction_id", "")[:16] + "...",
                r.get("parceiro", ""),
                f"R$ {r.get('valor', 0):.2f}",
                r.get("status", "").upper(),
                r.get("criado_em", "")[:19]
            ), tags=(tag,))
        self.tree_dash.tag_configure("pago", foreground=C_PAID)
        self.tree_dash.tag_configure("aguard", foreground=C_YELLOW)

    # --- COBRANÇAS ---
    def _build_page_cobranças(self):
        page = tk.Frame(self.main_area, bg=C_BG)
        self.pages["cobranças"] = page

        top = tk.Frame(page, bg=C_BG)
        top.pack(fill="x", padx=24, pady=(20, 8))
        tk.Label(top, text="Cobranças", font=("Segoe UI", 16, "bold"),
                 bg=C_BG, fg=C_TEXT).pack(side="left")
        tk.Button(top, text="  Atualizar", font=("Segoe UI", 9),
                  bg=C_CARD, fg=C_GREEN, bd=0, cursor="hand2",
                  command=self._atualizar_lista).pack(side="right", padx=4, ipady=6, ipadx=8)

        card = self._card(page)
        card.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        cols = ("transaction_id", "Parceiro", "Valor", "Status", "Criado em", "Pago em")
        self.tree_cobr = ttk.Treeview(card, columns=cols, show="headings")
        self._estilizar_tree(self.tree_cobr, cols, [200, 110, 90, 100, 160, 160])

        sb = ttk.Scrollbar(card, orient="vertical", command=self.tree_cobr.yview)
        self.tree_cobr.configure(yscrollcommand=sb.set)
        self.tree_cobr.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        sb.pack(side="right", fill="y", pady=8, padx=(0, 8))

    def _atualizar_lista(self):
        try:
            for item in self.tree_cobr.get_children():
                self.tree_cobr.delete(item)
        except Exception:
            return
        rows = self._get_cobranças()
        for r in rows:
            tag = "pago" if r.get("status") == "pago" else "aguard"
            self.tree_cobr.insert("", "end", values=(
                r.get("transaction_id", ""),
                r.get("parceiro", ""),
                f"R$ {r.get('valor', 0):.2f}",
                r.get("status", "").upper(),
                r.get("criado_em", "")[:19],
                r.get("pago_em", "") or "-"
            ), tags=(tag,))
        self.tree_cobr.tag_configure("pago", foreground=C_PAID)
        self.tree_cobr.tag_configure("aguard", foreground=C_YELLOW)
        self._update_dash_stats()

    # --- PARCEIROS ---
    def _build_page_parceiros(self):
        page = tk.Frame(self.main_area, bg=C_BG)
        self.pages["parceiros"] = page

        top = tk.Frame(page, bg=C_BG)
        top.pack(fill="x", padx=24, pady=(20, 8))
        tk.Label(top, text="Parceiros & Chaves de Acesso", font=("Segoe UI", 16, "bold"),
                 bg=C_BG, fg=C_TEXT).pack(side="left")

        btns = tk.Frame(top, bg=C_BG)
        btns.pack(side="right")
        tk.Button(btns, text="+  Novo Parceiro", font=("Segoe UI", 9, "bold"),
                  bg=C_GREEN, fg=C_BG, bd=0, cursor="hand2",
                  command=self._novo_parceiro).pack(side="left", padx=4, ipady=6, ipadx=10)
        tk.Button(btns, text="  Remover", font=("Segoe UI", 9),
                  bg=C_RED, fg=C_TEXT, bd=0, cursor="hand2",
                  command=self._remover_parceiro).pack(side="left", padx=4, ipady=6, ipadx=10)

        tk.Label(page, text="Cada parceiro usa sua chave no app client. Copie e envie para eles.",
                 font=("Segoe UI", 9), bg=C_BG, fg=C_GRAY).pack(anchor="w", padx=24, pady=(0, 8))

        card = self._card(page)
        card.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        cols = ("Nome", "Chave de Acesso", "Status")
        self.tree_parc = ttk.Treeview(card, columns=cols, show="headings", height=15)
        self._estilizar_tree(self.tree_parc, cols, [200, 400, 100])
        self.tree_parc.pack(fill="both", expand=True, padx=8, pady=8)
        self._refresh_parceiros()

    def _refresh_parceiros(self):
        for item in self.tree_parc.get_children():
            self.tree_parc.delete(item)
        for nome, chave in self.cfg["parceiros"].items():
            tag = "admin" if nome == "admin" else "normal"
            self.tree_parc.insert("", "end", values=(nome, chave, "ATIVO"), tags=(tag,))
        self.tree_parc.tag_configure("admin", foreground=C_GREEN)
        self.tree_parc.tag_configure("normal", foreground=C_TEXT)

    def _novo_parceiro(self):
        nome = simpledialog.askstring("Novo Parceiro", "Nome do parceiro:", parent=self)
        if not nome:
            return
        import secrets
        chave = secrets.token_hex(16)
        self.cfg["parceiros"][nome] = chave
        save_config(self.cfg)
        self._refresh_parceiros()
        messagebox.showinfo("Parceiro Criado",
                            f"Parceiro: {nome}\nChave: {chave}\n\nEnvie essa chave para o parceiro.")

    def _remover_parceiro(self):
        sel = self.tree_parc.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecione um parceiro para remover.")
            return
        item = self.tree_parc.item(sel[0])
        nome = item["values"][0]
        if nome == "admin":
            messagebox.showerror("Erro", "Nao e possivel remover o admin.")
            return
        if messagebox.askyesno("Confirmar", f"Remover parceiro '{nome}'?"):
            del self.cfg["parceiros"][nome]
            save_config(self.cfg)
            self._refresh_parceiros()

    # --- CONFIGURAÇÕES ---
    def _build_page_config(self):
        page = tk.Frame(self.main_area, bg=C_BG)
        self.pages["config"] = page

        tk.Label(page, text="Configuracoes", font=("Segoe UI", 16, "bold"),
                 bg=C_BG, fg=C_TEXT).pack(anchor="w", padx=24, pady=(20, 4))

        card = self._card(page, "Credenciais SigiloPay")
        card.pack(fill="x", padx=24, pady=8)

        self.cfg_entries = {}
        campos = [
            ("public_key", "Public Key (x-public-key)"),
            ("secret_key", "Secret Key (x-secret-key)"),
            ("api_base",   "URL Base da API SigiloPay"),
            ("webhook_url","URL do Webhook (seu servidor publico)"),
            ("porta",      "Porta do Servidor"),
        ]
        for key, label in campos:
            row = tk.Frame(card, bg=C_CARD)
            row.pack(fill="x", padx=12, pady=4)
            tk.Label(row, text=label, width=30, anchor="w",
                     font=("Segoe UI", 9), bg=C_CARD, fg=C_GRAY).pack(side="left")
            entry = tk.Entry(row, font=("Segoe UI", 10), bg=C_DARKGRAY,
                             fg=C_TEXT, bd=0, insertbackground=C_GREEN, width=50)
            entry.pack(side="left", ipady=6, padx=4, fill="x", expand=True)
            entry.insert(0, str(self.cfg.get(key, "")))
            if key == "secret_key":
                entry.config(show="*")
            self.cfg_entries[key] = entry

        tk.Button(card, text="Salvar Configuracoes",
                  font=("Segoe UI", 10, "bold"),
                  bg=C_GREEN, fg=C_BG, bd=0, cursor="hand2",
                  command=self._salvar_config).pack(padx=12, pady=12, ipady=8, ipadx=16, anchor="w")

        # Instrução ngrok
        info = self._card(page, "Como expor o servidor para a internet (ngrok)")
        info.pack(fill="x", padx=24, pady=8)

        instrucoes = (
            "1. Baixe o ngrok em: https://ngrok.com/download\n"
            "2. Abra o terminal e rode: ngrok http 8000\n"
            "3. Copie a URL gerada (ex: https://abc123.ngrok.io)\n"
            "4. Cole em 'URL do Webhook' acima e salve.\n"
            "5. Use essa mesma URL no app dos parceiros (SERVIDOR_URL)."
        )
        tk.Label(info, text=instrucoes, font=("Consolas", 9),
                 bg=C_CARD, fg=C_GRAY, justify="left").pack(padx=12, pady=8, anchor="w")

    def _salvar_config(self):
        for key, entry in self.cfg_entries.items():
            val = entry.get().strip()
            if key == "porta":
                try:
                    val = int(val)
                except Exception:
                    val = 8000
            self.cfg[key] = val
        save_config(self.cfg)
        self.lbl_porta.config(text=f"Porta: {self.cfg['porta']}")
        messagebox.showinfo("Salvo", "Configuracoes salvas com sucesso!")

    # --- LOGS ---
    def _build_page_logs(self):
        page = tk.Frame(self.main_area, bg=C_BG)
        self.pages["logs"] = page

        top = tk.Frame(page, bg=C_BG)
        top.pack(fill="x", padx=24, pady=(20, 4))
        tk.Label(top, text="Logs do Servidor", font=("Segoe UI", 16, "bold"),
                 bg=C_BG, fg=C_TEXT).pack(side="left")
        tk.Button(top, text="Limpar", font=("Segoe UI", 9),
                  bg=C_CARD, fg=C_GRAY, bd=0, cursor="hand2",
                  command=self._limpar_logs).pack(side="right", ipady=6, ipadx=8)

        card = self._card(page)
        card.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        self.txt_logs = tk.Text(card, font=("Consolas", 9), bg="#0d1117",
                                 fg="#00ff88", bd=0, state="disabled",
                                 insertbackground=C_GREEN)
        sb = ttk.Scrollbar(card, orient="vertical", command=self.txt_logs.yview)
        self.txt_logs.configure(yscrollcommand=sb.set)
        self.txt_logs.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        sb.pack(side="right", fill="y", pady=8, padx=(0, 8))

    def _add_log(self, linha):
        self._log_lines.append(f"[{datetime.now().strftime('%H:%M:%S')}] {linha}")
        if len(self._log_lines) > 500:
            self._log_lines = self._log_lines[-500:]
        self._refresh_logs()

    def _refresh_logs(self):
        try:
            self.txt_logs.config(state="normal")
            self.txt_logs.delete("1.0", "end")
            self.txt_logs.insert("end", "\n".join(self._log_lines))
            self.txt_logs.see("end")
            self.txt_logs.config(state="disabled")
        except Exception:
            pass

    def _limpar_logs(self):
        self._log_lines.clear()
        self._refresh_logs()

    # ─────────────────────────── SERVIDOR ────────────────────────────────────

    def _toggle_servidor(self):
        if self._server_running:
            self._stop_server()
        else:
            self._start_server()

    def _start_server(self):
        _write_server_files(self.cfg)
        porta = self.cfg.get("porta", 8000)

        self._add_log(f"Iniciando servidor na porta {porta}...")
        self.btn_servidor.config(state="disabled", text="Ligando...", bg=C_YELLOW)

        threading.Thread(target=self._run_server, args=(porta,), daemon=True).start()

    def _run_server(self, porta):
        import uvicorn
        import importlib
        import main as server_main
        importlib.reload(server_main)

        self._server_running = True
        self.after(0, lambda: self._on_server_started(porta))

        try:
            uvicorn.run(
                server_main.app,
                host="0.0.0.0",
                port=int(porta),
                log_level="info",
                access_log=False
            )
        except Exception as e:
            self._server_running = False
            self.after(0, lambda: self._add_log(f"ERRO: {e}"))
            self.after(0, self._on_server_stopped)

    def _on_server_started(self, porta):
        self._server_running = True
        self.btn_servidor.config(state="normal", text="DESLIGAR SERVIDOR", bg=C_RED)
        self.lbl_srv_dot.config(text=f"  ONLINE :{porta}", fg=C_GREEN)
        self._add_log(f"Servidor ONLINE em http://localhost:{porta}")
        self._add_log(f"Docs: http://localhost:{porta}/docs")

    def _stop_server(self):
        # Uvicorn não expõe um stop limpo; reiniciamos o processo
        self._server_running = False
        self.btn_servidor.config(state="normal", text="LIGAR SERVIDOR", bg=C_GREEN)
        self.lbl_srv_dot.config(text="  SERVIDOR OFF", fg=C_RED)
        self._add_log("Servidor desligado.")
        messagebox.showinfo("Servidor", "O servidor sera desligado ao fechar o painel.\nReinicie o painel para usar novamente.")

    def _on_server_stopped(self):
        self.btn_servidor.config(state="normal", text="LIGAR SERVIDOR", bg=C_GREEN)
        self.lbl_srv_dot.config(text="  SERVIDOR OFF", fg=C_RED)

    # ─────────────────────────── HELPERS ─────────────────────────────────────

    def _estilizar_tree(self, tree, colunas, larguras=None):
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background=C_CARD, foreground=C_TEXT,
                        fieldbackground=C_CARD, rowheight=28,
                        font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background=C_DARKGRAY,
                        foreground=C_GRAY, font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", C_BORDER)])

        for i, col in enumerate(colunas):
            larg = larguras[i] if larguras and i < len(larguras) else 120
            tree.heading(col, text=col)
            tree.column(col, width=larg, minwidth=60, anchor="w")

    def _on_close(self):
        self._server_running = False
        self.destroy()


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = PainelAdmin()
    app.mainloop()
