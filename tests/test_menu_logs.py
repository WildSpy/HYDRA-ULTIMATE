from subprocess import CompletedProcess
from unittest.mock import patch

from hydra.ui.menus import _log_source_status, _read_log_source, _sync_agent_log_snapshot


def test_read_log_source_tails_file_without_loading_it_as_one_string(tmp_path):
    log = tmp_path / "service.log"
    log.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    lines, error = _read_log_source("file", str(log), 2)

    assert lines == ["three", "four"]
    assert error == ""


def test_read_log_source_reports_missing_file(tmp_path):
    lines, error = _read_log_source("file", str(tmp_path / "missing.log"), 10)

    assert lines == []
    assert "не создан" in error


def test_read_log_source_uses_journalctl_for_systemd_unit():
    completed = CompletedProcess(
        args=[], returncode=0,
        stdout="2026-01-01 first\n2026-01-01 second\n", stderr="",
    )
    with patch("hydra.ui.menus.subprocess.run", return_value=completed) as run:
        lines, error = _read_log_source("journal", "sing-box", 25)

    assert lines == ["2026-01-01 first", "2026-01-01 second"]
    assert error == ""
    command = run.call_args.args[0]
    assert command[:3] == ["journalctl", "-u", "sing-box"]
    assert "25" in command


def test_journal_status_distinguishes_active_and_missing_units():
    with patch("hydra.ui.menus._unit_active", return_value=True):
        assert _log_source_status("journal", "sing-box") == "активно"

    with patch("hydra.ui.menus._unit_active", return_value=False), \
         patch("hydra.ui.menus._unit_known", return_value=False):
        assert _log_source_status("journal", "missing") == "не установлено"


def test_sync_agent_log_snapshot_reports_latest_line_and_freshness(tmp_path):
    log = tmp_path / "sync-agent.log"
    log.write_text("old\n\nlatest\n", encoding="utf-8")
    modified = log.stat().st_mtime

    line, freshness, stale = _sync_agent_log_snapshot(log, modified + 301)

    assert line == "latest"
    assert freshness == "5 мин назад"
    assert stale is False


def test_sync_agent_log_snapshot_marks_missed_intervals_as_stale(tmp_path):
    log = tmp_path / "sync-agent.log"
    log.write_text("last run\n", encoding="utf-8")
    modified = log.stat().st_mtime

    _, freshness, stale = _sync_agent_log_snapshot(log, modified + 601)

    assert freshness == "10 мин назад"
    assert stale is True
