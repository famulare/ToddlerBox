from toddlerbox.launcher import _EMBEDDED_RUNNERS, _module_name_for_command, _resolve_command, _restore_launcher_window


def test_resolve_command_uses_active_interpreter_for_python(monkeypatch):
    monkeypatch.setattr("toddlerbox.launcher.sys.executable", "/opt/toddlerbox/.venv/bin/python3.11")
    command = _resolve_command(["python", "-m", "toddlerbox.paint"])
    assert command == ["/opt/toddlerbox/.venv/bin/python3.11", "-m", "toddlerbox.paint"]


def test_resolve_command_falls_back_to_python3_when_executable_missing(monkeypatch):
    monkeypatch.setattr("toddlerbox.launcher.sys.executable", "")
    monkeypatch.setattr("toddlerbox.launcher.shutil.which", lambda name: "/usr/bin/python3" if name == "python3" else None)
    command = _resolve_command(["python3", "-m", "toddlerbox.photos"])
    assert command == ["/usr/bin/python3", "-m", "toddlerbox.photos"]


def test_resolve_command_keeps_non_python_commands():
    command = _resolve_command(["/usr/bin/echo", "hello"])
    assert command == ["/usr/bin/echo", "hello"]


def test_restore_launcher_window_reuses_existing_surface(monkeypatch):
    class FakeSurface:
        def get_rect(self):
            return "fake-rect"

    existing = FakeSurface()
    monkeypatch.setattr("toddlerbox.launcher.pygame.display.get_surface", lambda: existing)

    surface, rect = _restore_launcher_window()
    assert surface is existing
    assert rect == "fake-rect"


def test_restore_launcher_window_recreates_when_surface_missing(monkeypatch):
    monkeypatch.setattr("toddlerbox.launcher.pygame.display.get_surface", lambda: None)
    monkeypatch.setattr("toddlerbox.launcher.create_fullscreen_window", lambda: ("new-surface", "new-rect"))

    surface, rect = _restore_launcher_window()
    assert surface == "new-surface"
    assert rect == "new-rect"


def test_module_name_for_command_matches_builtin_module():
    module_name = _module_name_for_command(["python", "-m", "toddlerbox.paint"])
    assert module_name == "toddlerbox.paint"
    assert module_name in _EMBEDDED_RUNNERS


def test_module_name_for_command_ignores_non_module_command():
    module_name = _module_name_for_command(["/usr/bin/echo", "hello"])
    assert module_name is None


def test_supervised_launcher_refuses_uninstrumented_subprocess(monkeypatch):
    from unittest.mock import Mock
    from toddlerbox.launcher import LauncherApp, _launch_app
    monkeypatch.setenv("TODDLERBOX_HEALTH_SOCKET","/run/test-health")
    spawn = Mock()
    monkeypatch.setattr("toddlerbox.launcher.subprocess.Popen",spawn)
    result = _launch_app(LauncherApp("External","",["external"]),None,None,None,Mock())
    assert result == (False,None)
    spawn.assert_not_called()


def test_launcher_exception_cleans_resources_before_shutdown_ack(tmp_path,monkeypatch):
    from unittest.mock import Mock, call
    import pygame
    import pytest
    import toddlerbox.launcher as launcher
    monkeypatch.setenv("SDL_VIDEODRIVER","dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER","dummy")
    pygame.init()
    screen = pygame.display.set_mode((1024,600))
    config = {"data_root":str(tmp_path),"launcher":{"apps":[]}}
    monkeypatch.setattr(launcher,"load_config",lambda:config)
    monkeypatch.setattr(launcher,"create_fullscreen_window",lambda:(screen,screen.get_rect()))
    calls = Mock()
    photos = Mock()
    calls.attach_mock(photos.close,"close")
    quit_mock = Mock(wraps=pygame.quit)
    calls.attach_mock(quit_mock,"quit")
    ack = Mock()
    calls.attach_mock(ack,"ack")
    monkeypatch.setattr(launcher,"PhotosApp",lambda **kwargs:photos)
    monkeypatch.setattr(launcher,"_draw_launcher_frame",Mock(side_effect=RuntimeError("render failed")))
    monkeypatch.setattr(pygame,"quit",quit_mock)
    monkeypatch.setattr(launcher.health,"shutdown_complete",ack)
    with pytest.raises(RuntimeError):
        launcher.main()
    assert calls.mock_calls == [call.close(),call.quit(),call.ack()]
