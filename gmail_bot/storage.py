"""Foydalanuvchi sozlamalarini SQLite'da saqlash (App Password shifrlangan)."""
import sqlite3
from dataclasses import dataclass

from cryptography.fernet import Fernet


@dataclass
class UserSettings:
    chat_id: int
    email: str
    app_password: str
    last_uid: int


class Storage:
    def __init__(self, path: str, encryption_key: str):
        self._fernet = Fernet(encryption_key.encode())
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                chat_id      INTEGER PRIMARY KEY,
                email        TEXT NOT NULL,
                app_password BLOB NOT NULL,
                last_uid     INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._conn.commit()

    def save(self, chat_id: int, email: str, app_password: str, last_uid: int) -> None:
        token = self._fernet.encrypt(app_password.encode())
        self._conn.execute(
            """
            INSERT INTO users (chat_id, email, app_password, last_uid)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                email = excluded.email,
                app_password = excluded.app_password,
                last_uid = excluded.last_uid
            """,
            (chat_id, email, token, last_uid),
        )
        self._conn.commit()

    def get(self, chat_id: int) -> UserSettings | None:
        row = self._conn.execute(
            "SELECT chat_id, email, app_password, last_uid FROM users WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        return self._row_to_settings(row) if row else None

    def all(self) -> list[UserSettings]:
        rows = self._conn.execute(
            "SELECT chat_id, email, app_password, last_uid FROM users"
        ).fetchall()
        return [self._row_to_settings(r) for r in rows]

    def update_last_uid(self, chat_id: int, last_uid: int) -> None:
        self._conn.execute(
            "UPDATE users SET last_uid = ? WHERE chat_id = ?", (last_uid, chat_id)
        )
        self._conn.commit()

    def delete(self, chat_id: int) -> None:
        self._conn.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
        self._conn.commit()

    def _row_to_settings(self, row) -> UserSettings:
        chat_id, email, token, last_uid = row
        return UserSettings(
            chat_id=chat_id,
            email=email,
            app_password=self._fernet.decrypt(token).decode(),
            last_uid=last_uid,
        )
