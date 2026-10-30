from pathlib import Path
from toddlerbox.runtime.paint_timing import PaintTiming, BOUNDS_MS


def test_histograms_have_bounded_storage_and_keep_every_observation():
    now = [0.]
    probe = PaintTiming(Path('unused'), 10., clock=lambda: now[0])
    for _ in range(10000):
        probe.observe('display_flip', .02)
    metric = probe.snapshot()['metrics']['display_flip']
    assert metric['count'] == 10000
    assert len(metric['buckets']) == len(BOUNDS_MS) + 1
    assert sum(metric['buckets']) == 10000
    assert metric['max_ms'] == 20.
    now[0] = 10.
    probe.observe('display_flip', 1.)
    assert probe.snapshot()['metrics']['display_flip']['count'] == 10000
    assert probe.snapshot()['status'] == 'completed'


def test_frame_intervals_and_snapshots_are_independent():
    now = [1.]
    probe = PaintTiming(Path('unused'), 10., clock=lambda: now[0])
    probe.frame()
    now[0] += .016
    probe.frame()
    first = probe.snapshot()
    probe.observe('frame_interval', .1)
    assert first['metrics']['frame_interval']['count'] == 1
    assert sum(first['metrics']['frame_interval']['buckets']) == 1
    assert probe.snapshot()['metrics']['frame_interval']['count'] == 2


def test_missing_or_symlink_arm_file_disables_diagnostics(tmp_path, monkeypatch):
    import toddlerbox.runtime.paint_timing as module
    flag = tmp_path / 'flag'
    monkeypatch.setattr(module, 'FLAG', flag)
    assert PaintTiming.armed(tmp_path) is None
    target = tmp_path / 'target'
    target.write_text('{"expires_monotonic": 10}')
    flag.symlink_to(target)
    assert PaintTiming.armed(tmp_path) is None
