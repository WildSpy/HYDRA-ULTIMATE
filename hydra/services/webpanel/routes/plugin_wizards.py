"""Специфические мастера плагинов: AmneziaWG, Mieru, naive/trusttunnel transport,
telemt, wdtt."""
from __future__ import annotations

from hydra.services.webpanel.errors import BadRequest, NotFound
from hydra.services.webpanel.routes._common import get_plugin, load_state


# ══ AmneziaWG ═════════════════════════════════════════════════════════════════

def awg_profiles(ctx):
    p = get_plugin("amneziawg")
    state = load_state()
    return {"profiles": p.get_profiles(state)}


def awg_add_profile(ctx):
    p = get_plugin("amneziawg")
    name = str(ctx.get("name", "mobile") or "mobile")
    strategy = str(ctx.require("strategy"))
    carrier = str(ctx.get("carrier", "") or "").strip()
    preset = f"{strategy}:{carrier}" if carrier else f"{strategy}:generic"

    def _job():
        state = load_state()
        ok = p.add_profile(name, preset, state)
        return {"ok": bool(ok)}

    return {"task_id": ctx.tasks.start("awg-add-profile", _job)}


def awg_remove_profile(ctx):
    p = get_plugin("amneziawg")
    name = ctx.params["name"]

    def _job():
        state = load_state()
        return {"ok": bool(p.remove_profile(name, state))}

    return {"task_id": ctx.tasks.start("awg-remove-profile", _job)}


def awg_obfuscation_options(ctx):
    from hydra.plugins.amneziawg import presets
    return {
        "strategies": presets.list_strategies(),
        "carriers": presets.list_carriers("mobile"),
        "legacy_presets": presets.list_presets(),
    }


def awg_obfuscation_preview(ctx):
    from hydra.plugins.amneziawg import presets
    strategy = str(ctx.get("strategy", "wired") or "wired")
    carrier = ctx.get("carrier") or None
    params = presets.generate_params(strategy=strategy, carrier=carrier)
    return {"params": params, "strategy": strategy, "carrier": carrier}


def awg_rotate_obfuscation(ctx):
    p = get_plugin("amneziawg")
    profile = str(ctx.get("profile", "desktop") or "desktop")
    strategy = ctx.get("strategy")
    carrier = str(ctx.get("carrier", "") or "").strip()
    preset = None
    if strategy:
        preset = f"{strategy}:{carrier}" if carrier else str(strategy)

    def _job():
        state = load_state()
        return {"ok": bool(p.rotate_obfuscation(state, profile=profile, preset=preset))}

    return {"task_id": ctx.tasks.start("awg-rotate", _job)}


def awg_hardware_tune(ctx):
    def _job():
        from hydra.plugins.amneziawg.tuning import hw_tune_all
        return hw_tune_all()

    return {"task_id": ctx.tasks.start("awg-hw-tune", _job)}


# ══ Mieru ═════════════════════════════════════════════════════════════════════

def mieru_presets(ctx):
    from hydra.plugins.mieru import presets
    p = get_plugin("mieru")
    state = load_state()
    try:
        current = p.get_current_preset(state)
    except Exception:
        current = ""
    return {"presets": presets.list_presets(), "current": current}


def mieru_set_preset(ctx):
    p = get_plugin("mieru")
    name = str(ctx.require("preset"))

    def _job():
        state = load_state()
        return {"ok": bool(p.set_preset(state, name))}

    return {"task_id": ctx.tasks.start("mieru-set-preset", _job)}


# ══ Transport (naive / trusttunnel) ═══════════════════════════════════════════

def set_transport(ctx):
    name = ctx.params["name"]
    if name not in ("naive", "trusttunnel"):
        raise NotFound("Смена транспорта недоступна для этого плагина")
    p = get_plugin(name)
    mode = str(ctx.require("mode"))
    if mode not in ("tcp", "quic", "both"):
        raise BadRequest("mode должен быть tcp | quic | both")

    def _job():
        state = load_state()
        return {"ok": bool(p.set_transport(state, mode))}

    return {"task_id": ctx.tasks.start(f"{name}-transport", _job)}


# ══ Telemt ════════════════════════════════════════════════════════════════════

def telemt_get_config(ctx):
    state = load_state()
    ps = state.protocols.get("telemt")
    return {"config": dict(ps.config) if ps else {}}


def telemt_set_config(ctx):
    """Патч config telemt + reconfigure/apply как фоновая задача."""
    from hydra.core.state import update_state, get_protocol

    patch = ctx.body.get("config", ctx.body)
    if not isinstance(patch, dict) or not patch:
        raise BadRequest("Ожидается объект config с параметрами")
    # не даём перезаписать служебные ключи мусором — просто мержим верхний уровень
    patch = {k: v for k, v in patch.items() if k != "_"}

    def _mut(state):
        ps = get_protocol(state, "telemt")
        ps.config.update(patch)
        return True

    update_state(_mut)

    def _job():
        from hydra.core import orchestrator
        p = get_plugin("telemt")
        state = load_state()
        p.configure(state)
        p.apply(state)
        orchestrator.apply_config(state)
        return {"ok": True}

    return {"task_id": ctx.tasks.start("telemt-reconfigure", _job)}


def telemt_restart(ctx):
    from hydra.core.systemd import restart
    return {"ok": restart("telemt")}


# ══ qWDTT ═════════════════════════════════════════════════════════════════════

def _wdtt_manager():
    from hydra.plugins.wdtt import manager
    return manager


def wdtt_passwords(ctx):
    m = _wdtt_manager()
    data = m._load_passwords()
    pwds = data.get("passwords", {})
    rows = []
    for pw, entry in pwds.items():
        rows.append({
            "password": pw,
            "max_devices": entry.get("max_devices", 1),
            "expires_at": entry.get("expires_at", 0),
            "vk_hash": entry.get("vk_hash", ""),
            "down_bytes": entry.get("down_bytes", 0),
            "up_bytes": entry.get("up_bytes", 0),
            "is_deactivated": entry.get("is_deactivated", False),
        })
    return {"passwords": rows, "count": len(rows)}


def wdtt_create_password(ctx):
    import secrets
    from datetime import datetime, timedelta
    from hydra.plugins.wdtt.plugin import DEFAULT_DTLS_PORT, LOCAL_TUN_PORT
    from hydra.core.state import get_protocol

    m = _wdtt_manager()
    days = max(1, min(365, int(ctx.get("days", 30) or 30)))
    max_devs = max(1, min(10, int(ctx.get("max_devices", 1) or 1)))
    vk_hash = str(ctx.get("vk_hash", "") or "").strip()

    data = m._load_passwords()
    passwords = data.setdefault("passwords", {})
    if len(passwords) >= 10:
        raise BadRequest("Превышен лимит: максимум 10 паролей")

    chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
    new_pass = "".join(secrets.choice(chars) for _ in range(16))
    expires_at = int((datetime.now() + timedelta(days=days)).timestamp())
    passwords[new_pass] = {
        "device_ids": [], "max_devices": max_devs, "expires_at": expires_at,
        "down_bytes": 0, "up_bytes": 0, "vk_hash": vk_hash, "ports": "",
        "is_deactivated": False,
    }
    m._save_passwords(data)
    m._hot_reload()

    state = load_state()
    server_ip = state.network.server_ip or m._get_server_ip()
    ps = get_protocol(state, "wdtt")
    dtls_port = ps.config.get("dtls_port", DEFAULT_DTLS_PORT)
    vk_part = vk_hash if vk_hash else "ВК_ХЕШ"
    link = (f"qwdtt://config?name=qWDTT-{server_ip}&peer={server_ip}:{dtls_port}"
            f"&hashes={vk_part}&workers=16&port={LOCAL_TUN_PORT}&pass={new_pass}")
    return {"password": new_pass, "expires_at": expires_at,
            "max_devices": max_devs, "link": link}


def wdtt_delete_password(ctx):
    m = _wdtt_manager()
    pw = ctx.params["password"]
    data = m._load_passwords()
    if pw not in data.get("passwords", {}):
        raise NotFound("Пароль не найден")
    del data["passwords"][pw]
    m._save_passwords(data)
    m._hot_reload()
    return {"ok": True}


def wdtt_main_link(ctx):
    from hydra.plugins.wdtt.plugin import DEFAULT_DTLS_PORT, LOCAL_TUN_PORT
    from hydra.core.state import get_protocol
    m = _wdtt_manager()
    state = load_state()
    ps = get_protocol(state, "wdtt")
    main_pass = ps.config.get("main_password", "")
    if not main_pass:
        raise NotFound("Главный пароль не задан (qWDTT не установлен)")
    server_ip = state.network.server_ip or m._get_server_ip()
    dtls_port = ps.config.get("dtls_port", DEFAULT_DTLS_PORT)
    link = (f"qwdtt://config?name=qWDTT-{server_ip}&peer={server_ip}:{dtls_port}"
            f"&hashes=ВК_ХЕШ&workers=16&port={LOCAL_TUN_PORT}&pass={main_pass}")
    return {"link": link}


def wdtt_restart(ctx):
    from hydra.core.systemd import restart
    return {"ok": restart("wdtt")}


ROUTES = [
    # AmneziaWG
    ("GET", r"/api/plugins/amneziawg/profiles", awg_profiles),
    ("POST", r"/api/plugins/amneziawg/profiles", awg_add_profile),
    ("DELETE", r"/api/plugins/amneziawg/profiles/(?P<name>[a-z0-9_]+)", awg_remove_profile),
    ("GET", r"/api/plugins/amneziawg/obfuscation/options", awg_obfuscation_options),
    ("POST", r"/api/plugins/amneziawg/obfuscation/preview", awg_obfuscation_preview),
    ("POST", r"/api/plugins/amneziawg/obfuscation/rotate", awg_rotate_obfuscation),
    ("POST", r"/api/plugins/amneziawg/tune", awg_hardware_tune),
    # Mieru
    ("GET", r"/api/plugins/mieru/presets", mieru_presets),
    ("POST", r"/api/plugins/mieru/preset", mieru_set_preset),
    # Transport
    ("POST", r"/api/plugins/(?P<name>[a-z0-9_]+)/transport", set_transport),
    # Telemt
    ("GET", r"/api/plugins/telemt/config", telemt_get_config),
    ("PUT", r"/api/plugins/telemt/config", telemt_set_config),
    ("POST", r"/api/plugins/telemt/restart", telemt_restart),
    # qWDTT
    ("GET", r"/api/plugins/wdtt/passwords", wdtt_passwords),
    ("POST", r"/api/plugins/wdtt/passwords", wdtt_create_password),
    ("DELETE", r"/api/plugins/wdtt/passwords/(?P<password>[A-Za-z0-9]+)", wdtt_delete_password),
    ("GET", r"/api/plugins/wdtt/main-link", wdtt_main_link),
    ("POST", r"/api/plugins/wdtt/restart", wdtt_restart),
]
