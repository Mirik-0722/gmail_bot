import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    encryption_key: str
    poll_interval: int
    db_path: str
    allowed_users: frozenset[int]


def load_config() -> Config:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    key = os.getenv("ENCRYPTION_KEY", "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN .env faylida ko'rsatilmagan")
    if not key:
        raise SystemExit(
            "ENCRYPTION_KEY .env faylida ko'rsatilmagan. Yaratish:\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    allowed = os.getenv("ALLOWED_USERS", "")
    return Config(
        bot_token=token,
        encryption_key=key,
        poll_interval=int(os.getenv("POLL_INTERVAL", "30")),
        db_path=os.getenv("DB_PATH", "gmail_bot.db"),
        allowed_users=frozenset(int(x) for x in allowed.split(",") if x.strip()),
    )
