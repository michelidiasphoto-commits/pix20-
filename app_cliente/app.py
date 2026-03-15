"""
SIGILO PAY - APLICATIVO DO PARCEIRO
====================================
Interface desktop para gerar cobranças PIX.
Os parceiros usam este app SEM precisar do login da SigiloPay.

Requisitos:
  pip install requests pillow qrcode
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import requests
import io
import base64
import time
import os
import sys
try:
    from PIL import Image, ImageTk
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    import qrcode
    QR_OK = True
except ImportError:
    QR_OK = False

# ─── CONFIGURAÇÕES DO APP ────────────────────────────────────────────────────
# Troque pelo endereço do seu servidor (ex: http://seu-servidor.com ou ngrok)
SERVIDOR_URL = "http://localhost:8000"

# Chave de acesso do parceiro (cada parceiro tem a sua)
PARTNER_KEY = "chave_parceiro1_aqui"

# Cor do tema
COR_FUNDO    = "#0a0e1a"
COR_CARD     = "#141824"
COR_BORDA    = "#1e2538"
COR_DESTAQUE = "#00d4aa"
COR_BOTAO    = "#00d4aa"
COR_TEXTO    = "#e8eaf0"
COR_CINZA    = "#8892b0"
COR_PAGO     = "#00ff88"
COR_WAIT     = "#ffd700"
COR_ERRO     = "#ff4444"

# ─── JANELA PRINCIPAL ────────────────────────────────────────────────────────
class SigiloPayApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SIGILO PAY")
        self.geometry("480x720")
        self.resizable(False, False)
        self.configure(bg=COR_FUNDO)

        # Estado
        self.transaction_id = None
        self.polling_ativo = False
        self._poll_thread = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ---- Cabeçalho ----
        header = tk.Frame(self, bg=COR_FUNDO)
        header.pack(fill="x", padx=20, pady=(24, 0))

        tk.Label(header, text="SIGILO", font=("Segoe UI", 22, "bold"),
                 bg=COR_FUNDO, fg=COR_DESTAQUE).pack(side="left")
        tk.Label(header, text=" PAY", font=("Segoe UI", 22, "bold"),
                 bg=COR_FUNDO, fg=COR_TEXTO).pack(side="left")

        self.lbl_status_servidor = tk.Label(
            header, text="● offline", font=("Segoe UI", 9),
            bg=COR_FUNDO, fg=COR_ERRO
        )
        self.lbl_status_servidor.pack(side="right", pady=8)

        tk.Frame(self, bg=COR_BORDA, height=1).pack(fill="x", padx=20, pady=12)

        # ---- Card Formulário ----
        card = tk.Frame(self, bg=COR_CARD, bd=0, relief="flat")
        card.pack(fill="x", padx=20, pady=4)
        card.configure(highlightbackground=COR_BORDA, highlightthickness=1)

        tk.Label(card, text="GERAR COBRANÇA PIX", font=("Segoe UI", 11, "bold"),
                 bg=COR_CARD, fg=COR_TEXTO).pack(anchor="w", padx=16, pady=(14, 0))

        tk.Label(card, text="Valor (R$)", font=("Segoe UI", 9),
                 bg=COR_CARD, fg=COR_CINZA).pack(anchor="w", padx=16, pady=(10, 2))

        valor_frame = tk.Frame(card, bg=COR_BORDA)
        valor_frame.pack(fill="x", padx=16, pady=(0, 4))

        tk.Label(valor_frame, text="R$", font=("Segoe UI", 14, "bold"),
                 bg=COR_BORDA, fg=COR_DESTAQUE, width=3).pack(side="left", padx=(8, 0))

        self.entry_valor = tk.Entry(
            valor_frame, font=("Segoe UI", 18, "bold"),
            bg=COR_BORDA, fg=COR_TEXTO, bd=0,
            insertbackground=COR_DESTAQUE, width=12
        )
        self.entry_valor.pack(side="left", padx=4, pady=10)
        self.entry_valor.insert(0, "0,00")
        self.entry_valor.bind("<FocusIn>", lambda e: self._clear_entry())
        self.entry_valor.bind("<Return>", lambda e: self._gerar_pix())

        tk.Label(card, text="Descrição (opcional)", font=("Segoe UI", 9),
                 bg=COR_CARD, fg=COR_CINZA).pack(anchor="w", padx=16, pady=(8, 2))

        self.entry_desc = tk.Entry(
            card, font=("Segoe UI", 11),
            bg=COR_BORDA, fg=COR_TEXTO, bd=0,
            insertbackground=COR_DESTAQUE
        )
        self.entry_desc.pack(fill="x", padx=16, pady=(0, 14), ipady=8)
        self.entry_desc.insert(0, "Cobrança PIX")

        # ---- Botão Gerar ----
        self.btn_gerar = tk.Button(
            self, text="⚡  GERAR PIX",
            font=("Segoe UI", 13, "bold"),
            bg=COR_BOTAO, fg="#0a0e1a", bd=0, cursor="hand2",
            activebackground="#00b894", activeforeground="#0a0e1a",
            command=self._gerar_pix
        )
        self.btn_gerar.pack(fill="x", padx=20, pady=10, ipady=12)

        # ---- Área QR Code ----
        self.qr_frame = tk.Frame(self, bg=COR_CARD)
        self.qr_frame.pack(fill="x", padx=20, pady=4)
        self.qr_frame.configure(highlightbackground=COR_BORDA, highlightthickness=1)

        self.lbl_qr_title = tk.Label(
            self.qr_frame, text="QR CODE", font=("Segoe UI", 10, "bold"),
            bg=COR_CARD, fg=COR_CINZA
        )
        self.lbl_qr_title.pack(pady=(14, 0))

        self.lbl_qr = tk.Label(
            self.qr_frame, bg=COR_CARD,
            text="○  Nenhum QR Code gerado", font=("Segoe UI", 11),
            fg=COR_CINZA
        )
        self.lbl_qr.pack(pady=30)

        # ---- PIX Copia e Cola ----
        self.pix_text_frame = tk.Frame(self.qr_frame, bg=COR_CARD)
        self.pix_text_frame.pack(fill="x", padx=14, pady=(0, 6))

        self.lbl_pix_label = tk.Label(
            self.pix_text_frame, text="Pix Copia e Cola:",
            font=("Segoe UI", 9), bg=COR_CARD, fg=COR_CINZA
        )
        self.lbl_pix_label.pack(anchor="w")

        self.txt_pix = tk.Text(
            self.pix_text_frame, height=3, wrap="word",
            font=("Consolas", 8), bg=COR_BORDA, fg=COR_TEXTO,
            bd=0, state="disabled", insertbackground=COR_DESTAQUE
        )
        self.txt_pix.pack(fill="x", pady=(2, 0))

        self.btn_copiar = tk.Button(
            self.pix_text_frame, text="📋  Copiar código",
            font=("Segoe UI", 9), bg=COR_BORDA, fg=COR_DESTAQUE,
            bd=0, cursor="hand2", command=self._copiar_pix
        )
        self.btn_copiar.pack(anchor="e", pady=4)
        self.pix_text_frame.pack_forget()

        # ---- Status ----
        status_frame = tk.Frame(self, bg=COR_CARD)
        status_frame.pack(fill="x", padx=20, pady=4)
        status_frame.configure(highlightbackground=COR_BORDA, highlightthickness=1)

        tk.Label(status_frame, text="STATUS DO PAGAMENTO", font=("Segoe UI", 9, "bold"),
                 bg=COR_CARD, fg=COR_CINZA).pack(anchor="w", padx=14, pady=(10, 2))

        self.lbl_status = tk.Label(
            status_frame, text="Aguardando geração...",
            font=("Segoe UI", 13, "bold"),
            bg=COR_CARD, fg=COR_CINZA
        )
        self.lbl_status.pack(pady=(0, 14))

        # ---- Botão Verificar / Nova Cobrança ----
        self.btn_novo = tk.Button(
            self, text="↩  Nova Cobrança",
            font=("Segoe UI", 11),
            bg=COR_BORDA, fg=COR_CINZA, bd=0, cursor="hand2",
            activebackground=COR_CARD,
            command=self._nova_cobranca
        )
        self.btn_novo.pack(fill="x", padx=20, pady=(0, 4), ipady=8)
        self.btn_novo.pack_forget()

        # ---- Rodapé ----
        tk.Label(self, text="🔒  Conexão segura com servidores SigiloPay",
                 font=("Segoe UI", 8), bg=COR_FUNDO, fg=COR_CINZA).pack(pady=8)

        # Verifica servidor ao iniciar
        threading.Thread(target=self._verificar_servidor, daemon=True).start()

    # ── LÓGICA ──────────────────────────────────────────────────────────────

    def _clear_entry(self):
        v = self.entry_valor.get()
        if v in ("0,00", "0", ""):
            self.entry_valor.delete(0, "end")

    def _verificar_servidor(self):
        try:
            r = requests.get(f"{SERVIDOR_URL}/health", timeout=5)
            if r.status_code == 200:
                self.after(0, lambda: self.lbl_status_servidor.config(
                    text="● online", fg=COR_PAGO))
                return
        except Exception:
            pass
        self.after(0, lambda: self.lbl_status_servidor.config(
            text="● offline", fg=COR_ERRO))

    def _gerar_pix(self):
        # Pega e valida valor
        valor_str = self.entry_valor.get().replace(",", ".").replace("R$", "").strip()
        try:
            valor = float(valor_str)
            assert valor > 0
        except Exception:
            messagebox.showerror("Erro", "Digite um valor válido maior que zero.")
            return

        desc = self.entry_desc.get().strip() or "Cobrança PIX"

        self.btn_gerar.config(state="disabled", text="Gerando...", bg="#888")
        self._set_status("⏳  Conectando à SigiloPay...", COR_CINZA)

        threading.Thread(target=self._req_gerar_pix, args=(valor, desc), daemon=True).start()

    def _req_gerar_pix(self, valor, desc):
        try:
            resp = requests.post(
                f"{SERVIDOR_URL}/gerar_pix",
                json={"valor": valor, "descricao": desc},
                headers={"x-partner-key": PARTNER_KEY},
                timeout=30
            )
            data = resp.json()
        except requests.exceptions.ConnectionError:
            self.after(0, lambda: self._erro_geracao("Servidor offline. Verifique a conexão."))
            return
        except Exception as e:
            self.after(0, lambda: self._erro_geracao(str(e)))
            return

        if resp.status_code != 200 or not data.get("success"):
            msg = data.get("detail") or data.get("message") or str(data)
            self.after(0, lambda: self._erro_geracao(f"Erro: {msg}"))
            return

        self.after(0, lambda: self._exibir_qr(data))

    def _exibir_qr(self, data):
        self.transaction_id = data["transaction_id"]
        qr_code_b64 = data.get("qr_code", "")
        qr_text = data.get("qr_text", "")

        # Exibe QR Code
        qr_displayed = False

        if qr_code_b64 and PIL_OK:
            try:
                # Tenta decodificar base64
                if "base64," in qr_code_b64:
                    qr_code_b64 = qr_code_b64.split("base64,")[1]
                img_bytes = base64.b64decode(qr_code_b64)
                img = Image.open(io.BytesIO(img_bytes)).resize((220, 220), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self.lbl_qr.config(image=photo, text="")
                self.lbl_qr._photo = photo  # evita garbage collection
                qr_displayed = True
            except Exception:
                pass

        if not qr_displayed and qr_text and QR_OK and PIL_OK:
            # Gera QR Code localmente a partir do texto
            try:
                qr = qrcode.make(qr_text)
                qr = qr.resize((220, 220), Image.LANCZOS)
                photo = ImageTk.PhotoImage(qr)
                self.lbl_qr.config(image=photo, text="")
                self.lbl_qr._photo = photo
                qr_displayed = True
            except Exception:
                pass

        if not qr_displayed:
            self.lbl_qr.config(
                text="✅  PIX gerado!\nCopie o código abaixo.",
                fg=COR_DESTAQUE, image=""
            )

        # Exibe código copia e cola
        if qr_text:
            self.pix_text_frame.pack(fill="x", padx=14, pady=(0, 6))
            self.txt_pix.config(state="normal")
            self.txt_pix.delete("1.0", "end")
            self.txt_pix.insert("end", qr_text)
            self.txt_pix.config(state="disabled")

        self._set_status("🕐  Aguardando pagamento...", COR_WAIT)
        self.btn_gerar.config(state="disabled", text="Aguardando...", bg="#555")
        self.btn_novo.pack(fill="x", padx=20, pady=(0, 4), ipady=8)

        # Inicia polling de status
        self.polling_ativo = True
        self._poll_thread = threading.Thread(target=self._polling_status, daemon=True)
        self._poll_thread.start()

    def _polling_status(self):
        """Verifica o status a cada 5 segundos."""
        while self.polling_ativo and self.transaction_id:
            time.sleep(5)
            if not self.polling_ativo:
                break
            try:
                resp = requests.get(
                    f"{SERVIDOR_URL}/status/{self.transaction_id}",
                    headers={"x-partner-key": PARTNER_KEY},
                    timeout=10
                )
                data = resp.json()
                status = data.get("status", "aguardando")
            except Exception:
                continue

            if status == "pago":
                self.polling_ativo = False
                self.after(0, self._pagamento_confirmado)
                break

    def _pagamento_confirmado(self):
        self._set_status("✅  PAGAMENTO CONFIRMADO!", COR_PAGO)
        self.lbl_qr.config(
            text="✅  PAGO!", fg=COR_PAGO,
            font=("Segoe UI", 22, "bold"), image=""
        )
        if hasattr(self.lbl_qr, "_photo"):
            del self.lbl_qr._photo
        self.btn_gerar.config(state="normal", text="⚡  GERAR NOVO PIX", bg=COR_BOTAO)
        messagebox.showinfo("💰 Pagamento Recebido", "Pagamento PIX confirmado com sucesso!")

    def _erro_geracao(self, msg):
        self._set_status(f"❌  {msg}", COR_ERRO)
        self.btn_gerar.config(state="normal", text="⚡  GERAR PIX", bg=COR_BOTAO)
        messagebox.showerror("Erro", msg)

    def _set_status(self, texto, cor):
        self.lbl_status.config(text=texto, fg=cor)

    def _copiar_pix(self):
        texto = self.txt_pix.get("1.0", "end").strip()
        if texto:
            self.clipboard_clear()
            self.clipboard_append(texto)
            self.btn_copiar.config(text="✅  Copiado!")
            self.after(2000, lambda: self.btn_copiar.config(text="📋  Copiar código"))

    def _nova_cobranca(self):
        self.polling_ativo = False
        self.transaction_id = None
        self.entry_valor.delete(0, "end")
        self.entry_valor.insert(0, "0,00")
        self.lbl_qr.config(text="○  Nenhum QR Code gerado", fg=COR_CINZA,
                           font=("Segoe UI", 11), image="")
        if hasattr(self.lbl_qr, "_photo"):
            del self.lbl_qr._photo
        self.pix_text_frame.pack_forget()
        self.txt_pix.config(state="normal")
        self.txt_pix.delete("1.0", "end")
        self.txt_pix.config(state="disabled")
        self._set_status("Aguardando geração...", COR_CINZA)
        self.btn_gerar.config(state="normal", text="⚡  GERAR PIX", bg=COR_BOTAO)
        self.btn_novo.pack_forget()

    def _on_close(self):
        self.polling_ativo = False
        self.destroy()


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = SigiloPayApp()
    app.mainloop()
