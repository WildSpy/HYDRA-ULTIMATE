"""tests/test_webpanel_auth.py — хэш паролей, токены сессий, throttling."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hydra.services.webpanel import auth
from hydra.services.webpanel.config import PanelConfig


def test_password_hash_roundtrip():
    h = auth.hash_password("s3cret!", rounds=1000)
    assert h.startswith("pbkdf2_sha256$")
    assert auth.verify_password("s3cret!", h)
    assert not auth.verify_password("wrong", h)


def test_password_hash_is_salted():
    a = auth.hash_password("same", rounds=1000)
    b = auth.hash_password("same", rounds=1000)
    assert a != b  # разные соли
    assert auth.verify_password("same", a)
    assert auth.verify_password("same", b)


def test_verify_password_rejects_garbage():
    assert not auth.verify_password("x", "")
    assert not auth.verify_password("x", "not-a-hash")
    assert not auth.verify_password("", auth.hash_password("y", rounds=1000))


def _cfg():
    c = PanelConfig()
    c.auth.token_secret = "a" * 64
    c.auth.username = "admin"
    c.session_ttl_hours = 12
    return c


def test_token_roundtrip():
    cfg = _cfg()
    tok = auth.issue_token(cfg, "admin")
    assert auth.verify_token(cfg, tok) == "admin"


def test_token_tamper_detected():
    cfg = _cfg()
    tok = auth.issue_token(cfg, "admin")
    body, _, sig = tok.partition(".")
    assert auth.verify_token(cfg, body + ".deadbeef") is None
    assert auth.verify_token(cfg, tok + "x") is None


def test_token_wrong_secret():
    cfg = _cfg()
    tok = auth.issue_token(cfg, "admin")
    other = _cfg()
    other.auth.token_secret = "b" * 64
    assert auth.verify_token(other, tok) is None


def test_token_expiry():
    cfg = _cfg()
    cfg.session_ttl_hours = 0  # клампится в issue_token до 1 часа минимум
    tok = auth.issue_token(cfg, "admin")
    assert auth.verify_token(cfg, tok) == "admin"


def test_authenticate():
    cfg = _cfg()
    cfg.auth.password_hash = auth.hash_password("pw12345", rounds=1000)
    assert auth.authenticate(cfg, "admin", "pw12345")
    assert not auth.authenticate(cfg, "admin", "nope")
    assert not auth.authenticate(cfg, "other", "pw12345")


def test_login_throttle():
    t = auth.LoginThrottle(max_attempts=3, window=100, lockout=100)
    t.check("1.2.3.4")  # ok
    for _ in range(3):
        t.record_failure("1.2.3.4")
    try:
        t.check("1.2.3.4")
        assert False, "должно быть заблокировано"
    except ValueError as exc:
        assert int(str(exc)) > 0
    # другой IP не затронут
    t.check("9.9.9.9")


def test_throttle_success_resets():
    t = auth.LoginThrottle(max_attempts=2, window=100, lockout=100)
    t.record_failure("ip")
    t.record_success("ip")
    t.record_failure("ip")
    t.check("ip")  # не заблокирован — счётчик сброшен
