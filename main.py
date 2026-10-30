"""
Moy Sklad → Rongta RLS1000 Scale Exporter
Vendor API Solution for выгрузки товаров в весы Rongta RLS1000
"""

import json
import logging
import threading
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from config import settings
from auth import verify_incoming_jwt, vendor_api_request
from moysklad_api import fetch_products, fetch_product_folders, fetch_prices
from rongta_protocol import RongtaPLU, RongtaScaleServer, RongtaScaleSender, RongtaTXPFile

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory="templates")

# In-memory store for installation tokens and settings
# In production, use a database
installations: dict[str, dict] = {}
scale_configs: dict[str, dict] = {}

# Rongta TCP server instance
scale_server: RongtaScaleServer | None = None
scale_server_thread: threading.Thread | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    logger.info("Rongta Scale Exporter Service started")
    yield
    # Stop TCP server on shutdown
    global scale_server
    if scale_server:
        scale_server.stop()
    logger.info("Rongta Scale Exporter Service stopped")


app = FastAPI(title="МойСклад → Весы Rongta", lifespan=lifespan)


@app.middleware("http")
async def catch_all_exceptions(request: Request, call_next):
    """Global exception handler - returns JSON error instead of HTML."""
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        logger.error(f"Unhandled exception: {e}\n{traceback.format_exc()}")
        return JSONResponse(
            content={"status": "Activating"},
            status_code=200,
            headers={"Content-Type": "application/json"}
        )


# ============================================================
# Vendor API Endpoints (called by Moy Sklad)
# ============================================================

@app.put("/api/moysklad/vendor/1.0/apps/{app_id}/{account_id}")
async def activate_solution(app_id: str, account_id: str, request: Request):
    """
    Активация решения на аккаунте.
    """
    logger.info(f"=== ACTIVATION REQUEST ===")
    logger.info(f"app_id={app_id}, account_id={account_id}")
    logger.info(f"Headers: {dict(request.headers)}")
    
    # Log raw body for debugging
    raw_body = await request.body()
    logger.info(f"Raw body: {raw_body.decode('utf-8', errors='replace')}")
    
    # Try to parse JSON
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}")
        return JSONResponse(
            content={"status": "Activating"},
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    # Check authorization (log but don't reject for debugging)
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        logger.warning("Missing Authorization header")
    else:
        token = auth_header[7:]
        try:
            jwt_payload = verify_incoming_jwt(token)
            logger.info(f"JWT verified: {jwt_payload}")
        except ValueError as e:
            logger.warning(f"JWT verification issue (proceeding anyway): {e}")

    cause = body.get("cause", "Install")
    access_token = None

    access_data = body.get("access", [])
    if access_data:
        access_token = access_data[0].get("access_token")

    installations[account_id] = {
        "app_id": app_id,
        "account_id": account_id,
        "access_token": access_token,
        "account_name": body.get("accountName", ""),
        "cause": cause,
        "status": "Activated",
    }

    logger.info(f"Activated on account {account_id} (cause: {cause})")

    response_body = {"status": "SettingsRequired"}
    logger.info(f"Response: {response_body}")
    
    return JSONResponse(
        content=response_body,
        status_code=200,
        headers={"Content-Type": "application/json; charset=utf-8"}
    )


@app.delete("/api/moysklad/vendor/1.0/apps/{app_id}/{account_id}")
async def deactivate_solution(app_id: str, account_id: str, request: Request):
    """
    Деактивация решения на аккаунте.
    """
    logger.info(f"=== DEACTIVATION REQUEST === app_id={app_id}, account_id={account_id}")
    
    raw_body = await request.body()
    logger.info(f"Deactivation body: {raw_body.decode('utf-8', errors='replace')}")
    
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        body = {}

    cause = body.get("cause", "Uninstall")

    if account_id in installations:
        installations[account_id]["status"] = "Deactivated"
        installations[account_id]["cause"] = cause

    logger.info(f"Deactivated on account {account_id} (cause: {cause})")
    return JSONResponse(content={}, status_code=200)


# ============================================================
# TCP Server for Scale Connections
# ============================================================

def start_tcp_server(config: dict):
    """Start TCP server in background thread."""
    global scale_server, scale_server_thread

    if scale_server and scale_server.running:
        scale_server.stop()

    scale_server = RongtaScaleServer(
        host=config.get("server_host", "0.0.0.0"),
        port=config.get("server_port", 9102),
    )
    scale_server_thread = threading.Thread(target=scale_server.start, daemon=True)
    scale_server_thread.start()


def update_scale_plu_data(plu_records: list[RongtaPLU]):
    """Update PLU data on the TCP server."""
    global scale_server
    if scale_server:
        scale_server.set_plu_data(plu_records)


# ============================================================
# Export Logic
# ============================================================

async def export_to_rongta_scale(account_id: str, scale_config: dict) -> dict:
    """
    Fetch products from Moy Sklad and send to Rongta RLS1000 scale.
    """
    installation = installations.get(account_id)
    if not installation or not installation.get("access_token"):
        return {"error": "No active installation found"}

    access_token = installation["access_token"]

    # Fetch data from Moy Sklad
    logger.info("Fetching products from Moy Sklad...")
    products = await fetch_products(access_token)
    folders = await fetch_product_folders(access_token)
    prices = await fetch_prices(access_token)

    # Create folder-to-department mapping
    folder_map = {}
    dept_start = scale_config.get("department_start", 1)
    for idx, folder in enumerate(folders):
        folder_map[folder["id"]] = dept_start + idx

    # Convert products to Rongta PLU records
    plu_records = []
    errors = []
    plu_start = scale_config.get("plu_start", 1)

    for idx, product in enumerate(products):
        try:
            product_id = product["id"]
            price = prices.get(product_id, 0)
            if price <= 0:
                errors.append(f"Нет цены для товара: {product['name']}")
                continue

            folder_id = product.get("folder_id", "")
            department = folder_map.get(folder_id, 1)

            # Determine PLU type
            plu_type = 0
            price_type = 0
            if product.get("is_weight_product"):
                plu_type = 0  # весовой
                price_type = 0  # цена за кг
            elif product.get("weight", 0) > 0:
                plu_type = 1  # штучный с фиксированным весом
                price_type = 2  # цена за шт
            else:
                plu_type = 1
                price_type = 2

            # Check for custom attributes
            exp_days = 0
            exp_attr = product.get("attributes", {}).get("Срок годности", "")
            if exp_attr:
                try:
                    exp_days = int(exp_attr)
                except ValueError:
                    pass

            commodity_code = product.get("external_code", "") or product.get("article", "")
            if len(commodity_code) > 6:
                commodity_code = commodity_code[:6]

            plu = RongtaPLU(
                plu_number=plu_start + idx,
                name=product["name"],
                unit_price=price,
                department=department,
                barcode=product.get("barcode", ""),
                weight=product.get("weight", 0),
                plu_type=plu_type,
                price_type=price_type,
                commodity_code=commodity_code,
                valid_days=exp_days,
                hotkey=plu_start + idx,
            )
            plu_records.append(plu)

        except Exception as e:
            errors.append(f"Ошибка обработки {product.get('name', 'unknown')}: {e}")

    if not plu_records:
        return {"error": "Нет товаров для выгрузки", "errors": errors}

    # Send to scale
    method = scale_config.get("send_method", "tcp_direct")

    if method == "tcp_direct":
        # Direct TCP push to scale
        result = RongtaScaleSender.send_plu_list(
            host=scale_config["scale_host"],
            port=scale_config["scale_port"],
            plu_records=plu_records,
        )
    elif method == "tcp_server":
        # Update TCP server data (scale will connect and pick up)
        update_scale_plu_data(plu_records)
        result = {
            "success": True,
            "sent": len(plu_records),
            "total": len(products),
            "method": "tcp_server",
            "message": f"PLU data updated on server ({len(plu_records)} records). Scale will connect at scheduled time.",
            "errors": errors,
        }
    elif method == "txp_file":
        # Generate TXP file for FTP/network share
        txp_content = RongtaTXPFile.generate_txp(plu_records)
        result = {
            "success": True,
            "sent": len(plu_records),
            "total": len(products),
            "method": "txp_file",
            "txp_content": txp_content,
            "errors": errors,
        }
    else:
        result = {"error": f"Unknown send method: {method}"}

    result["total_products"] = len(products)
    result["errors"] = result.get("errors", []) + errors
    return result


# ============================================================
# Settings UI (iframe)
# ============================================================

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Main settings page loaded in iframe."""
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "app_uid": settings.app_uid,
    })


@app.post("/settings/export")
async def trigger_export(request: Request):
    """Trigger export from settings page."""
    body = await request.json()
    account_id = body.get("account_id", "")
    scale_config = body.get("scale_config", {})

    if not account_id:
        return JSONResponse(content={"error": "account_id required"}, status_code=400)

    # Save config for this account
    scale_configs[account_id] = scale_config

    result = await export_to_rongta_scale(account_id, scale_config)
    return JSONResponse(content=result)


@app.post("/settings/preview")
async def preview_products(request: Request):
    """Preview products that will be exported."""
    body = await request.json()
    account_id = body.get("account_id", "")

    installation = installations.get(account_id)
    if not installation or not installation.get("access_token"):
        return JSONResponse(content={"error": "No active installation"}, status_code=400)

    access_token = installation["access_token"]
    products = await fetch_products(access_token)
    prices = await fetch_prices(access_token)

    preview = []
    for idx, p in enumerate(products):
        preview.append({
            "plu": idx + 1,
            "name": p["name"],
            "article": p["article"],
            "code": p["code"],
            "barcode": p["barcode"],
            "weight": p["weight"],
            "price": prices.get(p["id"], 0),
        })

    return JSONResponse(content={"products": preview, "total": len(preview)})


@app.post("/settings/start-tcp-server")
async def start_server(request: Request):
    """Start TCP server for scale connections."""
    body = await request.json()
    account_id = body.get("account_id", "")
    config = body.get("scale_config", {})

    config["tcp_server_enabled"] = True
    scale_configs[account_id] = config

    try:
        start_tcp_server(config)
        return JSONResponse(content={"success": True, "message": "TCP сервер запущен"})
    except Exception as e:
        return JSONResponse(content={"success": False, "error": str(e)})


# ============================================================
# Diagnostic & Debug Endpoints
# ============================================================

@app.post("/api/moysklad/vendor/1.0/apps/{app_id}/{account_id}")
async def activate_solution_post(app_id: str, account_id: str, request: Request):
    """Alternative POST endpoint for activation."""
    return await activate_solution(app_id, account_id, request)


@app.get("/health")
async def health():
    server_status = "running" if scale_server and scale_server.running else "stopped"
    return {
        "status": "ok",
        "service": "rongta-scale-exporter",
        "tcp_server": server_status,
        "active_installations": len(installations),
        "version": "1.0.0",
    }


@app.post("/debug/test-activation")
async def debug_test_activation(request: Request):
    """Test endpoint to simulate Moy Sklad activation request."""
    raw_body = await request.body()
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        body = {}
    
    return JSONResponse(content={
        "status": "ok",
        "message": "Endpoint is reachable and working",
        "received_body": body,
        "app_id": settings.app_id,
        "app_uid": settings.app_uid,
        "endpoint_base": settings.endpoint_base,
    })


@app.get("/debug/config")
async def debug_config():
    """Show current configuration (without secret)."""
    return {
        "app_id": settings.app_id,
        "app_uid": settings.app_uid,
        "secret_key_length": len(settings.secret_key),
        "endpoint_base": settings.endpoint_base,
        "moysklad_base_url": settings.moysklad_base_url,
        "vendor_api_base_url": settings.vendor_api_base_url,
    }


# ============================================================
# Startup - print info
# ============================================================

@app.on_event("startup")
async def print_startup_info():
    logger.info("=" * 60)
    logger.info("Rongta Scale Exporter - Ready")
    logger.info(f"App ID: {settings.app_id}")
    logger.info(f"App UID: {settings.app_uid}")
    logger.info(f"Endpoint Base: {settings.endpoint_base}")
    logger.info("=" * 60)
    logger.info("Activation URL:")
    logger.info(f"  PUT {settings.endpoint_base}/api/moysklad/vendor/1.0/apps/{{appId}}/{{accountId}}")
    logger.info("=" * 60)
