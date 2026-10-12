"""Real bounded workers and durable files; no SDL object crosses worker threads."""
import json
import threading
import time

import pygame
import pytest

from toddlerbox.paint.app import PaintApp, RecallItem
from toddlerbox.typing.app import TypingApp, RecallSession
from toddlerbox.runtime import control


@pytest.fixture(params=['paint', 'typing'])
def app(request, tmp_path, monkeypatch):
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
    monkeypatch.setenv('SDL_AUDIODRIVER', 'dummy')
    config = tmp_path / 'config.yaml'
    config.write_text(f'data_root: {tmp_path / "data"}\n')
    monkeypatch.setenv('KIDBOX_CONFIG', str(config))
    pygame.init()
    screen = pygame.display.set_mode((1366, 768))
    value = PaintApp(screen=screen) if request.param == 'paint' else TypingApp(screen=screen)
    if isinstance(value, PaintApp):
        value.canvas_surface.fill((25, 90, 180))
        value._mark_canvas_changed()
    else:
        for char in 'café sun':
            value._insert_char(char)
    yield value
    if value._save_worker:
        value._save_worker.shutdown(wait=True)
    if isinstance(value, PaintApp) and value._recall_worker:
        value._recall_worker.shutdown(wait=True)
    pygame.quit()


def current(app):
    if isinstance(app, PaintApp):
        return pygame.image.tobytes(app.canvas_surface, 'RGB')
    return json.dumps(app._record(), ensure_ascii=False).encode('utf-8')


def drain(app, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app._service_transition()
        if app._transition_request is None and app._transition_pending is None and app._save_pending is None:
            return
        time.sleep(.001)
    pytest.fail('bounded save did not complete')


def assert_durable(app):
    if isinstance(app, PaintApp):
        saved = pygame.image.load(str(app.paint_dir / 'latest.png'))
        assert pygame.image.tobytes(saved, 'RGB') == current(app)
    else:
        assert app.current_path.read_bytes() == current(app)


def archive_files(app):
    return app._recall_archives() if isinstance(app, PaintApp) else list((app.typing_dir / 'archive').glob('*.json'))


def test_archive_before_clear_and_repeated_new_is_bounded_while_frames_continue(app, monkeypatch):
    module = 'toddlerbox.paint.app' if isinstance(app, PaintApp) else 'toddlerbox.typing.app'
    name = '_archive_pixels' if isinstance(app, PaintApp) else '_archive_payload'
    import importlib
    original = getattr(importlib.import_module(module), name)
    entered, release = threading.Event(), threading.Event()
    calls = []
    def blocked(*args):
        calls.append(threading.get_ident())
        entered.set()
        assert release.wait(3)
        return original(*args)
    monkeypatch.setattr(module + '.' + name, blocked)
    before = current(app)
    app._render()
    before_frame = pygame.image.tobytes(app.screen, 'RGBA')
    app._begin_transition('new')
    app._service_transition()
    assert entered.wait(1)
    try:
        for _ in range(10):
            app._begin_transition('new')
            app._service_transition()
            app._render()
            assert current(app) == before
            assert pygame.image.tobytes(app.screen, 'RGBA') == before_frame
        assert len(calls) == 1 and calls[0] != threading.get_ident()
        assert not archive_files(app)
    finally:
        release.set()
    drain(app)
    assert current(app) != before
    assert len(archive_files(app)) == 1
    assert_durable(app)
    if isinstance(app, PaintApp):
        assert pygame.image.tobytes(pygame.image.load(str(archive_files(app)[0])), 'RGB') == before
    else:
        assert json.loads(archive_files(app)[0].read_bytes())['rich_lines'] == json.loads(before)['rich_lines']


@pytest.mark.parametrize('failure', [OSError(28, 'disk full'), OSError('directory fsync uncertain')])
def test_failed_archive_keeps_exact_current_and_old_durable_files(app, monkeypatch, failure):
    if isinstance(app, PaintApp):
        assert app._autosave_latest()
        path = app.paint_dir / 'latest.png'
        target = 'toddlerbox.paint.app._save_pixels_atomic'
    else:
        assert app._save_current()
        path = app.current_path
        target = 'toddlerbox.typing.app.write_bytes'
    old_disk, before = path.read_bytes(), current(app)
    def failed(*args):
        raise failure
    monkeypatch.setattr(target, failed)
    app._begin_transition('new')
    drain(app)
    assert current(app) == before and path.read_bytes() == old_disk
    assert not archive_files(app)


def test_periodic_snapshot_does_not_claim_newer_edits_saved_and_final_save_orders_writes(app, monkeypatch):
    module = 'toddlerbox.paint.app' if isinstance(app, PaintApp) else 'toddlerbox.typing.app'
    name = '_save_pixels_atomic' if isinstance(app, PaintApp) else 'write_bytes'
    import importlib
    original = getattr(importlib.import_module(module), name)
    entered, release = threading.Event(), threading.Event()
    snapshots = []
    def blocked(*args):
        snapshots.append(args)
        entered.set()
        assert release.wait(3)
        return original(*args)
    monkeypatch.setattr(module + '.' + name, blocked)
    before = current(app)
    app._request_autosave()
    assert entered.wait(1)
    try:
        if isinstance(app, PaintApp):
            app.canvas_surface.fill((210, 30, 50))
            app._mark_canvas_changed()
        else:
            app._insert_char('!')
        for _ in range(10):
            app._request_autosave()
        assert len(snapshots) == 1
        assert app._save_for_control() is control.SAVE_PENDING
    finally:
        release.set()
    drain(app)
    assert current(app) != before
    assert app._saved_revision != app._canvas_revision if isinstance(app, PaintApp) else app._saved_payload != current(app)
    if isinstance(app, PaintApp):
        assert app._autosave_latest()
    else:
        assert app._save_current()
    assert_durable(app)


def test_home_during_pending_archive_waits_without_blocking_then_saves_newest(app, monkeypatch):
    module = 'toddlerbox.paint.app' if isinstance(app, PaintApp) else 'toddlerbox.typing.app'
    name = '_archive_pixels' if isinstance(app, PaintApp) else '_archive_payload'
    import importlib
    original = getattr(importlib.import_module(module), name)
    entered, release = threading.Event(), threading.Event()
    def blocked(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)
    monkeypatch.setattr(module + '.' + name, blocked)
    app._begin_transition('new')
    app._service_transition()
    assert entered.wait(1)
    app._exit_requested = True
    try:
        for _ in range(10):
            app._service_transition()
            assert app._poll_exit() is False
            app._render()
    finally:
        release.set()
    deadline = time.monotonic() + 5
    while not app._poll_exit():
        assert time.monotonic() < deadline
        app._service_transition()
        time.sleep(.001)
    assert len(archive_files(app)) == 1
    assert_durable(app)


def test_recall_archives_old_work_before_durable_promotion(app):
    before = current(app)
    if isinstance(app, PaintApp):
        source = app.paint_dir / 'selected.png'
        image = pygame.Surface((38, 31))
        for x in range(38):
            pygame.draw.line(image, (x * 6, 20, 110), (x, 0), (x, 30))
        pygame.image.save(image, str(source))
        # Same SDL conversion/resampling as the real old recall path.
        expected = pygame.transform.smoothscale(pygame.image.load(str(source)).convert_alpha(), app.canvas_rect.size)
        expected_pixels = pygame.image.tobytes(expected, 'RGB')
        app._handle_recall_selection(RecallItem(None, source), defer_saves=True)
    else:
        from toddlerbox.typing.app import Glyph
        item = RecallSession('archive', 'B', [[Glyph('B', 50, 'bold')]])
        app.recall_items = [item]
        app._apply_recall(0, defer_saves=True)
    assert current(app) == before
    drain(app)
    assert_durable(app)
    if isinstance(app, PaintApp):
        assert current(app) == expected_pixels
    else:
        assert app._current_text() == 'B'


def test_term_during_pending_archive_preserves_work_and_finishes_cleanup(app, monkeypatch):
    app._begin_transition('new')
    app._service_transition()
    # run's finally is the supervised TERM path, signal handler does no IO.
    monkeypatch.setattr(app, '_run', lambda: None)
    app.run(quit_on_exit=False)
    assert len(archive_files(app)) == 1
    assert_durable(app)


def test_new_repeat_and_home_go_through_real_touch_event_batches(app, monkeypatch):
    import importlib
    from types import SimpleNamespace
    module = 'toddlerbox.paint.app' if isinstance(app, PaintApp) else 'toddlerbox.typing.app'
    name = '_archive_pixels' if isinstance(app, PaintApp) else '_archive_payload'
    original = getattr(importlib.import_module(module), name)
    entered, release = threading.Event(), threading.Event()
    calls = []
    def blocked(*args):
        calls.append(True)
        entered.set()
        assert release.wait(3)
        return original(*args)
    monkeypatch.setattr(module + '.' + name, blocked)
    monkeypatch.setattr(module + '.health.stopping', lambda: False)
    monkeypatch.setattr(module + '.health.frame_complete', lambda: None)
    pygame.event.clear()
    before = current(app)
    new = app.action_buttons['new'].rect.center if isinstance(app, PaintApp) else app.new_button.rect.center
    home = app.action_buttons['home'].rect.center if isinstance(app, PaintApp) else app.home_button.rect.center
    def touch(kind, pos, finger):
        return pygame.event.Event(kind, touch_id=1, finger_id=finger,
                                  x=pos[0] / app.screen_rect.width, y=pos[1] / app.screen_rect.height)
    batches = iter([
        [touch(pygame.FINGERDOWN, new, 1)],
        [touch(pygame.FINGERUP, new, 1), touch(pygame.FINGERDOWN, new, 2)],
        [touch(pygame.FINGERUP, new, 2), touch(pygame.FINGERDOWN, home, 3)],
        [touch(pygame.FINGERUP, home, 3)],
    ])
    monkeypatch.setattr(pygame.event, 'get', lambda: next(batches, []))
    frames = []
    def tick(_fps):
        frames.append(current(app))
        if len(frames) < 6:
            assert current(app) == before
        if len(frames) == 6:
            release.set()
        assert len(frames) < 1000
        time.sleep(.001)
    app.clock = SimpleNamespace(tick=tick)
    try:
        app._run()
    finally:
        release.set()
    assert entered.is_set() and len(calls) == 1 and len(frames) >= 6
    assert len(archive_files(app)) == 1
    assert_durable(app)


def test_real_term_flag_during_blocked_archive_and_queued_autosave(app, monkeypatch):
    import importlib
    import signal
    from types import SimpleNamespace
    from toddlerbox.runtime import health
    module = 'toddlerbox.paint.app' if isinstance(app, PaintApp) else 'toddlerbox.typing.app'
    name = '_archive_pixels' if isinstance(app, PaintApp) else '_archive_payload'
    original = getattr(importlib.import_module(module), name)
    entered, release = threading.Event(), threading.Event()
    def blocked(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)
    monkeypatch.setattr(module + '.' + name, blocked)
    monkeypatch.setattr(health, '_stopping', False)
    monkeypatch.setattr(health, 'frame_complete', lambda: None)
    monkeypatch.setattr(pygame.event, 'get', lambda: [])
    previous_handler = signal.getsignal(signal.SIGTERM)
    health.install_shutdown_handlers()
    app._begin_transition('new')
    app._service_transition()
    assert entered.wait(1)
    # Authenticated/manual save and archive share one executor. This current
    # snapshot is queued behind the archive; it cannot overtake the final save.
    app._request_autosave()
    assert app._save_pending is not None
    ticks = []
    timer = None
    def tick(_fps):
        nonlocal timer
        ticks.append(True)
        if len(ticks) == 3:
            signal.raise_signal(signal.SIGTERM)
            timer = threading.Timer(.02, release.set)
            timer.start()
    app.clock = SimpleNamespace(tick=tick)
    try:
        app.run(quit_on_exit=False)
        assert health.stopping() and len(ticks) == 3
    finally:
        release.set()
        if timer is not None:
            timer.join()
        signal.signal(signal.SIGTERM, previous_handler)
    assert len(archive_files(app)) == 1
    assert_durable(app)


def test_failed_explicit_save_can_retry_after_storage_recovers(app, monkeypatch):
    module = 'toddlerbox.paint.app' if isinstance(app, PaintApp) else 'toddlerbox.typing.app'
    name = '_save_pixels_atomic' if isinstance(app, PaintApp) else 'write_bytes'
    import importlib
    original = getattr(importlib.import_module(module), name)
    def failed(*args):
        raise OSError(28, 'disk full')
    monkeypatch.setattr(module + '.' + name, failed)
    assert app._save_for_control() is control.SAVE_PENDING
    app._save_pending[1].exception(timeout=2)
    assert app._save_for_control() is False
    monkeypatch.setattr(module + '.' + name, original)
    assert app._save_for_control() is control.SAVE_PENDING
    drain(app)
    assert app._save_for_control() is True
    assert_durable(app)
