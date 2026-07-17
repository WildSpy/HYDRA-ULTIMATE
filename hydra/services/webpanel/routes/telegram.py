"""Маршруты раздела «Telegram-боты»."""
from __future__ import annotations

from hydra.services.webpanel.errors import BadRequest
from hydra.services.webpanel.routes._common import load_state


def _mask(token: str) -> str:
    if not token:
        return ""
    if len(token) <= 8:
        return "••••"
    return token[:4] + "…" + token[-4:]


def get_telegram(ctx):
    from hydra.core.systemd import is_active
    state = load_state()
    tg = state.telegram
    return {
        "admin_token_set": bool(tg.admin_token),
        "admin_token_masked": _mask(tg.admin_token),
        "admin_chat_id": tg.admin_chat_id,
        "bot_token_set": bool(tg.bot_token),
        "bot_token_masked": _mask(tg.bot_token),
        "admin_enabled": tg.admin_enabled,
        "bot_enabled": tg.bot_enabled,
        "admin_running": is_active("hydra-tg-admin"),
        "client_running": is_active("hydra-tg-bot"),
    }


def update_telegram(ctx):
    from hydra.core.state import update_state

    def _mut(state):
        if "admin_token" in ctx.body:
            state.telegram.admin_token = str(ctx.body["admin_token"] or "")
        if "admin_chat_id" in ctx.body:
            state.telegram.admin_chat_id = str(ctx.body["admin_chat_id"] or "")
        if "bot_token" in ctx.body:
            state.telegram.bot_token = str(ctx.body["bot_token"] or "")
        return True

    update_state(_mut)
    return get_telegram(ctx)


def _install_bot(kind: str):
    """kind: 'admin' | 'client'."""
    from hydra.core.systemd import install_service, start
    from hydra.core.state import update_state

    state = load_state()
    tg = state.telegram
    if kind == "admin":
        if not tg.admin_token:
            raise BadRequest("Сначала укажите admin-токен")
        unit = f"""[Unit]
Description=HYDRA Admin Bot
After=network.target
[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 -c "from hydra.services.telegram.bot import run_admin_bot; run_admin_bot('{tg.admin_token}', '{tg.admin_chat_id}')"
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
"""
        install_service("hydra-tg-admin", unit)
        start("hydra-tg-admin")

        def _mut(s):
            s.telegram.admin_enabled = True
            return True
        update_state(_mut)
    else:
        if not tg.bot_token:
            raise BadRequest("Сначала укажите client-токен")
        unit = f"""[Unit]
Description=HYDRA Client Bot
After=network.target
[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 -c "from hydra.services.telegram.bot import run_client_bot; run_client_bot('{tg.bot_token}', '{tg.admin_chat_id}')"
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
"""
        install_service("hydra-tg-bot", unit)
        start("hydra-tg-bot")

        def _mut(s):
            s.telegram.bot_enabled = True
            return True
        update_state(_mut)
    return {"ok": True}


def start_admin(ctx):
    return _install_bot("admin")


def start_client(ctx):
    return _install_bot("client")


def stop_all(ctx):
    from hydra.core.systemd import remove_unit
    from hydra.core.state import update_state
    remove_unit("hydra-tg-admin")
    remove_unit("hydra-tg-bot")

    def _mut(state):
        state.telegram.admin_enabled = False
        state.telegram.bot_enabled = False
        return True

    update_state(_mut)
    return {"ok": True}


ROUTES = [
    ("GET", r"/api/telegram", get_telegram),
    ("PUT", r"/api/telegram", update_telegram),
    ("POST", r"/api/telegram/admin/start", start_admin),
    ("POST", r"/api/telegram/client/start", start_client),
    ("POST", r"/api/telegram/stop", stop_all),
]
