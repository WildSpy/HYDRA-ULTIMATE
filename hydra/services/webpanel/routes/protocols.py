"""Маршруты раздела «Протоколы» — общие операции над плагинами.

Специфические мастера (AWG-обфускация, Mieru-пресеты, telemt, wdtt, transport)
живут в plugin_wizards.py. Безопасность и сетевые службы — в security.py/network.py,
но общие install/enable/disable для них тоже работают через эти маршруты.
"""
from __future__ import annotations

from hydra.services.webpanel.errors import BadRequest
from hydra.services.webpanel.routes._common import (
    get_plugin, load_state, serialize_plugin,
)


def list_protocols(ctx):
    from hydra.plugins import registry
    state = load_state()
    status_map = registry.status_all()

    def _group(plugins):
        return [serialize_plugin(p, status_map, state) for p in plugins]

    return {
        "transports": _group(registry.transports()),
        "enhancements": _group(registry.enhancements()),
        "security": _group(registry.security()),
    }


def get_protocol(ctx):
    from hydra.plugins import registry
    name = ctx.params["name"]
    p = get_plugin(name)
    state = load_state()
    status_map = registry.status_all()
    card = serialize_plugin(p, status_map, state)
    # Дополнительная информация из status().info
    try:
        st = p.status()
        card["info"] = st.info
    except Exception:
        card["info"] = {}
    return card


def _run_toggle(ctx, kind: str, fn_name: str):
    from hydra.core import orchestrator
    name = ctx.params["name"]
    get_plugin(name)  # 404, если нет

    def _job():
        state = load_state()
        fn = getattr(orchestrator, fn_name)
        return {"ok": bool(fn(state, name))}

    return {"task_id": ctx.tasks.start(f"{kind}-{name}", _job)}


def install(ctx):
    return _run_toggle(ctx, "install", "install_plugin")


def uninstall(ctx):
    return _run_toggle(ctx, "uninstall", "uninstall_plugin")


def enable(ctx):
    return _run_toggle(ctx, "enable", "enable")


def disable(ctx):
    return _run_toggle(ctx, "disable", "disable")


def reinstall(ctx):
    from hydra.core import orchestrator
    name = ctx.params["name"]
    get_plugin(name)

    def _job():
        state = load_state()
        orchestrator.uninstall_plugin(state, name)
        state = load_state()
        ok = orchestrator.install_plugin(state, name)
        if ok:
            state = load_state()
            orchestrator.enable(state, name)
        return {"ok": ok}

    return {"task_id": ctx.tasks.start(f"reinstall-{name}", _job)}


def clients(ctx):
    name = ctx.params["name"]
    p = get_plugin(name)
    state = load_state()
    try:
        rows = p.connected_clients(state)
    except TypeError:
        rows = p.connected_clients()
    except Exception:
        rows = []
    return {"clients": rows}


def traffic(ctx):
    name = ctx.params["name"]
    p = get_plugin(name)
    state = load_state()
    try:
        data = p.traffic(state)
    except Exception:
        data = {}
    return {"traffic": data}


def sync_configs(ctx):
    """Пересоздать конфиги пользователей для протокола (sync_user_configs)."""
    from hydra.core import orchestrator
    name = ctx.params["name"]
    get_plugin(name)

    def _job():
        state = load_state()
        orchestrator.sync_user_configs(state, name)
        return {"ok": True}

    return {"task_id": ctx.tasks.start(f"sync-{name}", _job)}


ROUTES = [
    ("GET", r"/api/protocols", list_protocols),
    ("GET", r"/api/protocols/(?P<name>[a-z0-9_]+)", get_protocol),
    ("POST", r"/api/protocols/(?P<name>[a-z0-9_]+)/install", install),
    ("POST", r"/api/protocols/(?P<name>[a-z0-9_]+)/uninstall", uninstall),
    ("POST", r"/api/protocols/(?P<name>[a-z0-9_]+)/enable", enable),
    ("POST", r"/api/protocols/(?P<name>[a-z0-9_]+)/disable", disable),
    ("POST", r"/api/protocols/(?P<name>[a-z0-9_]+)/reinstall", reinstall),
    ("POST", r"/api/protocols/(?P<name>[a-z0-9_]+)/sync", sync_configs),
    ("GET", r"/api/protocols/(?P<name>[a-z0-9_]+)/clients", clients),
    ("GET", r"/api/protocols/(?P<name>[a-z0-9_]+)/traffic", traffic),
]
