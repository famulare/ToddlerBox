from toddlerbox.config import load_config


def test_load_config_overrides(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("data_root: /tmp/data\npaint:\n  autosave_seconds: 5\n", encoding="utf-8")
    monkeypatch.setenv("KIDBOX_CONFIG", str(config_path))

    config = load_config()
    assert config["data_root"] == "/tmp/data"
    assert config["paint"]["autosave_seconds"] == 5

    monkeypatch.delenv("KIDBOX_CONFIG", raising=False)


def test_recognized_five_app_profiles_gain_math_without_rewriting_file(tmp_path, monkeypatch):
    import yaml
    from toddlerbox.config import STANDARD_ORDER, _standard_profile
    for nested in (False, True):
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump({"data_root": "/kept", "launcher": {"apps": _standard_profile(nested)}}))
        original = path.read_bytes()
        monkeypatch.setenv("KIDBOX_CONFIG", str(path))
        first = load_config()
        assert [a["name"] for a in first["launcher"]["apps"]] == list(STANDARD_ORDER)
        assert first["data_root"] == "/kept"
        assert path.read_bytes() == original
        assert load_config() == first


def test_custom_launcher_order_commands_paths_and_omissions_are_preserved(tmp_path, monkeypatch):
    import yaml
    from toddlerbox.config import _standard_profile
    for apps in ([], list(reversed(_standard_profile())),
                 [{**a, "icon_path": "my-cat.png"} for a in _standard_profile()]):
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump({"launcher": {"apps": apps}}))
        monkeypatch.setenv("KIDBOX_CONFIG", str(path))
        assert load_config()["launcher"]["apps"] == apps


def test_fresh_and_already_six_app_configuration_are_idempotent(tmp_path, monkeypatch):
    import yaml
    from toddlerbox.config import DEFAULT_CONFIG, STANDARD_ORDER
    path = tmp_path / "config.yaml"
    path.write_text("{}")
    monkeypatch.setenv("KIDBOX_CONFIG", str(path))
    assert [a["name"] for a in load_config()["launcher"]["apps"]] == list(STANDARD_ORDER)
    path.write_text(yaml.safe_dump(DEFAULT_CONFIG))
    assert load_config() == DEFAULT_CONFIG
