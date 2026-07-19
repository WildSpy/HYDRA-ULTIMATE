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


def test_pending_config_is_retried_when_limit_checks_are_disabled():
    state = AppState()
    state.install["sync_limits_enabled"] = False
    state.install["sync_warp_enabled"] = False
    state.install["sync_updates_enabled"] = False
    state.install["sync_config_pending"] = True

    with patch("hydra.core.state.load_state", return_value=state), \
         patch.object(sync_agent, "update_state", side_effect=_state_updater(state)), \
         patch.object(sync_agent, "check_traffic_limits") as check_limits, \
         patch.object(sync_agent, "_log"), \
         patch("hydra.core.orchestrator.apply_config", return_value=True) as apply:
        ok, _ = sync_agent.run_sync()

    assert ok is True
    assert "sync_config_pending" not in state.install
    check_limits.assert_not_called()
    apply.assert_called_once_with(state)


def test_manual_full_check_ignores_automatic_check_toggles():
    state = AppState()
    state.install.update({
        "sync_limits_enabled": False,
        "sync_warp_enabled": False,
        "sync_updates_enabled": False,
    })
    warp_status = MagicMock(enabled=False)

    with patch("hydra.core.state.load_state", return_value=state), \
         patch.object(sync_agent, "update_state", side_effect=_state_updater(state)), \
         patch.object(sync_agent, "check_traffic_limits", return_value=[]) as check_limits, \
         patch.object(sync_agent, "get_enabled", return_value=[]), \
         patch.object(sync_agent, "_log"), \
         patch("hydra.plugins.warp.plugin.WarpPlugin.status", return_value=warp_status) as warp_check, \
         patch("hydra.utils.downloader.latest_release", return_value="v1.13.11-extended-2.1.0") as latest, \
         patch("hydra.core.singbox.get_version", return_value="1.13.11-extended-2.1.0"):
        ok, _ = sync_agent.run_sync(force_all_checks=True, force_update_check=True)

    assert ok is True
    check_limits.assert_called_once_with(state)
    warp_check.assert_called_once()
    latest.assert_called_once()


def test_manual_run_reports_update_check_failure():
    state = AppState()
    state.install["sync_warp_enabled"] = False

    with patch("hydra.core.state.load_state", return_value=state), \
         patch.object(sync_agent, "update_state", side_effect=_state_updater(state)), \
         patch.object(sync_agent, "check_traffic_limits", return_value=[]), \
         patch.object(sync_agent, "get_enabled", return_value=[]), \
         patch.object(sync_agent, "_log"), \
         patch("hydra.utils.downloader.latest_release", return_value="unknown"):
        ok, message = sync_agent.run_sync(force_update_check=True)

    assert ok is False
    assert "Sing-Box" in message
