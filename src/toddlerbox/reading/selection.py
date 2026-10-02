from __future__ import annotations

from typing import Sequence

from toddlerbox.reading.catalog import Card


def choose_next(cards: Sequence[Card], current_id: str | None, rng) -> Card | None:
    """One uniform draw, excluding current. No schedule, history or retry loop."""
    unique = {card.id: card for card in cards}
    candidates = [card for identity, card in unique.items() if identity != current_id]
    return rng.choice(candidates) if candidates else None
