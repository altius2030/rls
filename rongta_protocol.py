"""
Rongta RLS1000 TCP/IP Protocol Implementation

Протокол обмена данными с весами Rongta RLS1000.

Формат пакета (бинарный):
  - Packet Length: 2 байта (big-endian), общая длина пакета включая заголовок
  - Command: 2 байта (big-endian), код команды
  - Data: переменная длина, данные команды

Пример пакетов:
  Start command:      0008 0201 (length=8, cmd=0x0201, no data)
  Response command:   0022 0102 02100000010000 (length=34, cmd=0x0102, data)

Команды:
  0x0201 - Start/Hello (инициатор - сервер)
  0x0102 - Response to Start (ответ весов)
  0x0203 - Send PLU data
  0x0104 - Acknowledge PLU data
  0x0205 - End session
  0x0106 - Final acknowledge

Режимы работы:
  1. TCP/IP mode: Весы подключаются к серверу, обмен бинарными пакетами
  2. TXP/TXU files: Текстовые файлы PLU, передаются через FTP/сетевую папку
"""

import struct
import socket
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RongtaPacket:
    """Rongta RLS1000 binary packet."""
    command: int
    data: bytes = b""

    @property
    def length(self) -> int:
        """Total packet length (header + data)."""
        return 4 + len(self.data)  # 2 bytes length + 2 bytes command + data

    def to_bytes(self) -> bytes:
        """Serialize packet to bytes."""
        packet_len = self.length
        header = struct.pack(">HH", packet_len, self.command)
        return header + self.data

    @classmethod
    def from_bytes(cls, data: bytes) -> "RongtaPacket":
        """Deserialize packet from bytes."""
        if len(data) < 4:
            raise ValueError("Packet too short")
        packet_len, command = struct.unpack(">HH", data[:4])
        payload = data[4:packet_len]
        return cls(command=command, data=payload)

    def __repr__(self):
        return f"RongtaPacket(cmd=0x{self.command:04X}, len={self.length}, data={self.data.hex()})"


class RongtaPLU:
    """PLU record for Rongta RLS1000 scale."""

    def __init__(
        self,
        plu_number: int,
        name: str,
        unit_price: float,
        department: int = 1,
        barcode: str = "",
        weight: float = 0.0,
        tare_weight: float = 0.0,
        expiration_days: int = 0,
        hotkey: int = 0,
        commodity_code: str = "",
        plu_type: int = 0,  # 0=весовой, 1=штучный
        price_type: int = 0,  # 0=цена за кг, 1=цена за 100г, 2=цена за шт
        label_type: int = 0,  # тип этикетки
        barcode_format: int = 0,  # формат штрихкода
        valid_days: int = 0,
        packing_type: int = 0,
    ):
        self.plu_number = plu_number
        self.name = name[:36]  # Max 36 chars per manual
        self.unit_price = unit_price  # Price in rubles (per kg or per piece)
        self.department = department
        self.barcode = barcode[:13]
        self.weight = weight
        self.tare_weight = tare_weight
        self.expiration_days = expiration_days
        self.hotkey = hotkey if hotkey > 0 else plu_number
        self.commodity_code = commodity_code[:6]  # 6-digit code
        self.plu_type = plu_type
        self.price_type = price_type
        self.label_type = label_type
        self.barcode_format = barcode_format
        self.valid_days = valid_days
        self.packing_type = packing_type

    def to_txp_line(self) -> str:
        """
        Convert to TXP file line format.

        TXP format is tab-delimited with the following columns:
        A: Hotkey (1-224)
        B: PLU Name (up to 36 chars)
        C: Fresh Commodity Code (6 digits)
        D: Department (1-99)
        E: Unit Price (in kopecks for per-kg items)
        F: Weight / Tare
        G: PLU Type (0=weight, 1=piece)
        H: Price Type (0=per kg, 1=per 100g, 2=per piece)
        I: Label Type
        J: Barcode
        K: Barcode Format
        L: Valid Days
        M: Packing Type
        """
        price_kopecks = int(self.unit_price * 100)
        weight_grams = int(self.weight * 1000)
        tare_grams = int(self.tare_weight * 1000)

        fields = [
            str(self.hotkey),          # A: Hotkey
            self.name,                 # B: PLU Name
            self.commodity_code,       # C: Fresh Commodity Code
            str(self.department),      # D: Department
            str(price_kopecks),        # E: Unit Price (kopecks)
            str(weight_grams),         # F: Weight (grams)
            str(self.plu_type),        # G: PLU Type
            str(self.price_type),      # H: Price Type
            str(self.label_type),      # I: Label Type
            self.barcode,              # J: Barcode
            str(self.barcode_format),  # K: Barcode Format
            str(self.valid_days),      # L: Valid Days
            str(self.packing_type),    # M: Packing Type
        ]
        return "\t".join(fields) + "\n"

    def to_binary_data(self) -> bytes:
        """
        Convert to binary format for TCP/IP protocol.

        Binary PLU record format (simplified based on RLS1000 protocol):
        - PLU Number: 4 bytes
        - Name: 36 bytes (ASCII, padded with spaces)
        - Price: 4 bytes (kopecks)
        - Department: 1 byte
        - Type: 1 byte
        - Barcode: 13 bytes (ASCII)
        - Weight: 4 bytes (grams)
        - Valid Days: 2 bytes
        """
        name_bytes = self.name.encode("ascii", errors="replace").ljust(36)[:36]
        barcode_bytes = self.barcode.encode("ascii", errors="replace").ljust(13)[:13]
        price_kopecks = int(self.unit_price * 100)
        weight_grams = int(self.weight * 1000)

        record = struct.pack(
            ">I 36s I B B 13s I H",
            self.plu_number,
            name_bytes,
            price_kopecks,
            self.department,
            self.plu_type,
            barcode_bytes,
            weight_grams,
            self.valid_days,
        )
        return record


class RongtaScaleServer:
    """
    TCP server that handles Rongta RLS1000 scale connections.

    The scale connects to this server at scheduled times to:
    1. Upload sales data (running account)
    2. Download updated PLU data
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 9102):
        self.host = host
        self.port = port
        self.server_socket = None
        self.running = False
        self.plu_records: list[RongtaPLU] = []
        self.on_plu_requested = None  # Callback when scale requests PLU data

    def set_plu_data(self, records: list[RongtaPLU]):
        """Set PLU data to send to scale."""
        self.plu_records = records

    def start(self):
        """Start the TCP server."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.settimeout(1.0)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.running = True
        logger.info(f"Rongta scale server started on {self.host}:{self.port}")

        while self.running:
            try:
                client_socket, addr = self.server_socket.accept()
                logger.info(f"Scale connected from {addr}")
                self._handle_client(client_socket, addr)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.error(f"Server error: {e}")

    def stop(self):
        """Stop the server."""
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        logger.info("Rongta scale server stopped")

    def _handle_client(self, client_socket: socket.socket, addr: tuple):
        """Handle a scale connection."""
        try:
            client_socket.settimeout(30)

            # Step 1: Receive Hello from scale
            data = client_socket.recv(1024)
            if not data:
                return

            packet = RongtaPacket.from_bytes(data)
            logger.info(f"Received: {packet}")

            if packet.command == 0x0201:
                # Scale sent Hello - respond with acknowledgment
                response = RongtaPacket(command=0x0102, data=b"\x02\x10\x00\x00\x01\x00\x00")
                client_socket.sendall(response.to_bytes())
                logger.info(f"Sent Hello response")

            # Step 2: Wait for PLU request or send PLU data
            data = client_socket.recv(1024)
            if data:
                packet = RongtaPacket.from_bytes(data)
                logger.info(f"Received: {packet}")

                if packet.command == 0x0203:
                    # Scale is ready to receive PLU data
                    self._send_plu_data(client_socket)

            # Step 3: End session
            end_packet = RongtaPacket(command=0x0205)
            client_socket.sendall(end_packet.to_bytes())
            logger.info(f"Session ended with {addr}")

        except socket.timeout:
            logger.warning(f"Timeout with {addr}")
        except Exception as e:
            logger.error(f"Error handling client {addr}: {e}")
        finally:
            client_socket.close()

    def _send_plu_data(self, client_socket: socket.socket):
        """Send PLU records to the scale."""
        for plu in self.plu_records:
            plu_data = plu.to_binary_data()
            packet = RongtaPacket(command=0x0203, data=plu_data)
            try:
                client_socket.sendall(packet.to_bytes())
                logger.debug(f"Sent PLU {plu.plu_number}: {plu.name}")
            except Exception as e:
                logger.error(f"Error sending PLU {plu.plu_number}: {e}")
                break
            time.sleep(0.05)  # Small delay between records


class RongtaTXPFile:
    """Generator for Rongta TXP/TXU PLU files."""

    HEADER = (
        "Hotkey\tPLU Name\tFresh Commodity Code\tDepartment\t"
        "Unit Price\tWeight\tPLU Type\tPrice Type\tLabel Type\t"
        "Barcode\tBarcode Format\tValid Days\tPacking Type\n"
    )

    @staticmethod
    def generate_txp(plu_records: list[RongtaPLU]) -> str:
        """Generate TXP file content (full PLU data)."""
        lines = [RongtaTXPFile.HEADER]
        for plu in plu_records:
            lines.append(plu.to_txp_line())
        return "".join(lines)

    @staticmethod
    def generate_txu(plu_records: list[RongtaPLU]) -> str:
        """Generate TXU file content (incremental update - add/modify)."""
        lines = [RongtaTXPFile.HEADER]
        for plu in plu_records:
            lines.append(plu.to_txp_line())
        return "".join(lines)

    @staticmethod
    def generate_delete_txu(plu_numbers: list[int]) -> str:
        """Generate TXU file for PLU deletion."""
        lines = [RongtaTXPFile.HEADER]
        for num in plu_numbers:
            lines.append(f"{num}\tDELETE\t\t\t\t\t\t\t\t\t\t\t\n")
        return "".join(lines)


class RongtaScaleSender:
    """
    Direct TCP sender for pushing PLU data to Rongta scales.

    For cases where the server pushes data to the scale
    (opposite of the normal flow where scale connects to server).
    """

    @staticmethod
    def send_plu_list(
        host: str,
        port: int,
        plu_records: list[RongtaPLU],
        timeout: int = 10,
    ) -> dict:
        """
        Send PLU list directly to scale via TCP.

        Args:
            host: Scale IP address
            port: Scale TCP port
            plu_records: List of PLU records
            timeout: Connection timeout

        Returns:
            Result dict with success status and details
        """
        results = {
            "success": False,
            "sent": 0,
            "total": len(plu_records),
            "errors": [],
        }

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))

            # Send Hello packet
            hello = RongtaPacket(command=0x0201)
            sock.sendall(hello.to_bytes())

            # Wait for response
            response_data = sock.recv(1024)
            response = RongtaPacket.from_bytes(response_data)

            if response.command == 0x0102:
                logger.info("Scale acknowledged connection")

                # Send each PLU
                for plu in plu_records:
                    try:
                        plu_data = plu.to_binary_data()
                        packet = RongtaPacket(command=0x0203, data=plu_data)
                        sock.sendall(packet.to_bytes())
                        results["sent"] += 1
                        logger.info(f"Sent PLU {plu.plu_number}: {plu.name}")
                        time.sleep(0.05)
                    except Exception as e:
                        error = f"Error sending PLU {plu.plu_number}: {e}"
                        results["errors"].append(error)
                        logger.error(error)

            # Send End packet
            end = RongtaPacket(command=0x0205)
            sock.sendall(end.to_bytes())

            sock.close()
            results["success"] = results["sent"] == results["total"]

        except socket.timeout:
            results["errors"].append("Connection timeout")
        except ConnectionRefusedError:
            results["errors"].append("Connection refused")
        except Exception as e:
            results["errors"].append(f"Connection error: {e}")

        return results

    @staticmethod
    def send_txp_file(host: str, port: int, txp_content: str, timeout: int = 10) -> dict:
        """
        Send TXP file content to scale via TCP text protocol.

        Some Rongta scales support receiving TXP data as raw text over TCP.
        """
        results = {
            "success": False,
            "sent": 0,
            "errors": [],
        }

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))

            # Send as raw text
            data = txp_content.encode("utf-8")
            total_sent = 0
            chunk_size = 1024

            while total_sent < len(data):
                chunk = data[total_sent:total_sent + chunk_size]
                sock.sendall(chunk)
                total_sent += len(chunk)
                results["sent"] += len(chunk)

            sock.close()
            results["success"] = True

        except Exception as e:
            results["errors"].append(str(e))

        return results
