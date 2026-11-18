"""Boosters: what coins buy, and the only way items are made (an admin's gift aside).

A booster is one kind of card (jokers, tarots, planets, spectrals or playing
cards), one **tier** (standard, boosted, premium: the table its cards are
rolled on) and one **size**, as the game's packs:

- **normal**: 2 cards shown, 1 to choose;
- **jumbo**: 4 cards shown, 1 to choose;
- **mega**: 4 cards shown, 2 to choose.

Buying one opens a **pack**: its cards are rolled at once (and kept: coming
back to it shows the same cards), then the player chooses, and only the cards
chosen become items. A pack never shows the same card twice (another of the
same rarity is drawn).

Each card is rolled on its table: the rarity (``RARITIES``: the game's joker
rarities; other cards have theirs from items.py), the card among those of its
kind and rarity, all equally likely, then the edition (``EDITIONS``: only those
the game gives that kind of card). ``Pools.odds`` says how rare a card and
edition are on its kind's standard table (one in N cards), which is what makes
an item more valuable than another (its value in coins, in the casino too).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from .errors import InvalidPick, PackOpened
from .items import CONSUMABLES, Edition, Kind, Rarity, Template


class Tier(StrEnum):
    STANDARD = "standard"
    BOOSTED = "boosted"
    PREMIUM = "premium"


class Size(StrEnum):
    NORMAL = "normal"
    JUMBO = "jumbo"
    MEGA = "mega"


RARITIES: dict[Tier, dict[Rarity, float]] = {
    Tier.STANDARD: {Rarity.COMMON: 70, Rarity.UNCOMMON: 25, Rarity.RARE: 4.5, Rarity.LEGENDARY: 0.5},
    Tier.BOOSTED: {Rarity.COMMON: 50, Rarity.UNCOMMON: 35, Rarity.RARE: 13, Rarity.LEGENDARY: 2},
    Tier.PREMIUM: {Rarity.UNCOMMON: 40, Rarity.RARE: 50, Rarity.LEGENDARY: 10},
}

_JOKER_EDITIONS: dict[Tier, dict[Edition, float]] = {
    Tier.STANDARD: {Edition.BASE: 85, Edition.FOIL: 8, Edition.HOLOGRAPHIC: 4.5, Edition.POLYCHROME: 2,
                    Edition.NEGATIVE: 0.5},
    Tier.BOOSTED: {Edition.BASE: 70, Edition.FOIL: 14, Edition.HOLOGRAPHIC: 9, Edition.POLYCHROME: 5,
                   Edition.NEGATIVE: 2},
    Tier.PREMIUM: {Edition.FOIL: 40, Edition.HOLOGRAPHIC: 30, Edition.POLYCHROME: 20, Edition.NEGATIVE: 10},
}
# tarot, planet and spectral cards: negative really rarely, as in the game
_CONSUMABLE_EDITIONS: dict[Tier, dict[Edition, float]] = {
    Tier.STANDARD: {Edition.BASE: 99.9, Edition.NEGATIVE: 0.1},
    Tier.BOOSTED: {Edition.BASE: 99.7, Edition.NEGATIVE: 0.3},
    Tier.PREMIUM: {Edition.BASE: 99, Edition.NEGATIVE: 1},
}
# playing cards: the standard tier is the game's Standard Pack (poll_edition at twice the rate, never negative)
_CARD_EDITIONS: dict[Tier, dict[Edition, float]] = {
    Tier.STANDARD: {Edition.BASE: 92, Edition.FOIL: 4, Edition.HOLOGRAPHIC: 2.8, Edition.POLYCHROME: 1.2},
    Tier.BOOSTED: {Edition.BASE: 76, Edition.FOIL: 12, Edition.HOLOGRAPHIC: 8, Edition.POLYCHROME: 4},
    Tier.PREMIUM: {Edition.FOIL: 50, Edition.HOLOGRAPHIC: 33, Edition.POLYCHROME: 17},
}


def editions(kind: Kind, tier: Tier) -> dict[Edition, float]:
    if kind is Kind.JOKER:
        return _JOKER_EDITIONS[tier]
    if kind in CONSUMABLES:
        return _CONSUMABLE_EDITIONS[tier]
    return _CARD_EDITIONS[tier]


@dataclass(frozen=True, kw_only=True)
class DropTable:
    kind: Kind
    tier: Tier
    rarities: Mapping[Rarity, float]
    editions: Mapping[Edition, float]


TABLES: dict[tuple[Kind, Tier], DropTable] = {
    (k, t): DropTable(kind=k, tier=t, rarities=RARITIES[t], editions=editions(k, t)) for k in Kind for t in Tier}


def table(kind: Kind, tier: Tier = Tier.STANDARD) -> DropTable:
    return TABLES[(kind, tier)]


# (cards shown, cards chosen)
SIZES: dict[Size, tuple[int, int]] = {Size.NORMAL: (2, 1), Size.JUMBO: (4, 1), Size.MEGA: (4, 2)}
# coins: a normal standard booster of each kind; the tiers and sizes cost so many times more
BASE_PRICES: dict[Kind, int] = {Kind.JOKER: 100, Kind.CARD: 100, Kind.SPECTRAL: 60, Kind.TAROT: 40, Kind.PLANET: 40}
TIER_PRICES: dict[Tier, float] = {Tier.STANDARD: 1, Tier.BOOSTED: 2.5, Tier.PREMIUM: 10}
SIZE_PRICES: dict[Size, float] = {Size.NORMAL: 1, Size.JUMBO: 1.5, Size.MEGA: 2}
# the game's packs each kind looks like (its boosters' art: p_<pack>_<size>_1)
PACK_ART: dict[Kind, str] = {Kind.JOKER: "buffoon", Kind.TAROT: "arcana", Kind.PLANET: "celestial",
                             Kind.SPECTRAL: "spectral", Kind.CARD: "standard"}


@dataclass(frozen=True, kw_only=True)
class Booster:
    id: str  # <kind>_<tier>_<size>
    kind: Kind
    tier: Tier
    size: Size
    choices: int  # cards shown
    picks: int  # cards chosen
    price: int  # coins
    art: str  # the game's pack it looks like (p_buffoon_mega_1 ...)

    @property
    def table(self) -> DropTable:
        return table(self.kind, self.tier)


def _booster(kind: Kind, tier: Tier, size: Size) -> Booster:
    choices, picks = SIZES[size]
    return Booster(id=f"{kind.value}_{tier.value}_{size.value}", kind=kind, tier=tier, size=size, choices=choices,
                   picks=picks, price=round(BASE_PRICES[kind] * TIER_PRICES[tier] * SIZE_PRICES[size]),
                   art=f"p_{PACK_ART[kind]}_{size.value}_1")


BOOSTERS: dict[str, Booster] = {b.id: b for b in (_booster(k, t, s) for k in Kind for t in Tier for s in Size)}


class Random(Protocol):
    def random(self) -> float: ...


def _weighted[T](weights: Mapping[T, float], rng: Random) -> T:
    items = [(k, w) for k, w in weights.items() if w > 0]
    total = sum(w for _, w in items)
    x = rng.random() * total
    for k, w in items:
        x -= w
        if x < 0:
            return k
    return items[-1][0]


class Pools:
    """The catalog's cards by kind and rarity: what a table rolls, and how rare each card is."""

    def __init__(self, templates: Iterable[Template]) -> None:
        self.by_kind: dict[Kind, dict[Rarity, list[Template]]] = {}
        self.by_variant: dict[str, Template] = {}
        for t in templates:
            self.by_kind.setdefault(t.kind, {}).setdefault(t.rarity, []).append(t)
            self.by_variant[t.variant] = t
        for by_rarity in self.by_kind.values():
            for pool in by_rarity.values():
                pool.sort(key=lambda t: t.variant)
        self._chances: dict[tuple[Kind, Tier], dict[Rarity, float]] = {}

    def chances(self, t: DropTable) -> dict[Rarity, float]:
        """The chance of each rarity on the table, among those its kind has."""
        cached = self._chances.get((t.kind, t.tier))
        if cached is not None:
            return cached
        by_rarity = self.by_kind.get(t.kind, {})
        rarities = {r: w for r, w in t.rarities.items() if w > 0 and by_rarity.get(r)}
        if not rarities and by_rarity:  # (the kind has none of the table's rarities: the closest lower one)
            lower = sorted((r for r in by_rarity if r <= max(t.rarities)), reverse=True)
            rarities = {lower[0]: 1.0} if lower else {}
        total = sum(rarities.values())
        out = {r: w / total for r, w in rarities.items()}
        self._chances[(t.kind, t.tier)] = out
        return out

    def roll(self, t: DropTable, rng: Random, shown: Iterable[str] = ()) -> tuple[Template, Edition]:
        """A card rolled on the table (another than those ``shown`` in its pack, while its rarity has one)."""
        rarity = _weighted(self.chances(t), rng)
        pool = self.by_kind[t.kind][rarity]
        seen = set(shown)
        fresh = [x for x in pool if x.variant not in seen] or pool
        template = fresh[min(len(fresh) - 1, int(rng.random() * len(fresh)))]
        return template, _weighted(t.editions, rng)

    def odds(self, template: Template, edition: Edition, t: DropTable | None = None) -> int:
        """One in how many cards of the table (its kind's standard one) is this card with this edition (0: it
        can't be rolled there)."""
        t = t or table(template.kind)
        if t.kind is not template.kind:
            return 0
        p_rarity = self.chances(t).get(template.rarity, 0.0)
        pool = self.by_kind.get(template.kind, {}).get(template.rarity, [])
        p_edition = t.editions.get(edition, 0) / sum(t.editions.values())
        p = p_rarity / max(1, len(pool)) * p_edition
        return round(1 / p) if p > 0 else 0

    def counts(self) -> dict[Kind, dict[Rarity, int]]:
        return {k: {r: len(p) for r, p in sorted(rs.items())} for k, rs in self.by_kind.items()}


@dataclass(frozen=True, kw_only=True)
class Choice:
    """A card shown in a pack."""

    kind: Kind
    key: str
    rarity: Rarity
    edition: Edition
    enhancement: str | None = None
    seal: str | None = None


def roll_pack(booster: Booster, pools: Pools, rng: Random) -> list[Choice]:
    out: list[Choice] = []
    shown: list[str] = []
    for _ in range(booster.choices):
        template, edition = pools.roll(booster.table, rng, shown)
        shown.append(template.variant)
        out.append(Choice(kind=template.kind, key=template.key, rarity=template.rarity, edition=edition,
                          enhancement=template.enhancement, seal=template.seal))
    return out


class PackStatus(StrEnum):
    OPEN = "open"  # its cards are shown, waiting for the player's choice
    OPENED = "opened"  # chosen: the cards chosen are items


@dataclass(kw_only=True)
class Pack:
    """A booster bought: its cards, rolled when it was bought, and the player's choice."""

    id: str
    owner: str
    booster: str  # Booster.id
    price: int  # the coins it cost
    picks: int
    choices: list[Choice]
    status: PackStatus
    created_at: datetime
    opened_at: datetime | None = None
    chosen: tuple[int, ...] = ()  # the cards chosen (indexes in choices)
    items: tuple[str, ...] = field(default=())  # the items they became


def choose(pack: Pack, picks: Sequence[int], now: datetime) -> list[Choice]:
    """The player's choice: as many cards as the booster gives, each once. Returns the cards chosen."""
    if pack.status is not PackStatus.OPEN:
        raise PackOpened("this pack is opened: its cards were chosen")
    if len(picks) != pack.picks:
        raise InvalidPick(f"choose {pack.picks} of the pack's {len(pack.choices)} cards")
    if len(set(picks)) != len(picks) or any(not 0 <= i < len(pack.choices) for i in picks):
        raise InvalidPick("each card is chosen once, among the pack's")
    pack.status = PackStatus.OPENED
    pack.opened_at = now
    pack.chosen = tuple(picks)
    return [pack.choices[i] for i in picks]
