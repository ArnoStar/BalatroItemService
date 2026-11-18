"""What an item is worth, in coins: its card, its upgrades, and its condition.

An item's **mint value** is what its card would be worth in perfect condition:

- its kind and rarity (``BASE``: a legendary joker is worth far more than a
  common planet),
- its edition (``EDITIONS``: foil x3 ... negative x25; a negative tarot,
  planet or spectral card, rarer still, x60),
- a playing card's enhancement and seal (``ENHANCEMENTS``, ``SEALS``),
- a joker's stake sticker, from a win of before boosters (``STAKE_BONUS`` a
  stake above White).

Its **value** is its mint value times its condition (condition.py), at least
1 coin. It is what the casino stakes an item at (fixed when it is staked),
what an upgrade aims at, and what the market shows next to a price. (``odds``,
one in how many cards of a booster an item is, stays as information: how
rare it is to find, not what it is worth.)
"""

from __future__ import annotations

from .items import CONSUMABLES, Edition, Item, Kind, Rarity

BASE: dict[Kind, dict[Rarity, int]] = {
    Kind.JOKER: {Rarity.COMMON: 150, Rarity.UNCOMMON: 400, Rarity.RARE: 1_500, Rarity.LEGENDARY: 12_000},
    Kind.TAROT: {Rarity.COMMON: 40, Rarity.UNCOMMON: 100, Rarity.RARE: 350, Rarity.LEGENDARY: 6_000},
    Kind.PLANET: {Rarity.COMMON: 40, Rarity.UNCOMMON: 100, Rarity.RARE: 350, Rarity.LEGENDARY: 6_000},
    Kind.SPECTRAL: {Rarity.COMMON: 40, Rarity.UNCOMMON: 100, Rarity.RARE: 350, Rarity.LEGENDARY: 6_000},
    Kind.CARD: {Rarity.COMMON: 30, Rarity.UNCOMMON: 100, Rarity.RARE: 400, Rarity.LEGENDARY: 1_600},
}
EDITIONS: dict[Edition, float] = {
    Edition.BASE: 1, Edition.FOIL: 3, Edition.HOLOGRAPHIC: 5, Edition.POLYCHROME: 10, Edition.NEGATIVE: 25,
}
CONSUMABLE_NEGATIVE = 60
ENHANCEMENTS: dict[str, float] = {
    "m_bonus": 1.0, "m_mult": 1.0, "m_wild": 1.1, "m_stone": 0.9, "m_glass": 1.35, "m_steel": 1.35, "m_gold": 1.25,
    "m_lucky": 1.3,
}
SEALS: dict[str, float] = {"Gold": 1.3, "Red": 1.4, "Blue": 1.15, "Purple": 1.15}
STAKE_BONUS = 0.04


def mint_value(kind: Kind, rarity: Rarity, edition: Edition, enhancement: str | None = None, seal: str | None = None,
               stake: int | None = None) -> int:
    """What the card is worth in perfect condition."""
    v = float(BASE[kind].get(rarity, BASE[kind][Rarity.COMMON]))
    v *= CONSUMABLE_NEGATIVE if kind in CONSUMABLES and edition is Edition.NEGATIVE else EDITIONS[edition]
    if enhancement:
        v *= ENHANCEMENTS.get(enhancement, 1.0)
    if seal:
        v *= SEALS.get(seal, 1.0)
    if stake and kind is Kind.JOKER:
        v *= 1 + STAKE_BONUS * (stake - 1)
    return round(v)


def worth(mint: int, condition: float) -> int:
    """An item's value: its mint value times its condition (at least 1 coin)."""
    return max(1, round(mint * condition))


def item_mint_value(item: Item) -> int:
    return mint_value(item.kind, item.rarity, item.edition, item.enhancement, item.seal, item.stake)


def item_value(item: Item) -> int:
    return worth(item_mint_value(item), item.condition)
