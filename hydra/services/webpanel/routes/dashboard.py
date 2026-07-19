"""Маршрут дашборда: сводка по системе, sing-box, плагинам, пользователям."""
from __future__ import annotations

from hydra.services.webpanel.routes._common import load_state


def _sys_info() -> dict:
    info = {"cpu_percent": None, "mem_percent": None, "mem_total": None,
            "mem_used": None, "disk_percent": None, "uptime": None, "load": None}
    try:
        import psutil  # type: ignore
        info["cpu_percent"] = psutil.cpu_percent(interval=0.2)
        vm = psutil.virtual_memory()
        info["mem_percent"] = vm.percent
        info["mem_total"] = vm.total
        info["mem_used"] = vm.used
        info["disk_percent"] = psutil.disk_usage("/").percent
        return info
    except Exception:
        pass
    # Фолбэк на /proc (Linux) без psutil
    try:
        with open("/proc/loadavg") as fh:
            info["load"] = fh.read().split()[:3]
        with open("/proc/meminfo") as fh:
            mem = {}
            for line in fh:
                parts = line.split()
                if len(parts) >= 2:
                    mem[parts[0].rstrip(":")] = int(parts[1]) * 1024
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", 0)
        if total:
            info["mem_total"] = total
            info["mem_used"] = total - avail
            info["mem_percent"] = round((total - avail) / total * 100, 1)
    except Exception:
        pass
    return info


def dashboard(ctx):
    from hydra.core import singbox
    from hydra.plugins import registry
    from hydra.utils import net

    state = load_state()
    status_map = registry.status_all()

    transports = registry.transports()
    enhancements = registry.enhancements()
    sec = registry.security()

    def _counts(plugins):
        total = len(plugins)
        # enabled — авторитетно из AppState (как в TUI), не из состояния службы
        active = sum(1 for p in plugins
                     if state.protocols.get(p.meta.name)
                     and state.protocols[p.meta.name].enabled)
        return {"total": total, "active": active}

    users = state.users
    active_users = sum(1 for u in users if not u.blocked)

    try:
        pub_ip = net.public_ip()
    except Exception:
        pub_ip = ""

    return {
        "singbox": {
            "installed": singbox.is_installed(),
            "running": singbox.is_running(),
            "version": singbox.get_version(),
        },
        "system": _sys_info(),
        "network": {
            "public_ip": pub_ip,
            "domain": state.network.domain,
            "sub_domain": state.network.sub_domain,
            "server_ip": state.network.server_ip,
        },
        "counts": {
            "transports": _counts(transports),
            "enhancements": _counts(enhancements),
            "security": _counts(sec),
            "users": {"total": len(users), "active": active_users},
        },
        "protocols": status_map,
    }


ROUTES = [
    ("GET", r"/api/dashboard", dashboard),
]
