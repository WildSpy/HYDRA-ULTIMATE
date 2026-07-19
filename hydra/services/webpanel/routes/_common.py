"""Общие помощники для обработчиков маршрутов."""
from __future__ import annotations

from typing import Optional

from hydra.services.webpanel.errors import NotFound


def load_state():
    from hydra.core.state import load_state as _ls
    return _ls()


def get_plugin(name: str):
    """Возвращает плагин или бросает 404."""
    from hydra.plugins import registry
    p = registry.get(name)
    if p is None:
        raise NotFound(f"Плагин '{name}' не найден")
    return p


def plugin_category(name: str) -> str:
    from hydra.plugins import registry
    p = registry.get(name)
    return p.meta.category.value if p else "transport"


def serialize_user(user, state, include_traffic: bool = True) -> dict:
    """Приводит User к JSON-словарю для UI."""
    from hydra.services.subscriptions.generator import get_subscription_url
    limit_bytes = int(user.traffic_limit_gb * 1073741824) if user.traffic_limit_gb else 0
    try:
        sub_url = get_subscription_url(user, state)
    except Exception:
        sub_url = ""
    return {
        "email": user.email,
        "uuid": user.uuid,
        "traffic_limit_gb": user.traffic_limit_gb,
        "traffic_used_bytes": int(user.traffic_used_bytes),
        "traffic_limit_bytes": limit_bytes,
        "expiry_date": user.expiry_date,
        "blocked": user.blocked,
        "created_at": user.created_at,
        "telegram_id": user.telegram_id,
        "subscription_url": sub_url,
        "per_protocol": {
            proto: int(stats.get("traffic_used_bytes", 0))
            for proto, stats in (user.credentials or {}).items()
            if isinstance(stats, dict)
        } if include_traffic else {},
    }


def serialize_plugin(p, status_map: dict, state) -> dict:
    """Базовая карточка плагина (без тяжёлых вызовов).

    installed/enabled берутся из AppState (state.protocols) — это авторитетный
    источник, которым управляет orchestrator.enable/disable, как в TUI.
    running — из p.status() (реальное состояние службы).
    """
    st = status_map.get(p.meta.name, {})
    ps = state.protocols.get(p.meta.name)
    return {
        "name": p.meta.name,
        "description": p.meta.description,
        "category": p.meta.category.value,
        "version": p.meta.version,
        "needs_domain": p.meta.needs_domain,
        "installed": bool(ps.installed) if ps else bool(st.get("installed", False)),
        "enabled": bool(ps.enabled) if ps else bool(st.get("enabled", False)),
        "running": bool(st.get("running", False)),
        "port": int((ps.port if ps and ps.port else st.get("port", 0)) or 0),
        "config": dict(ps.config) if ps else {},
    }


def human_bytes(n: int) -> str:
    n = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} EiB"
