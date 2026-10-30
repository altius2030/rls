"""
Скрипт для тестирования Vendor API аутентификации.
Генерирует JWT-токен и проверяет его.
"""

import time
import uuid
import jwt
from config import settings


def create_test_jwt():
    """Create a JWT token as Moy Sklad would send."""
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + 300,
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm="HS256")
    return token


def test_incoming_auth():
    """Test JWT verification for incoming requests."""
    from auth import verify_incoming_jwt

    token = create_test_jwt()
    print(f"Generated JWT: {token[:50]}...")

    try:
        payload = verify_incoming_jwt(token)
        print(f"✅ JWT verified successfully!")
        print(f"   Payload: {payload}")
    except ValueError as e:
        print(f"❌ JWT verification failed: {e}")


def test_outgoing_auth():
    """Test JWT creation for outgoing requests."""
    from auth import create_outgoing_jwt

    token = create_outgoing_jwt()
    print(f"\nOutgoing JWT: {token[:50]}...")

    # Verify it's valid
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        print(f"✅ Outgoing JWT is valid!")
        print(f"   sub (appUid): {payload['sub']}")
        print(f"   iat: {payload['iat']}")
        print(f"   exp: {payload['exp']}")
        print(f"   jti: {payload['jti']}")
    except Exception as e:
        print(f"❌ Outgoing JWT error: {e}")


if __name__ == "__main__":
    print("=== Testing Vendor API JWT Authentication ===\n")
    print(f"App ID: {settings.app_id}")
    print(f"App UID: {settings.app_uid}")
    print()

    test_incoming_auth()
    test_outgoing_auth()

    print("\n=== Test Complete ===")
