"""Launcher plumbing: port selection, duplicate detection, frozen paths.

These decisions happen before anything is served, so a mistake here is a user
staring at a window that never opens a browser - with no log to explain it.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import launcher


@pytest.fixture
def taken_port():
    """A port genuinely held open for the duration of a test."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        yield sock.getsockname()[1]


def test_free_port_is_actually_free():
    port = launcher._free_port()
    assert launcher._port_is_free(port)


def test_a_held_port_reads_as_taken(taken_port):
    assert launcher._port_is_free(taken_port) is False


def test_already_ours_recognises_our_own_health_response(taken_port):
    body = b'{"status":"ok","version":"1.0.0","wifi_backend":"mock","simulated":true}'
    response = mock.MagicMock()
    response.read.return_value = body
    response.__enter__.return_value = response

    with mock.patch.object(launcher.urllib.request, "urlopen", return_value=response):
        assert launcher._already_ours(taken_port) is True


def test_already_ours_rejects_an_unrelated_service(taken_port):
    """Something else on port 8000 must not be mistaken for a second copy of
    us, or the launcher would send the user to a stranger's web page."""
    response = mock.MagicMock()
    response.read.return_value = b"<html><body>Someone else's app</body></html>"
    response.__enter__.return_value = response

    with mock.patch.object(launcher.urllib.request, "urlopen", return_value=response):
        assert launcher._already_ours(taken_port) is False


def test_already_ours_is_false_when_nothing_answers():
    with mock.patch.object(
        launcher.urllib.request, "urlopen", side_effect=OSError("connection refused")
    ):
        assert launcher._already_ours(59999) is False


def test_duplicate_launch_opens_the_browser_and_exits_without_starting_a_server(taken_port):
    """Double-clicking twice should surface the window you already have."""
    opened: list[str] = []
    with (
        mock.patch.object(launcher, "_already_ours", return_value=True),
        mock.patch.object(launcher.webbrowser, "open", side_effect=opened.append),
    ):
        code = launcher.main(["--port", str(taken_port)])

    assert code == 0
    assert opened == [f"http://127.0.0.1:{taken_port}"]


def test_duplicate_launch_respects_no_browser(taken_port):
    with (
        mock.patch.object(launcher, "_already_ours", return_value=True),
        mock.patch.object(launcher.webbrowser, "open") as opener,
    ):
        assert launcher.main(["--port", str(taken_port), "--no-browser"]) == 0
    opener.assert_not_called()


def test_frozen_build_keeps_data_out_of_the_disposable_bundle_dir(tmp_path, monkeypatch):
    """PyInstaller wipes its extraction directory on exit, so a survey written
    there would not survive closing the window."""
    import importlib

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    bundle = tmp_path / "bundle"  # stands in for the temp extraction dir
    bundle.mkdir()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "CheckSignalWiFi"), raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    for var in ("CSW_DATA_DIR", "CSW_EXPORT_DIR", "CSW_FRONTEND_DIST", "XDG_DATA_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(fake_home / "AppData" / "Local"))

    config = importlib.reload(importlib.import_module("backend.app.config"))
    try:
        assert config.IS_FROZEN is True
        assert bundle not in config.DATA_DIR.parents and bundle != config.DATA_DIR
        assert config.APP_DIR_NAME in str(config.DATA_DIR)
        assert config.DATA_DIR.is_dir()
        # The UI, being read-only, does ship inside the bundle.
        assert bundle / "frontend_dist" == config.FRONTEND_DIST
    finally:
        # Other tests share this module; restore the unfrozen view.
        monkeypatch.undo()
        importlib.reload(config)
