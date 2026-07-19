from __future__ import annotations

import pytest

from hydra.core.state import AppState, User, validate_state


def test_validate_state_accepts_defaults_and_users():
    validate_state(AppState(users=[User(email="u@example.com", uuid="u1")]))


def test_validate_state_rejects_invalid_port():
    state = AppState()
    state.network.tproxy_port = 70000
    with pytest.raises(ValueError, match="tproxy_port"):
        validate_state(state)


def test_validate_state_rejects_invalid_email():
    with pytest.raises(ValueError, match="email"):
        validate_state(AppState(users=[User(email="invalid", uuid="u1")]))
