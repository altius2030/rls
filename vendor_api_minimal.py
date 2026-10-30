"""
Rongta RLS1000 — Минимальный Vendor API сервер.
Активация + iframe с инструкцией.
"""

import json
import logging
import time
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse

APP_ID = "658bfe45-c3f0-4e68-b02e-72231fdef826"
APP_UID = "rongtams.altius2030"
SECRET_KEY = "ot5UqHhXAgnWjHiJWRlYpTvDBAZPMYMBBO2knX4sssY4ArEsBrnZbX0IcaKnGNIcV5OlMOp5K8dPl4S4vvbx3Csw8Q8C4P2uHjba4dWbGntg1HXAdYjmzVJ4qMywU9l6"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Файл для хранения токенов (переживает перезапуск)
TOKEN_FILE = Path(__file__).resolve().parent / "tokens.json"

def load_tokens() -> dict:
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def save_tokens(tokens: dict):
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2, ensure_ascii=False), encoding="utf-8")

@app.put("/api/moysklad/vendor/1.0/apps/{app_id}/{account_id}")
async def activate(app_id: str, account_id: str, request: Request):
    body = await request.json()
    token = None
    for a in body.get("access", []):
        token = a.get("access_token")
        if token:
            break
    tokens = load_tokens()
    tokens[account_id] = {
        "token": token,
        "account_name": body.get("accountName", ""),
        "activated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    save_tokens(tokens)
    logger.info(f"ACTIVATE: account={account_id}, token={'yes' if token else 'no'}")
    return JSONResponse(content={"status": "Activated"})


@app.delete("/api/moysklad/vendor/1.0/apps/{app_id}/{account_id}")
async def deactivate(app_id: str, account_id: str, request: Request):
    tokens = load_tokens()
    tokens.pop(account_id, None)
    save_tokens(tokens)
    return JSONResponse(content={}, status_code=200)


@app.get("/api/token")
async def get_token():
    """Получить токен для iframe."""
    tokens = load_tokens()
    for acc_id, entry in tokens.items():
        if entry.get("token"):
            return JSONResponse(content={"token": entry["token"], "accountId": acc_id, "ok": True})
    return JSONResponse(content={"ok": False, "error": "no_token"}, status_code=404)


# ============================================================
# iframe для МоегоСклада
# ============================================================

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """iframe — отдаём статический HTML."""
    html_path = Path(__file__).resolve().parent / "iframe" / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    # Fallback
    return HTMLResponse(content="<h1 style='font-family:sans-serif;padding:20px'>Загрузка... Обновите страницу</h1>")


@app.get("/download/rongta_send.py")
async def download_script():
    """Скачать скрипт отправки в весы."""
    script_path = Path(__file__).resolve().parent / "rongta_send.py"
    if not script_path.exists():
        script_path = Path("rongta_send.py").resolve()
    if script_path.exists():
        content = script_path.read_text(encoding="utf-8")
        return PlainTextResponse(
            content=content,
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=rongta_send.py"}
        )
    return PlainTextResponse(
        content="# Script not found at: " + str(script_path),
        status_code=404,
        media_type="text/plain"
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
