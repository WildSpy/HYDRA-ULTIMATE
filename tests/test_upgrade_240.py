from pathlib import Path
import shutil

from hydra.core import state as state_module


def test_240_state_survives_current_load_and_save(tmp_path, monkeypatch):
    fixture = Path(__file__).parent / "fixtures" / "state-2.4.0.json"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    state_file = state_dir / "state.json"
    shutil.copy2(fixture, state_file)
    monkeypatch.setattr(state_module, "STATE_DIR", state_dir)
    monkeypatch.setattr(state_module, "STATE_FILE", state_file)

    loaded = state_module.load_state()
    state_module.save_state(loaded)
    reloaded = state_module.load_state()

    assert reloaded.users[0].email == "legacy@example.com"
    assert reloaded.users[0].uuid == "legacy-uuid"
    assert reloaded.users[0].credentials["naive"]["password"] == "preserve-me"
