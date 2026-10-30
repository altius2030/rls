"""
Rongta RLS1000 — Vendor API + CORS Proxy + iframe.
"""

import json
import logging
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

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


def get_first_token() -> str:
    for entry in load_tokens().values():
        if entry.get("token"):
            return entry["token"]
    return ""


# ============================================================
# Vendor API
# ============================================================

@app.put("/api/moysklad/vendor/1.0/apps/{app_id}/{account_id}")
async def activate(app_id: str, account_id: str, request: Request):
    body = await request.json()
    token = None
    for a in body.get("access", []):
        token = a.get("access_token")
        if token:
            break
    tokens = load_tokens()
    tokens[account_id] = {"token": token, "account_name": body.get("accountName", ""), "activated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    save_tokens(tokens)
    return JSONResponse(content={"status": "Activated"})


@app.delete("/api/moysklad/vendor/1.0/apps/{app_id}/{account_id}")
async def deactivate(app_id: str, account_id: str, request: Request):
    tokens = load_tokens()
    tokens.pop(account_id, None)
    save_tokens(tokens)
    return JSONResponse(content={}, status_code=200)


@app.get("/health")
async def health():
    return {"status": "ok"}


# ============================================================
# CORS Proxy — iframe вызывает наш сервер, он проксирует в МС
# ============================================================

@app.get("/api/products")
async def proxy_products():
    """Получить товары из МС (обход CORS)."""
    token = get_first_token()
    if not token:
        return JSONResponse(content={"error": "no_token", "products": []}, status_code=400)

    headers = {"Authorization": f"Bearer {token}", "Accept-Encoding": "gzip"}
    base = "https://api.moysklad.ru/api/remap/1.2"

    async with httpx.AsyncClient(timeout=30) as cli:
        # Загружаем группы
        folders = []
        url = f"{base}/entity/productfolder?limit=100"
        while url:
            r = await cli.get(url, headers=headers)
            if r.status_code != 200:
                break
            d = r.json()
            for row in d.get("rows", []):
                folders.append({"id": row.get("id", ""), "name": row.get("name", "")})
            url = d.get("meta", {}).get("nextHref")

        folder_map = {f["id"]: i + 1 for i, f in enumerate(folders)}

        # Загружаем товары
        products = []
        url = f"{base}/entity/product?limit=100&expand=salePrices"
        while url:
            r = await cli.get(url, headers=headers)
            if r.status_code != 200:
                break
            d = r.json()

            for row in d.get("rows", []):
                bc = ""
                for b in (row.get("barcodes") or []):
                    bc = b.get("ean13") or b.get("ean8") or b.get("code") or ""
                    if bc:
                        break

                price = 0
                for sp in (row.get("salePrices") or []):
                    pt = (sp.get("priceType") or {}).get("name", "")
                    if pt in ["Цена продажи", "Розничная"]:
                        price = (sp.get("value") or 0) / 100
                        break
                else:
                    if row.get("salePrices"):
                        price = (row["salePrices"][0].get("value") or 0) / 100

                fr = row.get("productFolder") or {}
                fid = fr.get("id", "")
                code = row.get("code") or row.get("externalCode") or ""

                products.append({
                    "name": row.get("name") or "",
                    "code": code,
                    "barcode": bc,
                    "weight": row.get("weight") or 0,
                    "isWeighed": row.get("weighed") or False,
                    "price": price,
                    "folderIndex": folder_map.get(fid, 0),
                })

            url = d.get("meta", {}).get("nextHref")

    return JSONResponse(content={"products": products, "total": len(products)})


# ============================================================
# iframe + download
# ============================================================

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    html_path = Path(__file__).resolve().parent / "iframe" / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Not found</h1>")


@app.get("/download/rongta_send.py")
async def download_script():
    p = Path(__file__).resolve().parent / "rongta_send.py"
    if not p.exists():
        p = Path("rongta_send.py").resolve()
    if p.exists():
        return PlainTextResponse(
            content=p.read_text(encoding="utf-8"),
            headers={"Content-Disposition": "attachment; filename=rongta_send.py"}
        )
    return PlainTextResponse(content="# Not found", status_code=404)
