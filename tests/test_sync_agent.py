from unittest.mock import MagicMock, patch

from hydra.core.state import AppState, User
from hydra.services import sync_agent


def _state_updater(state: AppState):
    def update(mutator):
        result = mutator(state)
        return state, result
    return update


def test_failed_config_apply_is_retried_on_next_sync():
    user = User(email="alice@example.com", uuid="token")
    state = AppState(users=[user])
    warp_status = MagicMock(enabled=False)

    with patch.object(sync_agent, "update_state", side_effect=_state_updater(state)), \
         patch.object(sync_agent, "check_traffic_limits", side_effect=[[user.email], []]), \
         patch.object(sync_agent, "get_enabled", return_value=[]), \
         patch.object(sync_agent, "_log"), \
         patch("hydra.core.orchestrator.apply_config", side_effect=[False, True]) as apply, \
         patch("hydra.plugins.warp.plugin.WarpPlugin.status", return_value=warp_status):
        sync_agent.run_sync()
        assert user.blocked is True
        assert state.install["sync_config_pending"] is True

        sync_agent.run_sync()

    assert "sync_config_pending" not in state.install
    assert apply.call_count == 2


def test_expired_user_is_blocked_and_config_is_applied():
    user = User(
        email="expired@example.com",
        uuid="token",
        expiry_date="2000-01-01T00:00:00Z",
    )
    state = AppState(users=[user])
    warp_status = MagicMock(enabled=False)

    with patch.object(sync_agent, "update_state", side_effect=_state_updater(state)), \
         patch.object(sync_agent, "check_traffic_limits", return_value=[]), \
         patch.object(sync_agent, "get_enabled", return_value=[]), \
         patch.object(sync_agent, "_log"), \
         patch("hydra.core.orchestrator.apply_config", return_value=True) as apply, \
         patch("hydra.plugins.warp.plugin.WarpPlugin.status", return_value=warp_status):
        sync_agent.run_sync()

    assert user.blocked is True
    assert "sync_config_pending" not in state.install
    apply.assert_called_once()


def test_failed_warp_apply_is_queued_for_retry():
    state = AppState()
    warp_status = MagicMock(enabled=True)
    cache = MagicMock()
    cache.exists.return_value = False

    with patch.object(sync_agent, "update_state", side_effect=_state_updater(state)), \
         patch.object(sync_agent, "check_traffic_limits", return_value=[]), \
         patch.object(sync_agent, "get_enabled", return_value=[]), \
         patch.object(sync_agent, "_log"), \
         patch.object(sync_agent, "Path", return_value=cache), \
         patch("hydra.core.orchestrator.apply_config", return_value=False), \
         patch("hydra.plugins.warp.plugin.WarpPlugin.status", return_value=warp_status), \
         patch("hydra.plugins.warp.plugin.WarpPlugin.update_external_rules", return_value=(True, "ok")):
        sync_agent.run_sync()

    assert state.install["sync_config_pending"] is True
