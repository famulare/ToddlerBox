from concurrent.futures import Future
from types import SimpleNamespace

import pygame
import pytest

from toddlerbox.paint.app import PaintApp, _bucket_fill
from toddlerbox.ui.common import PointerInput


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    config = tmp_path / "config.yaml"
    colors = "\n".join(f"    - [{i}, {i}, {i}]" for i in range(14))
    config.write_text(f"data_root: {tmp_path / 'data'}\npaint:\n  palette:\n{colors}\n")
    monkeypatch.setenv("KIDBOX_CONFIG", str(config))
    pygame.init()
    screen = pygame.display.set_mode((1024, 600))
    instance = PaintApp(screen=screen)
    yield instance
    if instance._recall_worker:
        instance._recall_worker.shutdown(wait=True, cancel_futures=True)
    if instance._save_worker:
        instance._save_worker.shutdown(wait=True, cancel_futures=True)
    pygame.quit()


def test_bucket_preserves_unrelated_boundary_pixel():
    image = pygame.Surface((5, 3))
    image.fill("white")
    image.set_at((0, 1), "black")
    _bucket_fill(image, (3, 1), (255, 0, 0))
    assert image.get_at((0, 1))[:3] == (0, 0, 0)
    assert image.get_at((3, 1))[:3] == (255, 0, 0)


@pytest.mark.parametrize("tool", ["round", "fountain", "eraser"])
def test_tap_marks_canvas_and_single_undo_restores_it(app, tool):
    app.current_tool = tool
    app.canvas_surface.fill("black" if tool == "eraser" else "white")
    before = pygame.image.tobytes(app.canvas_surface, "RGB")
    app._handle_pointer_down(app.canvas_rect.center)
    app._handle_pointer_up()
    assert pygame.image.tobytes(app.canvas_surface, "RGB") != before
    app._undo()
    assert pygame.image.tobytes(app.canvas_surface, "RGB") == before


def test_ignored_keys_do_not_starve_periodic_autosave(app, monkeypatch):
    now = [0.0]
    saves = []
    app.last_autosave = 0
    app.clock = SimpleNamespace(tick=lambda _fps: None)
    monkeypatch.setattr(app, "_render", lambda: None)
    monkeypatch.setattr(app, "_request_autosave", lambda: saves.append(now[0]))
    monkeypatch.setattr("toddlerbox.paint.app.time.monotonic", lambda: now[0])
    monkeypatch.setattr("toddlerbox.paint.app.health.stopping", lambda: now[0] >= 30)
    monkeypatch.setattr("toddlerbox.paint.app.health.frame_complete", lambda: None)
    def events():
        now[0] += 1
        return [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F1, mod=0)]
    monkeypatch.setattr(pygame.event, "get", events)
    app._run()
    assert saves == [10, 20, 30]


def test_unchanged_canvas_does_not_encode_again(app, monkeypatch):
    assert app._autosave_latest()
    def unexpected(*_args):
        pytest.fail("unchanged canvas should not be re-encoded")
    monkeypatch.setattr("toddlerbox.paint.app._save_surface_atomic", unexpected)
    assert app._autosave_latest()


def test_new_at_capacity_preserves_both_current_and_archived_work(app):
    app.config["paint"]["max_archives"] = 0  # Coerced to one safe archive.
    app._handle_pointer_down(app.canvas_rect.center)
    assert app._archive_current()
    archived = app._recall_archives()[0]
    original_archive = archived.read_bytes()
    app._handle_pointer_move((app.canvas_rect.centerx + 20, app.canvas_rect.centery))
    before = pygame.image.tobytes(app.canvas_surface, "RGB")
    app._handle_pointer_down(app.action_buttons["new"].rect.center)
    assert pygame.image.tobytes(app.canvas_surface, "RGB") == before
    assert archived.read_bytes() == original_archive


def test_quarantined_save_is_not_recalled_or_counted_as_archive(app):
    quarantined = app.paint_dir / "corrupt-example.png"
    quarantined.write_bytes(b"damaged")
    app.config["paint"]["max_archives"] = 1
    assert app._archive_current()
    assert quarantined.read_bytes() == b"damaged"
    assert quarantined not in app._recall_archives()


def test_palette_stays_inside_allocated_area_at_small_screen(app):
    for swatch in app.palette_buttons:
        assert app.controls_rect.contains(swatch.rect)
        assert all(not swatch.rect.colliderect(action.rect)
                   for action in app.action_buttons.values())


def test_raw_finger_motion_draws_and_second_finger_does_not_steal_stroke(app, monkeypatch):
    x, y = app.canvas_rect.center
    def event(kind, identity=1, offset=0):
        return pygame.event.Event(kind, finger_id=identity, touch_id=1,
                                  x=(x + offset) / app.screen_rect.width,
                                  y=y / app.screen_rect.height)
    events = [event(pygame.FINGERDOWN), event(pygame.FINGERUP, 2),
              event(pygame.FINGERMOTION, offset=40), event(pygame.FINGERUP),
              pygame.event.Event(pygame.QUIT)]
    monkeypatch.setattr(pygame.event, "get", lambda: events)
    app._run()
    local = (x + 35 - app.canvas_rect.left, y - app.canvas_rect.top)
    assert app.canvas_surface.get_at(local)[:3] != (255, 255, 255)
    assert len(app.undo_stack) == 1


def test_focus_reset_discards_already_fetched_pointer_events(app, monkeypatch):
    batches = iter([
        [pygame.event.Event(pygame.WINDOWFOCUSLOST),
         pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=app.canvas_rect.center)],
        [pygame.event.Event(pygame.QUIT)],
    ])
    monkeypatch.setattr(pygame.event, "get", lambda: next(batches))
    app._run()
    assert app.undo_stack == []


def test_recall_open_schedules_only_visible_thumbnail_without_blocking(app):
    assert app._archive_current()
    calls = []
    pending = Future()
    app._recall_worker = SimpleNamespace(submit=lambda *args: calls.append(args) or pending,
                                        shutdown=lambda **kwargs: None)
    app._open_recall()
    app._pump_recall_thumbnail()
    app._pump_recall_thumbnail()
    assert len(calls) == 1
    assert app.recall_items[1].thumb is None


def test_low_disk_reserve_refuses_archive_without_clearing_canvas(app, monkeypatch):
    app._handle_pointer_down(app.canvas_rect.center)
    before = pygame.image.tobytes(app.canvas_surface, "RGB")
    monkeypatch.setattr("toddlerbox.paint.app.has_archive_reserve", lambda *_args: False)
    app._handle_pointer_down(app.action_buttons["new"].rect.center)
    assert pygame.image.tobytes(app.canvas_surface, "RGB") == before
    assert app._recall_archives() == []


def test_periodic_save_is_bounded_and_does_not_mark_newer_edits_saved(app):
    pending = Future()
    jobs = []
    app._save_worker = SimpleNamespace(submit=lambda *args: jobs.append(args) or pending,
                                      shutdown=lambda **kwargs: None)
    app._handle_pointer_down(app.canvas_rect.center)
    snapshot_revision = app._canvas_revision
    app._request_autosave()
    app._handle_pointer_move((app.canvas_rect.centerx + 30, app.canvas_rect.centery))
    app._request_autosave()
    assert len(jobs) == 1  # A slow disk cannot accumulate a queue of snapshots.
    assert app._saved_revision != app._canvas_revision
    pending.set_result(None)
    app._finish_pending_save()
    assert app._saved_revision == snapshot_revision
    assert app._saved_revision != app._canvas_revision


def test_home_flushes_newest_canvas_after_older_background_save(app):
    app._handle_pointer_down(app.canvas_rect.center)
    app._request_autosave()
    app._handle_pointer_move((app.canvas_rect.centerx + 40, app.canvas_rect.centery))
    assert app._handle_pointer_down(app.action_buttons["home"].rect.center)
    committed = pygame.image.load(str(app.paint_dir / "latest.png"))
    assert pygame.image.tobytes(committed, "RGB") == pygame.image.tobytes(app.canvas_surface, "RGB")
    assert app._save_pending is None


def test_failed_background_save_keeps_canvas_dirty_for_retry(app):
    pending = Future()
    pending.set_exception(OSError("disk full"))
    app._save_pending = (app._canvas_revision, pending)
    app._finish_pending_save()
    assert app._saved_revision != app._canvas_revision
    assert app._autosave_latest()
