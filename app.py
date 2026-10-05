import os
import re
import secrets
import time
from pathlib import Path

from flask import Flask, request, session, redirect, url_for, render_template_string
from telethon import TelegramClient
from telethon.errors import (
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    SessionPasswordNeededError,
)

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SECRET_KEY = os.environ["WEB_SECRET_KEY"]

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

BASE = Path(os.environ.get("SESSION_DIR", "/tmp/telegram_sessions"))
BASE.mkdir(parents=True, exist_ok=True)

# Estado temporário em memória. Em produção com múltiplas instâncias,
# substitua por armazenamento compartilhado.
pending = {}

PAGE = """
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Conectar conta Telegram</title>
<style>
body{font-family:system-ui,-apple-system,sans-serif;background:#0e1621;color:#fff;margin:0}
main{max-width:480px;margin:40px auto;padding:24px}
.card{background:#17212b;padding:24px;border-radius:18px}
h1{font-size:24px;margin-top:0}
p{color:#c8d1da;line-height:1.45}
input,button{width:100%;box-sizing:border-box;padding:14px;border-radius:10px;font-size:17px;margin-top:12px}
input{border:1px solid #3b4a59;background:#0e1621;color:#fff}
button{border:0;background:#2aabee;color:#fff;font-weight:700}
.err{background:#4b2020;padding:12px;border-radius:10px;color:#ffd6d6}
.ok{background:#173f2b;padding:12px;border-radius:10px;color:#c9f7dc}
small{display:block;color:#94a3b1;margin-top:16px}
</style>
</head>
<body><main><div class="card">
<h1>🔐 Conectar conta Telegram</h1>
{% if error %}<div class="err">{{ error }}</div>{% endif %}
{% if success %}
<div class="ok">✅ Conta conectada com sucesso.</div>
<p>Você já pode fechar esta página e voltar ao bot.</p>
{% elif step == "code" %}
<p>Digite o código oficial recebido na sua conta Telegram.</p>
<form method="post" action="/confirm">
<input name="code" inputmode="numeric" autocomplete="one-time-code" placeholder="Código" required>
<button type="submit">Confirmar</button>
</form>
<small>O código é usado apenas para concluir esta tentativa e não é gravado em banco de dados.</small>
{% else %}
<p>Informe o número da sua própria conta, com DDI. Ex.: +5511999999999</p>
<form method="post" action="/send-code">
<input name="phone" type="tel" autocomplete="tel" placeholder="+55..." required>
<button type="submit">Continuar</button>
</form>
<small>Conecte somente uma conta que pertence a você.</small>
{% endif %}
</div></main></body></html>
"""

def clean_phone(v):
    v = (v or "").strip()
    digits = re.sub(r"\D", "", v)
    if not (8 <= len(digits) <= 15):
        return None
    return "+" + digits

def cleanup():
    now = time.time()
    for k in list(pending):
        if now - pending[k]["created"] > 600:
            pending.pop(k, None)

@app.get("/")
def index():
    cleanup()
    return render_template_string(PAGE, step="phone", error=None, success=False)

@app.post("/send-code")
def send_code():
    cleanup()
    phone = clean_phone(request.form.get("phone"))
    if not phone:
        return render_template_string(PAGE, step="phone", error="Número inválido.", success=False), 400

    token = secrets.token_urlsafe(24)
    session_path = str(BASE / f"pending_{token}")
    client = TelegramClient(session_path, API_ID, API_HASH)
    client.connect()
    try:
        sent = client.send_code_request(phone)
    except Exception:
        client.disconnect()
        return render_template_string(PAGE, step="phone", error="Não foi possível enviar o código. Confira o número e tente novamente.", success=False), 400
    finally:
        client.disconnect()

    pending[token] = {
        "phone": phone,
        "phone_code_hash": sent.phone_code_hash,
        "session_path": session_path,
        "created": time.time(),
    }
    session["login_token"] = token
    return render_template_string(PAGE, step="code", error=None, success=False)

@app.post("/confirm")
def confirm():
    cleanup()
    token = session.get("login_token")
    data = pending.get(token)
    if not data:
        return redirect(url_for("index"))

    code = re.sub(r"\D", "", request.form.get("code", ""))
    if not code:
        return render_template_string(PAGE, step="code", error="Digite o código recebido.", success=False), 400

    client = TelegramClient(data["session_path"], API_ID, API_HASH)
    client.connect()
    try:
        client.sign_in(
            phone=data["phone"],
            code=code,
            phone_code_hash=data["phone_code_hash"],
        )
        me = client.get_me()
        if not me:
            raise RuntimeError("Conta não autorizada")
        # Sessão final identificada pelo ID da própria conta Telegram.
        final_base = BASE / f"user_{me.id}"
        src = Path(data["session_path"] + ".session")
        dst = Path(str(final_base) + ".session")
        client.disconnect()
        if src.exists():
            src.replace(dst)
        pending.pop(token, None)
        session.pop("login_token", None)
        return render_template_string(PAGE, step="done", error=None, success=True)
    except SessionPasswordNeededError:
        return render_template_string(
            PAGE, step="code",
            error="Esta conta usa verificação em duas etapas. Este fluxo não coleta senha 2FA.",
            success=False
        ), 400
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        return render_template_string(PAGE, step="code", error="Código inválido ou expirado.", success=False), 400
    except Exception:
        return render_template_string(PAGE, step="code", error="Não foi possível concluir a conexão.", success=False), 400
    finally:
        try:
            if client.is_connected():
                client.disconnect()
        except Exception:
            pass

@app.get("/health")
def health():
    return {"ok": True}
