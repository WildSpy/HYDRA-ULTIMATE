"""hydra/services/webpanel/server.py — HTTP-сервер веб-панели (только stdlib).

ThreadingHTTPServer + BaseHTTPRequestHandler. Вся логика маршрутизации вынесена в
WebApp.handle(), который работает с абстрактными (method, path, headers, body) —
это делает диспетчер тестируемым без сокетов.

Обработчики маршрутов вызывают существующие функции ядра HYDRA in-process
(сервер работает под root, как и TUI).
"""
from __future__ import annotations

import json
import mimetypes
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional

from hydra.services.webpanel import auth as auth_mod
from hydra.services.webpanel.config import PanelConfig, load_config
from hydra.services.webpanel.errors import ApiError, NotFound, Unauthorized
from hydra.services.webpanel.tasks import MANAGER

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Заголовки безопасности для всех ответов.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


class Route:
    """Один маршрут API: метод, скомпилированный regex пути, обработчик."""

    __slots__ = ("method", "pattern", "handler", "auth_required")

    def __init__(self, method: str, pattern: str, handler: Callable[["Ctx"], Any],
                 auth_required: bool = True):
        self.method = method.upper()
        # Полное соответствие пути; именованные группы -> ctx.params
        self.pattern = re.compile("^" + pattern + "$")
        self.handler = handler
        self.auth_required = auth_required


class Ctx:
    """Контекст запроса, передаваемый в обработчик маршрута."""

    def __init__(self, app: "WebApp", method: str, path: str, params: dict,
                 query: dict, body: dict, headers: dict, client_ip: str,
                 username: Optional[str]):
        self.app = app
        self.method = method
        self.path = path
        self.params = params            # из regex-групп пути
        self.query = query             # dict[str, str] (первое значение)
        self.body = body               # разобранный JSON (dict) или {}
        self.headers = headers
        self.client_ip = client_ip
        self.username = username
        self.tasks = MANAGER
        self.config = app.config

    # ── удобные геттеры входных данных ────────────────────────────────────
    def get(self, key: str, default: Any = None) -> Any:
        if key in self.body:
            return self.body[key]
        return self.query.get(key, default)

    def require(self, key: str) -> Any:
        val = self.get(key)
        if val is None or val == "":
            from hydra.services.webpanel.errors import BadRequest
            raise BadRequest(f"Не указан обязательный параметр: {key}")
        return val


class WebApp:
    """Ядро приложения: конфиг, throttle, таблица маршрутов, диспетчеризация."""

    def __init__(self, config: Optional[PanelConfig] = None):
        self.config = config or load_config()
        self.throttle = auth_mod.LoginThrottle()
        from hydra.services.webpanel.routes import build_routes
        self.routes: list[Route] = build_routes()

    # ── основной вход: (метод, путь, заголовки, тело) -> (код, заголовки, байты)
    def handle(self, method: str, raw_path: str, headers: dict,
               body_bytes: bytes, client_ip: str) -> tuple[int, dict, bytes]:
        parsed = urllib.parse.urlparse(raw_path)
        path = parsed.path
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}

        if path.startswith("/api/"):
            return self._handle_api(method, path, query, headers, body_bytes, client_ip)
        return self._handle_static(method, path)

    # ── API ────────────────────────────────────────────────────────────────
    def _handle_api(self, method, path, query, headers, body_bytes, client_ip):
        # Разбор JSON-тела
        body: dict = {}
        if body_bytes:
            try:
                body = json.loads(body_bytes.decode("utf-8"))
                if not isinstance(body, dict):
                    body = {"_": body}
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._json(400, {"error": "Некорректный JSON в теле запроса"})

        # Поиск маршрута
        matched: Optional[Route] = None
        params: dict = {}
        path_exists = False
        for route in self.routes:
            m = route.pattern.match(path)
            if not m:
                continue
            path_exists = True
            if route.method == method:
                matched = route
                params = m.groupdict()
                break

        if matched is None:
            if path_exists:
                return self._json(405, {"error": "Метод не поддерживается"})
            return self._json(404, {"error": "Эндпоинт не найден"})

        # Авторизация
        username = self._authed_user(headers)
        if matched.auth_required and username is None:
            return self._json(401, {"error": "Требуется авторизация"})

        ctx = Ctx(self, method, path, params, query, body, headers, client_ip, username)
        try:
            result = matched.handler(ctx)
        except ApiError as exc:
            return self._json(exc.status, {"error": exc.message})
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            return self._json(500, {"error": f"Внутренняя ошибка: {exc}"})

        status = 200
        if isinstance(result, tuple) and len(result) == 2:
            result, status = result
        if result is None:
            result = {"ok": True}
        return self._json(status, result)

    def _authed_user(self, headers: dict) -> Optional[str]:
        authz = headers.get("authorization") or headers.get("Authorization") or ""
        if authz.lower().startswith("bearer "):
            token = authz[7:].strip()
            return auth_mod.verify_token(self.config, token)
        return None

    # ── Статика (SPA) ────────────────────────────────────────────────────────
    def _handle_static(self, method: str, path: str) -> tuple[int, dict, bytes]:
        if method not in ("GET", "HEAD"):
            return self._json(405, {"error": "Метод не поддерживается"})

        rel = path.lstrip("/")
        if rel == "":
            rel = "index.html"

        target = (STATIC_DIR / rel).resolve()
        # Защита от path traversal
        if not str(target).startswith(str(STATIC_DIR.resolve())):
            return self._json(403, {"error": "Доступ запрещён"})

        if not target.is_file():
            # SPA-фолбэк: любой не-файловый путь -> index.html
            target = STATIC_DIR / "index.html"
            if not target.is_file():
                return self._json(404, {"error": "Панель не собрана (нет index.html)"})

        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",
                                                   "application/json"):
            ctype += "; charset=utf-8"
        data = target.read_bytes()
        headers = {"Content-Type": ctype}
        # для index.html не кэшируем, для ассетов можно
        if target.name != "index.html":
            headers["Cache-Control"] = "public, max-age=3600"
        return 200, headers, data

    # ── помощник JSON-ответа ──────────────────────────────────────────────────
    @staticmethod
    def _json(status: int, payload: dict) -> tuple[int, dict, bytes]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return status, {"Content-Type": "application/json; charset=utf-8"}, data


class _Handler(BaseHTTPRequestHandler):
    server_version = "HydraPanel/1.0"
    app: WebApp = None  # type: ignore[assignment]

    def log_message(self, format, *args):  # тишина в stdout
        pass

    def _client_ip(self) -> str:
        # За обратным прокси можно доверять X-Forwarded-For, но по умолчанию — сокет.
        return self.client_address[0] if self.client_address else "?"

    def _dispatch(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length > 0 else b""
        headers = {k.lower(): v for k, v in self.headers.items()}
        try:
            status, resp_headers, data = self.app.handle(
                method, self.path, headers, body, self._client_ip())
        except Exception as exc:  # noqa: BLE001
            status, resp_headers, data = 500, {"Content-Type": "application/json"}, \
                json.dumps({"error": str(exc)}).encode("utf-8")

        self.send_response(status)
        for key, value in resp_headers.items():
            self.send_header(key, value)
        for key, value in _SECURITY_HEADERS.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if method != "HEAD":
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")


def serve(host: Optional[str] = None, port: Optional[int] = None,
          tls: Optional[bool] = None) -> None:
    """Запускает сервер панели (блокирующе)."""
    app = WebApp()
    cfg = app.config
    bind_host = host or cfg.host
    bind_port = port or cfg.port
    use_tls = cfg.tls.enabled if tls is None else tls

    _Handler.app = app
    httpd = ThreadingHTTPServer((bind_host, bind_port), _Handler)

    scheme = "http"
    if use_tls:
        cert, key = _resolve_cert(cfg)
        if cert and key:
            import ssl
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certfile=cert, keyfile=key)
            httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
            scheme = "https"
        else:
            print("WARNING: TLS включён, но сертификат не найден — запуск по HTTP.")

    if not cfg.is_provisioned:
        print("WARNING: пароль администратора не задан! "
              "Выполните: python3 -m hydra.services.webpanel.auth set-password")

    print(f"HYDRA Web Panel: {scheme}://{bind_host}:{bind_port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def _resolve_cert(cfg: PanelConfig) -> tuple[Optional[str], Optional[str]]:
    """Возвращает (cert, key): из конфига, либо из сертификатов HYDRA/Let's Encrypt."""
    if cfg.tls.cert and cfg.tls.key and Path(cfg.tls.cert).exists():
        return cfg.tls.cert, cfg.tls.key
    try:
        from hydra.core.state import load_state
        from hydra.services.subscriptions.generator import find_any_cert
        cert, key = find_any_cert(load_state())
        if cert and key:
            return cert, key
    except Exception:
        pass
    return None, None
