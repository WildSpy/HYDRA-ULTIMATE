"""tests/test_webpanel_server.py — маршрутизация, авторизация, статика."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import hydra.services.webpanel.config as config_mod
from hydra.services.webpanel import auth


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "STATE_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "webpanel.json")
    from hydra.services.webpanel.server import WebApp
    application = WebApp()
    application.config.auth.username = "admin"
    application.config.auth.password_hash = auth.hash_password("pw12345", rounds=1000)
    if not application.config.auth.token_secret:
        application.config.auth.token_secret = "c" * 64
    return application


def _call(app, method, path, body=None, headers=None):
    raw = json.dumps(body).encode() if body is not None else b""
    status, hdrs, data = app.handle(method, path, headers or {}, raw, "127.0.0.1")
    try:
        payload = json.loads(data)
    except Exception:
        payload = data
    return status, payload


def test_routes_built(app):
    assert len(app.routes) > 50


def test_login_success_and_session(app):
    status, payload = _call(app, "POST", "/api/login",
                            {"username": "admin", "password": "pw12345"})
    assert status == 200
    token = payload["token"]
    status, payload = _call(app, "GET", "/api/session",
                            headers={"authorization": "Bearer " + token})
    assert status == 200
    assert payload["username"] == "admin"


def test_login_bad_password(app):
    status, payload = _call(app, "POST", "/api/login",
                            {"username": "admin", "password": "nope"})
    assert status == 401


def test_protected_requires_auth(app):
    status, _ = _call(app, "GET", "/api/dashboard")
    assert status == 401


def test_unknown_endpoint_404(app):
    status, _ = _call(app, "GET", "/api/does-not-exist",
                      headers={"authorization": "Bearer " + _token(app)})
    assert status == 404


def test_method_not_allowed_405(app):
    # /api/login существует только для POST
    status, _ = _call(app, "GET", "/api/login")
    assert status == 405


def test_invalid_json_body(app):
    status, _, _ = None, None, None
    st, hdrs, data = app.handle("POST", "/api/login", {}, b"{bad json",
                                "127.0.0.1")
    assert st == 400


def test_static_index_served(app):
    st, hdrs, data = app.handle("GET", "/", {}, b"", "127.0.0.1")
    assert st == 200
    assert b"HYDRA" in data


def test_static_spa_fallback(app):
    st, hdrs, data = app.handle("GET", "/users", {}, b"", "127.0.0.1")
    assert st == 200
    assert b"<!DOCTYPE html>" in data


def test_static_path_traversal_blocked(app):
    st, hdrs, data = app.handle("GET", "/../etc/passwd", {}, b"", "127.0.0.1")
    assert st == 403


def _token(app):
    return auth.issue_token(app.config, "admin")
