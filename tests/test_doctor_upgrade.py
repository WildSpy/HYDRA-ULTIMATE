from unittest.mock import patch

from hydra.core.doctor import run_doctor
from hydra.core.state import AppState
from hydra.core.upgrade import check_upgrade


def test_doctor_reports_required_failures():
    with patch("hydra.core.doctor.shutil.which", return_value=None), \
         patch("hydra.core.doctor.os.access", return_value=False):
        result = run_doctor(AppState())
    assert result["ok"] is False
    assert "state_directory" in result["required_failures"]


def test_upgrade_check_accepts_clean_supported_state(tmp_path):
    (tmp_path / ".git").mkdir()
    completed = type("Result", (), {"returncode": 0, "stdout": ""})()
    with patch("hydra.core.upgrade.shutil.which", return_value="git"), \
         patch("hydra.core.upgrade.run", return_value=completed):
        result = check_upgrade(AppState(), tmp_path)
    assert result["ready"] is True
    assert result["backup_required"] is True
