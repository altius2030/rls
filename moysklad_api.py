import httpx
from config import settings


async def fetch_products(access_token: str) -> list[dict]:
    """Fetch all products from Moy Sklad JSON API 1.2."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
    }

    products = []
    url = f"{settings.moysklad_base_url}/entity/product?limit=100&offset=0"

    async with httpx.AsyncClient(timeout=30) as client:
        while url:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            rows = data.get("rows", [])
            for row in rows:
                product = extract_product_data(row)
                products.append(product)

            # Pagination
            next_href = data.get("meta", {}).get("nextHref")
            url = next_href if next_href else None

    return products


async def fetch_product_folders(access_token: str) -> list[dict]:
    """Fetch all product folders (groups) from Moy Sklad."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
    }

    folders = []
    url = f"{settings.moysklad_base_url}/entity/productfolder?limit=100&offset=0"

    async with httpx.AsyncClient(timeout=30) as client:
        while url:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            rows = data.get("rows", [])
            for row in rows:
                folders.append({
                    "id": row.get("id"),
                    "name": row.get("name", ""),
                    "code": row.get("code", ""),
                    "external_code": row.get("externalCode", ""),
                    "path_name": row.get("pathName", ""),
                })

            next_href = data.get("meta", {}).get("nextHref")
            url = next_href if next_href else None

    return folders


async def fetch_prices(access_token: str) -> dict[str, float]:
    """Fetch sell prices for all products."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
    }

    prices = {}
    url = f"{settings.moysklad_base_url}/context/companysetting/pricetype"

    async with httpx.AsyncClient(timeout=30) as client:
        # First get default price type
        try:
            resp = await client.get(
                f"{settings.moysklad_base_url}/entity/product/metadata/price",
                headers=headers,
            )
            # If we can get price type, use it
        except Exception:
            pass

        # Fetch products with expand=salePrices
        products_url = f"{settings.moysklad_base_url}/entity/product?limit=100&offset=0&expand=salePrices"
        while products_url:
            response = await client.get(products_url, headers=headers)
            response.raise_for_status()
            data = response.json()

            for row in data.get("rows", []):
                product_id = row.get("id")
                sale_prices = row.get("salePrices", [])
                # Find the default sell price (usually first or with specific priceType)
                for price in sale_prices:
                    if price.get("priceType", {}).get("name", "") in ["Цена продажи", "Розничная"]:
                        prices[product_id] = price.get("value", 0) / 100  # Convert from kopecks
                        break
                else:
                    # Take first price if no default found
                    if sale_prices:
                        prices[product_id] = sale_prices[0].get("value", 0) / 100

            next_href = data.get("meta", {}).get("nextHref")
            products_url = next_href if next_href else None

    return prices


def extract_product_data(product: dict) -> dict:
    """Extract relevant scale data from a Moy Sklad product entity."""
    # Get weight
    weight = product.get("weight", 0)

    # Get barcodes
    barcodes = product.get("barcodes", [])
    barcode_str = ""
    if barcodes:
        for bc in barcodes:
            code = bc.get("ean13") or bc.get("ean8") or bc.get("code") or ""
            if code:
                barcode_str = code
                break

    # Get product folder for department mapping
    folder_ref = product.get("productFolder", {})
    folder_id = folder_ref.get("id", "") if folder_ref else ""

    # Get UOM
    uom = product.get("uom", {})
    uom_name = uom.get("name", "") if uom else ""

    # Get attributes (custom fields)
    attributes = {}
    for attr in product.get("attributes", []):
        attr_name = attr.get("name", "")
        attr_value = attr.get("value")
        if attr_value is not None:
            if isinstance(attr_value, dict):
                attributes[attr_name] = attr_value.get("name", str(attr_value))
            else:
                attributes[attr_name] = str(attr_value)

    return {
        "id": product.get("id", ""),
        "name": product.get("name", ""),
        "article": product.get("article", ""),
        "code": product.get("code", ""),
        "external_code": product.get("externalCode", ""),
        "barcode": barcode_str,
        "weight": weight,
        "uom": uom_name,
        "folder_id": folder_id,
        "is_weight_product": product.get("weighed", False),
        "attributes": attributes,
    }
