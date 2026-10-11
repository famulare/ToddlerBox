import importlib.util
from pathlib import Path
import signal
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('volume_controller', Path(__file__).parents[1]/'system/controller.py')
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


@pytest.fixture
def volume(monkeypatch):
    calls, killed = [], []
    process = SimpleNamespace(pid=4242, result=None)
    process.poll = lambda: process.result
    monkeypatch.setattr(controller.subprocess, 'Popen', lambda args, **kw: calls.append((args, kw)) or process)
    monkeypatch.setattr(controller.os, 'killpg', lambda pid, sig: killed.append((pid, sig)))
    return controller.VolumeKeys(1001), calls, killed, process


@pytest.mark.parametrize('code,action', [(113,'mute'),(114,'down'),(115,'up')])
def test_media_key_runs_fixed_command_as_child_without_waiting(volume, code, action, monkeypatch):
    keys,calls,_,_ = volume
    monkeypatch.setenv('NOTIFY_SOCKET','@controller')
    keys.event(code,1,0)
    keys.tick(0,child_mode=True)
    argv,options=calls[0]
    assert argv == ['/usr/sbin/runuser','-u','toddlerbox','--','/usr/bin/env',
                    'XDG_RUNTIME_DIR=/run/user/1001','/usr/local/libexec/toddlerbox-volume',action]
    assert options['start_new_session'] and 'NOTIFY_SOCKET' not in options['env']


def test_parent_mode_never_spawns_volume_command(volume):
    keys,calls,_,_=volume
    keys.event(115,1,0)
    keys.tick(0,child_mode=False)
    assert not calls and not keys.pending


def test_stalled_command_is_killed_without_blocking_or_starting_more(volume):
    keys,calls,killed,process=volume
    keys.event(115,1,0);keys.event(114,1,.1)
    keys.tick(0,child_mode=True)
    keys.tick(1.99,child_mode=True)
    assert not killed and len(calls)==1
    keys.tick(2,child_mode=True)
    assert killed==[(4242,signal.SIGKILL)] and len(calls)==1
    process.result=-9
    keys.tick(2.1,child_mode=True)
    assert len(calls)==2 and calls[1][0][-1]=='down'


def test_parent_transition_cancels_pending_and_active_volume_work(volume):
    keys,calls,killed,_=volume
    keys.event(115,1,0);keys.tick(0,child_mode=True)
    keys.event(114,1,.1);keys.tick(.2,child_mode=False)
    assert not keys.pending and len(calls)==1 and killed==[(4242,signal.SIGKILL)]


def test_mute_never_repeats_and_volume_repeat_is_bounded(volume):
    keys,_,_,_=volume
    keys.event(113,1,0)
    for i in range(100):keys.event(113,2,i*.01)
    assert keys.pending==['mute']
    for i in range(1000):keys.event(115,2,i*.01)
    assert len(keys.pending)==8
    keys.event(115,0,20);keys.event(29,1,20)
    assert len(keys.pending)==8


def test_new_press_after_release_preserves_taps_even_without_autorepeat_delay(volume):
    keys,_,_,_=volume
    keys.event(115,1,0);keys.event(115,0,.01);keys.event(115,1,.02)
    assert keys.pending==['up','up']


@pytest.mark.parametrize('action,expected', [
    ('up',['set-mute @DEFAULT_AUDIO_SINK@ 0','set-volume --limit 1.0 @DEFAULT_AUDIO_SINK@ 5%+']),
    ('down',['set-mute @DEFAULT_AUDIO_SINK@ 0','set-volume --limit 1.0 @DEFAULT_AUDIO_SINK@ 5%-']),
    ('mute',['set-mute @DEFAULT_AUDIO_SINK@ toggle']),
])
def test_real_shell_helper_uses_expected_output_and_ceiling(tmp_path, action, expected):
    import os
    import shlex
    import subprocess
    log=tmp_path/'commands'
    fake=tmp_path/'wpctl'
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >>"$VOLUME_TEST_LOG"\n')
    fake.chmod(0o700)
    source=(Path(__file__).parents[1]/'system/bin/toddlerbox-volume').read_text()
    # Only substitute the executable boundary; execute the actual shell logic.
    source=source.replace('/usr/bin/wpctl',shlex.quote(str(fake)))
    environment=dict(os.environ,VOLUME_TEST_LOG=str(log))
    subprocess.run(['/bin/sh','-s','--',action],input=source,text=True,env=environment,check=True)
    assert log.read_text().splitlines()==expected


def test_shell_helper_refuses_unknown_actions_without_commands(tmp_path):
    import subprocess
    helper=Path(__file__).parents[1]/'system/bin/toddlerbox-volume'
    result=subprocess.run(['/bin/sh',str(helper),'up; arbitrary-command'],capture_output=True)
    assert result.returncode==2 and result.stdout==result.stderr==b''


def test_real_startup_helper_uses_only_versioned_python_module(tmp_path):
    import os
    import shlex
    import subprocess
    log = tmp_path / 'command'
    fake = tmp_path / 'python'
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >"$VOLUME_TEST_LOG"\n')
    fake.chmod(0o700)
    source = (Path(__file__).parents[1]/'system/bin/toddlerbox-volume').read_text()
    source = source.replace('/opt/toddlerbox/current/.venv/bin/python', shlex.quote(str(fake)))
    subprocess.run(['/bin/sh','-s','--','startup'], input=source, text=True,
                   env=dict(os.environ,VOLUME_TEST_LOG=str(log)),check=True)
    assert log.read_text() == '-m toddlerbox.runtime.audio\n'
