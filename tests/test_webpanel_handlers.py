"""tests/test_webpanel_handlers.py — обработчики пользователей против temp state.

Оркестратор и генератор подписок подменяются лёгкими стабами, чтобы тесты не
требовали root/systemd/сети.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import hydra.core.state as state_mod
from hydra.core.state import User, add_user as _real_add


class FakeTasks:
    def start(self, kind, thunk):
        # выполняем синхронно и возвращаем псевдо-id
        self.last = thunk()
        return "deadbeef0001"


class Ctx:
    """Минимальный контекст для вызова обработчиков в тестах."""
    def __init__(self, body=None, params=None, query=None):
        self.body = body or {}
        self.params = params or {}
        self.query = query or {}
        self.tasks = FakeTasks()
        self.username = "admin"
        self.client_ip = "127.0.0.1"

    def get(self, key, default=None):
        if key in self.body:
            return self.body[key]
        return self.query.get(key, default)

    def require(self, key):
        val = self.get(key)
        if val is None or val == "":
            from hydra.services.webpanel.errors import BadRequest
            raise BadRequest("missing " + key)
        return val


@pytest.fixture
def temp_state(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state_mod, "STATE_FILE", tmp_path / "state.json")
    # стаб оркестратора: только мутация state + сохранение, без apply_config
    import hydra.core.orchestrator as orch

    def fake_add(state, user):
        _real_add(state, user)
        state_mod.save_state(state)

    def fake_remove(state, email):
        state.users = [u for u in state.users if u.email != email]
        state_mod.save_state(state)

    def fake_block(state, email):
        u = state_mod.find_user(state, email)
        if u:
            u.blocked = True
            state_mod.save_state(state)

    def fake_unblock(state, email):
        u = state_mod.find_user(state, email)
        if u:
            u.blocked = False
            state_mod.save_state(state)

    monkeypatch.setattr(orch, "add_user", fake_add)
    monkeypatch.setattr(orch, "remove_user", fake_remove)
    monkeypatch.setattr(orch, "block_user", fake_block)
    monkeypatch.setattr(orch, "unblock_user", fake_unblock)

    # стаб URL подписки, чтобы не дёргать сеть
    import hydra.services.subscriptions.generator as gen
    monkeypatch.setattr(gen, "get_subscription_url", lambda u, s: "https://sub/" + u.uuid)
    return tmp_path


def test_add_and_list_user(temp_state):
    from hydra.services.webpanel.routes import users
    res = users.add_user(Ctx(body={"email": "a@b.c", "traffic_limit_gb": 5}))
    assert res["email"] == "a@b.c"
    assert res["uuid"]
    assert res["traffic_limit_gb"] == 5

    listing = users.list_users(Ctx())
    emails = [u["email"] for u in listing["users"]]
    assert "a@b.c" in emails


def test_add_duplicate_user_conflict(temp_state):
    from hydra.services.webpanel.routes import users
    from hydra.services.webpanel.errors import Conflict
    users.add_user(Ctx(body={"email": "dup@x.y"}))
    with pytest.raises(Conflict):
        users.add_user(Ctx(body={"email": "dup@x.y"}))


def test_set_limit_and_expiry(temp_state):
    from hydra.services.webpanel.routes import users
    users.add_user(Ctx(body={"email": "u@x.y"}))

    r = users.set_limit(Ctx(params={"email": "u@x.y"}, body={"traffic_limit_gb": 42}))
    assert r["traffic_limit_gb"] == 42

    r = users.set_expiry(Ctx(params={"email": "u@x.y"}, body={"expiry_date": "2030-01-15"}))
    assert r["expiry_date"].startswith("2030-01-15")


def test_set_expiry_bad_date(temp_state):
    from hydra.services.webpanel.routes import users
    from hydra.services.webpanel.errors import BadRequest
    users.add_user(Ctx(body={"email": "u2@x.y"}))
    with pytest.raises(BadRequest):
        users.set_expiry(Ctx(params={"email": "u2@x.y"}, body={"expiry_date": "15-01-2030"}))


def test_block_unblock(temp_state):
    from hydra.services.webpanel.routes import users
    users.add_user(Ctx(body={"email": "b@x.y"}))
    users.block_user(Ctx(params={"email": "b@x.y"}))
    assert users.get_user(Ctx(params={"email": "b@x.y"}))["blocked"] is True
    users.unblock_user(Ctx(params={"email": "b@x.y"}))
    assert users.get_user(Ctx(params={"email": "b@x.y"}))["blocked"] is False


def test_get_missing_user_404(temp_state):
    from hydra.services.webpanel.routes import users
    from hydra.services.webpanel.errors import NotFound
    with pytest.raises(NotFound):
        users.get_user(Ctx(params={"email": "ghost@x.y"}))


def test_delete_user(temp_state):
    from hydra.services.webpanel.routes import users
    users.add_user(Ctx(body={"email": "d@x.y"}))
    users.delete_user(Ctx(params={"email": "d@x.y"}))
    assert users.list_users(Ctx())["users"] == []
