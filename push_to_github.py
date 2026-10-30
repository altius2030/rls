import json
import urllib.request
import base64
import os

TOKEN = os.environ.get("GH_TOKEN", "")
REPO = "altius2030/rls"

def create_file(path: str, content: str):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    data = json.dumps({
        "message": f"Add {path}",
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
    }).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/vnd.github.v3+json")
    try:
        with urllib.request.urlopen(req) as resp:
            return {"path": path, "status": resp.status, "ok": True}
    except Exception as e:
        return {"path": path, "ok": False, "error": str(e)}

# Files to create
files = {
    "requirements.txt": "fastapi==0.115.0\nuvicorn==0.32.0\n",
    "railway.json": json.dumps({
        "$schema": "https://railway.app/railway.schema.json",
        "build": {"builder": "NIXPACKS"},
        "deploy": {
            "startCommand": "python -m uvicorn vendor_api_minimal:app --host 0.0.0.0 --port $PORT",
            "healthcheckPath": "/health"
        }
    }, indent=2),
    "vendor_api_minimal.py": '''import json
import logging
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse

app = FastAPI()

@app.put("/api/moysklad/vendor/1.0/apps/{app_id}/{account_id}")
async def activate(app_id: str, account_id: str, request: Request):
    return JSONResponse(content={"status": "Activated"})

@app.delete("/api/moysklad/vendor/1.0/apps/{app_id}/{account_id}")
async def deactivate(app_id: str, account_id: str, request: Request):
    return JSONResponse(content={}, status_code=200)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    html_path = Path(__file__).resolve().parent / "iframe" / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Not found</h1>", status_code=404)

@app.get("/download/rongta_send.py")
async def download_script():
    script_path = Path(__file__).resolve().parent / "rongta_send.py"
    if script_path.exists():
        return PlainTextResponse(
            content=script_path.read_text(encoding="utf-8"),
            headers={"Content-Disposition": "attachment; filename=rongta_send.py"}
        )
    return PlainTextResponse(content="# Not found", status_code=404)
''',
}

results = []
for path, content in files.items():
    r = create_file(path, content)
    print(r)
