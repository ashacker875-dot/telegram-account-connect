# telegram-account-connect

Backend HTTPS para autenticação da própria conta Telegram.

## Variáveis no Render
- TELEGRAM_API_ID
- TELEGRAM_API_HASH
- WEB_SECRET_KEY
- SESSION_DIR (opcional)

Build: `pip install -r requirements.txt`
Start: `gunicorn app:app`

Não coloque credenciais, códigos de login ou arquivos `.session` no GitHub.
