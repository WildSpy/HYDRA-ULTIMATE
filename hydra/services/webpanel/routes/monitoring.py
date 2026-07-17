"""Маршруты раздела «Мониторинг»: трафик, подключения, система, логи,
sync-agent, clash-api."""
from __future__ import annotations

from pathlib import Path

from hydra.services.webpanel.errors import BadRequest, NotFound
from hydra.services.webpanel.routes._common import load_state, serialize_user

# Разрешённые к чтению лог-файлы (защита от произвольного чтения ФС).
LOG_FILES = {
    "singbox": "/var/log/sing-box/sing-box.log",
    "install": "/var/log/hydra/install.log",
    "sync-agent": "/var/log/hydra/sync-agent.log",
    "traffic-daemon": "/var/log/hydra/traffic-daemon.log",
    "fail2ban": "/var/log/fail2ban.log",
    "honeypot": "/var/log/hydra-honeypot.log",
    "caddy-naive": "/var/log/caddy-naive/access.log",
}


def traffic(ctx):
    from hydra.services.traffic import refresh_traffic_state, protocol_totals
    try:
        state = refresh_traffic_state()
    except Exception:
        state = load_state()
    return {
        "users": [serialize_user(u, state) for u in state.users],
        "protocol_totals": protocol_totals(state),
    }


def connections(ctx):
    from hydra.services.active_connections import (
        tracked_active_connections, traffic_daemon_fresh,
    )
    state = load_state()
    clash_enabled = getattr(state.network, "clash_api_enabled", False)
    rows = []
    fresh = False
    if clash_enabled:
        try:
            rows = tracked_active_connections(state)
            fresh = traffic_daemon_fresh(state)
        except Exception:
            rows = []
    return {
        "clash_api_enabled": clash_enabled,
        "daemon_fresh": fresh,
        "connections": rows,
    }


def system(ctx):
    from hydra.services.webpanel.routes.dashboard import _sys_info
    return {"system": _sys_info()}


def logs_list(ctx):
    out = []
    for key, path_str in LOG_FILES.items():
        p = Path(path_str)
        out.append({
            "key": key,
            "path": path_str,
            "exists": p.exists(),
            "size": p.stat().st_size if p.exists() else 0,
        })
    return {"logs": out}


def log_tail(ctx):
    key = ctx.params["key"]
    if key not in LOG_FILES:
        raise NotFound("Неизвестный лог-файл")
    lines = int(ctx.query.get("lines", 100))
    lines = max(1, min(lines, 2000))
    p = Path(LOG_FILES[key])
    if not p.exists():
        return {"key": key, "path": str(p), "lines": [], "exists": False}
    try:
        content = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise BadRequest(f"Не удалось прочитать лог: {exc}")
    return {"key": key, "path": str(p), "exists": True, "lines": content[-lines:]}


# ── Sync Agent ────────────────────────────────────────────────────────────────

def sync_run(ctx):
    def _job():
        from hydra.services.sync_agent import run_sync
        run_sync()
        return {"ok": True}
    return {"task_id": ctx.tasks.start("sync-agent-run", _job)}


def sync_timer_enable(ctx):
    from hydra.core.systemd import install_timer
    from hydra.services.webpanel.routes.subscriptions import _install_dir
    install_dir = _install_dir()
    ok = install_timer(
        "hydra-sync-agent",
        f"""[Unit]
Description=HYDRA Sync Agent
After=network.target
[Service]
Type=oneshot
User=root
WorkingDirectory={install_dir}
Environment=PYTHONPATH={install_dir}
ExecStart=/usr/bin/python3 -m hydra.services.sync_agent
""",
        """[Unit]
Description=HYDRA Sync Agent Timer
[Timer]
OnCalendar=*:0/5
Persistent=true
[Install]
WantedBy=timers.target
""")
    return {"ok": ok}


def sync_timer_disable(ctx):
    from hydra.core.systemd import remove_unit
    remove_unit("hydra-sync-agent.timer")
    remove_unit("hydra-sync-agent.service")
    return {"ok": True}


def sync_status(ctx):
    import subprocess
    r = subprocess.run(["systemctl", "is-active", "hydra-sync-agent.timer"],
                       capture_output=True, text=True)
    active = r.stdout.strip() == "active"
    log_path = Path("/var/log/hydra/sync-agent.log")
    last = ""
    if log_path.exists():
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
            last = lines[-1] if lines else ""
        except Exception:
            pass
    return {"timer_active": active, "last_log": last}


# ── Clash API ─────────────────────────────────────────────────────────────────

def clash_status(ctx):
    import subprocess
    state = load_state()
    net = state.network
    r = subprocess.run(["systemctl", "is-active", "hydra-traffic-daemon.service"],
                       capture_output=True, text=True)
    return {
        "enabled": getattr(net, "clash_api_enabled", False),
        "port": getattr(net, "clash_api_port", 9090),
        "secret_set": bool(getattr(net, "clash_api_secret", "")),
        "daemon_active": r.stdout.strip() == "active",
    }


def clash_update(ctx):
    """Меняет параметры Clash API и применяет конфиг (фоновая задача)."""
    from hydra.core.state import update_state

    changed = {}
    if "enabled" in ctx.body:
        changed["clash_api_enabled"] = bool(ctx.body["enabled"])
    if "port" in ctx.body:
        try:
            port = int(ctx.body["port"])
        except (TypeError, ValueError):
            raise BadRequest("port должен быть числом")
        if not (1024 <= port <= 65535):
            raise BadRequest("port вне диапазона 1024-65535")
        changed["clash_api_port"] = port
    if "secret" in ctx.body:
        changed["clash_api_secret"] = str(ctx.body["secret"] or "")

    if not changed:
        raise BadRequest("Нет изменений")

    def _mut(state):
        for k, v in changed.items():
            setattr(state.network, k, v)
        return True

    update_state(_mut)

    def _job():
        from hydra.core.orchestrator import apply_config
        return {"applied": apply_config(load_state())}

    return {"task_id": ctx.tasks.start("clash-api-apply", _job)}


ROUTES = [
    ("GET", r"/api/monitoring/traffic", traffic),
    ("GET", r"/api/monitoring/connections", connections),
    ("GET", r"/api/monitoring/system", system),
    ("GET", r"/api/monitoring/logs", logs_list),
    ("GET", r"/api/monitoring/logs/(?P<key>[a-z0-9\-]+)", log_tail),
    ("POST", r"/api/monitoring/sync-agent/run", sync_run),
    ("GET", r"/api/monitoring/sync-agent", sync_status),
    ("POST", r"/api/monitoring/sync-agent/timer/enable", sync_timer_enable),
    ("POST", r"/api/monitoring/sync-agent/timer/disable", sync_timer_disable),
    ("GET", r"/api/monitoring/clash-api", clash_status),
    ("PUT", r"/api/monitoring/clash-api", clash_update),
]
