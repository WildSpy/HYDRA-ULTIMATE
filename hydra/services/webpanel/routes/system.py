"""Маршруты раздела «Ядро и система» + управление задачами."""
from __future__ import annotations

from hydra.services.webpanel.errors import NotFound
from hydra.services.webpanel.routes._common import load_state


def core_status(ctx):
    from hydra.core import singbox
    return {
        "installed": singbox.is_installed(),
        "running": singbox.is_running(),
        "version": singbox.get_version(),
        "config_path": str(singbox.SINGBOX_CONFIG),
    }


def singbox_install(ctx):
    """Установка/переустановка sing-box + apply_config — как фоновая задача."""
    from hydra.core import singbox, orchestrator
    force = bool(ctx.get("force", False))

    def _job():
        ok = singbox.install(force=force)
        if ok:
            state = load_state()
            orchestrator.apply_config(state)
        return {"installed": ok}

    task_id = ctx.tasks.start("singbox-install", _job)
    return {"task_id": task_id}


def singbox_start(ctx):
    from hydra.core import singbox
    return {"ok": singbox.start()}


def singbox_stop(ctx):
    from hydra.core import singbox
    return {"ok": singbox.stop()}


def singbox_restart(ctx):
    from hydra.core import singbox
    return {"ok": singbox.restart()}


def apply_config(ctx):
    """Пересборка и применение конфигурации — фоновая задача (может длиться)."""
    from hydra.core import orchestrator

    def _job():
        state = load_state()
        return {"applied": orchestrator.apply_config(state)}

    task_id = ctx.tasks.start("apply-config", _job)
    return {"task_id": task_id}


# ── задачи ──────────────────────────────────────────────────────────────────

def task_get(ctx):
    task = ctx.tasks.get(ctx.params["id"])
    if task is None:
        raise NotFound("Задача не найдена")
    return task.to_dict()


def task_list(ctx):
    return {"tasks": ctx.tasks.list()}


def panel_info(ctx):
    """Версия панели и параметры установки (для футера и проверки обновлений)."""
    from hydra.services.webpanel import __version__
    from hydra.services.webpanel.updater import (
        install_dir, DEFAULT_REPO, DEFAULT_BRANCH,
    )
    from hydra.core.systemd import is_active
    return {
        "version": __version__,
        "install_dir": str(install_dir()),
        "repo": DEFAULT_REPO,
        "branch": DEFAULT_BRANCH,
        "service_active": is_active("hydra-webpanel"),
    }


def panel_update(ctx):
    """Скачивает свежий пакет панели из форка и перезапускает службу (фон. задача)."""
    repo = ctx.get("repo")
    branch = ctx.get("branch")

    def _job():
        from hydra.services.webpanel import updater
        info = updater.fetch_and_install(
            repo or updater.DEFAULT_REPO, branch or updater.DEFAULT_BRANCH)
        # Перезапуск в отдельной сессии — ответ успеет уйти до рестарта процесса.
        updater.restart_service_detached()
        info["restarting"] = True
        print("Служба будет перезапущена через ~1 сек. Переподключитесь к панели.")
        return info

    return {"task_id": ctx.tasks.start("panel-update", _job)}


def qr_svg(ctx):
    """QR-код в виде SVG. Собирается вручную из матрицы qrcode — без зависимостей
    от PIL/lxml/svg-фабрик (нужен только чистый пакет qrcode)."""
    text = ctx.require("text")
    try:
        import qrcode
    except ImportError:
        from hydra.services.webpanel.errors import ApiError
        raise ApiError("Библиотека qrcode не установлена на сервере", 501)

    qr = qrcode.QRCode(border=2, box_size=1,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    n = len(matrix)
    scale = 10
    size = n * scale
    rects = []
    for y, row in enumerate(matrix):
        for x, val in enumerate(row):
            if val:
                rects.append(f'<rect x="{x*scale}" y="{y*scale}" width="{scale}" height="{scale}"/>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
           f'viewBox="0 0 {size} {size}" shape-rendering="crispEdges">'
           f'<rect width="{size}" height="{size}" fill="#ffffff"/>'
           f'<g fill="#000000">{"".join(rects)}</g></svg>')
    return {"svg": svg}


def install_qrcode(ctx):
    """Устанавливает библиотеку qrcode через pip (фоновая задача)."""
    def _job():
        import subprocess
        import sys
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "qrcode"],
                           capture_output=True, text=True, timeout=180)
        print(r.stdout or "")
        print(r.stderr or "")
        if r.returncode != 0:
            raise RuntimeError("pip install qrcode завершился с ошибкой")
        # проверяем, что теперь импортируется
        subprocess.run([sys.executable, "-c", "import qrcode"], check=True)
        return {"ok": True}

    return {"task_id": ctx.tasks.start("install-qrcode", _job)}


ROUTES = [
    ("GET", r"/api/system", core_status),
    ("POST", r"/api/system/singbox/install", singbox_install),
    ("POST", r"/api/system/singbox/start", singbox_start),
    ("POST", r"/api/system/singbox/stop", singbox_stop),
    ("POST", r"/api/system/singbox/restart", singbox_restart),
    ("POST", r"/api/system/apply", apply_config),
    ("GET", r"/api/tasks", task_list),
    ("GET", r"/api/tasks/(?P<id>[a-f0-9]+)", task_get),
    ("GET", r"/api/qr", qr_svg),
    ("POST", r"/api/system/qrcode/install", install_qrcode),
    ("GET", r"/api/system/panel", panel_info),
    ("POST", r"/api/system/panel/update", panel_update),
]
