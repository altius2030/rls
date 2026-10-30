import time
import uuid
import jwt
import httpx
from config import settings


def verify_incoming_jwt(token: str) -> dict:
    """Verify JWT token from Moy Sklad (incoming requests)."""
    import logging
    logger = logging.getLogger(__name__)
    
    # First try without verification to inspect the token
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
        logger.info(f"JWT payload (unverified): {unverified}")
    except Exception as e:
        logger.warning(f"Could not decode JWT (even without verification): {e}")
    
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],
            options={"require": ["iat", "exp", "jti"]},
        )
        logger.info(f"JWT verified successfully, payload keys: {list(payload.keys())}")
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT expired")
        raise ValueError("Token expired")
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT verification failed: {e}")
        raise ValueError(f"Invalid token: {e}")


def create_outgoing_jwt() -> str:
    """Create JWT token for outgoing requests to Moy Sklad Vendor API."""
    now = int(time.time())
    payload = {
        "sub": settings.app_uid,
        "iat": now,
        "exp": now + settings.token_lifetime,
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm="HS256")
    return token


async def vendor_api_request(method: str, path: str, body: dict | None = None) -> httpx.Response:
    """Make an authenticated request to Moy Sklad Vendor API."""
    token = create_outgoing_jwt()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }
    url = f"{settings.vendor_api_base_url}{path}"
    async with httpx.AsyncClient() as client:
        response = await client.request(method, url, headers=headers, json=body)
    return response
