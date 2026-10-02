import pygame

from toddlerbox.ui.common import PointerInput, pointer_event_pos


def finger(kind, identity=1, **extra):
    return pygame.event.Event(kind, finger_id=identity, touch_id=7, x=.5, y=.25, **extra)


def test_raw_touch_owns_gesture_and_emulated_mouse_never_duplicates_it():
    pointer = PointerInput()
    # SDL ordering must not decide whether a physical touch counts twice.
    emulated = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(50, 25), button=1, touch=True)
    assert not pointer.accept(emulated)
    assert pointer.accept(finger(pygame.FINGERDOWN))
    assert not pointer.accept(emulated)
    assert pointer.accept(finger(pygame.FINGERMOTION))
    assert pointer.accept(finger(pygame.FINGERUP))
    assert not pointer.accept(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, touch=True))


def test_secondary_finger_cannot_move_or_release_primary_gesture():
    pointer = PointerInput()
    assert pointer.accept(finger(pygame.FINGERDOWN))
    for kind in (pygame.FINGERDOWN, pygame.FINGERMOTION, pygame.FINGERUP):
        assert not pointer.accept(finger(kind, identity=2))
    assert pointer.accept(finger(pygame.FINGERMOTION))
    assert pointer.accept(finger(pygame.FINGERUP))


def test_reset_rejects_stale_motion_and_release_but_allows_next_mouse_gesture():
    pointer = PointerInput()
    assert pointer.accept(finger(pygame.FINGERDOWN))
    pointer.reset()
    assert not pointer.accept(finger(pygame.FINGERMOTION))
    assert not pointer.accept(finger(pygame.FINGERUP))
    assert pointer.accept(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1))
    assert pointer.accept(pygame.event.Event(pygame.MOUSEMOTION, pos=(20, 30)))
    assert pointer.accept(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1))
    assert pointer.accept(pygame.event.Event(pygame.MOUSEWHEEL, y=1))


def test_finger_motion_uses_same_coordinates_as_down_and_up():
    rect = pygame.Rect(0, 0, 1366, 768)
    assert {pointer_event_pos(finger(kind), rect) for kind in
            (pygame.FINGERDOWN, pygame.FINGERMOTION, pygame.FINGERUP)} == {(683, 192)}
