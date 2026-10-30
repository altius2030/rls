"""
TCP/IP Scale Protocol Module

Generic TCP/IP protocol for sending PLU data to scales.
Supports common scale data formats.
"""

import socket
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ScalePLU:
    """PLU record for scale."""
    plu_number: int           # PLU number (1-999999)
    name: str                 # Product name (max ~20-40 chars depending on scale)
    price: float             # Price per kg/unit (in rubles)
    barcode: str = ""        # Barcode
    weight: float = 0        # Tare weight or fixed weight
    department: int = 1      # Department number
    expiration_days: int = 0 # Shelf life in days
    fixed_weight: bool = False # True for fixed weight items (штучные)
    plu_type: int = 0        # 0=weight, 1=fix weight/piece


def format_plu_record(plu: ScalePLU) -> str:
    """Format PLU record for TCP/IP scales (generic CSV-like format)."""
    name = plu.name[:40]  # Truncate to 40 chars for most scales
    
    # Generic format: PLU,NAME,PRICE,BARCODE,WEIGHT,DEPT,EXPDATE,TYPE
    record = (
        f"PLU={plu.plu_number}|"
        f"NAME={name}|"
        f"PRICE={plu.price:.2f}|"
        f"BARCODE={plu.barcode}|"
        f"TARE={plu.weight:.3f}|"
        f"DEPT={plu.department}|"
        f"EXPDATE={plu.expiration_days}|"
        f"TYPE={plu.plu_type}\n"
    )
    return record


async def send_to_scale(
    host: str,
    port: int,
    plu_records: list[ScalePLU],
    timeout: int = 10,
) -> dict:
    """
    Send PLU records to scale via TCP/IP.
    
    Args:
        host: Scale IP address
        port: Scale TCP port
        plu_records: List of PLU records to send
        timeout: Connection timeout in seconds
    
    Returns:
        dict with result status and details
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

        for plu in plu_records:
            try:
                record = format_plu_record(plu)
                sock.sendall(record.encode("utf-8"))
                results["sent"] += 1
                logger.info(f"Sent PLU {plu.plu_number}: {plu.name}")
            except Exception as e:
                error_msg = f"Failed to send PLU {plu.plu_number}: {e}"
                results["errors"].append(error_msg)
                logger.error(error_msg)

        sock.close()
        results["success"] = len(results["errors"]) == 0

    except socket.timeout:
        results["errors"].append("Connection timeout")
        logger.error("Scale connection timeout")
    except ConnectionRefusedError:
        results["errors"].append("Connection refused - check scale IP and port")
        logger.error("Scale connection refused")
    except Exception as e:
        results["errors"].append(f"Connection error: {e}")
        logger.error(f"Scale connection error: {e}")

    return results


def convert_product_to_plu(
    product: dict,
    price: float,
    plu_number: int,
    department: int,
    expiration_days: int = 0,
) -> ScalePLU:
    """Convert a Moy Sklad product dict to a ScalePLU record."""
    weight = product.get("weight", 0)
    
    # Determine PLU type based on product properties
    plu_type = 0  # weight
    if product.get("is_weight_product"):
        plu_type = 0  # weight
    elif weight > 0 and not product.get("is_weight_product"):
        plu_type = 1  # fixed weight/piece

    return ScalePLU(
        plu_number=plu_number,
        name=product.get("name", ""),
        price=price,
        barcode=product.get("barcode", ""),
        weight=weight,
        department=department,
        expiration_days=expiration_days,
        plu_type=plu_type,
    )
