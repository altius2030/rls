import os
from pathlib import Path


def _load_env():
    """Manually load .env file."""
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()


_load_env()


class Settings:
    """Application settings loaded from environment variables."""
    
    def __init__(self):
        self.app_id = os.getenv("APP_ID", "658bfe45-c3f0-4e68-b02e-72231fdef826")
        self.app_uid = os.getenv("APP_UID", "rongtams.altius2030")
        self.secret_key = os.getenv("SECRET_KEY", "ot5UqHhXAgnWjHiJWRlYpTvDBAZPMYMBBO2knX4sssY4ArEsBrnZbX0IcaKnGNIcV5OlMOp5K8dPl4S4vvbx3Csw8Q8C4P2uHjba4dWbGntg1HXAdYjmzVJ4qMywU9l6")
        self.moysklad_base_url = os.getenv("MOYSKLAD_BASE_URL", "https://api.moysklad.ru/api/remap/1.2")
        self.vendor_api_base_url = os.getenv("VENDOR_API_BASE_URL", "https://apps-api.moysklad.ru/api/vendor/1.0")
        self.endpoint_base = os.getenv("ENDPOINT_BASE", "https://your-domain.com")
        self.host = os.getenv("HOST", "0.0.0.0")
        self.port = int(os.getenv("PORT", "8000"))
        self.token_lifetime = int(os.getenv("TOKEN_LIFETIME", "300"))


settings = Settings()
