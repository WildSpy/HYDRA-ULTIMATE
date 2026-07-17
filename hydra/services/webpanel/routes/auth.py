"""Маршруты аутентификации: login / logout / session."""
from __future__ import annotations

from hydra.services.webpanel import auth as auth_mod
from hydra.services.webpanel.errors import BadRequest, Unauthorized


def login(ctx):
    username = str(ctx.get("username", "") or "")
    password = str(ctx.get("password", "") or "")
    if not username or not password:
        raise BadRequest("Укажите логин и пароль")

    cfg = ctx.config
    if not cfg.is_provisioned:
        raise Unauthorized("Пароль администратора не задан на сервере")

    key = ctx.client_ip
    try:
        ctx.app.throttle.check(key)
    except ValueError as exc:
        raise Unauthorized(f"Слишком много попыток. Повторите через {exc} сек.")

    if not auth_mod.authenticate(cfg, username, password):
        ctx.app.throttle.record_failure(key)
        raise Unauthorized("Неверный логин или пароль")

    ctx.app.throttle.record_success(key)
    token = auth_mod.issue_token(cfg, username)
    return {"token": token, "username": username,
            "expires_in": cfg.session_ttl_hours * 3600}


def logout(ctx):
    # Токены stateless (HMAC), поэтому серверная инвалидция не требуется —
    # клиент просто забывает токен.
    return {"ok": True}


def session(ctx):
    return {"username": ctx.username, "authenticated": True}


ROUTES = [
    ("POST", r"/api/login", login, False),
    ("POST", r"/api/logout", logout, False),
    ("GET", r"/api/session", session, True),
]
