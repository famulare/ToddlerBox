"""A damaged parent config edit never stops the child session or moves child work."""
import pygame
import pytest

from toddlerbox import config as config_module
from toddlerbox.config import DEFAULT_CONFIG, check, config_errors, load_config
from toddlerbox.launcher import _load_apps, _reset_shared_display_state
from toddlerbox.ui.common import load_image

STANDARD = [app["name"] for app in DEFAULT_CONFIG["launcher"]["apps"]]


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    monkeypatch.setenv("KIDBOX_CONFIG", str(path))
    monkeypatch.delenv("TODDLERBOX_DATA_ROOT", raising=False)
    return path


@pytest.mark.parametrize("text", [
    "launcher:\n\tapps: []\n",               # tab indent
    "data_root: '/var/lib/toddlerbox\n",     # unclosed quote
    "- just\n- a list\n",                    # non-mapping top level
    "launcher: null\npaint: null\nphotos: 5\nmusic: loud\n",
    "launcher:\n  apps: null\n",
    "launcher:\n  apps:\n    - Paint\n    - {name: X, command: \"python -m 'unbalanced\"}\n",
    "data_root: null\n",
    "launcher:\n  photos_prewarm_idle_ms: soon\n  photos_prewarm: 'false'\n",
    "paint:\n  autosave_seconds: .nan\n  palette: [[1, 2], red, [300, 0, 0]]\n",
])
def test_damaged_config_yields_a_usable_standard_configuration(config_file, text):
    config_file.write_text(text)
    config = load_config()
    assert config_errors()
    assert [app.name for app in _load_apps(config)] == STANDARD
    assert isinstance(config["data_root"], str)
    assert int(config["launcher"].get("photos_prewarm_idle_ms", 600)) >= 0
    assert all(len(color) == 3 for color in config["paint"]["palette"])
    assert config["paint"].get("autosave_seconds", 10) >= 1


def test_non_utf8_and_unreadable_files_fall_back(config_file):
    config_file.write_bytes(b"data_root: \xff\xfe\n")
    assert [app.name for app in _load_apps(load_config())] == STANDARD
    config_file.unlink()
    config_file.mkdir()
    assert [app.name for app in _load_apps(load_config())] == STANDARD


def test_missing_named_config_never_falls_back_to_a_development_file(config_file, tmp_path, monkeypatch):
    (tmp_path / "cwd").mkdir()
    (tmp_path / "cwd/config.yaml").write_text("data_root: ./data\n")
    monkeypatch.chdir(tmp_path / "cwd")
    config = load_config()
    assert config["data_root"] == DEFAULT_CONFIG["data_root"]
    assert any("missing" in problem for problem in config_errors())


def test_session_pin_keeps_child_work_in_place_whatever_the_file_says(config_file, monkeypatch):
    config_file.write_text("data_root: /somewhere/else\n")
    monkeypatch.setenv("TODDLERBOX_DATA_ROOT", "/var/lib/toddlerbox")
    assert load_config()["data_root"] == "/var/lib/toddlerbox"
    config_file.write_text("{broken")
    assert load_config()["data_root"] == "/var/lib/toddlerbox"


def test_previously_accepted_values_keep_their_meaning(config_file):
    config_file.write_text(
        "music: {volume: 4, autoplay: false, latency_ms: -125.5}\n"
        "photos: {thumb_cache_limit: 3, show_arrows: 'yes'}\n"
        "paint: {autosave_seconds: '30'}\n"
        "typing: {autosave_seconds: 12.5}\n"
        "launcher:\n  photos_prewarm_batch: true\n  apps:\n"
        "    - {name: 7, icon_path: x.png, command: python -m toddlerbox.paint}\n"
        "    - {name: Inert}\n")
    config = load_config()
    assert config["music"] == {"volume": 4, "autoplay": False, "latency_ms": -125.5}
    assert config["photos"] == {"thumb_cache_limit": 3, "show_arrows": "yes"}
    assert config["paint"]["autosave_seconds"] == "30" and config["typing"]["autosave_seconds"] == 12.5
    assert [app.name for app in _load_apps(config)] == ["7", "Inert"]
    assert not config_errors()


def test_huge_numbers_never_break_loading_or_checking(config_file, tmp_path):
    config_file.write_text("music: {volume: " + "9" * 400 + "}\npaint: {autosave_seconds: " + "9" * 400 + "}\n")
    config = load_config()
    assert str(config["music"]["volume"]).startswith("999")
    assert check(config_file) == []


def test_mutating_a_loaded_config_does_not_change_defaults(config_file):
    config_file.write_text("")
    load_config()["paint"]["palette"].clear()
    assert load_config()["paint"]["palette"] == DEFAULT_CONFIG["paint"]["palette"]


def test_parent_check_command_reports_problems_and_exit_status(tmp_path, capsys):
    good, bad = tmp_path / "good.yaml", tmp_path / "bad.yaml"
    good.write_text("data_root: /var/lib/toddlerbox\n")
    bad.write_text("launcher:\n\tapps: []\n")
    assert config_module.main(["--check", str(good)]) == 0
    assert "Config OK" in capsys.readouterr().out
    assert config_module.main(["--check", str(bad)]) == 1
    assert "unreadable" in capsys.readouterr().out
    assert check(tmp_path / "absent.yaml") == [f"{tmp_path / 'absent.yaml'}: missing"]


@pytest.fixture
def display(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    screen = pygame.display.set_mode((320, 240))
    yield screen
    pygame.quit()


@pytest.mark.parametrize("data", [b"", b"\x89PNG\r\n\x1a\n" + b"\0" * 20, None])
def test_damaged_or_odd_icon_paths_give_the_placeholder(display, tmp_path, data):
    icon = tmp_path / "icon.png"
    if data is None:
        icon.mkdir()
    else:
        icon.write_bytes(data)
    assert load_image(str(icon)) is None


def test_launcher_resets_clip_and_key_repeat_after_an_activity(display):
    display.set_clip(pygame.Rect(10, 10, 20, 20))
    pygame.key.set_repeat(400, 30)
    _reset_shared_display_state(display)
    assert display.get_clip() == display.get_rect()
    assert pygame.key.get_repeat() == (0, 0)
