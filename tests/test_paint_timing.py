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


def test_window_storage_and_tool_changes_are_bounded_and_snapshots_independent():
    import json
    now = [0.]
    probe = PaintTiming(Path('unused'), 600., clock=lambda: now[0])
    names = ['render_work', 'display_flip', 'event_batch', 'clock_tick',
             'frame_interval', 'autosave_snapshot', 'event_pump', 'sdl_touch_queue_age']
    for index in range(299):
        now[0] = index * 2.
        probe.state('eraser' if index % 2 else 'fountain')
        for name in names:
            probe.observe(name, .001)
        probe.count('events_received', 4)
    first = probe.snapshot()
    assert len(first['windows']) == 60
    assert len(first['tool_changes']) == 64
    assert first['windows'][0]['seconds'] == 478
    assert len(json.dumps(first)) < 65536
    probe.observe('event_pump', .005)
    assert first['windows'][-1]['metrics']['event_pump']['count'] == 1
    assert probe.snapshot()['windows'][-1]['metrics']['event_pump']['count'] == 2
    probe.state('private-unrecognized-value')
    assert 'private-unrecognized-value' not in json.dumps(probe.snapshot())


def test_sdl_touch_peek_keeps_event_order_and_payload_out_of_report(monkeypatch):
    import ctypes
    import pygame
    import pytest
    from toddlerbox.runtime.touch_queue_timing import TouchQueueTiming, _Event
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
    monkeypatch.setenv('SDL_AUDIODRIVER', 'dummy')
    pygame.init()
    try:
        pygame.display.set_mode((40, 40))
        pygame.event.clear()
        sample = TouchQueueTiming.available()
        if sample is None:
            pytest.skip('Native diagnostic requires the verified Linux x86-64 SDL ABI')
        sample.sdl.SDL_PushEvent.argtypes = [ctypes.POINTER(_Event)]
        sample.sdl.SDL_PushEvent.restype = ctypes.c_int
        # Synthetic native events only, in dummy SDL; no physical-device injection.
        for kind in (0x700, 0x702, 0x701):
            event = _Event()
            event.header[0] = kind
            assert sample.sdl.SDL_PushEvent(ctypes.byref(event)) == 1
        pygame.time.delay(20)
        count, ages = sample.sample()
        assert count == 3 and len(ages) == 3
        assert all(.015 <= age < 1. for age in ages)
        assert bytes(sample.events) == b'\0' * ctypes.sizeof(sample.events)
        assert [e.type for e in pygame.event.get(pump=False)] == [0x700, 0x702, 0x701]
        assert sample.sample() == (0, [])
        event = _Event()
        event.header[0] = 0x702
        for _ in range(100):
            assert sample.sdl.SDL_PushEvent(ctypes.byref(event)) == 1
        assert sample.sample()[0] == 64
        assert len(pygame.event.get(pump=False)) == 100
    finally:
        pygame.quit()


def test_touch_queue_wrap_future_and_expiry_are_not_misread_as_latency():
    from types import SimpleNamespace
    from toddlerbox.runtime.touch_queue_timing import TouchQueueTiming
    def peek(events, capacity, action, low, high):
        assert (capacity, action, low, high) == (64, 1, 0x700, 0x702)
        for i, stamp in enumerate([0xfffffffc, 6, 0]):
            events[i].header[1] = stamp
        return 3
    sampler = TouchQueueTiming(SimpleNamespace(SDL_PeepEvents=peek, SDL_GetTicks=lambda: 5))
    assert sampler.sample() == (3, [.009])
    now = [0.]
    probe = PaintTiming(Path('unused'), 1., clock=lambda: now[0])
    probe.queue_probe = sampler
    probe.sample_touch_queue()
    assert probe.snapshot()['metrics']['sdl_touch_queue_age']['count'] == 1
    now[0] = 1.
    sampler.sample = lambda: (_ for _ in ()).throw(AssertionError('expired probe sampled'))
    probe.sample_touch_queue()
    assert probe.snapshot()['metrics']['sdl_touch_queue_age']['count'] == 1


def test_unsupported_native_abi_never_loads_sdl(monkeypatch):
    from toddlerbox.runtime import touch_queue_timing as module
    monkeypatch.setattr(module.platform, 'machine', lambda: 'unsupported')
    monkeypatch.setattr(module.ctypes, 'CDLL', lambda *_args: (_ for _ in ()).throw(
        AssertionError('unsupported ABI attempted native load')))
    assert module.TouchQueueTiming.available() is None


def test_timing_export_drops_unrecognized_window_and_tool_content():
    import importlib.util
    import json
    script = Path(__file__).resolve().parents[1] / 'scripts/collect-paint-timing.py'
    spec = importlib.util.spec_from_file_location('paint_timing_export', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.sanitize({'windows': [{'seconds': 2, 'coordinates': 'PRIVATE',
        'counts': {'typed_text': 'PRIVATE', 'events_received': 2},
        'metrics': {'sdl_touch_queue_age': {'count': 1, 'sum_ms': 20, 'max_ms': 20},
                    'PRIVATE': {'count': 1, 'sum_ms': 1, 'max_ms': 1}}}],
        'tool_changes': [{'seconds': 1, 'tool': 'eraser', 'image': 'PRIVATE'},
                         {'seconds': 2, 'tool': 'PRIVATE'}]})
    assert 'PRIVATE' not in json.dumps(result)
    assert result['windows'][0]['metrics']['sdl_touch_queue_age']['max_ms'] == 20
    assert result['tool_changes'] == [{'seconds': 1, 'tool': 'eraser'}]
