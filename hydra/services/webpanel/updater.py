"""hydra/services/webpanel/updater.py — самообновление пакета веб-панели.

Скачивает свежий tar-архив ветки форка и заменяет ТОЛЬКО каталог
hydra/services/webpanel (+ requirements-webpanel.txt) в текущей установке.
Остальная платформа (state.json, плагины, sing-box) не затрагивается.

Используется:
  • API-маршрутом POST /api/system/panel/update (кнопка в панели);
  • CLI:  python3 -m hydra.services.webpanel.updater [--repo URL] [--branch B] [--restart]
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from hydra.services.webpanel import __version__ as CURRENT_VERSION

DEFAULT_REPO = os.environ.get("HYDRA_PANEL_REPO", "https://github.com/WildSpy/HYDRA-ULTIMATE")
DEFAULT_BRANCH = os.environ.get("HYDRA_PANEL_BRANCH", "main")
SERVICE_NAME = "hydra-webpanel"


def install_dir() -> Path:
    """Корень установки HYDRA (…/updater.py → parents[3] = /opt/hydra)."""
    return Path(__file__).resolve().parents[3]


def _read_version(webpanel_dir: Path) -> str:
    init = webpanel_dir / "__init__.py"
    try:
        for line in init.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("__version__"):
                return line.split("=", 1)[1].strip().strip("\"'")
    except Exception:
        pass
    return "?"


def fetch_and_install(repo: str = DEFAULT_REPO, branch: str = DEFAULT_BRANCH,
                      target: str | Path | None = None) -> dict:
    """Скачивает архив ветки и обновляет каталог webpanel. Возвращает отчёт."""
    target_dir = Path(target) if target else install_dir()
    url = f"{repo}/archive/refs/heads/{branch}.tar.gz"
    print(f"Загрузка {url} …")
    req = urllib.request.Request(url, headers={"User-Agent": "hydra-webpanel-updater"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 — фиксированный https
        payload = resp.read()
    print(f"Получено {len(payload)} байт, распаковка…")

    tmp = Path(tempfile.mkdtemp())
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tf:
            try:
                tf.extractall(tmp, filter="data")  # py3.12+: защита от path traversal
            except TypeError:
                tf.extractall(tmp)                 # py<3.12

        src = None
        src_root = None
        for root in tmp.iterdir():
            if not root.is_dir():
                continue
            candidate = root / "hydra" / "services" / "webpanel"
            if candidate.is_dir():
                src, src_root = candidate, root
                break
        if src is None:
            raise RuntimeError(
                f"В архиве нет hydra/services/webpanel (проверьте ветку '{branch}')")

        new_version = _read_version(src)
        dest = target_dir / "hydra" / "services" / "webpanel"
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Полная замена содержимого пакета (удаление старых файлов не мешает
        # уже запущенному процессу — код перечитается при рестарте).
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)

        req_file = src_root / "requirements-webpanel.txt"
        if req_file.exists():
            shutil.copy2(req_file, target_dir / "requirements-webpanel.txt")

        print(f"Обновлено: {CURRENT_VERSION} → {new_version} в {dest}")
        return {
            "ok": True,
            "old_version": CURRENT_VERSION,
            "new_version": new_version,
            "target": str(target_dir),
            "changed": new_version != CURRENT_VERSION,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def restart_service_detached(delay: float = 2.0) -> None:
    """Перезапускает службу панели в отдельной сессии, чтобы HTTP-ответ успел уйти."""
    subprocess.Popen(  # noqa: S603
        ["/bin/sh", "-c", f"sleep {delay}; systemctl restart {SERVICE_NAME}"],
        start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _main(argv: list[str]) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="hydra.services.webpanel.updater",
                                     description="Обновление веб-панели HYDRA")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--restart", action="store_true", help="Перезапустить службу после обновления")
    args = parser.parse_args(argv)

    info = fetch_and_install(args.repo, args.branch)
    if args.restart:
        print("Перезапуск службы hydra-webpanel…")
        subprocess.run(["systemctl", "restart", SERVICE_NAME], check=False)
    return 0 if info.get("ok") else 1


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
