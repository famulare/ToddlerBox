import importlib.util
from pathlib import Path
import pytest


@pytest.mark.parametrize('scenario,expected,request_parent', [
    ('return', 'returned-to-parent', False),
    ('timeout', 'deadline', True),
    ('no-start', 'gles-start-not-observed', True),
    ('terminate', 'interrupted', False),
])
def test_observer_always_removes_override_and_bounds_child_trial(tmp_path, monkeypatch, scenario, expected, request_parent):
    spec = importlib.util.spec_from_file_location(
        'renderer_watch', Path(__file__).resolve().parents[1] / 'scripts/watch-cage-renderer-trial.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    now = [0.]
    records, requested = [], []
    flag = tmp_path / 'trial'
    monkeypatch.setattr(module, 'FLAG', flag)
    monkeypatch.setattr(module.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(module.signal, 'signal', lambda *_: None)
    monkeypatch.setattr(module.time, 'clock_gettime', lambda _: now[0])
    def sleep(seconds):
        now[0] += seconds
        if scenario == 'terminate':
            module.STOP = True
    monkeypatch.setattr(module.time, 'sleep', sleep)
    def mode():
        if now[0] < .05 or scenario == 'terminate':
            return 'parent'
        if scenario == 'return' and now[0] >= .3:
            return 'parent'
        return 'child'
    monkeypatch.setattr(module, 'mode', mode)
    monkeypatch.setattr(module, 'gles_cage_present', lambda: scenario not in {'no-start', 'terminate'} and now[0] >= .1)
    monkeypatch.setattr(module, 'record', lambda value: records.append(dict(value)))
    monkeypatch.setattr(module, 'parent', lambda: requested.append(True) or True)
    module.main()
    assert not flag.exists()
    assert records[-1]['status'] == expected
    assert records[-1]['override_removed']
    assert bool(requested) == request_parent
    assert now[0] <= 241
