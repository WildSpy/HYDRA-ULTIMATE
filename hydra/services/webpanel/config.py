"""hydra/services/webpanel/config.py — конфигурация веб-панели.

Хранится в /var/lib/hydra/webpanel.json (рядом со state.json). Содержит сетевые
параметры (host/port/TLS), учётные данные администратора (хэш пароля) и секрет
для подписи токенов сессий. Файл создаётся автоматически при первом обращении.
"""
from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# Переиспользуем каталог состояния HYDRA, чтобы всё лежало в одном месте.
try:
    from hydra.core.state import STATE_DIR
except Exception:  # pragma: no cover - фолбэк на случай нестандартной установки
    STATE_DIR = Path("/var/lib/hydra")

CONFIG_FILE = STATE_DIR / "webpanel.json"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8088


@dataclass
class TLSConfig:
    enabled: bool = False
    cert: str = ""
    key: str = ""


@dataclass
class AuthConfig:
    username: str = "admin"
    password_hash: str = ""        # формат см. auth.hash_password
    token_secret: str = ""         # hex, используется для HMAC-подписи токенов


@dataclass
class PanelConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    tls: TLSConfig = field(default_factory=TLSConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    session_ttl_hours: int = 12

    # ── сериализация ──────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PanelConfig":
        tls = data.get("tls", {}) or {}
        auth = data.get("auth", {}) or {}
        return cls(
            host=data.get("host", DEFAULT_HOST),
            port=int(data.get("port", DEFAULT_PORT)),
            tls=TLSConfig(
                enabled=bool(tls.get("enabled", False)),
                cert=tls.get("cert", ""),
                key=tls.get("key", ""),
            ),
            auth=AuthConfig(
                username=auth.get("username", "admin"),
                password_hash=auth.get("password_hash", ""),
                token_secret=auth.get("token_secret", ""),
            ),
            session_ttl_hours=int(data.get("session_ttl_hours", 12)),
        )

    @property
    def is_provisioned(self) -> bool:
        """Установлен ли пароль администратора."""
        return bool(self.auth.password_hash)


def load_config() -> PanelConfig:
    """Загружает конфиг; создаёт файл с дефолтами + секретом токена, если нет."""
    if not CONFIG_FILE.exists():
        cfg = PanelConfig()
        cfg.auth.token_secret = secrets.token_hex(32)
        save_config(cfg)
        return cfg
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        raw = {}
    cfg = PanelConfig.from_dict(raw)
    if not cfg.auth.token_secret:
        cfg.auth.token_secret = secrets.token_hex(32)
        save_config(cfg)
    return cfg


def save_config(cfg: PanelConfig) -> None:
    """Атомарно сохраняет конфиг (temp + replace), права 0600."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".json.tmp")
    data = json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False)
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(CONFIG_FILE)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass
