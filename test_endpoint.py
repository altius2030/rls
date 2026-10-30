"""
Тест Vendor API эндпоинта локально.
Запустите этот скрипт чтобы убедиться что сервер работает правильно.
"""

import json
import time
import uuid
import jwt
import httpx

APP_ID = "658bfe45-c3f0-4e68-b02e-72231fdef826"
APP_UID = "rongtams.altius2030"
SECRET_KEY = "ot5UqHhXAgnWjHiJWRlYpTvDBAZPMYMBBO2knX4sssY4ArEsBrnZbX0IcaKnGNIcV5OlMOp5K8dPl4S4vvbx3Csw8Q8C4P2uHjba4dWbGntg1HXAdYjmzVJ4qMywU9l6"


def create_jwt():
    now = int(time.time())
    payload = {"iat": now, "exp": now + 300, "jti": str(uuid.uuid4())}
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def test_activation(url: str):
    """Тест PUT активации."""
    test_account = f"test-{uuid.uuid4().hex[:8]}"
    full_url = f"{url}/api/moysklad/vendor/1.0/apps/{APP_ID}/{test_account}"
    
    print(f"\n{'='*50}")
    print(f"Тест активации: {full_url}")
    
    token = create_jwt()
    body = {
        "appUid": APP_UID,
        "accountName": "Тест",
        "cause": "Install",
        "access": [{"resource": "https://api.moysklad.ru/api/remap/1.2", "scope": ["admin"], "access_token": "test-token"}],
    }
    
    try:
        resp = httpx.put(full_url, json=body, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }, timeout=10)
        
        print(f"Статус: {resp.status_code}")
        print(f"Ответ: {resp.text}")
        
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") in ["Activated", "SettingsRequired", "Activating"]:
                print(f"✅ Статус ответа корректный: {data['status']}")
                return True
        
        print(f"❌ Некорректный ответ")
        return False
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False


def test_deactivation(url: str):
    """Тест DELETE деактивации."""
    test_account = f"test-{uuid.uuid4().hex[:8]}"
    full_url = f"{url}/api/moysklad/vendor/1.0/apps/{APP_ID}/{test_account}"
    
    print(f"\n{'='*50}")
    print(f"Тест деактивации: {full_url}")
    
    try:
        resp = httpx.delete(full_url, json={"cause": "Uninstall"}, timeout=10)
        print(f"Статус: {resp.status_code}")
        print(f"Ответ: {resp.text}")
        return resp.status_code in [200, 204]
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False


def test_without_auth(url: str):
    """Тест без авторизации ( Moy Sklad всегда шлет JWT )."""
    test_account = f"test-{uuid.uuid4().hex[:8]}"
    full_url = f"{url}/api/moysklad/vendor/1.0/apps/{APP_ID}/{test_account}"
    
    print(f"\n{'='*50}")
    print(f"Тест без JWT: {full_url}")
    
    try:
        resp = httpx.put(full_url, json={"cause": "Install"}, timeout=10)
        print(f"Статус: {resp.status_code}")
        print(f"Ответ: {resp.text}")
        return resp.status_code == 200
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False


if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    
    print("ТЕСТИРОВАНИЕ VENDOR API")
    print(f"URL: {url}")
    
    results = []
    results.append(("Активация с JWT", test_activation(url)))
    results.append(("Деактивация", test_deactivation(url)))
    results.append(("Без JWT", test_without_auth(url)))
    
    print(f"\n{'='*50}")
    print("РЕЗУЛЬТАТЫ:")
    for name, ok in results:
        print(f"  {'✅' if ok else '❌'} {name}")
