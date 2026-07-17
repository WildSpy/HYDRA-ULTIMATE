"""Маршруты раздела «Сетевые службы»: DNSCrypt и WARP."""
from __future__ import annotations

from hydra.services.webpanel.errors import BadRequest, Conflict, NotFound
from hydra.services.webpanel.routes._common import get_plugin, load_state


# ══ DNSCrypt ══════════════════════════════════════════════════════════════════

def dnscrypt_status(ctx):
    from hydra.plugins import registry
    from hydra.plugins.dnscrypt import manager as m
    st = registry.status_all().get("dnscrypt", {})
    try:
        names = m._get_current_server_names()
    except Exception:
        names = []
    return {"status": st, "server_names": names}


def dnscrypt_measure(ctx):
    """Скачивает список резолверов и измеряет задержку (фоновая задача)."""
    def _job():
        from hydra.plugins.dnscrypt import manager as m
        resolvers, sorted_by_rtt, debug = m._fetch_resolver_list()
        top = resolvers[:60]
        measured = m._measure_all_latency(top)
        return {
            "resolvers": [{"name": n, "rtt_ms": rtt} for n, rtt in measured],
            "count": len(resolvers),
        }

    return {"task_id": ctx.tasks.start("dnscrypt-measure", _job)}


def dnscrypt_apply_resolvers(ctx):
    from hydra.plugins.dnscrypt import manager as m
    from hydra.core.state import update_state, get_protocol
    names = ctx.require("server_names")
    if isinstance(names, str):
        names = [n.strip() for n in names.replace(",", " ").split() if n.strip()]
    if not names:
        raise BadRequest("Список резолверов пуст")
    ok = m._apply_server_names(names)

    def _mut(state):
        get_protocol(state, "dnscrypt").config["server_names"] = names
        return True

    update_state(_mut)
    return {"ok": bool(ok), "server_names": names}


# ══ WARP ══════════════════════════════════════════════════════════════════════

def _warp_destinations() -> list[str]:
    from hydra.plugins.warp.plugin import WARP_PROFILES_DIR, WGCF_PROFILE
    dests = ["direct"]
    try:
        for p in sorted(WARP_PROFILES_DIR.glob("*.conf")):
            dests.append(f"warp_{p.stem}")
    except Exception:
        pass
    try:
        if WGCF_PROFILE.exists():
            dests.append("warp")
    except Exception:
        pass
    return dests


def warp_status(ctx):
    from hydra.plugins import registry
    from hydra.plugins.warp.plugin import EXTERNAL_LISTS, WARP_PROFILES_DIR
    state = load_state()
    ps = state.protocols.get("warp")
    cfg = ps.config if ps else {}
    st = registry.status_all().get("warp", {})
    try:
        profiles = sorted([p.stem for p in WARP_PROFILES_DIR.glob("*.conf")])
    except Exception:
        profiles = []
    return {
        "status": st,
        "local_lists": cfg.get("local_lists", {}),
        "list_targets": cfg.get("list_targets", {}),
        "external_lists": EXTERNAL_LISTS,
        "profiles": profiles,
        "destinations": _warp_destinations(),
    }


def warp_create_list(ctx):
    from hydra.core.state import update_state, get_protocol
    name = str(ctx.require("name")).strip().lower()
    if not name.isalnum():
        raise BadRequest("Имя списка: только буквы и цифры")

    def _mut(state):
        cfg = get_protocol(state, "warp").config
        local = cfg.setdefault("local_lists", {})
        if name in local:
            raise Conflict("Список с таким именем уже существует")
        local[name] = {"domains": [], "ips": []}
        cfg.setdefault("list_targets", {})[f"local:{name}"] = "none"
        return True

    update_state(_mut)
    return {"ok": True, "name": name}


def warp_delete_list(ctx):
    from hydra.core.state import update_state, get_protocol
    name = ctx.params["name"]
    if name == "default":
        raise BadRequest("Системный список 'default' удалить нельзя")

    def _mut(state):
        cfg = get_protocol(state, "warp").config
        local = cfg.setdefault("local_lists", {})
        if name not in local:
            raise NotFound("Список не найден")
        del local[name]
        cfg.setdefault("list_targets", {}).pop(f"local:{name}", None)
        return True

    update_state(_mut)
    _apply_if_enabled()
    return {"ok": True}


def warp_update_list(ctx):
    """Заменяет содержимое локального списка. body: {domains: [], ips: []}."""
    from hydra.core.state import update_state, get_protocol
    name = ctx.params["name"]
    domains = ctx.get("domains")
    ips = ctx.get("ips")

    def _mut(state):
        cfg = get_protocol(state, "warp").config
        local = cfg.setdefault("local_lists", {})
        if name not in local:
            raise NotFound("Список не найден")
        if domains is not None:
            local[name]["domains"] = list(domains)
        if ips is not None:
            local[name]["ips"] = list(ips)
        return True

    update_state(_mut)
    return {"ok": True}


def warp_set_routing(ctx):
    """Назначает точку выхода списку. body: {key, target}."""
    from hydra.core.state import update_state, get_protocol
    key = str(ctx.require("key"))          # local:<name> | ext:<key>
    target = str(ctx.require("target"))    # none|direct|warp|warp_<profile>
    valid = set(_warp_destinations()) | {"none"}
    if target not in valid:
        raise BadRequest(f"Недопустимая точка выхода. Доступно: {sorted(valid)}")

    def _mut(state):
        cfg = get_protocol(state, "warp").config
        cfg.setdefault("list_targets", {})[key] = target
        return True

    update_state(_mut)

    fetch_ext = key.startswith("ext:") and target != "none"

    def _job():
        result = {"ok": True}
        if fetch_ext:
            p = get_plugin("warp")
            ok, msg = p.update_external_rules()
            result["external_update"] = {"ok": ok, "message": msg}
        from hydra.core import orchestrator
        state = load_state()
        ps = state.protocols.get("warp")
        if ps and ps.enabled:
            orchestrator.apply_config(state)
        return result

    return {"task_id": ctx.tasks.start("warp-routing", _job)}


def warp_update_external(ctx):
    def _job():
        p = get_plugin("warp")
        ok, msg = p.update_external_rules()
        from hydra.core import orchestrator
        state = load_state()
        ps = state.protocols.get("warp")
        if ps and ps.enabled:
            orchestrator.apply_config(state)
        return {"ok": ok, "message": msg}

    return {"task_id": ctx.tasks.start("warp-external-update", _job)}


def _apply_if_enabled():
    try:
        from hydra.core import orchestrator
        state = load_state()
        ps = state.protocols.get("warp")
        if ps and ps.enabled:
            orchestrator.apply_config(state)
    except Exception:
        pass


ROUTES = [
    # DNSCrypt
    ("GET", r"/api/network/dnscrypt", dnscrypt_status),
    ("POST", r"/api/network/dnscrypt/resolvers/measure", dnscrypt_measure),
    ("PUT", r"/api/network/dnscrypt/resolvers", dnscrypt_apply_resolvers),
    # WARP
    ("GET", r"/api/network/warp", warp_status),
    ("POST", r"/api/network/warp/local-lists", warp_create_list),
    ("PUT", r"/api/network/warp/local-lists/(?P<name>[a-z0-9]+)", warp_update_list),
    ("DELETE", r"/api/network/warp/local-lists/(?P<name>[a-z0-9]+)", warp_delete_list),
    ("PUT", r"/api/network/warp/routing", warp_set_routing),
    ("POST", r"/api/network/warp/external/update", warp_update_external),
]
