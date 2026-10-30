"""
Rongta RLS1000 — Выгрузка товаров из МоегоСклада в весы.
Поддержка нескольких весов в сети.

Запуск:
  python rongta_export.py              # интерактивный режим
  rongta_export_gui.bat                # запуск с окном (двойной клик)
"""

import json
import os
import sys
import time
import struct
import socket
import urllib.request
import urllib.error
import urllib.parse
import subprocess
import logging
from pathlib import Path
from datetime import datetime

# === Настройки ===
EXPORT_DIR = Path(__file__).parent / "exports"
EXPORT_DIR.mkdir(exist_ok=True)
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "export.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("rongta-export")

# МойСклад
MOYSKLAD_API = "https://api.moysklad.ru/api/remap/1.2"

# === Ронгта протокол ===

def build_packet(command: int, data: bytes = b"") -> bytes:
    length = 4 + len(data)
    return struct.pack(">HH", length, command) + data


def send_plu_to_scale(host: str, port: int, plu_records: list, timeout: int = 10) -> dict:
    """Отправить PLU напрямую в весы по TCP/IP."""
    result = {"host": host, "success": False, "sent": 0, "error": ""}

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))

        # Hello
        sock.sendall(build_packet(0x0201))
        resp = sock.recv(4096)
        if len(resp) < 4:
            result["error"] = "Нет ответа на Hello"
            sock.close()
            return result

        # PLU записи
        for rec in plu_records:
            name_bytes = rec["name"].encode("ascii", errors="replace").ljust(36)[:36]
            barcode_bytes = rec["barcode"].encode("ascii", errors="replace").ljust(13)[:13]

            plu_data = struct.pack(
                ">I 36s I B B 13s I H",
                rec["plu"],           # PLU number
                name_bytes,           # Name
                rec["price_kop"],     # Price (kopecks)
                rec["dept"],          # Department
                rec["plu_type"],      # 0=весовой, 1=штучный
                barcode_bytes,        # Barcode
                rec["weight_g"],      # Weight (grams)
                rec["valid_days"],    # Valid days
            )
            sock.sendall(build_packet(0x0203, plu_data))
            result["sent"] += 1
            time.sleep(0.02)

        # End
        sock.sendall(build_packet(0x0205))
        sock.close()
        result["success"] = True

    except socket.timeout:
        result["error"] = "Таймаут"
    except ConnectionRefusedError:
        result["error"] = "Отказано в подключении"
    except Exception as e:
        result["error"] = str(e)

    return result


# === Авторизация ===

def get_token(username: str, password: str) -> str:
    # Основной endpoint
    urls = [
        MOYSKLAD_API + "/security/token",
        "https://api.moysklad.ru/api/remap/1.2/security/token",
    ]

    headers_list = [
        {"Content-Type": "application/json", "Accept": "application/json", "Accept-Encoding": "gzip"},
        {"Content-Type": "application/json", "Accept": "application/json"},
        {"Content-Type": "application/json;charset=UTF-8", "Accept": "application/json"},
    ]

    data = json.dumps({"username": username, "password": password}, ensure_ascii=False).encode("utf-8")

    for url in urls:
        for headers in headers_list:
            try:
                req = urllib.request.Request(url, data=data, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    token = result.get("access_token", "")
                    if token:
                        return token
                    print(f"  Ответ без токена: {json.dumps(result, ensure_ascii=False)}")
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                print(f"  {e.code} headers={list(headers.keys())}")
                if e.code == 401:
                    print(f"    {body[:200]}")
                elif e.code == 415:
                    pass  # Пропускаем 415
            except Exception as e:
                print(f"  Exception: {e}")

    # Пробуем Basic Auth
    print("  Пробую Basic Auth...")
    import base64
    creds = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
    headers_basic = {
        "Authorization": f"Basic {creds}",
        "Accept": "application/json",
    }
    try:
        req = urllib.request.Request(urls[0], headers=headers_basic)
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            token = result.get("access_token", "")
            if token:
                return token
            print(f"  Basic Auth ответ: {json.dumps(result, ensure_ascii=False)[:200]}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  Basic Auth: {e.code} {body[:200]}")
    except Exception as e:
        print(f"  Basic Auth error: {e}")

    return ""


def load_config() -> dict:
    config_file = Path(__file__).parent / "export_config.json"
    if config_file.exists():
        try:
            return json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_config(config: dict):
    config_file = Path(__file__).parent / "export_config.json"
    config_file.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


# === API ===

def api_request(url: str, token: str) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"API error {url}: {e}")
        return {}


def fetch_products(token: str) -> list:
    """Загрузить все товары из МС."""
    print("  Загрузка групп товаров...")
    folders = []
    url = MOYSKLAD_API + "/entity/productfolder?limit=100"
    while url:
        data = api_request(url, token)
        if not data:
            break
        for row in data.get("rows", []):
            folders.append({"id": row.get("id", ""), "name": row.get("name", "")})
        url = data.get("meta", {}).get("nextHref")

    folder_map = {f["id"]: idx + 1 for idx, f in enumerate(folders)}

    print("  Загрузка товаров...")
    products = []
    url = MOYSKLAD_API + "/entity/product?limit=100&expand=salePrices"
    while url:
        data = api_request(url, token)
        if not data:
            break

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
                pt = sp.get("priceType", {}).get("name", "")
                if pt in ["Цена продажи", "Розничная"]:
                    price = sp.get("value", 0) / 100
                    break
            else:
                if sale_prices:
                    price = sale_prices[0].get("value", 0) / 100

            folder_ref = row.get("productFolder", {})
            folder_id = folder_ref.get("id", "") if folder_ref else ""

            products.append({
                "name": row.get("name", ""),
                "article": row.get("article", ""),
                "externalCode": row.get("externalCode", ""),
                "barcode": barcode,
                "weight": row.get("weight", 0),
                "isWeightProduct": row.get("weighed", False),
                "price": price,
                "folderIndex": folder_map.get(folder_id, 0),
            })

        url = data.get("meta", {}).get("nextHref")
        print(f"    Загружено {len(products)}...")

    return products


def products_to_plu(products: list, plu_start: int = 1, dept_start: int = 1) -> list:
    """Конвертировать товары в PLU-записи."""
    records = []
    for idx, p in enumerate(products):
        records.append({
            "plu": plu_start + idx,
            "name": (p.get("name", "") or "")[:36],
            "fresh_code": (p.get("externalCode", "") or p.get("article", ""))[:6],
            "dept": min(dept_start + (p.get("folderIndex", 0)), 99),
            "price_kop": int((p.get("price", 0) or 0) * 100),
            "weight_g": int((p.get("weight", 0) or 0) * 1000),
            "plu_type": 0 if p.get("isWeightProduct") else 1,
            "price_type": 0 if p.get("isWeightProduct") else 2,
            "barcode": (p.get("barcode", "") or "")[:13],
            "valid_days": 0,
        })
    return records


def generate_txp(products: list, plu_start: int = 1, dept_start: int = 1) -> str:
    """Сформировать TXP-файл."""
    lines = [
        "Hotkey\tPLU Name\tFresh Commodity Code\tDepartment\tUnit Price\tWeight\t"
        "PLU Type\tPrice Type\tLabel Type\tBarcode\tBarcode Format\tValid Days\tPacking Type"
    ]
    for p in products:
        price_kop = int((p.get("price", 0) or 0) * 100)
        weight_g = int((p.get("weight", 0) or 0) * 1000)
        is_weight = 0 if p.get("isWeightProduct") else 1
        dept = min(dept_start + (p.get("folderIndex", 0)), 99)

        lines.append("\t".join([
            str(plu_start + products.index(p)),
            (p.get("name", "") or "")[:36],
            (p.get("externalCode", "") or p.get("article", ""))[:6],
            str(dept),
            str(price_kop),
            str(weight_g),
            str(is_weight),
            str(0 if is_weight == 0 else 2),
            "0",
            (p.get("barcode", "") or "")[:13],
            "0", "0", "0",
        ]))
    return "\n".join(lines)


# === Main ===

def main():
    print("=" * 60)
    print("  Rongta RLS1000 — Выгрузка товаров из МоегоСклада")
    print("=" * 60)

    config = load_config()

    # --- Логин / Пароль ---
    username = config.get("username", "")
    password = config.get("password", "")

    if username and password:
        print(f"\nЛогин: {username}")
        save_creds = input("Использовать сохранённые данные? (y/n, по умолчанию y): ").strip().lower()
        if save_creds == "n":
            username = ""
            password = ""

    if not username:
        username = input("\nЛогин МойСклад (email): ").strip()
    if not password:
        password = input("Пароль МойСклад: ").strip()

    if not username or not password:
        print("Логин и пароль обязательны!")
        return

    print("\nАвторизация...")
    token = get_token(username, password)
    if not token:
        print("❌ Ошибка авторизации! Проверьте логин и пароль.")
        input("\nНажмите Enter для выхода...")
        return

    print("✅ Авторизация успешна!")

    # Сохраняем credentials
    config["username"] = username
    config["password"] = password

    # --- IP адреса весов ---
    saved_scales = config.get("scales", [])
    if saved_scales:
        print(f"\nСохранённые весы: {', '.join(s['ip'] for s in saved_scales)}")
        use_saved = input("Использовать их? (y/n, по умолчанию y): ").strip().lower()
        if use_saved == "n":
            saved_scales = []

    if not saved_scales:
        print("\nВведите IP адреса весов через запятую (например: 192.168.1.100, 192.168.1.101):")
        ips_input = input("IP: ").strip()
        default_port = int(config.get("default_port", 9102))
        port_input = input(f"Порт (по умолчанию {default_port}): ").strip()
        port = int(port_input) if port_input else default_port

        for ip in ips_input.split(","):
            ip = ip.strip()
            if ip:
                saved_scales.append({"ip": ip, "port": port})

    config["scales"] = saved_scales
    config["default_port"] = saved_scales[0]["port"] if saved_scales else 9102
    save_config(config)

    if not saved_scales:
        print("❌ Не указаны IP адреса весов!")
        input("\nНажмите Enter для выхода...")
        return

    # --- Загрузка товаров ---
    print("\nЗагрузка товаров из МоегоСклада...")
    products = fetch_products(token)

    if not products:
        print("❌ Товары не загружены!")
        input("\nНажмите Enter для выхода...")
        return

    print(f"\n✅ Загружено {len(products)} товаров")

    # --- Формирование PLU ---
    plu_start = int(config.get("plu_start", 1))
    dept_start = int(config.get("dept_start", 1))
    plu_records = products_to_plu(products, plu_start, dept_start)

    # --- Отправка в весы ---
    print(f"\nОтправка в {len(saved_scales)} весов...")
    results = []

    for scale in saved_scales:
        ip = scale["ip"]
        port = scale.get("port", 9102)
        print(f"\n  → {ip}:{port}...")

        result = send_plu_to_scale(ip, port, plu_records)
        results.append(result)

        if result["success"]:
            print(f"    ✅ Отправлено {result['sent']} PLU")
        else:
            print(f"    ❌ Ошибка: {result['error']}")

    # --- Итог ---
    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count

    print("\n" + "=" * 60)
    print(f"  Итого: {success_count} успешно, {fail_count} ошибок")

    # --- Сохранение TXP ---
    txp_content = generate_txp(products, plu_start, dept_start)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    txp_path = EXPORT_DIR / f"rongta_plu_{timestamp}.txp"
    txp_path.write_text(txp_content, encoding="utf-8")
    print(f"\n  TXP сохранён: {txp_path}")

    # --- Открыть в PLU Manager (опционально) ---
    plu_manager = r"C:\Program Files (x86)\RLS1000\RTPLU.exe"
    if os.path.exists(plu_manager):
        open_plu = input("\nОткрыть TXP в PLU Manager для ручной отправки? (y/n): ").strip().lower()
        if open_plu == "y":
            subprocess.Popen([plu_manager, str(txp_path)])

    input("\nНажмите Enter для выхода...")


if __name__ == "__main__":
    main()
