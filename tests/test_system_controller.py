import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "controller", Path(__file__).parents[1] / "system/controller.py")
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


def test_startup_failure_exhausts_three_restarts_then_parent():
    guard = controller.Watchdog(0)
    assert guard.check(89) is None
    assert [guard.check(t) for t in (90, 180, 270, 360)] == ["restart"] * 3 + ["parent"]


def test_hung_event_loop_is_detected_and_intermittent_frames_do_not_reset_budget():
    guard = controller.Watchdog(0)
    for attempt in range(3):
        now = attempt * 100 + 1
        guard.frame(now)
        assert guard.check(now + 19) is None
        assert guard.check(now + 20) == "restart"
    guard.frame(301)
    assert guard.check(321) == "parent"


def test_parent_escape_needs_continuous_hold_on_one_keyboard():
    chord = controller.EscapeChord()
    chord.event(1, 29, 1)
    chord.event(1, 56, 1)
    chord.event(2, 102, 1)
    assert not chord.held(0)
    assert not chord.held(10)
    chord.event(1, 102, 1)
    assert not chord.held(11)
    assert not chord.held(12.9)
    assert chord.held(13)
    chord.event(1, 102, 0)
    assert not chord.held(14)


def test_unplugging_keyboard_cancels_escape():
    chord = controller.EscapeChord()
    for code in [29, 56, 102]:
        chord.event(1, code, 1)
    assert not chord.held(0)
    chord.keys.pop(1)
    assert not chord.held(3)
