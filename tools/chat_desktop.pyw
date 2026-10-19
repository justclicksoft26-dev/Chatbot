"""
ECOSAFR Chat Desktop — double-click to open.
Connects to the local server on port 8002.
"""
import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import json
import urllib.request
import urllib.error
import subprocess
import sys
import os
import time

SERVER_URL = "http://localhost:8002/chat/"
USER_ID    = "desktop_user"
ROLE       = "admin"
BG         = "#1e1e2e"
BG2        = "#2a2a3e"
ACCENT     = "#7c6ff7"
USER_CLR   = "#4fc3f7"
BOT_CLR    = "#a5d6a7"
ERR_CLR    = "#ef9a9a"
FG         = "#e0e0e0"
FONT_MSG   = ("Segoe UI", 11)
FONT_IN    = ("Segoe UI", 12)


def _find_python():
    """Return python.exe path (not pythonw.exe) for running uvicorn."""
    exe = sys.executable
    # pythonw.exe → python.exe
    if exe.lower().endswith("pythonw.exe"):
        candidate = exe[:-11] + "python.exe"
        if os.path.exists(candidate):
            return candidate
    return exe


def _start_server():
    """Start uvicorn in background if not already running."""
    try:
        urllib.request.urlopen("http://localhost:8002/docs", timeout=2)
        return  # already up
    except Exception:
        pass
    python = _find_python()
    base   = os.path.dirname(os.path.abspath(__file__))
    log    = os.path.join(base, "server.log")
    subprocess.Popen(
        [python, "-m", "uvicorn", "app:app",
         "--host", "0.0.0.0", "--port", "8002", "--log-level", "warning"],
        cwd=base,
        stdout=open(log, "w"),
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


class ChatApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ECOSAFR Chat")
        self.geometry("720x560")
        self.minsize(500, 400)
        self.configure(bg=BG)
        self._build_ui()
        self._check_server()

    # ── UI ────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=ACCENT, height=48)
        hdr.pack(fill="x")
        tk.Label(hdr, text="  ECOSAFR AI Chat", bg=ACCENT, fg="white",
                 font=("Segoe UI", 14, "bold"), anchor="w").pack(side="left", padx=12, pady=8)
        self.status_lbl = tk.Label(hdr, text="⏳ جاري التشغيل...", bg=ACCENT, fg="white",
                                   font=("Segoe UI", 10))
        self.status_lbl.pack(side="right", padx=12)

        # Chat area
        self.chat = scrolledtext.ScrolledText(
            self, wrap="word", state="disabled",
            bg=BG2, fg=FG, font=FONT_MSG,
            relief="flat", bd=0, padx=12, pady=8,
            spacing3=6,
        )
        self.chat.pack(fill="both", expand=True, padx=0, pady=(0, 0))
        self.chat.tag_config("user",  foreground=USER_CLR, justify="right")
        self.chat.tag_config("bot",   foreground=BOT_CLR,  justify="left")
        self.chat.tag_config("error", foreground=ERR_CLR,  justify="left")
        self.chat.tag_config("meta",  foreground="#888",   justify="left",
                              font=("Segoe UI", 9))

        # Input bar
        bar = tk.Frame(self, bg=BG, pady=8, padx=8)
        bar.pack(fill="x")
        self.entry = tk.Entry(bar, font=FONT_IN, bg=BG2, fg=FG,
                              insertbackground=FG, relief="flat", bd=4)
        self.entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.entry.bind("<Return>", lambda e: self._send())
        self.entry.bind("<KP_Enter>", lambda e: self._send())

        self.send_btn = tk.Button(
            bar, text="إرسال ➤", bg=ACCENT, fg="white",
            font=("Segoe UI", 11, "bold"), relief="flat",
            activebackground="#6a5fdf", activeforeground="white",
            padx=14, pady=6, cursor="hand2",
            command=self._send,
        )
        self.send_btn.pack(side="right", padx=(8, 0))

    # ── Server health ─────────────────────────────────────────────────

    def _check_server(self):
        def probe():
            for _ in range(60):
                try:
                    urllib.request.urlopen("http://localhost:8002/docs", timeout=3)
                    self.after(0, lambda: self.status_lbl.config(text="🟢 متصل"))
                    self.after(0, lambda: self._append(
                        "bot", "مرحباً! السيرفر جاهز. اكتب سؤالك بالعربي أو الإنجليزي.\n"))
                    return
                except Exception:
                    time.sleep(1)
            self.after(0, lambda: self.status_lbl.config(text="🔴 خطأ في التشغيل"))
            self.after(0, lambda: self._append(
                "error", "⚠️ السيرفر ما اشتغلش تلقائياً — تحقق من server.log بجانب الملف\n"))
        threading.Thread(target=probe, daemon=True).start()

    # ── Messaging ─────────────────────────────────────────────────────

    def _append(self, tag, text):
        self.chat.config(state="normal")
        self.chat.insert("end", text, tag)
        self.chat.config(state="disabled")
        self.chat.see("end")

    def _send(self):
        q = self.entry.get().strip()
        if not q:
            return
        self.entry.delete(0, "end")
        self._append("user", f"\n🧑 {q}\n")
        self.send_btn.config(state="disabled", text="⏳")
        self.status_lbl.config(text="🔄 جاري...")
        threading.Thread(target=self._call_api, args=(q,), daemon=True).start()

    def _call_api(self, question):
        payload = json.dumps({
            "question": question,
            "user_id":  USER_ID,
            "role":     ROLE,
        }).encode("utf-8")
        try:
            req = urllib.request.Request(
                SERVER_URL,
                data=payload,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            answer  = data.get("answer", "لا يوجد رد")
            method  = data.get("method", "")
            rows    = data.get("row_count", 0)
            ms      = data.get("execution_time_ms", 0)
            meta    = f"  [{method} | {rows} rows | {ms}ms]\n"

            self.after(0, lambda: self._append("bot",  f"\n🤖 {answer}\n"))
            self.after(0, lambda: self._append("meta", meta))
            self.after(0, lambda: self.status_lbl.config(text="🟢 متصل"))

        except Exception as ex:
            self.after(0, lambda: self._append("error", f"\n⚠️ خطأ: {ex}\n"))
            self.after(0, lambda: self.status_lbl.config(text="🔴 خطأ"))
        finally:
            self.after(0, lambda: self.send_btn.config(state="normal", text="إرسال ➤"))


if __name__ == "__main__":
    _start_server()
    app = ChatApp()
    app.mainloop()
