"""Bounded, visit-local navigation; callers store only small immutable values."""
from __future__ import annotations

from typing import Generic, TypeVar

T = TypeVar("T")


class History(Generic[T]):
    def __init__(self, capacity: int = 100):
        if capacity < 1:
            raise ValueError("History capacity must be positive")
        self.capacity = capacity
        self.entries: list[T] = []
        self.index = -1

    @property
    def can_back(self):
        return self.index > 0

    @property
    def can_forward(self):
        return self.index + 1 < len(self.entries)

    def replace(self, value: T):
        if self.index >= 0:
            self.entries[self.index] = value

    def append(self, value: T):
        del self.entries[self.index + 1:]
        self.entries.append(value)
        if len(self.entries) > self.capacity:
            del self.entries[0]
        self.index = len(self.entries) - 1

    def move(self, direction: int):
        if direction not in (-1, 1):
            raise ValueError("History moves one entry at a time")
        if not 0 <= self.index + direction < len(self.entries):
            return None
        self.index += direction
        return self.entries[self.index]
