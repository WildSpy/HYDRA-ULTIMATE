"""
hydra/services/sync_agent.py — Фоновый агент синхронизации v2.

Проверяет лимиты трафика и сроки действия подписок.
Уведомляет плагины при блокировке пользователя.
Запускается через systemd timer каждые 5 минут.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from hydra.core.state import update_state
from hydra.plugins.registry import get_enabled
from hydra.services.traffic import check_traffic_limits


def run_sync(force_update_check: bool = False) -> None:
    """
    Основная логика синхронизации:
      1. Проверить лимиты трафика -> заблокировать превысивших
      2. Проверить TTL (срок действия) -> заблокировать истёкших
      3. Уведомить плагины о блокировке
      4. Применить измененный конфиг к службам
    """
    from hydra.core.state import load_state
    now = datetime.now(timezone.utc)

    # Сначала считываем текущие настройки активности
    state = load_state()
    limits_enabled = state.install.get("sync_limits_enabled", True)
    warp_enabled = state.install.get("sync_warp_enabled", True)
    updates_enabled = state.install.get("sync_updates_enabled", True)

    blocked = {}
    if limits_enabled:
        # Refresh counters, evaluate all restrictions and persist the block in one
        # lock transaction. The pending marker survives a crash or failed apply.
        def refresh_and_block(latest):
            exceeded = set(check_traffic_limits(latest))
            blocked_users: dict[str, str] = {}
            for user in latest.users:
                if user.blocked:
                    continue
                reason = ""
                if user.email in exceeded:
                    reason = "traffic limit exceeded"
                elif user.expiry_date:
                    try:
                        dt_str = user.expiry_date
                        if dt_str.endswith("Z"):
                            dt_str = dt_str[:-1] + "+00:00"
                        expiry = datetime.fromisoformat(dt_str)
                        if expiry.tzinfo is None:
                            expiry = expiry.replace(tzinfo=timezone.utc)
                        if expiry <= now:
                            reason = "subscription expired"
                    except (ValueError, TypeError):
                        _log(f"User {user.email} has an invalid expiry date")
                if reason:
                    user.blocked = True
                    blocked_users[user.email] = reason
            if blocked_users:
                latest.install["sync_config_pending"] = True
            return blocked_users

        state, blocked = update_state(refresh_and_block)
        for email, reason in blocked.items():
            _log(f"User {email} blocked: {reason}")
            user = next((item for item in state.users if item.email == email), None)
            if user is None:
                continue
            for plugin in get_enabled(state):
                try:
                    plugin.on_user_block(user, state)
                except Exception as exc:
                    _log(f"Plugin {plugin.meta.name} block hook failed for {email}: {exc}")

        # A failed or interrupted apply must be retried on the next timer tick.
        if state.install.get("sync_config_pending"):
            from hydra.core.orchestrator import apply_config
            try:
                applied = apply_config(state)
            except Exception as exc:
                applied = False
                _log(f"Server config apply failed: {exc}")
            if applied:
                def clear_pending(latest):
                    return latest.install.pop("sync_config_pending", None) is not None

                state, _ = update_state(clear_pending)
                _log("Applied server config due to user access changes")
            else:
                _log("Server config apply failed; will retry on the next run")
    else:
        _log("Sync: User limits check is disabled by settings")

    # 3. WARP: автообновление внешних списков (раз в 24 часа)
    if warp_enabled:
        try:
            from hydra.plugins.warp.plugin import WarpPlugin
            from hydra.core.orchestrator import apply_config
            p = WarpPlugin()
            status = p.status()
            if status.enabled:
                # Проверяем кэш
                cache_file = Path("/var/lib/hydra/warp_external.json")
                need_update = True
                if cache_file.exists():
                    try:
                        import json
                        data = json.loads(cache_file.read_text(encoding="utf-8"))
                        up_str = data.get("updated_at")
                        if up_str:
                            updated_at = datetime.fromisoformat(up_str)
                            diff = datetime.now() - updated_at
                            if diff.total_seconds() < 86400:
                                need_update = False
                        elif data.get("last_attempt_at"):
                            attempted_at = datetime.fromisoformat(data["last_attempt_at"])
                            if (datetime.now() - attempted_at).total_seconds() < 3600:
                                need_update = False
                    except Exception:
                        pass
                
                if need_update:
                    _log("WARP: Triggering daily auto-update of external rules...")
                    ok, msg = p.update_external_rules()
                    _log(f"WARP: Update result: {msg}")
                    if ok:
                        if apply_config(state):
                            _log("WARP: Updated rules applied")
                        else:
                            def mark_pending(latest):
                                latest.install["sync_config_pending"] = True

                            state, _ = update_state(mark_pending)
                            _log("WARP: Config apply failed; will retry on the next run")
        except Exception as e:
            _log(f"WARP auto-update check failed: {e}")
    else:
        _log("Sync: WARP external rules auto-update is disabled by settings")

    # 4. Sing-Box updates checking (раз в 24 часа или принудительно)
    if updates_enabled or force_update_check:
        try:
            from hydra.utils.downloader import latest_release
            from hydra.core.singbox import EXTENDED_REPO, get_version, parse_version

            last_check = state.install.get("singbox_last_update_check")
            need_check = True
            if not force_update_check and last_check:
                try:
                    last_dt = datetime.fromisoformat(last_check)
                    # Проверяем каждые 24 часа (86400 секунд)
                    if (datetime.now(timezone.utc) - last_dt).total_seconds() < 86400:
                        need_check = False
                except Exception:
                    pass

            if need_check:
                _log("Sing-Box Update: Checking for updates...")
                latest_ver = latest_release(EXTENDED_REPO)
                if latest_ver and latest_ver != "unknown":
                    current_ver = get_version()
                    
                    curr_parsed = parse_version(current_ver)
                    late_parsed = parse_version(latest_ver)
                    update_avail = late_parsed > curr_parsed
                    
                    _log(f"Sing-Box Update: Current version: {current_ver}, latest version on GitHub: {latest_ver}, update available: {update_avail}")

                    def save_update_info(latest):
                        latest.install["singbox_last_update_check"] = datetime.now(timezone.utc).isoformat()
                        latest.install["singbox_update_available"] = update_avail
                        latest.install["singbox_latest_version"] = latest_ver
                        return True

                    state, _ = update_state(save_update_info)
                else:
                    _log("Sing-Box Update: Failed to get latest version from GitHub")
        except Exception as e:
            _log(f"Sing-Box Update: Update check failed: {e}")
    else:
        _log("Sync: Sing-Box update check is disabled by settings")

    pending = bool(state.install.get("sync_config_pending"))
    _log(f"Sync completed: newly blocked users={len(blocked)}, config pending={pending}")

def _log(msg: str) -> None:
    try:
        log = Path("/var/log/hydra/sync-agent.log")
        log.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with log.open("a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


if __name__ == "__main__":
    try:
        run_sync()
    except Exception as e:
        _log(f"Sync failed: {e}")
        print(f"Sync agent error: {e}", file=sys.stderr)
        sys.exit(1)
