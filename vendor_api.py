"""
Vendor API + iframe сервер для выгрузки товаров в весы Rongta RLS1000.
Единый файл: активация, деактивация, UI (iframe), API товаров.
"""

import json
import time
import logging
from pathlib import Path

import jwt
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

APP_ID = "658bfe45-c3f0-4e68-b02e-72231fdef826"
APP_UID = "rongtams.altius2030"
SECRET_KEY = "ot5UqHhXAgnWjHiJWRlYpTvDBAZPMYMBBO2knX4sssY4ArEsBrnZbX0IcaKnGNIcV5OlMOp5K8dPl4S4vvbx3Csw8Q8C4P2uHjba4dWbGntg1HXAdYjmzVJ4qMywU9l6"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

INSTALL_FILE = Path(__file__).parent / "installations.json"


def load_installations() -> dict:
    if INSTALL_FILE.exists():
        return json.loads(INSTALL_FILE.read_text(encoding="utf-8"))
    return {}


def save_installations(data: dict):
    INSTALL_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ============================================================
# Middleware: логирование всех запросов
# ============================================================

@app.middleware("http")
async def log_requests(request: Request, call_next):
    body = await request.body()
    logger.info(f"→ {request.method} {request.url.path}")
    if body:
        logger.info(f"  body: {body.decode('utf-8', errors='replace')[:300]}")
    response = await call_next(request)
    logger.info(f"  ← {response.status_code}")
    return response


# ============================================================
# Vendor API: активация / деактивация
# ============================================================

@app.put("/api/moysklad/vendor/1.0/apps/{app_id}/{account_id}")
async def activate(app_id: str, account_id: str, request: Request):
    body = await request.json()
    cause = body.get("cause", "Install")
    access_token = None
    access_data = body.get("access", [])
    if access_data:
        access_token = access_data[0].get("access_token")

    installs = load_installations()
    installs[account_id] = {
        "app_id": app_id,
        "account_id": account_id,
        "access_token": access_token,
        "account_name": body.get("accountName", ""),
        "cause": cause,
        "activated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    save_installations(installs)

    logger.info(f"✅ ACTIVATED: account={account_id}, cause={cause}, token={'yes' if access_token else 'no'}")

    return JSONResponse(
        content={"status": "Activated"},
        headers={"Content-Type": "application/json; charset=utf-8"},
    )


@app.delete("/api/moysklad/vendor/1.0/apps/{app_id}/{account_id}")
async def deactivate(app_id: str, account_id: str, request: Request):
    body = {}
    try:
        raw = await request.body()
        if raw:
            body = json.loads(raw)
    except Exception:
        pass

    cause = body.get("cause", "Uninstall")
    installs = load_installations()
    if account_id in installs:
        installs[account_id]["status"] = "Deactivated"
        installs[account_id]["cause"] = cause
        save_installations(installs)

    logger.info(f"✅ DEACTIVATED: account={account_id}, cause={cause}")
    return JSONResponse(content={}, status_code=200)


# ============================================================
# iframe UI
# ============================================================

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request})


# ============================================================
# API: получение товаров из МоегоСклада
# ============================================================

@app.get("/api/products")
async def get_products(account_id: str = ""):
    installs = load_installations()
    if not account_id:
        for acc_id, info in installs.items():
            if info.get("access_token"):
                account_id = acc_id
                break

    install = installs.get(account_id, {})
    access_token = install.get("access_token")

    if not access_token:
        return JSONResponse(content={"error": "no_token", "products": [], "total": 0})

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json",
    }

    # Загружаем группы
    folders = []
    folders_url = "https://api.moysklad.ru/api/remap/1.2/entity/productfolder?limit=100"
    async with httpx.AsyncClient(timeout=30) as client:
        while folders_url:
            resp = await client.get(folders_url, headers=headers)
            if resp.status_code != 200:
                break
            data = resp.json()
            for row in data.get("rows", []):
                folders.append({"id": row.get("id", ""), "name": row.get("name", "")})
            folders_url = data.get("meta", {}).get("nextHref")

    folder_map = {}
    for idx, f in enumerate(folders):
        folder_map[f["id"]] = idx + 1

    # Загружаем товары с ценами
    products = []
    url = "https://api.moysklad.ru/api/remap/1.2/entity/product?limit=100&expand=salePrices"
    async with httpx.AsyncClient(timeout=30) as client:
        while url:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                break
            data = resp.json()

            for row in data.get("rows", []):
                barcodes = row.get("barcodes", [])
                barcode = ""
                if barcodes:
                    for bc in barcodes:
                        code = bc.get("ean13") or bc.get("ean8") or bc.get("code") or ""
                        if code:
                            barcode = code
                            break

                price = 0
                sale_prices = row.get("salePrices", [])
                for sp in sale_prices:
                    pt_name = sp.get("priceType", {}).get("name", "")
                    if pt_name in ["Цена продажи", "Розничная"]:
                        price = sp.get("value", 0) / 100
                        break
                else:
                    if sale_prices:
                        price = sale_prices[0].get("value", 0) / 100

                folder_ref = row.get("productFolder", {})
                folder_id = folder_ref.get("id", "") if folder_ref else ""

                products.append({
                    "id": row.get("id", ""),
                    "name": row.get("name", ""),
                    "article": row.get("article", ""),
                    "code": row.get("code", ""),
                    "externalCode": row.get("externalCode", ""),
                    "barcode": barcode,
                    "weight": row.get("weight", 0),
                    "isWeightProduct": row.get("weighed", False),
                    "price": price,
                    "folderIndex": folder_map.get(folder_id, 0),
                    "productFolderId": folder_id,
                })

            url = data.get("meta", {}).get("nextHref")

    return JSONResponse(content={"products": products, "total": len(products)})


# ============================================================
# Health check
# ============================================================

@app.get("/health")
async def health():
    installs = load_installations()
    return {"status": "ok", "installations": len(installs)}
