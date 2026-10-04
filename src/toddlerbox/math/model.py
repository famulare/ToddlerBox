from __future__ import annotations

from dataclasses import dataclass
import math

MODES = ("numbers", "addition", "subtraction")
# Each drawing depicts one countable object. Do not use arbitrary Reading cards.
MOTIFS = ("cat", "dog", "pig", "hen", "fish", "frog", "egg", "bun", "crab", "ant")


@dataclass(frozen=True)
class Options:
    max_number: int = 100
    low_number_weight: int = 12
    mode: str = "numbers"
    volume: float = 0.35


def options_from_config(config, logger) -> Options:
    raw = config.get("math", {})
    if not isinstance(raw, dict):
        raw = {}
        logger.info("Invalid Math configuration; using defaults")
    values = {}
    for key, low, high in (("max_number", 0, 100), ("low_number_weight", 1, 100)):
        value = raw.get(key, getattr(Options(), key))
        if type(value) is not int or not low <= value <= high:
            logger.info(f"Invalid Math {key}; using default")
            value = getattr(Options(), key)
        values[key] = value
    mode = raw.get("mode", "numbers")
    if mode in ("numerals", "count"):
        mode = "numbers"  # Read-only compatibility with the first trial.
    if not isinstance(mode, str) or mode not in MODES:
        logger.info("Invalid Math mode; using default")
        mode = "numbers"
    volume = raw.get("volume", 0.35)
    if type(volume) not in (int, float) or (type(volume) is float and not math.isfinite(volume)):
        logger.info("Invalid Math volume; using default")
        volume = 0.35
    return Options(**values, mode=mode, volume=max(0.0, min(1.0, volume)))


@dataclass(frozen=True)
class Example:
    mode: str
    a: int
    b: int = 0
    motif: str = "cat"

    def __post_init__(self):
        if self.mode not in MODES or self.motif not in MOTIFS:
            raise ValueError("Unknown Math example")
        if any(type(n) is not int or not 0 <= n <= 100 for n in (self.a, self.b)):
            raise ValueError("Math numbers must be integers between zero and 100")
        if ((self.mode == "numbers" and self.b != 0)
                or (self.mode == "addition" and self.a + self.b > 100)
                or (self.mode == "subtraction" and self.b > self.a)):
            raise ValueError("Math example outside supported range")

    @property
    def result(self):
        if self.mode == "addition":
            return self.a + self.b
        if self.mode == "subtraction":
            return self.a - self.b
        return self.a

    @property
    def identity(self):
        # Changing the drawing must not disguise an immediately repeated question.
        return self.mode, self.a, self.b


def prompt_distribution(mode: str, options: Options, current: Example | None = None):
    """Finite base distribution, conditioned on excluding the current prompt.

    Each total has its integer weight, divided equally among its ordered splits.
    Excluding a prompt *after* this division preserves all remaining relative
    probabilities. No rejection loops, progression or historical scheduling.
    """
    if mode not in MODES:
        raise ValueError("Unknown Math mode")
    rows = []
    for number in range(options.max_number + 1):
        weight = options.low_number_weight if number <= 20 else 1
        splits = range(number + 1) if mode in ("addition", "subtraction") else (0,)
        for split in splits:
            if mode == "addition":
                a, b = split, number - split
            elif mode == "subtraction":
                a, b = number, split
            else:
                a, b = number, 0
            if current is not None and (mode, a, b) == current.identity:
                continue
            rows.append(((a, b), weight / len(splits)))
    return rows


def choose_next(mode, options, rng, current=None, *, motifs=MOTIFS):
    rows = prompt_distribution(mode, options, current)
    if not rows:
        return current
    a, b = rng.choices([pair for pair, _ in rows], weights=[w for _, w in rows], k=1)[0]
    return Example(mode, a, b, rng.choice(motifs))
