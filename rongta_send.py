#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rongta RLS1000 — Отправка TXP-файла в весы (для ПК).

Запуск:
  python rongta_send.py                          # интерактивный режим
  python rongta_send.py --file plu.txp           # указать файл
  python rongta_send.py --file plu.txp --ips 192.168.1.100 192.168.1.101
"""

import os
import sys
import json
import time
import struct
import socket
import argparse
import logging
from pathlib import Path
from datetime import datetime

# === Настройки ===
DEFAULT_PORT = 9102
CONFIG_FILE = Path(__file__).parent / "send_config.json"
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "send.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("rongta-send")


# === Протокол Rongta ===

def build_packet(command: int, data: bytes = b"") -> bytes:
    """Построить пакет протокола Rongta."""
    length = 4 + len(data)
    return struct.pack(">HH", length, command) + data


def parse_txp(filepath: str) -> list:
    """Разобрать TXP-файл."""
    records = []
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines[1:]:  # Пропускаем заголовок
        parts = line.strip().split("\t")
        if len(parts) < 5:
            continue
        try:
            records.append({
                "plu": int(parts[0]),
                "name": parts[1][:36],
                "fresh_code": parts[2][:6] if len(parts) > 2 else "",
                "dept": int(parts[3]) if len(parts) > 3 and parts[3] else 1,
                "price_kop": int(parts[4]) if len(parts) > 4 and parts[4] else 0,
                "weight_g": int(parts[5]) if len(parts) > 5 and parts[5] else 0,
                "plu_type": int(parts[6]) if len(parts) > 6 and parts[6] else 0,
                "barcode": parts[9][:13] if len(parts) > 9 else "",
                "valid_days": int(parts[11]) if len(parts) > 11 and parts[11] else 0,
            })
        except (ValueError, IndexError):
            continue

    return records


def send_to_scale(host: str, port: int, records: list, timeout: int = 10) -> dict:
    """Отправить PLU в весы по TCP/IP."""
    result = {"host": host, "port": port, "success": False, "sent": 0, "error": ""}

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))

        # Hello
        sock.sendall(build_packet(0x0201))
        resp = sock.recv(4096)
        if len(resp) < 4:
            result["error"] = "Нет ответа"
            sock.close()
            return result

        # PLU записи
        for rec in records:
            name_bytes = rec["name"].encode("ascii", errors="replace").ljust(36)[:36]
            barcode_bytes = rec["barcode"].encode("ascii", errors="replace").ljust(13)[:13]

            plu_data = struct.pack(
                ">I 36s I B B 13s I H",
                rec["plu"],
                name_bytes,
                rec["price_kop"],
                rec["dept"],
                rec["plu_type"],
                barcode_bytes,
                rec["weight_g"],
                rec["valid_days"],
            )
            sock.sendall(build_packet(0x0203, plu_data))
            result["sent"] += 1
            time.sleep(0.02)

        # End
        sock.sendall(build_packet(0x0205))
        try:
            sock.recv(4096)
        except socket.timeout:
            pass
        sock.close()
        result["success"] = True

    except socket.timeout:
        result["error"] = "Таймаут подключения"
    except ConnectionRefusedError:
        result["error"] = "Отказано в подключении"
    except OSError as e:
        result["error"] = str(e)

    return result


# === Main ===

def main():
    print("=" * 60)
    print("  Rongta RLS1000 — Отправка TXP в весы")
    print("=" * 60)

    # Загружаем конфиг
    config = {}
    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    # --- Файл TXP ---
    txp_file = None
    if len(sys.argv) > 2 and sys.argv[1] == "--file":
        txp_file = sys.argv[2]
    elif config.get("last_file") and Path(config["last_file"]).exists():
        print(f"\nПоследний файл: {config['last_file']}")
        use_last = input("Использовать его? (y/n, по умолчанию y): ").strip().lower()
        if use_last != "n":
            txp_file = config["last_file"]

    if not txp_file:
        txp_file = input("\nПуть к TXP-файлу: ").strip()

    if not txp_file or not os.path.exists(txp_file):
        print("Файл не найден!")
        return

    # --- IP адреса ---
    saved_scales = config.get("scales", [])
    if saved_scales:
        print(f"\nСохранённые весы: {', '.join(s['ip'] for s in saved_scales)}")
        use_saved = input("Использовать их? (y/n, по умолчанию y): ").strip().lower()
        if use_saved == "n":
            saved_scales = []

    if not saved_scales:
        print("\nВведите IP адреса весов через запятую:")
        ips_input = input("IP: ").strip()
        port_input = input("Порт (по умолчанию 9102): ").strip()
        port = int(port_input) if port_input else DEFAULT_PORT

        for ip in ips_input.split(","):
            ip = ip.strip()
            if ip:
                saved_scales.append({"ip": ip, "port": port})

    if not saved_scales:
        print("Не указаны IP адреса!")
        return

    # Сохраняем
    config["scales"] = saved_scales
    config["last_file"] = txp_file
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")

    # --- Парсим TXP ---
    print(f"\nЗагрузка TXP: {txp_file}")
    records = parse_txp(txp_file)
    print(f"  Найдено {len(records)} PLU-записей")

    if not records:
        print("Файл пуст или некорректен!")
        return

    # --- Отправка ---
    print(f"\nОтправка в {len(saved_scales)} весов...\n")
    results = []

    for scale in saved_scales:
        ip = scale["ip"]
        port = scale.get("port", DEFAULT_PORT)
        print(f"  → {ip}:{port} ...")

        result = send_to_scale(ip, port, records)
        results.append(result)

        if result["success"]:
            print(f"    ✅ {result['sent']} PLU отправлено")
        else:
            print(f"    ❌ {result['error']}")

    # --- Итог ---
    ok = sum(1 for r in results if r["success"])
    fail = len(results) - ok
    print(f"\n{'=' * 40}")
    print(f"  Результат: {ok} успешно, {fail} ошибок")


if __name__ == "__main__":
    main()
    input("\nНажмите Enter для выхода...")
