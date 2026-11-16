from pathlib import Path

import pytest

from jobradar import autostart
from jobradar.paths import Paths


@pytest.fixture
def paths(tmp_path):
    return Paths(tmp_path)


def test_windows_dry_run(paths, monkeypatch, tmp_path):
    monkeypatch.setattr(autostart.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    out = autostart.enable(paths, dry_run=True)
    assert "JobRadar.vbs" in out and "Startup" in out and "-m jobradar run" in out
    assert f'JOBRADAR_HOME") = "{tmp_path}"' in out
    assert not (tmp_path / "AppData").exists()


def test_linux_dry_run(paths, monkeypatch):
    monkeypatch.setattr(autostart.sys, "platform", "linux")
    out = autostart.enable(paths, dry_run=True)
    assert "jobradar.service" in out and "Restart=on-failure" in out
    assert "systemctl --user enable --now jobradar.service" in out
    assert "systemctl" in autostart.disable(paths, dry_run=True)


def test_macos_dry_run(paths, monkeypatch):
    monkeypatch.setattr(autostart.sys, "platform", "darwin")
    out = autostart.enable(paths, dry_run=True)
    assert "com.jobradar.plist" in out and "launchctl load" in out and "RunAtLoad" in out


def test_windows_enable_disable_roundtrip(paths, monkeypatch, tmp_path):
    monkeypatch.setattr(autostart.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    assert not autostart.is_enabled()
    autostart.enable(paths)
    assert autostart.is_enabled()
    assert Path(autostart._target()).read_text(encoding="utf-8").startswith("'")
    autostart.disable(paths)
    assert not autostart.is_enabled()
    assert "no estaba" in autostart.disable(paths)
