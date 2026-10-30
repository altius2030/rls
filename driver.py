"""
Rongta RLS1000 — Драйвер для Windows
Получает TXP-файл и отправляет в весы по TCP/IP.

Запуск:
  python driver.py                   # Запуск в фоне
  python driver.py --file plu.txp    # Отправить файл напрямую
  python driver.py --install         # Регистрация URI-протокола
  python driver.py --host 192.168.1.100 --port 9102
"""

import sys
import os
import time
import socket
import struct
import logging
import argparse
from pathlib import Path

# === Настройки ===
DEFAULT_SCALE_HOST = "192.168.1.87"  # IP RLS1000 по умолчанию
DEFAULT_SCALE_PORT = 9102
BUFFER_SIZE = 4096

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "driver.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("rongta-driver")


# === Протокол Rongta RLS1000 ===

def build_packet(command: int, data: bytes = b"") -> bytes:
    """Построить пакет протокола Rongta."""
    length = 4 + len(data)  # 2 байта length + 2 байта command + data
    return struct.pack(">HH", length, command) + data


def parse_response(data: bytes) -> tuple:
    """Разобрать ответный пакет."""
    if len(data) < 4:
        return 0, b""
    length, command = struct.unpack(">HH", data[:4])
    return command, data[4:length]


def parse_txp_file(filepath: str) -> list:
    """
    Разобрать TXP-файл и получить список PLU.
    
    Формат TXP (табуляция):
    Hotkey  PLU Name  FreshCode  Department  UnitPrice  Weight  PLU Type  Price Type  Label Type  Barcode  BarcodeFormat  ValidDays  PackingType
    """
    records = []
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    if not lines:
        return records
    
    # Пропускаем заголовок
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        
        try:
            record = {
                "hotkey": int(parts[0]) if parts[0] else 1,
                "name": parts[1][:36],
                "fresh_code": parts[2][:6] if len(parts) > 2 else "",
                "department": int(parts[3]) if len(parts) > 3 and parts[3] else 1,
                "unit_price_kopecks": int(parts[4]) if len(parts) > 4 and parts[4] else 0,
                "weight_grams": int(parts[5]) if len(parts) > 5 and parts[5] else 0,
                "plu_type": int(parts[6]) if len(parts) > 6 and parts[6] else 0,
                "price_type": int(parts[7]) if len(parts) > 7 and parts[7] else 0,
                "label_type": int(parts[8]) if len(parts) > 8 and parts[8] else 0,
                "barcode": parts[9][:13] if len(parts) > 9 else "",
                "barcode_format": int(parts[10]) if len(parts) > 10 and parts[10] else 0,
                "valid_days": int(parts[11]) if len(parts) > 11 and parts[11] else 0,
                "packing_type": int(parts[12]) if len(parts) > 12 and parts[12] else 0,
            }
            records.append(record)
        except (ValueError, IndexError) as e:
            logger.warning(f"Пропущена строка: {line[:50]}... Ошибка: {e}")
    
    return records


def send_plu_to_scale(host: str, port: int, records: list) -> dict:
    """
    Отправить PLU-записи в весы Rongta RLS1000.
    """
    result = {"success": False, "sent": 0, "total": len(records), "errors": []}
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((host, port))
        logger.info(f"Подключено к весам {host}:{port}")
        
        # 1. Hello-пакет
        hello = build_packet(0x0201)
        sock.sendall(hello)
        logger.info("Отправлен Hello-пакет")
        
        # Ответ
        resp = sock.recv(BUFFER_SIZE)
        cmd, _ = parse_response(resp)
        if cmd == 0x0102:
            logger.info("Весы ответили: OK")
        else:
            logger.warning(f"Неожиданный ответ: 0x{cmd:04X}")
        
        # 2. Отправка PLU-записей
        for rec in records:
            # Формируем бинарную запись PLU
            name_bytes = rec["name"].encode("ascii", errors="replace").ljust(36)[:36]
            barcode_bytes = rec["barcode"].encode("ascii", errors="replace").ljust(13)[:13]
            
            # PLU binary format
            plu_data = struct.pack(
                ">I 36s I B B 13s I H",
                rec["hotkey"],       # PLU number
                name_bytes,           # Name (36 bytes)
                rec["unit_price_kopecks"],  # Price in kopecks
                rec["department"],    # Department (1 byte)
                rec["plu_type"],      # Type (0=weight, 1=piece)
                barcode_bytes,        # Barcode (13 bytes)
                rec["weight_grams"],  # Weight in grams
                rec["valid_days"],    # Valid days
            )
            
            packet = build_packet(0x0203, plu_data)
            sock.sendall(packet)
            result["sent"] += 1
            
            if result["sent"] % 50 == 0:
                logger.info(f"Отправлено {result['sent']} PLU...")
            
            time.sleep(0.02)  # Небольшая задержка
        
        # 3. End-пакет
        end = build_packet(0x0205)
        sock.sendall(end)
        logger.info("Отправлен End-пакет")
        
        # Финальный ответ
        try:
            final = sock.recv(BUFFER_SIZE)
            cmd, _ = parse_response(final)
            logger.info(f"Финальный ответ: 0x{cmd:04X}")
        except socket.timeout:
            pass
        
        sock.close()
        result["success"] = True
        logger.info(f"Выгрузка завершена: {result['sent']} PLU отправлено")
        
    except socket.timeout:
        result["errors"].append("Таймаут подключения к весам")
        logger.error("Таймаут подключения к весам")
    except ConnectionRefusedError:
        result["errors"].append(f"Весы отказали в подключении: {host}:{port}")
        logger.error(f"Весы отказали в подключении: {host}:{port}")
    except Exception as e:
        result["errors"].append(str(e))
        logger.error(f"Ошибка: {e}")
    
    return result


def install_uri_protocol():
    """Регистрация кастомного URI-протокола rongta:// в Windows."""
    try:
        import winreg
        
        exe_path = os.path.abspath(sys.argv[0])
        if exe_path.endswith(".py"):
            # Для Python-скрипта используем pythonw
            python_dir = os.path.dirname(sys.executable)
            pythonw = os.path.join(python_dir, "pythonw.exe")
            if not os.path.exists(pythonw):
                pythonw = os.path.join(python_dir, "python.exe")
            command = f'"{pythonw}" "{exe_path}" --protocol "%1"'
        else:
            # Для .exe
            command = f'"{exe_path}" --protocol "%1"'
        
        # Регистрация протокола
        key_path = r"SOFTWARE\Classes\rongta"
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:Rongta Scale Protocol")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
            
            with winreg.CreateKeyEx(key, r"shell\open\command", 0, winreg.KEY_WRITE) as cmd_key:
                winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, command)
        
        logger.info(f"URI-протокол rongta:// зарегистрирован")
        print(f"✅ Протокол rongta:// зарегистрирован")
        print(f"   Команда: {command}")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка регистрации протокола: {e}")
        print(f"❌ Ошибка: {e}")
        return False


def handle_protocol_call(url: str):
    """Обработка вызова rongta://export?file=...&driver=..."""
    logger.info(f"Получен вызов протокола: {url}")
    
    # Парсим параметры
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    
    filepath = params.get("file", [""])[0]
    host = params.get("host", [DEFAULT_SCALE_HOST])[0]
    port = int(params.get("port", [DEFAULT_SCALE_PORT])[0])
    
    if not filepath or not os.path.exists(filepath):
        logger.error(f"TXP-файл не найден: {filepath}")
        print(f"❌ Файл не найден: {filepath}")
        return
    
    records = parse_txp_file(filepath)
    if not records:
        logger.error("TXP-файл пуст или некорректен")
        return
    
    logger.info(f"Загружено {len(records)} PLU из {filepath}")
    result = send_plu_to_scale(host, port, records)
    
    if result["success"]:
        logger.info(f"✅ Успешно отправлено {result['sent']} PLU в весы")
    else:
        logger.error(f"❌ Ошибка отправки: {result['errors']}")


# === Главная функция ===

def main():
    parser = argparse.ArgumentParser(description="Rongta RLS1000 Scale Driver")
    parser.add_argument("--file", "-f", help="TXP-файл для отправки")
    parser.add_argument("--host", default=DEFAULT_SCALE_HOST, help="IP весов")
    parser.add_argument("--port", type=int, default=DEFAULT_SCALE_PORT, help="Порт весов")
    parser.add_argument("--install", action="store_true", help="Регистрация URI-протокола")
    parser.add_argument("--protocol", help="Обработка вызова URI-протокола")
    
    args = parser.parse_args()
    
    logger.info("=" * 50)
    logger.info("Rongta RLS1000 Scale Driver")
    logger.info("=" * 50)
    
    if args.protocol:
        handle_protocol_call(args.protocol)
        return
    
    if args.install:
        install_uri_protocol()
        return
    
    if args.file:
        records = parse_txp_file(args.file)
        logger.info(f"Загружено {len(records)} PLU")
        result = send_plu_to_scale(args.host, args.port, records)
        
        if result["success"]:
            print(f"\n✅ Готово! Отправлено {result['sent']} PLU в весы {args.host}:{args.port}")
        else:
            print(f"\n❌ Ошибка: {result['errors']}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
