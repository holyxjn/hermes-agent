import plistlib
from unittest.mock import patch


def test_service_path_skips_nonexistent_node_modules(tmp_path):
    """Service PATH should not include node_modules/.bin if it doesn't exist."""
    from hermes_cli.gateway import _build_service_path_dirs
    with patch("hermes_cli.gateway.get_hermes_home", return_value=tmp_path / ".hermes"):
        dirs = _build_service_path_dirs(project_root=tmp_path)
    node_modules_bin = str(tmp_path / "node_modules" / ".bin")
    assert node_modules_bin not in dirs


def test_service_path_includes_node_modules_when_present(tmp_path):
    """Service PATH should include node_modules/.bin when it exists."""
    nm_bin = tmp_path / "node_modules" / ".bin"
    nm_bin.mkdir(parents=True)
    from hermes_cli.gateway import _build_service_path_dirs
    with patch("hermes_cli.gateway.get_hermes_home", return_value=tmp_path / ".hermes"):
        dirs = _build_service_path_dirs(project_root=tmp_path)
    assert str(nm_bin) in dirs


def test_service_path_includes_hermes_home_node_modules(tmp_path):
    """Service PATH should include ~/.hermes/node_modules/.bin when it exists."""
    hermes_nm = tmp_path / ".hermes" / "node_modules" / ".bin"
    hermes_nm.mkdir(parents=True)
    from hermes_cli.gateway import _build_service_path_dirs
    with patch("hermes_cli.gateway.get_hermes_home", return_value=tmp_path / ".hermes"):
        dirs = _build_service_path_dirs(project_root=tmp_path)
    assert str(hermes_nm) in dirs


def test_launchd_path_prefers_active_venv_over_legacy_venv(tmp_path, monkeypatch):
    """launchd PATH should resolve hermes from the active venv before stale project/venv."""
    active_bin = tmp_path / ".venv" / "bin"
    legacy_bin = tmp_path / "venv" / "bin"
    active_bin.mkdir(parents=True)
    legacy_bin.mkdir(parents=True)

    import hermes_cli.gateway as gateway_cli

    hermes_home = tmp_path / ".hermes"
    monkeypatch.setattr(gateway_cli, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(gateway_cli, "get_hermes_home", lambda: hermes_home)
    monkeypatch.setattr(gateway_cli.sys, "prefix", str(tmp_path / ".venv"))
    monkeypatch.setattr(gateway_cli.sys, "base_prefix", str(tmp_path / "base-python"))
    monkeypatch.setattr(gateway_cli.shutil, "which", lambda _cmd: None)
    monkeypatch.setenv("PATH", f"{legacy_bin}:{active_bin}:/usr/bin")

    plist = plistlib.loads(gateway_cli.generate_launchd_plist().encode("utf-8"))
    path_entries = plist["EnvironmentVariables"]["PATH"].split(":")

    assert path_entries[0] == str(active_bin)
    assert path_entries.index(str(active_bin)) < path_entries.index(str(legacy_bin))
