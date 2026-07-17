"""Маршруты раздела «Сервер подписок» (hydra-sub)."""
from __future__ import annotations

from hydra.services.webpanel.errors import BadRequest
from hydra.services.webpanel.routes._common import load_state


def _install_dir() -> str:
    from pathlib import Path
    for candidate in ("/opt/hydra", "/opt/HYDRA-ULTIMATE", "/root/HYDRA-ULTIMATE"):
        if Path(candidate).exists():
            return candidate
    return "/opt/hydra"


def _install_unit(state) -> bool:
    from hydra.core.systemd import install_service
    install_dir = _install_dir()
    host = "127.0.0.1" if getattr(state.network, "sub_domain", "") else "0.0.0.0"
    content = f"""[Unit]
Description=HYDRA Subscription Server
After=network.target
Wants=network.target

[Service]
Type=simple
User=root
WorkingDirectory={install_dir}
Environment=PYTHONPATH={install_dir}
ExecStart=/usr/bin/python3 -m hydra.services.subscriptions.generator --host {host} --port 9443
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
    return install_service("hydra-sub", content)


def status(ctx):
    from hydra.core.systemd import is_active
    from hydra.services.subscriptions.generator import find_any_cert
    state = load_state()
    cert, key = find_any_cert(state)
    return {
        "running": is_active("hydra-sub"),
        "sub_domain": getattr(state.network, "sub_domain", ""),
        "cert": cert or "",
        "cert_present": bool(cert and key),
        "port": 9443,
    }


def start(ctx):
    from hydra.core.systemd import start as svc_start
    from hydra.services.subscriptions.generator import find_any_cert
    state = load_state()
    cert, key = find_any_cert(state)
    if not (cert and key):
        raise BadRequest("Нет TLS-сертификата — сервер подписок работает только по HTTPS")
    _install_unit(state)
    return {"ok": svc_start("hydra-sub")}


def stop(ctx):
    import subprocess
    from hydra.core.systemd import stop as svc_stop
    svc_stop("hydra-sub")
    subprocess.run(["systemctl", "disable", "hydra-sub"], capture_output=True)
    return {"ok": True}


def restart(ctx):
    from hydra.core.systemd import restart as svc_restart
    from hydra.services.subscriptions.generator import find_any_cert
    state = load_state()
    cert, key = find_any_cert(state)
    if not (cert and key):
        raise BadRequest("Нет TLS-сертификата")
    return {"ok": svc_restart("hydra-sub")}


def set_domain(ctx):
    from hydra.core.state import update_state
    domain = str(ctx.get("sub_domain", "") or "").strip()

    def _mut(state):
        state.network.sub_domain = domain
        return True

    state, _ = update_state(_mut)
    # Перестроить SNI-роутер и переустановить юнит
    try:
        from hydra.core.sni_router import rebuild as rebuild_mux
        rebuild_mux(state)
    except Exception:
        pass
    _install_unit(state)
    return {"ok": True, "sub_domain": domain}


def obtain_cert(ctx):
    """Выпуск Let's Encrypt через certbot (фоновая задача)."""
    state = load_state()
    if not getattr(state.network, "sub_domain", ""):
        raise BadRequest("Сначала настройте домен подписок")

    def _job():
        return {"ok": _certbot(load_state())}

    return {"task_id": ctx.tasks.start("certbot", _job)}


def _certbot(state) -> bool:
    """Портирование _obtain_cert_for_sub из TUI (без интерактива)."""
    import shutil
    import subprocess
    from pathlib import Path

    sub_domain = state.network.sub_domain
    cert_path = Path(f"/etc/letsencrypt/live/{sub_domain}/fullchain.pem")
    key_path = Path(f"/etc/letsencrypt/live/{sub_domain}/privkey.pem")
    if cert_path.exists() and key_path.exists():
        r = subprocess.run(
            ["openssl", "x509", "-checkend", "2592000", "-noout", "-in", str(cert_path)],
            capture_output=True)
        if r.returncode == 0:
            print(f"Сертификат для {sub_domain} уже действителен.")
            return True

    print(f"Получение SSL-сертификата для {sub_domain} через certbot...")
    if not shutil.which("certbot"):
        print("Установка certbot...")
        subprocess.run(["apt-get", "update"], capture_output=True)
        subprocess.run(["apt-get", "install", "-y", "certbot"], capture_output=True)

    services_to_stop = ["haproxy", "caddy-naive", "nginx", "apache2"]
    was_running = []
    for s in services_to_stop:
        r = subprocess.run(["systemctl", "is-active", s], capture_output=True, text=True)
        if r.stdout.strip() == "active":
            print(f"Временно останавливаем {s}...")
            subprocess.run(["systemctl", "stop", s])
            was_running.append(s)

    subprocess.run(["ufw", "allow", "80/tcp"], capture_output=True)
    r = subprocess.run([
        "certbot", "certonly", "--standalone", "-d", sub_domain,
        "--non-interactive", "--agree-tos",
        "--register-unsafely-without-email", "--keep-until-expiring",
    ], capture_output=True, text=True)
    print(r.stdout or "")
    print(r.stderr or "")

    for s in reversed(was_running):
        subprocess.run(["systemctl", "start", s])

    if r.returncode == 0:
        # перестроить роутер и перезапустить сервер подписок
        try:
            from hydra.core.sni_router import rebuild as rebuild_mux
            rebuild_mux(state)
        except Exception:
            pass
        from hydra.core.systemd import restart as svc_restart
        svc_restart("hydra-sub")
        print("Сертификат успешно получен!")
        return True
    print("Ошибка работы certbot!")
    return False


ROUTES = [
    ("GET", r"/api/subscriptions", status),
    ("POST", r"/api/subscriptions/start", start),
    ("POST", r"/api/subscriptions/stop", stop),
    ("POST", r"/api/subscriptions/restart", restart),
    ("PUT", r"/api/subscriptions/domain", set_domain),
    ("POST", r"/api/subscriptions/certbot", obtain_cert),
]
