"""Маршруты раздела «Пользователи»."""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime

from hydra.services.webpanel.errors import BadRequest, Conflict, NotFound
from hydra.services.webpanel.routes._common import load_state, serialize_user


def _find_or_404(state, email):
    from hydra.core.state import find_user
    u = find_user(state, email)
    if u is None:
        raise NotFound(f"Пользователь '{email}' не найден")
    return u


def list_users(ctx):
    from hydra.services.traffic import refresh_traffic_state, protocol_totals
    try:
        state = refresh_traffic_state()
    except Exception:
        state = load_state()
    return {
        "users": [serialize_user(u, state) for u in state.users],
        "protocol_totals": protocol_totals(state),
    }


def add_user(ctx):
    from hydra.core import orchestrator
    from hydra.core.state import User, find_user

    email = str(ctx.require("email")).strip()
    if not email:
        raise BadRequest("Email не может быть пустым")

    state = load_state()
    if find_user(state, email):
        raise Conflict(f"Пользователь '{email}' уже существует")

    user = User(
        email=email,
        uuid=str(_uuid.uuid4()),
        traffic_limit_gb=float(ctx.get("traffic_limit_gb", 0) or 0),
        expiry_date=str(ctx.get("expiry_date", "") or ""),
        created_at=datetime.utcnow().isoformat() + "Z",
        telegram_id=ctx.get("telegram_id"),
    )
    orchestrator.add_user(state, user)
    state = load_state()
    return serialize_user(_find_or_404(state, email), state)


def get_user(ctx):
    state = load_state()
    user = _find_or_404(state, ctx.params["email"])
    return serialize_user(user, state)


def delete_user(ctx):
    from hydra.core import orchestrator
    email = ctx.params["email"]
    state = load_state()
    _find_or_404(state, email)
    orchestrator.remove_user(state, email)
    return {"ok": True}


def block_user(ctx):
    from hydra.core import orchestrator
    email = ctx.params["email"]
    state = load_state()
    _find_or_404(state, email)
    orchestrator.block_user(state, email)
    return {"ok": True}


def unblock_user(ctx):
    from hydra.core import orchestrator
    email = ctx.params["email"]
    state = load_state()
    _find_or_404(state, email)
    orchestrator.unblock_user(state, email)
    return {"ok": True}


def set_limit(ctx):
    from hydra.core.state import update_state
    email = ctx.params["email"]
    try:
        limit = float(ctx.require("traffic_limit_gb"))
    except (TypeError, ValueError):
        raise BadRequest("traffic_limit_gb должно быть числом")
    auto_unblock = bool(ctx.get("auto_unblock", False))

    def _mut(state):
        from hydra.core.state import find_user
        u = find_user(state, email)
        if u is None:
            raise NotFound(f"Пользователь '{email}' не найден")
        u.traffic_limit_gb = max(0.0, limit)
        return True

    update_state(_mut)
    if auto_unblock:
        from hydra.core import orchestrator
        state = load_state()
        u = _find_or_404(state, email)
        if u.blocked:
            orchestrator.unblock_user(state, email)
    state = load_state()
    return serialize_user(_find_or_404(state, email), state)


def set_expiry(ctx):
    from hydra.core.state import update_state
    email = ctx.params["email"]
    raw = str(ctx.get("expiry_date", "") or "").strip()
    # пусто = бессрочно; иначе принимаем YYYY-MM-DD или полный ISO
    expiry = ""
    if raw:
        date_part = raw.split("T")[0]
        try:
            datetime.strptime(date_part, "%Y-%m-%d")
        except ValueError:
            raise BadRequest("Дата должна быть в формате YYYY-MM-DD")
        expiry = f"{date_part}T23:59:59Z"
    auto_unblock = bool(ctx.get("auto_unblock", False))

    def _mut(state):
        from hydra.core.state import find_user
        u = find_user(state, email)
        if u is None:
            raise NotFound(f"Пользователь '{email}' не найден")
        u.expiry_date = expiry
        return True

    update_state(_mut)
    if auto_unblock:
        from hydra.core import orchestrator
        state = load_state()
        u = _find_or_404(state, email)
        if u.blocked:
            orchestrator.unblock_user(state, email)
    state = load_state()
    return serialize_user(_find_or_404(state, email), state)


def user_configs(ctx):
    """Ссылки и конфиги пользователя по всем включённым транспортам."""
    from hydra.plugins import registry
    from hydra.services.subscriptions.generator import get_subscription_url

    email = ctx.params["email"]
    state = load_state()
    user = _find_or_404(state, email)

    protocols = []
    for p in registry.enabled(state):
        from hydra.plugins.base import PluginCategory
        if p.meta.category != PluginCategory.TRANSPORT:
            continue
        entry = {"name": p.meta.name, "links": [], "config": ""}
        # ссылки: сначала множественные, потом одиночная
        try:
            getter = getattr(p, "client_links", None)
            if callable(getter):
                links = getter(user, state)
                if isinstance(links, str):
                    links = [links]
                entry["links"] = [l for l in (links or []) if l]
        except Exception:
            pass
        if not entry["links"]:
            try:
                link = p.client_link(user, state)
                if link:
                    entry["links"] = [link]
            except Exception:
                pass
        try:
            cfg = p.generate_client_config(user, state)
            if cfg:
                entry["config"] = cfg
        except Exception:
            pass
        protocols.append(entry)

    try:
        sub_url = get_subscription_url(user, state)
    except Exception:
        sub_url = ""

    return {"email": email, "subscription_url": sub_url, "protocols": protocols}


def user_subscription(ctx):
    """Base64-подписка пользователя (как отдаёт hydra-sub)."""
    from hydra.services.subscriptions.generator import (
        generate_base64_sub, get_subscription_url,
    )
    email = ctx.params["email"]
    state = load_state()
    user = _find_or_404(state, email)
    try:
        content = generate_base64_sub(user, state)
    except Exception as exc:
        content = ""
    return {
        "email": email,
        "url": get_subscription_url(user, state),
        "base64": content,
    }


ROUTES = [
    ("GET", r"/api/users", list_users),
    ("POST", r"/api/users", add_user),
    ("GET", r"/api/users/(?P<email>[^/]+)", get_user),
    ("DELETE", r"/api/users/(?P<email>[^/]+)", delete_user),
    ("POST", r"/api/users/(?P<email>[^/]+)/block", block_user),
    ("POST", r"/api/users/(?P<email>[^/]+)/unblock", unblock_user),
    ("PUT", r"/api/users/(?P<email>[^/]+)/limit", set_limit),
    ("PUT", r"/api/users/(?P<email>[^/]+)/expiry", set_expiry),
    ("GET", r"/api/users/(?P<email>[^/]+)/configs", user_configs),
    ("GET", r"/api/users/(?P<email>[^/]+)/subscription", user_subscription),
]
