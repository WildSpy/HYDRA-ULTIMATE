from unittest.mock import patch

from hydra.core.state import AppState, NetworkConfig, PluginState
from hydra.core import status


def test_build_status_uses_effective_dnscrypt_state_without_mutating_config():
    state = AppState(
        network=NetworkConfig(dnscrypt_enabled=False),
        protocols={"dnscrypt": PluginState(enabled=True)},
    )
    with patch(
        "hydra.plugins.registry.status_all",
        return_value={"dnscrypt": {"enabled": True, "running": True}},
    ):
        payload = status.build_status(state)

    assert payload["network"]["dnscrypt_enabled"] is True
    assert payload["network"]["configured_dnscrypt_enabled"] is False
    assert state.network.dnscrypt_enabled is False
