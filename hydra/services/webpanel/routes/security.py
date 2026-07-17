"""Маршруты раздела «Безопасность»: fail2ban, ipban, honeypot."""
from __future__ import annotations

from hydra.services.webpanel.errors import BadRequest, NotFound
from hydra.services.webpanel.routes._common import get_plugin, load_state


# ══ Общие toggle-операции для плагинов безопасности ═══════════════════════════

def toggle_all(ctx):
    """Включить/выключить все плагины безопасности (fail2ban+honeypot+ipban)."""
    from hydra.core import orchestrator
    enable = bool(ctx.get("enable", True))

    def _job():
        results = {}
        for name in ("fail2ban", "honeypot", "ipban"):
            try:
                if enable:
                    state = load_state()
                    orchestrator.install_plugin(state, name)
                    state = load_state()
                    orchestrator.enable(state, name)
                else:
                    state = load_state()
                    orchestrator.disable(state, name)
                results[name] = "ok"
            except Exception as exc:  # noqa: BLE001
                results[name] = f"error: {exc}"
        return results

    return {"task_id": ctx.tasks.start("security-toggle-all", _job)}


# ══ Fail2ban ══════════════════════════════════════════════════════════════════

def fail2ban_status(ctx):
    from hydra.plugins.fail2ban import manager as m
    p = get_plugin("fail2ban")
    state = load_state()
    jails = p.jail_options(state)
    active_jails = m._f2b_list_jails() if m._f2b_active() else []
    banned = {}
    for jail in active_jails:
        try:
            banned[jail] = m._f2b_jail_info(jail)
        except Exception:
            banned[jail] = {}
    cfg = state.protocols.get("fail2ban")
    return {
        "installed": m._f2b_installed(),
        "active": m._f2b_active(),
        "jails": jails,
        "active_jails": active_jails,
        "banned": banned,
        "whitelist": (cfg.config.get("whitelist", []) if cfg else []),
    }


def fail2ban_ban(ctx):
    from hydra.plugins.fail2ban import manager as m
    targets = ctx.require("targets")
    if isinstance(targets, str):
        targets = [t.strip() for t in targets.replace(",", " ").split() if t.strip()]
    jail = str(ctx.get("jail", "") or "")
    if not jail:
        active = m._f2b_list_jails()
        jail = active[0] if active else "hydra-sshd"

    resolved_ips: list[str] = []
    labels: list[str] = []
    for raw in targets:
        try:
            display, kind, cidrs = m._resolve_to_cidrs(raw)
            resolved_ips.extend(cidrs)
            labels.append(f"{display} ({kind}, {len(cidrs)})")
        except Exception as exc:  # noqa: BLE001
            labels.append(f"{raw}: ошибка ({exc})")

    banned = m._f2b_ban_many(jail, resolved_ips) if resolved_ips else 0
    return {"jail": jail, "banned": banned, "resolved": labels}


def fail2ban_unban(ctx):
    from hydra.plugins.fail2ban import manager as m
    ips = ctx.require("ips")
    if isinstance(ips, str):
        ips = [i.strip() for i in ips.replace(",", " ").split() if i.strip()]
    ok, fail = m._f2b_unban_many(ips)
    return {"unbanned": ok, "failed": fail}


def fail2ban_log(ctx):
    from hydra.plugins.fail2ban import manager as m
    return {"lines": m._f2b_log_lines()}


def fail2ban_clear_log(ctx):
    from hydra.plugins.fail2ban import manager as m
    ok, msg = m._f2b_clear_log()
    return {"ok": ok, "message": msg}


def fail2ban_history(ctx):
    from hydra.plugins.fail2ban import manager as m
    return {"history": m._f2b_today_ban_history()}


def fail2ban_set_jail(ctx):
    """Настройка джейла: bantime/findtime/maxretry/enabled."""
    from hydra.core.state import update_state, get_protocol
    jail = ctx.params["jail"]
    fields = {}
    for key in ("bantime", "findtime", "maxretry"):
        if key in ctx.body:
            val = str(ctx.body[key])
            if not val.isdigit() or int(val) <= 0:
                raise BadRequest(f"{key} должно быть положительным числом")
            fields[key] = val
    if "enabled" in ctx.body:
        fields["enabled"] = bool(ctx.body["enabled"])
    if not fields:
        raise BadRequest("Нет изменений")

    def _mut(state):
        cfg = get_protocol(state, "fail2ban").config
        jails = cfg.setdefault("jails", {})
        jails.setdefault(jail, {}).update(fields)
        return True

    update_state(_mut)

    def _job():
        p = get_plugin("fail2ban")
        state = load_state()
        from hydra.core.state import save_state
        ok = p.apply(state)
        save_state(state)
        return {"ok": ok}

    return {"task_id": ctx.tasks.start("fail2ban-jail", _job)}


def fail2ban_restore_defaults(ctx):
    def _job():
        p = get_plugin("fail2ban")
        state = load_state()
        from hydra.core.state import save_state
        ok = p.restore_defaults(state)
        save_state(state)
        return {"ok": ok}

    return {"task_id": ctx.tasks.start("fail2ban-restore", _job)}


def fail2ban_whitelist(ctx):
    """Добавить/удалить запись из whitelist. body: {action: add|remove, value}."""
    from hydra.core.state import update_state, get_protocol
    action = str(ctx.require("action"))
    value = str(ctx.require("value")).strip()
    if action not in ("add", "remove"):
        raise BadRequest("action: add | remove")

    def _mut(state):
        cfg = get_protocol(state, "fail2ban").config
        wl = cfg.setdefault("whitelist", [])
        if action == "add" and value not in wl:
            wl.append(value)
        elif action == "remove" and value in wl:
            wl.remove(value)
        return True

    update_state(_mut)

    def _job():
        p = get_plugin("fail2ban")
        state = load_state()
        from hydra.core.state import save_state
        ok = p.apply(state)
        save_state(state)
        return {"ok": ok}

    return {"task_id": ctx.tasks.start("fail2ban-whitelist", _job)}


# ══ IPBan ═════════════════════════════════════════════════════════════════════

def ipban_status(ctx):
    p = get_plugin("ipban")
    try:
        st = p.status()
        info = st.info
    except Exception:
        info = {}
    try:
        banned = p.list_banned()
    except Exception:
        banned = []
    return {"info": info, "banned": banned, "count": len(banned)}


def ipban_ban(ctx):
    p = get_plugin("ipban")
    raw = str(ctx.require("target"))
    comment = str(ctx.get("comment", "") or "")
    ok = p.ban_ip(raw, comment)
    return {"ok": bool(ok)}


def ipban_unban(ctx):
    p = get_plugin("ipban")
    display = ctx.params["target"]
    ok = p.unban_ip(display)
    return {"ok": bool(ok)}


def ipban_flush(ctx):
    p = get_plugin("ipban")
    try:
        p._remove_iptables_rules()
        p._save_state({"entries": []})
        p._ensure_iptables_rules()
    except Exception as exc:  # noqa: BLE001
        raise BadRequest(f"Не удалось снять баны: {exc}")
    return {"ok": True}


# ══ Honeypot ══════════════════════════════════════════════════════════════════

def honeypot_status(ctx):
    p = get_plugin("honeypot")
    cfg = p._load_state()
    try:
        st = p.status()
        running = st.running
    except Exception:
        running = False
    return {
        "running": running,
        "port": cfg.get("port"),
        "whitelist": cfg.get("whitelist", []),
        "banned": list(cfg.get("banned", {}).keys()),
    }


def honeypot_set_port(ctx):
    p = get_plugin("honeypot")
    try:
        port = int(ctx.require("port"))
    except (TypeError, ValueError):
        raise BadRequest("port должен быть числом")
    if not (1 <= port <= 65535):
        raise BadRequest("port вне диапазона")
    cfg = p._load_state()
    cfg["port"] = port
    p._save_state(cfg)
    p._write_script(port, cfg.get("whitelist", []))
    from hydra.core.systemd import restart
    restart("hydra-honeypot")
    return {"ok": True, "port": port}


def honeypot_whitelist(ctx):
    p = get_plugin("honeypot")
    action = str(ctx.require("action"))
    value = str(ctx.require("value")).strip()
    cfg = p._load_state()
    wl = cfg.setdefault("whitelist", [])
    if action == "add" and value not in wl:
        wl.append(value)
    elif action == "remove" and value in wl:
        wl.remove(value)
    else:
        if action not in ("add", "remove"):
            raise BadRequest("action: add | remove")
    p._save_state(cfg)
    return {"ok": True, "whitelist": cfg["whitelist"]}


def honeypot_unban(ctx):
    p = get_plugin("honeypot")
    ip = ctx.params["ip"]
    ok = p._unban_ip(ip)
    return {"ok": bool(ok)}


ROUTES = [
    ("POST", r"/api/security/toggle-all", toggle_all),
    # fail2ban
    ("GET", r"/api/security/fail2ban", fail2ban_status),
    ("POST", r"/api/security/fail2ban/ban", fail2ban_ban),
    ("POST", r"/api/security/fail2ban/unban", fail2ban_unban),
    ("GET", r"/api/security/fail2ban/log", fail2ban_log),
    ("POST", r"/api/security/fail2ban/log/clear", fail2ban_clear_log),
    ("GET", r"/api/security/fail2ban/history", fail2ban_history),
    ("PUT", r"/api/security/fail2ban/jail/(?P<jail>[a-z0-9\-]+)", fail2ban_set_jail),
    ("POST", r"/api/security/fail2ban/restore-defaults", fail2ban_restore_defaults),
    ("POST", r"/api/security/fail2ban/whitelist", fail2ban_whitelist),
    # ipban
    ("GET", r"/api/security/ipban", ipban_status),
    ("POST", r"/api/security/ipban/ban", ipban_ban),
    ("DELETE", r"/api/security/ipban/ban/(?P<target>[^/]+)", ipban_unban),
    ("POST", r"/api/security/ipban/flush", ipban_flush),
    # honeypot
    ("GET", r"/api/security/honeypot", honeypot_status),
    ("PUT", r"/api/security/honeypot/port", honeypot_set_port),
    ("POST", r"/api/security/honeypot/whitelist", honeypot_whitelist),
    ("DELETE", r"/api/security/honeypot/ban/(?P<ip>[^/]+)", honeypot_unban),
]
