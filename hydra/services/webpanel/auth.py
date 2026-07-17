"""hydra/services/webpanel/auth.py — аутентификация веб-панели.

- Пароль администратора хранится как PBKDF2-HMAC-SHA256 (stdlib hashlib).
- Сессии — это HMAC-подписанные bearer-токены с временем истечения (без БД сессий).
- Простой throttling логина по IP (защита от перебора).

CLI:
    python3 -m hydra.services.webpanel.auth set-password [--username admin] [password]
    python3 -m hydra.services.webpanel.auth show
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from typing import Optional

from hydra.services.webpanel.config import PanelConfig, load_config, save_config

# ── Пароль (PBKDF2) ───────────────────────────────────────────────────────────

_PBKDF2_ROUNDS = 200_000
_PBKDF2_PREFIX = "pbkdf2_sha256"


def hash_password(password: str, *, rounds: int = _PBKDF2_ROUNDS) -> str:
    """Возвращает строку формата pbkdf2_sha256$rounds$salt_hex$hash_hex."""
    if not password:
        raise ValueError("Пароль не может быть пустым")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return f"{_PBKDF2_PREFIX}${rounds}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """Проверяет пароль против сохранённого хэша (constant-time)."""
    if not encoded or not password:
        return False
    try:
        prefix, rounds_s, salt_hex, hash_hex = encoded.split("$")
        if prefix != _PBKDF2_PREFIX:
            return False
        rounds = int(rounds_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(digest, expected)


# ── Токены сессий (HMAC) ──────────────────────────────────────────────────────

def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def issue_token(cfg: PanelConfig, username: str) -> str:
    """Создаёт подписанный токен вида base64(payload).hmac_hex."""
    ttl = max(1, int(cfg.session_ttl_hours)) * 3600
    payload = {"u": username, "exp": int(time.time()) + ttl, "n": secrets.token_hex(8)}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(cfg.auth.token_secret.encode("utf-8"), body.encode("ascii"),
                   hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(cfg: PanelConfig, token: str) -> Optional[str]:
    """Проверяет токен; возвращает username или None."""
    if not token or "." not in token or not cfg.auth.token_secret:
        return None
    body, _, sig = token.partition(".")
    expected = hmac.new(cfg.auth.token_secret.encode("utf-8"), body.encode("ascii"),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64d(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload.get("u")


# ── Throttling логина ─────────────────────────────────────────────────────────

class LoginThrottle:
    """Ограничивает частоту неудачных попыток входа по ключу (IP)."""

    def __init__(self, max_attempts: int = 5, window: int = 300, lockout: int = 300):
        self.max_attempts = max_attempts
        self.window = window
        self.lockout = lockout
        self._lock = threading.Lock()
        self._fails: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}

    def check(self, key: str) -> None:
        """Бросает ValueError с секундами до разблокировки, если ключ заблокирован."""
        now = time.time()
        with self._lock:
            until = self._locked_until.get(key, 0)
            if until > now:
                raise ValueError(str(int(until - now)))

    def record_failure(self, key: str) -> None:
        now = time.time()
        with self._lock:
            attempts = [t for t in self._fails.get(key, []) if now - t < self.window]
            attempts.append(now)
            self._fails[key] = attempts
            if len(attempts) >= self.max_attempts:
                self._locked_until[key] = now + self.lockout
                self._fails[key] = []

    def record_success(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)
            self._locked_until.pop(key, None)


# ── Высокоуровневые операции ──────────────────────────────────────────────────

def authenticate(cfg: PanelConfig, username: str, password: str) -> bool:
    """Проверяет пару логин/пароль."""
    if not hmac.compare_digest(username or "", cfg.auth.username or ""):
        # всё равно считаем хэш, чтобы не палить существование пользователя по таймингу
        verify_password(password or "", cfg.auth.password_hash)
        return False
    return verify_password(password or "", cfg.auth.password_hash)


def set_password(username: str, password: str) -> None:
    """Устанавливает логин/пароль администратора и сохраняет конфиг."""
    cfg = load_config()
    if username:
        cfg.auth.username = username
    cfg.auth.password_hash = hash_password(password)
    if not cfg.auth.token_secret:
        cfg.auth.token_secret = secrets.token_hex(32)
    save_config(cfg)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _main(argv: list[str]) -> int:
    import argparse
    import getpass

    parser = argparse.ArgumentParser(prog="hydra.services.webpanel.auth")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("set-password", help="Задать логин/пароль администратора")
    sp.add_argument("--username", default="")
    sp.add_argument("password", nargs="?", default=None)

    sub.add_parser("show", help="Показать текущего пользователя и статус")

    cp = sub.add_parser("configure", help="Задать сетевые параметры панели")
    cp.add_argument("--host", default=None)
    cp.add_argument("--port", type=int, default=None)
    tls = cp.add_mutually_exclusive_group()
    tls.add_argument("--tls", dest="tls", action="store_true")
    tls.add_argument("--no-tls", dest="tls", action="store_false")
    cp.set_defaults(tls=None)
    cp.add_argument("--cert", default=None)
    cp.add_argument("--key", default=None)

    args = parser.parse_args(argv)

    if args.cmd == "set-password":
        password = args.password
        if not password:
            password = getpass.getpass("Новый пароль администратора: ")
            confirm = getpass.getpass("Повторите пароль: ")
            if password != confirm:
                print("Пароли не совпадают.")
                return 1
        if len(password) < 6:
            print("Пароль слишком короткий (минимум 6 символов).")
            return 1
        set_password(args.username, password)
        cfg = load_config()
        print(f"Пароль установлен. Пользователь: {cfg.auth.username}")
        return 0

    if args.cmd == "show":
        cfg = load_config()
        print(f"Пользователь: {cfg.auth.username}")
        print(f"Пароль задан: {'да' if cfg.is_provisioned else 'НЕТ'}")
        print(f"Bind: {cfg.host}:{cfg.port}  TLS: {'вкл' if cfg.tls.enabled else 'выкл'}")
        return 0

    if args.cmd == "configure":
        cfg = load_config()
        if args.host is not None:
            cfg.host = args.host
        if args.port is not None:
            cfg.port = args.port
        if args.tls is not None:
            cfg.tls.enabled = args.tls
        if args.cert is not None:
            cfg.tls.cert = args.cert
        if args.key is not None:
            cfg.tls.key = args.key
        save_config(cfg)
        print(f"Готово. Bind: {cfg.host}:{cfg.port}  TLS: {'вкл' if cfg.tls.enabled else 'выкл'}")
        return 0

    return 1


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
