"""
hydra/utils/crypto.py — Генерация паролей/токенов и детерминированное выведение ключей.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path

MASTER_KEY_FILE = Path(os.environ.get("HYDRA_MASTER_KEY_FILE", "/var/lib/hydra/master.key"))


def _master_key() -> bytes | None:
    """Return the installation secret when one exists.

    Existing installations without this file keep legacy derived credentials;
    bootstrap creates it only for fresh installations.
    """
    try:
        key = MASTER_KEY_FILE.read_bytes()
    except OSError:
        return None
    return key if len(key) >= 32 else None

# Без неоднозначных символов (0/O, 1/l/I) — для ручного ввода с телефона.
_PASSWORD_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"


def gen_password(length: int = 16) -> str:
    """Случайный пароль из _PASSWORD_CHARS."""
    return "".join(secrets.choice(_PASSWORD_CHARS) for _ in range(length))


def gen_token(nbytes: int = 24) -> str:
    """secrets.token_urlsafe(nbytes)."""
    return secrets.token_urlsafe(nbytes)


def derive_key(purpose: str, seed: str) -> str:
    """Детерминированный ключ: base64(sha256(f'{purpose}|{seed}')).

    Используется AWG и другими плагинами для воспроизводимых per-user кредов.
    """
    payload = f"{purpose}|{seed}".encode()
    key = _master_key()
    digest = hmac.new(key, payload, hashlib.sha256).digest() if key else hashlib.sha256(payload).digest()
    return base64.b64encode(digest).decode()


def derive_hex_key(purpose: str, seed: str) -> str:
    """Детерминированный hex-ключ: sha256(f'{purpose}|{seed}').

    Используется NaiveProxy для URL-безопасных учетных данных без спецсимволов.
    """
    payload = f"{purpose}|{seed}".encode()
    key = _master_key()
    return hmac.new(key, payload, hashlib.sha256).hexdigest() if key else hashlib.sha256(payload).hexdigest()
