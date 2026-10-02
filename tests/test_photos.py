from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace

import pygame

from toddlerbox.photos.app import PhotosApp
from toddlerbox.photos.app import _is_image, _list_photos, _load_exif_cache, _parse_exif_datetime, _thumb_name


def test_thumb_name():
    path = Path("/data/photos/library/Summer.jpg")
    assert _thumb_name(path) == "Summer_jpg.png"


def test_is_image():
    assert _is_image(Path("photo.PNG"))
    assert not _is_image(Path("notes.txt"))


def test_parse_exif_datetime():
    assert _parse_exif_datetime("2024:10:05 11:22:33") == datetime(2024, 10, 5, 11, 22, 33)
    assert _parse_exif_datetime("2024-10-05 11:22:33") is None
    assert _parse_exif_datetime(None) is None


def test_list_photos_uses_cached_taken_date(tmp_path):
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"img")
    stat = path.stat()
    taken_ts = datetime(2020, 1, 2, 3, 4, 5).timestamp()
    cache = {"photo.jpg": taken_ts}

    paths, dirty = _list_photos(tmp_path, cache)
    assert [p.name for p in paths] == ["photo.jpg"]
    assert not dirty
    assert cache["photo.jpg"] == taken_ts


def test_list_photos_orders_newest_first_by_taken_date_then_mtime(tmp_path):
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    c = tmp_path / "c.jpg"
    txt = tmp_path / "notes.txt"
    for path in (a, b, c, txt):
        path.write_bytes(b"x")

    # Newest mtime first among non-EXIF images.
    c.touch()
    a.touch()
    b.touch()

    cache = {
        "a.jpg": datetime(2020, 1, 1, 8, 0, 0).timestamp(),
        "b.jpg": datetime(2021, 1, 1, 8, 0, 0).timestamp(),
    }
    paths, dirty = _list_photos(tmp_path, cache)
    assert [path.name for path in paths] == ["b.jpg", "a.jpg", "c.jpg"]
    assert dirty


def test_list_photos_populates_missing_cache_from_exif(monkeypatch, tmp_path):
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"x")
    taken = datetime(2022, 1, 1, 1, 2, 3)
    monkeypatch.setattr("toddlerbox.photos.app._photo_taken_at", lambda _path: taken)
    cache = {}

    _paths, dirty = _list_photos(tmp_path, cache)

    assert dirty
    assert cache["photo.jpg"] == taken.timestamp()


def test_load_exif_cache_replaces_incompatible_format(tmp_path):
    cache_path = tmp_path / "exif_cache.json"
    cache_path.write_text(json.dumps({"photo.jpg": {"taken": 123.0}}), encoding="utf-8")

    loaded = _load_exif_cache(cache_path)

    assert loaded == {}
    rewritten = json.loads(cache_path.read_text(encoding="utf-8"))
    assert rewritten == {}


def _make_photos_state_app() -> PhotosApp:
    app = PhotosApp.__new__(PhotosApp)
    app.pointer_down = False
    app.pointer_input = photos_module.PointerInput()
    app.drag_start = None
    app.drag_delta = (0, 0)
    app.strip_drag_last_y = None
    app.strip_pressed_index = None
    app.strip_drag_distance = 0
    app.logger = SimpleNamespace(info=lambda *_args, **_kwargs: None)
    return app


def test_should_reset_for_key_ignores_escape():
    app = _make_photos_state_app()
    event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0)
    assert app._should_reset_for_key(event) is False


def test_should_reset_for_key_matches_function_shortcut():
    app = _make_photos_state_app()
    event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F11, mod=0)
    assert app._should_reset_for_key(event) is True


def test_should_reset_for_key_matches_modified_chord():
    app = _make_photos_state_app()
    event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=pygame.KMOD_CTRL)
    assert app._should_reset_for_key(event) is True


def test_handle_resume_resets_pointer_state_and_clears_motion(monkeypatch):
    app = _make_photos_state_app()
    app.pointer_down = True
    app.pointer_input.owner = ("finger", 1, 2)
    app.drag_start = (100, 200)
    app.drag_delta = (50, 4)
    app.strip_drag_last_y = 75
    app.strip_pressed_index = 3
    app.strip_drag_distance = 22

    cleared: list[int] = []

    monkeypatch.setattr(pygame.event, "clear", lambda events: cleared.extend(events))

    app._handle_resume("test")

    assert app.pointer_down is False
    assert app.pointer_input.owner is None
    assert app.drag_start is None
    assert app.drag_delta == (0, 0)
    assert app.strip_drag_last_y is None
    assert app.strip_pressed_index is None
    assert app.strip_drag_distance == 0
    assert pygame.MOUSEMOTION in cleared
    assert pygame.MOUSEBUTTONDOWN in cleared
    assert pygame.MOUSEBUTTONUP in cleared
    assert pygame.MOUSEWHEEL in cleared


import threading

import pytest
from PIL import Image

from toddlerbox.photos import app as photos_module


@pytest.fixture
def photo_app_factory(monkeypatch, tmp_path):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    pygame.init()
    screen = pygame.display.set_mode((640, 480))
    monkeypatch.setattr(photos_module, "load_config", lambda: {"data_root": str(tmp_path)})
    apps = []

    def make():
        app = PhotosApp(screen=screen)
        apps.append(app)
        return app

    yield make
    for app in apps:
        app.close()
        if app._future is not None:
            app._future.result(timeout=5)
    pygame.quit()


def _finish_preparation(app, *, indices=None):
    for _ in range(100):
        if app._future is not None:
            app._future.result(timeout=5)
        app._service_preparation(indices)
        if app._future is None:
            return
    raise AssertionError("photo preparation did not settle")


@pytest.mark.parametrize("orientation, expected_size", [(6, (20, 40)), (8, (20, 40)), (3, (40, 20))])
def test_main_and_thumbnail_apply_exif_orientation(tmp_path, photo_app_factory, orientation, expected_size):
    # Distinct left/right halves also check rotation direction, beyond dimensions.
    source = Image.new("RGB", (40, 20), "red")
    source.paste("blue", (20, 0, 40, 20))
    exif = Image.Exif()
    exif[274] = orientation
    path = tmp_path / "phone.jpg"
    source.save(path, exif=exif, quality=100, subsampling=0)
    app = photo_app_factory()
    main = photos_module._load_photo_surface(path)
    pixels = photos_module._prepare_thumbnail(path, app.thumb_dir / "phone.png", (100, 100))
    thumb = photos_module._surface_from_pixels(pixels)
    assert main.get_size() == thumb.get_size() == expected_size
    assert pygame.image.tobytes(main, "RGBA") == pygame.image.tobytes(thumb, "RGBA")
    if orientation == 6:
        assert main.get_at((10, 5)).r > 240
        assert main.get_at((10, 35)).b > 240
    elif orientation == 8:
        assert main.get_at((10, 5)).b > 240
        assert main.get_at((10, 35)).r > 240
    else:
        assert main.get_at((5, 10)).b > 240


def test_constructor_and_prewarm_do_not_wait_for_metadata(monkeypatch, photo_app_factory):
    entered, release = threading.Event(), threading.Event()

    def blocked_scan(*_args):
        entered.set()
        assert release.wait(5)
        return []

    monkeypatch.setattr(photos_module, "_scan_library", blocked_scan)
    try:
        app = photo_app_factory()
        assert entered.wait(2)
        future = app._future
        for _ in range(50):
            app._load_next_thumbnail()
        assert app._future is future  # No growing work queue while decoding stalls.
        assert app.items == []
        assert not future.done()
    finally:
        release.set()


def test_relaunch_refreshes_added_removed_and_replaced_photos(photo_app_factory, tmp_path):
    app = photo_app_factory()
    _finish_preparation(app)
    assert app.items == []
    image_path = app.library_dir / "new.png"
    Image.new("RGB", (40, 20), "red").save(image_path)
    app.relaunch(app.screen, app.screen_rect, app.clock)
    _finish_preparation(app)
    assert [item.path.name for item in app.items] == ["new.png"]
    assert app.current_image.get_at((0, 0)).r == 255
    Image.new("RGB", (20, 40), "blue").save(image_path)
    app.relaunch(app.screen, app.screen_rect, app.clock)
    _finish_preparation(app)
    assert app.current_image.get_at((0, 0)).b == 255
    assert app.items[0].thumb.get_size() == (20, 40)
    image_path.unlink()
    app.relaunch(app.screen, app.screen_rect, app.clock)
    _finish_preparation(app)
    assert app.items == []
    assert app.current_image is None
    assert not list(app.thumb_dir.glob("*.png"))


def test_thumbnail_memory_is_bounded_and_evicted_items_reload(photo_app_factory):
    app = photo_app_factory()
    for i in range(12):
        Image.new("RGB", (20, 20), (i * 10, 0, 0)).save(app.library_dir / f"{i}.png")
    app.thumb_cache_limit = 8
    app.relaunch(app.screen, app.screen_rect, app.clock)
    for idx in range(12):
        _finish_preparation(app, indices=[idx])
        assert app.items[idx].thumb is not None
        assert sum(item.thumb is not None for item in app.items) <= 8
    assert app.items[0].thumb is None
    _finish_preparation(app, indices=[0])
    assert app.items[0].thumb is not None
    assert sum(item.thumb is not None for item in app.items) == 8


def test_slow_old_decode_cannot_replace_new_selection(monkeypatch, photo_app_factory):
    entered, release = threading.Event(), threading.Event()
    decode = photos_module._decode_photo
    main_thread = threading.get_ident()
    frombytes = pygame.image.frombytes

    def check_main_thread(*args, **kwargs):
        assert threading.get_ident() == main_thread
        return frombytes(*args, **kwargs)

    monkeypatch.setattr(pygame.image, "frombytes", check_main_thread)
    app = photo_app_factory()
    for name, color in (("old.png", "red"), ("new.png", "blue")):
        Image.new("RGB", (20, 20), color).save(app.library_dir / name)
    app.relaunch(app.screen, app.screen_rect, app.clock)
    while not app.items:
        app._future.result(timeout=5)
        # Hold off main decoding until the controlled worker is installed.
        if app._job_kind == "scan" and app._job_key == (app._generation,):
            break
        app._service_preparation(thumbnails=False)

    def blocked_decode(path, *args, **kwargs):
        if path.name == "new.png":
            entered.set()
            assert release.wait(5)
        assert threading.get_ident() != main_thread
        return decode(path, *args, **kwargs)

    monkeypatch.setattr(photos_module, "_decode_photo", blocked_decode)
    try:
        app._service_preparation(thumbnails=False)
        assert app.items[0].path.name == "new.png"
        assert entered.wait(2)
        pending = app._future
        app._change_index(1)
        assert app._future is pending
        assert app.current_image is None
        release.set()
        _finish_preparation(app)
        assert app.items[app.current_index].path.name == "old.png"
        assert app.current_image.get_at((0, 0)).r == 255
    finally:
        release.set()


def test_swipe_ignores_secondary_fingers_and_emulated_mouse(monkeypatch, photo_app_factory):
    app = photo_app_factory()
    _finish_preparation(app)
    app.items = [photos_module.PhotoItem(Path(f"{i}.png")) for i in range(3)]
    monkeypatch.setattr(app, "_render", lambda: None)
    monkeypatch.setattr(app, "_load_current_image", lambda: None)
    monkeypatch.setattr(app, "_service_preparation", lambda **_kwargs: None)
    monkeypatch.setattr(photos_module.health, "stopping", lambda: False)
    events = [
        pygame.event.Event(pygame.FINGERDOWN, finger_id=1, touch_id=1, x=0.7, y=0.5),
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(448, 240), touch=True),
        pygame.event.Event(pygame.FINGERDOWN, finger_id=2, touch_id=1, x=0.7, y=0.5),
        pygame.event.Event(pygame.FINGERMOTION, finger_id=2, touch_id=1, x=0.95, y=0.5),
        pygame.event.Event(pygame.FINGERUP, finger_id=2, touch_id=1, x=0.95, y=0.5),
        pygame.event.Event(pygame.FINGERMOTION, finger_id=1, touch_id=1, x=0.4, y=0.5),
        pygame.event.Event(pygame.MOUSEMOTION, pos=(610, 240), touch=True),
        pygame.event.Event(pygame.FINGERUP, finger_id=1, touch_id=1, x=0.4, y=0.5),
        pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(610, 240), touch=True),
        pygame.event.Event(pygame.QUIT),
    ]
    monkeypatch.setattr(pygame.event, "get", lambda: events)
    app.run(quit_on_exit=False)
    assert app.current_index == 1
    assert app.pointer_input.owner is None


def test_home_stops_remaining_events_in_current_batch(monkeypatch, photo_app_factory):
    app = photo_app_factory()
    _finish_preparation(app)
    monkeypatch.setattr(app, "_render", lambda: None)
    monkeypatch.setattr(app, "_service_preparation", lambda **_kwargs: None)
    monkeypatch.setattr(photos_module.health, "stopping", lambda: False)
    events = [
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=app.home_button.rect.center),
        pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=app.home_button.rect.center),
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(400, 240)),
    ]
    monkeypatch.setattr(pygame.event, "get", lambda: events)
    app.run(quit_on_exit=False)
    assert app.drag_start is None
    assert app.pointer_input.owner is None


@pytest.mark.parametrize("reset_event", [
    pygame.event.Event(pygame.WINDOWFOCUSLOST),
    pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F11, mod=0),
])
def test_input_reset_discards_remaining_fetched_batch(monkeypatch, photo_app_factory, reset_event):
    app = photo_app_factory()
    _finish_preparation(app)
    app.items = [photos_module.PhotoItem(Path(f"{i}.png")) for i in range(3)]
    monkeypatch.setattr(app, "_render", lambda: None)
    monkeypatch.setattr(app, "_load_current_image", lambda: None)
    monkeypatch.setattr(app, "_service_preparation", lambda **_kwargs: None)
    monkeypatch.setattr(photos_module.health, "stopping", lambda: False)
    batches = iter([
        [
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(448, 240)),
            reset_event,
            pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(448, 240)),
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(448, 240)),
            pygame.event.Event(pygame.MOUSEMOTION, pos=(248, 240)),
            pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(248, 240)),
        ],
        [pygame.event.Event(pygame.QUIT)],
    ])
    monkeypatch.setattr(pygame.event, "get", lambda: next(batches))
    app.run(quit_on_exit=False)
    assert app.current_index == 0
    assert app.pointer_down is False
    assert app.drag_start is None
    assert app.pointer_input.owner is None


@pytest.mark.parametrize("reset_event", [
    pygame.event.Event(pygame.WINDOWFOCUSLOST),
    pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F11, mod=0),
])
def test_input_reset_preserves_quit_in_same_batch(monkeypatch, photo_app_factory, reset_event):
    app = photo_app_factory()
    _finish_preparation(app)
    monkeypatch.setattr(app, "_render", lambda: None)
    monkeypatch.setattr(app, "_service_preparation", lambda **_kwargs: None)
    monkeypatch.setattr(photos_module.health, "stopping", lambda: False)
    batches = iter([[
        reset_event,
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(448, 240)),
        pygame.event.Event(pygame.QUIT),
    ]])
    monkeypatch.setattr(pygame.event, "get", lambda: next(batches))
    app.run(quit_on_exit=False)
    assert app.drag_start is None
    assert app.pointer_input.owner is None


def test_oversized_photo_is_rejected_before_pixel_decode(monkeypatch):
    from contextlib import nullcontext

    header = SimpleNamespace(width=8000, height=5001)
    monkeypatch.setattr(photos_module.Image, "open", lambda _path: nullcontext(header))

    def unexpected_decode(_image):
        pytest.fail("oversized image reached full-resolution decode")

    monkeypatch.setattr(photos_module.ImageOps, "exif_transpose", unexpected_decode)
    with pytest.raises(ValueError, match="40000000-pixel limit"):
        photos_module._decode_photo(Path("oversized.png"), (80, 80))
