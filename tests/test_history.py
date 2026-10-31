import pytest

from toddlerbox.ui.history import History


def test_branch_truncates_only_forward_and_replaces_current_state():
    h = History()
    for value in ('a', 'b', 'c'):
        h.append(value)
    assert h.move(-1) == 'b'
    h.replace('revealed b')
    assert h.move(1) == 'c'
    assert h.move(-1) == 'revealed b'
    h.append('d')
    assert h.entries == ['a', 'revealed b', 'd']
    assert not h.can_forward


def test_capacity_and_edges_are_bounded():
    h = History(2)
    assert h.move(-1) is None and h.move(1) is None
    for value in range(10):
        h.append(value)
    assert h.entries == [8, 9]
    assert h.move(-1) == 8
    assert h.move(-1) is None
    assert h.index == 0
    assert h.move(1) == 9
    assert h.move(1) is None
    with pytest.raises(ValueError):
        History(0)
    with pytest.raises(ValueError):
        h.move(2)
