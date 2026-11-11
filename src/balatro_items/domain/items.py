"""Items: a joker or a tag of the game, with an edition, owned by a player.

An item is a collectible. It changes nothing in a run: the game shows it, it
never plays it. Every item is numbered among the items of the same key and
edition (``serial``: #1 was the first found), remembers where it came from
(``source``, ``source_run``) and, when it came from a win, the stake it was
won at (``stake``: the game's stake sticker). It can only change hands again
when its trade hold is over (``tradable_at``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum


class Kind(StrEnum):
    JOKER = "joker"
    TAG = "tag"


class Edition(StrEnum):
    """The game's editions (Card:set_edition)."""

    BASE = "base"
    FOIL = "foil"
    HOLOGRAPHIC = "holographic"
    POLYCHROME = "polychrome"
    NEGATIVE = "negative"


class Rarity(IntEnum):
    """The game's joker rarities (tags get one here: TAG_RARITY)."""

    COMMON = 1
    UNCOMMON = 2
    RARE = 3
    LEGENDARY = 4


# Tags have no rarity in the game: those whose effect is rarer here are rarer.
TAG_RARITY: dict[str, Rarity] = {
    "tag_negative": Rarity.RARE,
    "tag_polychrome": Rarity.RARE,
    "tag_holo": Rarity.UNCOMMON,
    "tag_foil": Rarity.UNCOMMON,
    "tag_rare": Rarity.UNCOMMON,
    "tag_ethereal": Rarity.UNCOMMON,
    "tag_double": Rarity.UNCOMMON,
    "tag_voucher": Rarity.UNCOMMON,
}


@dataclass(frozen=True, kw_only=True)
class Template:
    """What can be found: a joker or a tag of the game's catalog."""

    kind: Kind
    key: str
    name: str
    rarity: Rarity
    sprite: dict[str, object] | None = None  # the catalog's sprite (atlas, pos, soul_pos)


@dataclass(kw_only=True)
class Item:
    id: str
    kind: Kind
    key: str
    edition: Edition
    rarity: Rarity
    stake: int | None  # the stake of the win it came from (None: not from a win)
    serial: int  # its number among the items of its key and edition (given when it is stored)
    owner: str
    source: str  # how it was found (drops.Grant.reason, or "gift")
    source_run: str | None
    created_at: datetime
    acquired_at: datetime  # when its owner got it
    tradable_at: datetime  # the end of its trade hold

    def tradable(self, now: datetime) -> bool:
        return now >= self.tradable_at


@dataclass(frozen=True, kw_only=True)
class Transfer:
    """An item changing hands (``from_owner`` None: it was found)."""

    item: str
    from_owner: str | None
    to_owner: str
    at: datetime
    trade: str | None = None


@dataclass(kw_only=True)
class PlayerRecord:
    """A player this service has seen: their name (from their tokens), whether
    they may trade (a counted win: the game API says), and their showcase."""

    id: str
    name: str | None
    has_won: bool
    showcase: str | None  # the item shown on their title screen and profile
    created_at: datetime
    synced_at: datetime | None = None  # the last time their runs were read
