import pytest

from toddlerbox.ui.preload import preview_indices


@pytest.mark.parametrize("count,visible,limit,expected", [
    (0, [], 8, []), (20, [3, 4], 0, []),
    (20, [3, 4], 8, [3, 4, 5, 2, 6, 1, 7, 0]),
    (3, [0, 2], 8, [0, 2, 1]),
    (4, [], 8, [0, 1, 2, 3]),
    (20, [18, 19], 4, [18, 19, 17, 16]),
])
def test_preload_visible_first_then_neighbours_without_exceeding_budget(count, visible, limit, expected):
    assert preview_indices(count, visible, limit) == expected
