import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hydra.core.singbox import parse_version, update_kernel, SINGBOX_BIN, SINGBOX_CONFIG
from hydra.core.state import AppState


def test_parse_version():
    assert parse_version("1.18.0-extended") == (1, 18, 0)
    assert parse_version("v1.19.1") == (1, 19, 1)
    assert parse_version("1.19.0-extended-b8") == (1, 19, 0, 8)
    assert parse_version("1.13.14-extended-2.5.0") == (1, 13, 14, 2, 5, 0)
    assert parse_version("v1.13.14-extended-2.5.2") == (1, 13, 14, 2, 5, 2)
    assert parse_version(None) == (0,)
    assert parse_version("invalid") == (0,)


@pytest.fixture
def mock_singbox_paths(tmp_path):
    bin_path = tmp_path / "sing-box"
    config_path = tmp_path / "config.json"
    bin_path.write_text("original binary content")
    config_path.write_text("{}")
    
    with patch("hydra.core.singbox.SINGBOX_BIN", bin_path), \
         patch("hydra.core.singbox.SINGBOX_CONFIG", config_path):
        yield bin_path, config_path


def test_update_kernel_success(mock_singbox_paths):
    bin_path, config_path = mock_singbox_paths
    
    state = AppState()
    state.install["singbox_update_available"] = True
    state.install["singbox_latest_version"] = "v1.19.0"

    def dummy_update_state(mutator):
        mutator(state)
        return state, None

    # Simulate success: install updates the binary file content
    def mock_install_success(force=False):
        bin_path.write_text("new binary content")
        return True

    with patch("hydra.core.singbox.is_running", return_value=True), \
         patch("hydra.core.singbox.install", side_effect=mock_install_success) as mock_install, \
         patch("hydra.core.singbox.get_version", return_value="1.19.0"), \
         patch("hydra.core.singbox._run") as mock_run, \
         patch("hydra.core.singbox.start", return_value=True) as mock_start, \
         patch("hydra.core.state.update_state", side_effect=dummy_update_state):
        
        run_result = MagicMock()
        run_result.returncode = 0
        mock_run.return_value = run_result

        success, msg = update_kernel()
        assert success is True
        assert "успешно обновлено" in msg
        assert bin_path.read_text() == "new binary content"
        # backup is removed
        assert not bin_path.with_suffix(".bak").exists()
        assert state.install.get("singbox_update_available") is None


def test_update_kernel_fail_installation(mock_singbox_paths):
    bin_path, config_path = mock_singbox_paths
    
    # Simulate failed install: it modifies/corrupts the binary then returns False
    def mock_install_fail(force=False):
        bin_path.write_text("corrupted content")
        return False

    with patch("hydra.core.singbox.is_running", return_value=True), \
         patch("hydra.core.singbox.install", side_effect=mock_install_fail), \
         patch("hydra.core.singbox.stop") as mock_stop, \
         patch("hydra.core.singbox.start") as mock_start:
        
        success, msg = update_kernel()
        assert success is False
        assert "Не удалось скачать или распаковать" in msg
        # Verification that the original file is restored
        assert bin_path.read_text() == "original binary content"
        mock_start.assert_called_once()


def test_update_kernel_fail_verification(mock_singbox_paths):
    bin_path, config_path = mock_singbox_paths
    
    def mock_install_succ(force=False):
        bin_path.write_text("broken executable")
        return True

    with patch("hydra.core.singbox.is_running", return_value=True), \
         patch("hydra.core.singbox.install", side_effect=mock_install_succ), \
         patch("hydra.core.singbox.get_version", return_value=None), \
         patch("hydra.core.singbox.stop") as mock_stop, \
         patch("hydra.core.singbox.start") as mock_start:
        
        success, msg = update_kernel()
        assert success is False
        assert "Новый бинарник не запускается" in msg
        assert bin_path.read_text() == "original binary content"
        mock_start.assert_called_once()


def test_update_kernel_fail_config_check(mock_singbox_paths):
    bin_path, config_path = mock_singbox_paths
    
    def mock_install_succ(force=False):
        bin_path.write_text("incompatible config binary")
        return True

    with patch("hydra.core.singbox.is_running", return_value=True), \
         patch("hydra.core.singbox.install", side_effect=mock_install_succ), \
         patch("hydra.core.singbox.get_version", return_value="1.19.0"), \
         patch("hydra.core.singbox._run") as mock_run, \
         patch("hydra.core.singbox.stop") as mock_stop, \
         patch("hydra.core.singbox.start") as mock_start:
        
        run_result = MagicMock()
        run_result.returncode = 1  # config check fails
        mock_run.return_value = run_result

        success, msg = update_kernel()
        assert success is False
        assert "Конфигурация несовместима" in msg
        assert bin_path.read_text() == "original binary content"
        mock_start.assert_called_once()


def test_update_kernel_fail_service_start(mock_singbox_paths):
    bin_path, config_path = mock_singbox_paths
    
    def mock_install_succ(force=False):
        bin_path.write_text("unrunnable service binary")
        return True

    with patch("hydra.core.singbox.is_running", return_value=True), \
         patch("hydra.core.singbox.install", side_effect=mock_install_succ), \
         patch("hydra.core.singbox.get_version", return_value="1.19.0"), \
         patch("hydra.core.singbox._run") as mock_run, \
         patch("hydra.core.singbox.stop") as mock_stop, \
         patch("hydra.core.singbox.start", side_effect=[False, True]) as mock_start:  # first start fails, second rollback start succeeds
        
        run_result = MagicMock()
        run_result.returncode = 0
        mock_run.return_value = run_result

        success, msg = update_kernel()
        assert success is False
        assert "Служба не смогла запуститься" in msg
        assert bin_path.read_text() == "original binary content"
        assert mock_start.call_count == 2
