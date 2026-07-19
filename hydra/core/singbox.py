"""
hydra/core/singbox.py — Управление Sing-Box.

Установка, запуск, генерация конфига, проверка статуса.
Sing-Box — центральный оркестратор: все протоколы → inbound'ы,
WARP/DNS/GeoIP → outbound/route/rules.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from hydra.plugins.base import ConfigFragment
from hydra.core.state import AppState, PluginState, load_state, save_state

SINGBOX_BIN = Path("/usr/local/bin/sing-box")
SINGBOX_CONFIG = Path("/etc/sing-box/config.json")
SINGBOX_SERVICE = Path("/etc/systemd/system/sing-box.service")
LOG_FILE = Path("/var/log/hydra/install.log")


def _find_singbox():
    """Ищет бинарник sing-box в известных путях."""
    for p in ("/usr/local/bin/sing-box", "/usr/bin/sing-box"):
        if Path(p).exists():
            return Path(p)
    w = shutil.which("sing-box")
    return Path(w) if w else None


def _log(level: str, msg: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        ts = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{level}] {msg}\n")
    except Exception:
        pass


def _run(cmd: list, capture: bool = True, timeout: int = 30) -> subprocess.CompletedProcess:
    import os
    kw = {"timeout": timeout}
    if capture:
        kw.update(capture_output=True, text=True, encoding="utf-8", errors="replace")
    else:
        kw.update(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    env = os.environ.copy()
    env["ENABLE_DEPRECATED_LEGACY_DNS_SERVERS"] = "true"
    env["ENABLE_DEPRECATED_MISSING_DOMAIN_RESOLVER"] = "true"
    return subprocess.run(cmd, env=env, **kw)


# ═════════════════════════════════════════════════════════════════════════════
#  Установка
# ═════════════════════════════════════════════════════════════════════════════

def is_installed() -> bool:
    """Проверяет, установлен ли Sing-Box."""
    return _find_singbox() is not None


def get_version() -> Optional[str]:
    """Возвращает версию установленного Sing-Box."""
    bin_path = _find_singbox()
    if not bin_path:
        return None
    r = _run([str(bin_path), "version"])
    if r.returncode == 0:
        first_line = r.stdout.strip().split("\n")[0]
        parts = first_line.split()
        for p in parts:
            if p[0].isdigit():
                return p
    return None


EXTENDED_REPO = "shtorm-7/sing-box-extended"


def install(force: bool = False) -> bool:
    """Устанавливает sing-box-extended из GitHub releases."""
    if not force and is_installed() and "extended" in (get_version() or "").lower():
        return True

    _log("INFO", "Installing sing-box-extended...")

    # Останавливаем службу перед заменой бинарника, чтобы не было конфликтов
    try:
        stop()
    except Exception as e:
        _log("WARNING", f"Failed to stop sing-box: {e}")

    from hydra.utils.net import detect_arch
    from hydra.utils.downloader import download_github_asset_filtered, extract_tarball

    arch = detect_arch()  # "amd64" | "arm64"

    def _match(name: str) -> bool:
        """Точный фильтр: linux-{arch}.tar.gz без суффиксов."""
        return (
            f"linux-{arch}.tar.gz" in name
            and "compressed" not in name
            and "musl" not in name
            and "glibc" not in name
            and "purego" not in name
        )

    dest = Path("/tmp/singbox-install")
    dest.mkdir(parents=True, exist_ok=True)
    tarball = dest / "sing-box.tar.gz"

    if not download_github_asset_filtered(EXTENDED_REPO, _match, tarball):
        _log("ERROR", "Failed to download sing-box-extended")
        return False

    extract_tarball(tarball, dest)

    # Найти бинарник sing-box в распакованном каталоге
    candidate = None
    for p in dest.rglob("sing-box"):
        if p.is_file() and p.stat().st_size > 1_000_000:  # >1MB = бинарник
            candidate = p
            break

    if not candidate:
        _log("ERROR", "sing-box binary not found in archive")
        shutil.rmtree(str(dest), ignore_errors=True)
        return False

    # Удаляем старый бинарник, если он существует, для исключения "Text file busy"
    if SINGBOX_BIN.exists():
        try:
            SINGBOX_BIN.unlink()
        except Exception as e:
            _log("WARNING", f"Failed to unlink {SINGBOX_BIN}: {e}")

    import shutil as _sh
    _sh.move(str(candidate), str(SINGBOX_BIN))
    SINGBOX_BIN.chmod(0o755)
    _sh.rmtree(str(dest), ignore_errors=True)

    _log("INFO", f"sing-box-extended installed: {get_version()}")
    return is_installed()


# ═════════════════════════════════════════════════════════════════════════════
#  Генерация конфига
# ═════════════════════════════════════════════════════════════════════════════

def _base_config(state: AppState) -> dict:
    config = {
        "log": {"level": "info", "timestamp": True},
        "inbounds": [
            {
                "type": "socks",
                "tag": "socks-in",
                "listen": "127.0.0.1",
                "listen_port": 1080,
            },
        ],
        "outbounds": [
            {
                "type": "direct",
                "tag": "direct",
            }
        ],
        "route": {
            "rules": [],
            "auto_detect_interface": True,
            "default_mark": 255,
            "final": "direct",
        },
    }
    if state.network.tproxy_enabled:
        config["inbounds"].append({
            "type": "tproxy",
            "tag": "tproxy-in",
            "listen": "::",
            "listen_port": state.network.tproxy_port,
        })
        # Предотвращение петель маршрутизации TPROXY
        config["route"]["rules"].append({
            "inbound": ["tproxy-in"],
            "port": [state.network.tproxy_port],
            "action": "reject"
        })
        config["route"]["rules"].append({
            "action": "sniff",
            "sniffer": ["http", "tls", "quic"],
        })
        
    if getattr(state.network, "clash_api_enabled", False):
        port = getattr(state.network, "clash_api_port", 9090)
        secret = getattr(state.network, "clash_api_secret", "")
        config["experimental"] = {
            "clash_api": {
                "external_controller": f"127.0.0.1:{port}",
                "secret": secret
            }
        }
        
    return config


def _dns_config(state: AppState) -> dict:
    """DNS-конфиг по умолчанию (публичные DoH)."""
    return {
        "servers": [
            {
                "tag": "dns-remote",
                "address": "https://dns.quad9.net/dns-query",
                "address_resolver": "dns-direct",
                "strategy": "ipv4_only",
                "detour": "direct",
            },
            {
                "tag": "dns-direct",
                "address": "1.1.1.1",
                "detour": "direct",
            },
        ],
        "rules": [],
    }


def generate_config(state: AppState, fragments: dict[str, ConfigFragment]) -> dict:
    config = _base_config(state)
    
    if "endpoints" not in config:
        config["endpoints"] = []

    for name, frag in fragments.items():
        config["inbounds"].extend(frag.inbounds)
        config["outbounds"].extend(frag.outbounds)
        config["route"]["rules"].extend(frag.route_rules)
        if hasattr(frag, "endpoints") and frag.endpoints:
            config["endpoints"].extend(frag.endpoints)

    if "endpoints" in config and not config["endpoints"]:
        config.pop("endpoints")

    # DNS-конфиг (DNSCrypt / публичные DoH)
    dns_config = {}
    for name, frag in fragments.items():
        if hasattr(frag, "dns") and frag.dns:
            dns_config = frag.dns
            break
    config["dns"] = dns_config if dns_config else _dns_config(state)

    # Если плагины не дали ни одного inbound — добавляем fallback
    if not config["inbounds"]:
        config["inbounds"].append({
            "type": "mixed", "tag": "mixed-in",
            "listen": "127.0.0.1", "listen_port": 2080,
        })
    # Гарантируем direct outbound (нужен для DNS и как fallback)
    has_direct = any(o.get("tag") == "direct" for o in config["outbounds"])
    if not has_direct:
        config["outbounds"].append({"type": "direct", "tag": "direct"})

    return config


def write_config(config: dict) -> bool:
    """Записывает конфиг и проверяет валидность."""
    SINGBOX_CONFIG.parent.mkdir(parents=True, exist_ok=True)

    tmp = SINGBOX_CONFIG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")

    # Валидация
    bin_path = _find_singbox()
    if not bin_path:
        return False
    r = _run([str(bin_path), "check", "-c", str(tmp)])
    if r.returncode != 0:
        # Сохраним невалидный конфиг для отладки
        debug_path = Path("/var/log/hydra/warp_debug_config.json")
        try:
            debug_path.parent.mkdir(parents=True, exist_ok=True)
            debug_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        _log("ERROR", f"Sing-Box config invalid. Stdout: {r.stdout} Stderr: {r.stderr}")
        tmp.unlink(missing_ok=True)
        return False

    tmp.replace(SINGBOX_CONFIG)
    return True


# ═════════════════════════════════════════════════════════════════════════════
#  Управление службой
# ═════════════════════════════════════════════════════════════════════════════

def _install_service() -> bool:
    """Создаёт systemd-юнит для sing-box."""
    bin_path = _find_singbox()
    if not bin_path:
        return False

    # Создаём рабочую директорию (нужна для sing-box run)
    work_dir = Path("/var/lib/sing-box")
    work_dir.mkdir(parents=True, exist_ok=True)

    unit = f"""[Unit]
Description=sing-box service
Documentation=https://sing-box.sagernet.org
After=network.target nss-lookup.target

[Service]
Type=simple
User=root
WorkingDirectory=/var/lib/sing-box
Environment=LEGACY_DNS_SERVERS=true ENABLE_DEPRECATED_LEGACY_DNS_SERVERS=true ENABLE_DEPRECATED_MISSING_DOMAIN_RESOLVER=true
ExecStart={bin_path} run -c {SINGBOX_CONFIG}
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=30
LimitNPROC=500
LimitNOFILE=1000000
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_SYS_PTRACE
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_SYS_PTRACE

[Install]
WantedBy=multi-user.target
"""
    SINGBOX_SERVICE.parent.mkdir(parents=True, exist_ok=True)
    SINGBOX_SERVICE.write_text(unit)
    subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
    return True


def start() -> bool:
    """Запускает sing-box. Создаёт минимальный конфиг, если его нет."""
    # Сбрасываем предыдущее состояние (мог застрять в auto-restart)
    _run(["systemctl", "stop", "sing-box"], capture=False)

    if not SINGBOX_CONFIG.exists():
        _log("INFO", "No config found, creating minimal default...")
        minimal = {
            "log": {"level": "info"},
            "inbounds": [
                {"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1", "listen_port": 2080}
            ],
            "outbounds": [
                {"type": "direct", "tag": "direct"}
            ],
        }
        write_config(minimal)

    _install_service()
    r = _run(["systemctl", "start", "sing-box"], capture=False)
    if r.returncode != 0:
        return False
    time.sleep(1)
    if is_running():
        enable_autostart()
        return True
    return False


def stop() -> bool:
    """Останавливает sing-box."""
    _run(["systemctl", "stop", "sing-box"], capture=False)
    return not is_running()


def reload() -> bool:
    """Перезагружает конфиг sing-box (graceful)."""
    if not is_running():
        return start()
    r = _run(["systemctl", "reload", "sing-box"], capture=False)
    return r.returncode == 0


def restart() -> bool:
    """Полный перезапуск sing-box."""
    _run(["systemctl", "restart", "sing-box"], capture=False)
    time.sleep(1)
    return is_running()


def is_running() -> bool:
    """Проверяет, работает ли sing-box."""
    r = _run(["systemctl", "is-active", "--quiet", "sing-box"])
    return r.returncode == 0


def enable_autostart() -> None:
    """Включает автозапуск при загрузке."""
    _run(["systemctl", "enable", "sing-box"], capture=False)


def status_text() -> str:
    """Возвращает текстовый статус Sing-Box."""
    version = get_version()
    running = is_running()
    state = load_state()
    update_suffix = ""
    if state.install.get("singbox_update_available") and version:
        update_suffix = " (Доступно обновление)"
    return (
        f"Sing-Box: {version or 'не установлен'}{update_suffix} | "
        f"{'✓ запущен' if running else '✗ остановлен'}"
    )


def parse_version(v_str: Optional[str]) -> tuple[int, ...]:
    """Парсит строку версии в кортеж чисел для сравнения."""
    if not v_str:
        return (0,)
    import re
    match = re.search(r'(\d+(?:\.\d+)+)', v_str)
    if match:
        try:
            return tuple(map(int, match.group(1).split('.')))
        except ValueError:
            pass
    return (0,)


def update_kernel() -> tuple[bool, str]:
    """
    Обновляет ядро sing-box до последней версии с созданием резервной копии и автооткатом.
    Возвращает (success, message).
    """
    if not SINGBOX_BIN.exists():
        return False, "Sing-Box не установлен, обновление невозможно"

    backup_bin = SINGBOX_BIN.with_suffix(".bak")
    _log("INFO", f"Creating backup of sing-box binary to {backup_bin}")
    
    # 1. Создаем резервную копию бинарника
    try:
        if backup_bin.exists():
            backup_bin.unlink()
        shutil.copy2(SINGBOX_BIN, backup_bin)
    except Exception as e:
        _log("ERROR", f"Failed to create backup: {e}")
        return False, f"Ошибка создания резервной копии: {e}"

    # Запоминаем, был ли сервис запущен до обновления
    was_running = is_running()

    # 2. Скачиваем и устанавливаем обновление
    success_install = False
    try:
        # install(force=True) выполняет скачивание, остановку и замену
        success_install = install(force=True)
    except Exception as e:
        _log("ERROR", f"Installation failed during update: {e}")
        success_install = False

    if not success_install:
        # Откат
        _log("ERROR", "Installation failed, rolling back to backup...")
        try:
            stop()
        except Exception:
            pass
        try:
            if backup_bin.exists():
                if SINGBOX_BIN.exists():
                    SINGBOX_BIN.unlink()
                shutil.copy2(backup_bin, SINGBOX_BIN)
                SINGBOX_BIN.chmod(0o755)
            if was_running:
                start()
            return False, "Не удалось скачать или распаковать обновление. Выполнен откат."
        except Exception as rb_err:
            _log("CRITICAL", f"Rollback failed: {rb_err}")
            return False, f"Ошибка при установке и сбой отката: {rb_err}"

    # 3. Верифицируем новый бинарник
    new_version = get_version()
    if not new_version:
        _log("ERROR", "New binary verification failed (cannot get version), rolling back...")
        try:
            stop()
        except Exception:
            pass
        try:
            if SINGBOX_BIN.exists():
                SINGBOX_BIN.unlink()
            shutil.copy2(backup_bin, SINGBOX_BIN)
            SINGBOX_BIN.chmod(0o755)
            if was_running:
                start()
            return False, "Новый бинарник не запускается. Выполнен откат."
        except Exception as rb_err:
            return False, f"Новый бинарник поврежден и сбой отката: {rb_err}"

    # 4. Проверяем валидность конфига
    if SINGBOX_CONFIG.exists():
        r = _run([str(SINGBOX_BIN), "check", "-c", str(SINGBOX_CONFIG)])
        if r.returncode != 0:
            _log("ERROR", f"New binary rejected existing config, rolling back. Stderr: {r.stderr}")
            try:
                stop()
            except Exception:
                pass
            try:
                if SINGBOX_BIN.exists():
                    SINGBOX_BIN.unlink()
                shutil.copy2(backup_bin, SINGBOX_BIN)
                SINGBOX_BIN.chmod(0o755)
                if was_running:
                    start()
                return False, "Конфигурация несовместима с новым ядром. Выполнен откат."
            except Exception as rb_err:
                return False, f"Конфигурация несовместима и сбой отката: {rb_err}"

    # 5. Перезапуск и проверка службы
    if was_running:
        _log("INFO", "Restarting service and checking status...")
        if not start():
            _log("ERROR", "Service failed to start with new binary, rolling back...")
            try:
                stop()
            except Exception:
                pass
            try:
                if SINGBOX_BIN.exists():
                    SINGBOX_BIN.unlink()
                shutil.copy2(backup_bin, SINGBOX_BIN)
                SINGBOX_BIN.chmod(0o755)
                start()
                return False, "Служба не смогла запуститься с новым ядром. Выполнен откат."
            except Exception as rb_err:
                return False, f"Служба не запустилась и сбой отката: {rb_err}"

    # Очистка
    try:
        backup_bin.unlink(missing_ok=True)
    except Exception as e:
        _log("WARNING", f"Failed to remove backup file: {e}")

    try:
        from hydra.core.state import update_state
        def reset_update_flag(latest):
            latest.install.pop("singbox_update_available", None)
            latest.install.pop("singbox_latest_version", None)
            return True
        update_state(reset_update_flag)
    except Exception as e:
        _log("WARNING", f"Failed to reset update flags in state: {e}")

    return True, f"Ядро успешно обновлено до версии {new_version}"

