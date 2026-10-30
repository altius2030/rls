"""
Ронгта РЛС1000 — Локальный сервер-драйвер для ПК.
Получает TXP-файл от iframe (через localhost) и запускает PLU Manager.

Запуск:
  python local_driver.py

Порт по умолчанию: 9101
PLU Manager: C:\Program Files (x86)\RLS1000\RTPLU.exe
"""

import os
import sys
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# === Настройки ===
PORT = 9101
PLU_MANAGER_PATH = r"C:\Program Files (x86)\RLS1000\RTPLU.exe"
EXPORT_DIR = Path.home() / "RongtaExports"
EXPORT_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("rongta-local-driver")

app = FastAPI(title="Rongta Local Driver", version="1.0")


@app.get("/health")
async def health():
    plu_exists = os.path.exists(PLU_MANAGER_PATH)
    return {"status": "ok", "plu_manager_exists": plu_exists, "plu_manager_path": PLU_MANAGER_PATH}


@app.post("/export")
async def export_txp(request: Request):
    """
    Получить TXP-файл, сохранить на диск и открыть в PLU Manager.
    """
    body = await request.json()
    txp_content = body.get("txp", "")
    filename = body.get("filename", "rongta_plu.txp")

    if not txp_content:
        return JSONResponse(content={"error": "No TXP content"}, status_code=400)

    # Сохраняем TXP файл
    filepath = EXPORT_DIR / filename
    filepath.write_text(txp_content, encoding="utf-8")
    logger.info(f"TXP saved: {filepath} ({len(txp_content)} bytes)")

    # Открываем в PLU Manager
    launched = False
    error_msg = ""
    try:
        if os.path.exists(PLU_MANAGER_PATH):
            subprocess.Popen([PLU_MANAGER_PATH, str(filepath)], shell=False)
            launched = True
            logger.info(f"PLU Manager launched with: {filepath}")
        else:
            error_msg = f"PLU Manager not found: {PLU_MANAGER_PATH}"
            logger.error(error_msg)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Failed to launch PLU Manager: {e}")

    return JSONResponse(content={
        "success": True,
        "launched": launched,
        "filepath": str(filepath),
        "plu_manager": PLU_MANAGER_PATH,
        "error": error_msg,
        "message": "PLU Manager запущен с TXP-файлом" if launched else "Не удалось запустить PLU Manager"
    })


@app.post("/save-txp")
async def save_txp(request: Request):
    """Сохранить TXP файл (без запуска PLU Manager)."""
    body = await request.json()
    txp_content = body.get("txp", "")
    filename = body.get("filename", "rongta_plu.txp")

    if not txp_content:
        return JSONResponse(content={"error": "No TXP content"}, status_code=400)

    filepath = EXPORT_DIR / filename
    filepath.write_text(txp_content, encoding="utf-8")

    return JSONResponse(content={
        "success": True,
        "filepath": str(filepath),
        "message": f"TXP сохранён: {filepath}"
    })


@app.get("/info")
async def info():
    return {
        "plu_manager_path": PLU_MANAGER_PATH,
        "plu_manager_exists": os.path.exists(PLU_MANAGER_PATH),
        "export_dir": str(EXPORT_DIR),
    }


if __name__ == "__main__":
    import uvicorn

    print("=" * 60)
    print("  Rongta RLS1000 — Локальный драйвер")
    print(f"  PLU Manager: {PLU_MANAGER_PATH}")
    print(f"  Export dir:  {EXPORT_DIR}")
    print(f"  URL:         http://localhost:{PORT}")
    print("=" * 60)

    uvicorn.run(app, host="127.0.0.1", port=PORT)
