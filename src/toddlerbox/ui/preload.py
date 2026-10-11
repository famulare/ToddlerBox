"""Bounded thumbnail working sets: visible items first, then nearby items."""


def preview_indices(count: int, visible: list[int], limit: int) -> list[int]:
    indices = list(dict.fromkeys(i for i in visible if 0 <= i < count))[:limit]
    if not count or not limit:
        return []
    if not indices:
        indices = [0]
    first, last = min(indices), max(indices)
    # Visible callers normally provide a contiguous range; also handle holes
    # without skipping an item or searching indefinitely at the boundaries.
    for index in range(first, last + 1):
        if len(indices) == min(count, limit):
            return indices
        if index not in indices:
            indices.append(index)
    distance = 1
    while len(indices) < min(count, limit):
        for index in (last + distance, first - distance):
            if 0 <= index < count and index not in indices:
                indices.append(index)
                if len(indices) == min(count, limit):
                    break
        distance += 1
    return indices
