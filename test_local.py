"""
Локальный тест активации решения.
Имитирует запрос от МоегоСклада для проверки работы эндпоинта.
"""

import time
import uuid
import json
import httpx
import jwt
from config import settings


def create_moysklad_jwt() -> str:
    """Создать JWT так, как это делает МойСклад."""
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + 300,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def test_activation(base_url: str = "http://localhost:8000"):
    """Тест активации решения."""
    
    # Тестовый accountId
    test_account_id = "test-account-001"
    app_id = settings.app_id
    
    url = f"{base_url}/api/moysklad/vendor/1.0/apps/{app_id}/{test_account_id}"
    
    print(f"\n{'='*60}")
    print(f"ТЕСТ АКТИВАЦИИ")
    print(f"{'='*60}")
    print(f"URL: {url}")
    print(f"App ID: {app_id}")
    print(f"Account ID: {test_account_id}")
    print()
    
    # Создаём JWT
    token = create_moysklad_jwt()
    print(f"JWT создан: {token[:50]}...")
    
    # Тело запроса (как от МоегоСклада)
    body = {
        "appUid": settings.app_uid,
        "accountName": "Тестовый аккаунт",
        "cause": "Install",
        "access": [
            {
                "resource": "https://api.moysklad.ru/api/remap/1.2",
                "scope": ["admin"],
                "access_token": "test-access-token-1234567890"
            }
        ],
        "subscription": {
            "tariffId": "test-tariff-id",
            "trial": True,
            "tariffName": "Базовый",
            "expiryMoment": "2025-12-31T23:59:59+03:00",
            "notForResale": False,
            "partner": False
        }
    }
    
    print(f"\nТело запроса:")
    print(json.dumps(body, indent=2, ensure_ascii=False))
    
    # Отправляем запрос
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    
    print(f"\nОтправляем PUT-запрос...")
    
    try:
        response = httpx.put(url, json=body, headers=headers, timeout=30)
        
        print(f"\n{'='*60}")
        print(f"РЕЗУЛЬТАТ")
        print(f"{'='*60}")
        print(f"Статус: {response.status_code}")
        print(f"Заголовки: {dict(response.headers)}")
        print(f"Тело ответа: {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            if data.get("status") in ["Activated", "SettingsRequired", "Activating"]:
                print(f"\n✅ УСПЕХ! Статус: {data['status']}")
            else:
                print(f"\n⚠️ Неожиданный статус: {data.get('status')}")
        else:
            print(f"\n❌ ОШИБКА! Код: {response.status_code}")
            
    except httpx.ConnectError as e:
        print(f"\n❌ Ошибка подключения: {e}")
        print("Убедитесь, что сервер запущен на localhost:8000")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")


def test_health(base_url: str = "http://localhost:8000"):
    """Тест health endpoint."""
    url = f"{base_url}/health"
    print(f"\nПроверка health: {url}")
    
    try:
        response = httpx.get(url, timeout=10)
        print(f"Статус: {response.status_code}")
        print(f"Ответ: {response.json()}")
    except Exception as e:
        print(f"Ошибка: {e}")


def test_debug_config(base_url: str = "http://localhost:8000"):
    """Тест config endpoint."""
    url = f"{base_url}/debug/config"
    print(f"\nПроверка конфигурации: {url}")
    
    try:
        response = httpx.get(url, timeout=10)
        print(f"Статус: {response.status_code}")
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Ошибка: {e}")


def test_deactivation(base_url: str = "http://localhost:8000"):
    """Тест деактивации."""
    test_account_id = "test-account-001"
    app_id = settings.app_id
    url = f"{base_url}/api/moysklad/vendor/1.0/apps/{app_id}/{test_account_id}"
    
    print(f"\n{'='*60}")
    print(f"ТЕСТ ДЕАКТИВАЦИИ")
    print(f"{'='*60}")
    
    token = create_moysklad_jwt()
    body = {"cause": "Uninstall"}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    
    try:
        response = httpx.delete(url, json=body, headers=headers, timeout=10)
        print(f"Статус: {response.status_code}")
        print(f"Ответ: {response.text}")
        
        if response.status_code in [200, 204]:
            print("✅ Деактивация успешна")
        else:
            print(f"❌ Ошибка: {response.status_code}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")


if __name__ == "__main__":
    import sys
    
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    
    print("=" * 60)
    print("ЛОКАЛЬНОЕ ТЕСТИРОВАНИЕ VENDOR API")
    print("=" * 60)
    
    test_health(base_url)
    test_debug_config(base_url)
    test_activation(base_url)
    test_deactivation(base_url)
    
    print(f"\n{'='*60}")
    print("ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ")
    print("=" * 60)
