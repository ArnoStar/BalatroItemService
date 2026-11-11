"""What the use cases take and return: plain dataclasses, serialized as they
are by the HTTP layer (field names are the JSON names)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from balatro_items.domain import Edition, Kind, Rarity, TradeStatus


@dataclass(frozen=True, kw_only=True)
class Player:
    """Who is calling: the identity service's account, or the anonymous player
    when the service runs without sign-in. ``token``: theirs, to read their runs
    from the game API (never shown)."""

    id: str
    name: str | None = None
    roles: frozenset[str] = frozenset()
    token: str | None = field(default=None, repr=False)


@dataclass(frozen=True, kw_only=True)
class ItemView:
    id: str
    kind: Kind
    key: str  # the game's key (j_joker, tag_negative ...)
    name: str
    edition: Edition
    rarity: Rarity  # 1 Common, 2 Uncommon, 3 Rare, 4 Legendary
    stake: int | None  # the stake of the win it came from (the game's stake sticker); None: not from a win
    serial: int  # its number among the items of its key and edition (#1: the first found)
    minted: int  # how many items of its key and edition have been found so far
    odds: int  # one in this many drops (standard table) is this item with this edition: higher is rarer
    owner: str
    owner_name: str | None
    source: str  # weekly, weekly_win, first_deck_win, first_stake_win, gift
    source_run: str | None  # the run it was found in (watchable in the game)
    found_at: datetime
    acquired_at: datetime  # when its owner got it
    tradable_at: datetime  # the end of its trade hold
    tradable: bool
    sprite: dict[str, Any] | None = None  # the game's sprite: {atlas, pos: {x, y}, soul_pos}


@dataclass(frozen=True, kw_only=True)
class TransferView:
    from_player: str | None  # None: found
    from_name: str | None
    to_player: str
    to_name: str | None
    at: datetime
    trade: str | None


@dataclass(frozen=True, kw_only=True)
class ItemDetail:
    item: ItemView
    history: list[TransferView]  # oldest first


@dataclass(frozen=True, kw_only=True)
class WeekView:
    week: str  # ISO week (UTC), e.g. 2026-W46
    weekly_found: bool  # this week's item for a finished run (ante 3 or more) is found
    weekly_win_found: bool  # this week's item for a win is found
    next_week_at: datetime  # when the next week's items can be found


@dataclass(frozen=True, kw_only=True)
class MeView:
    id: str
    name: str | None
    can_trade: bool  # trading opens after the first counted win
    admin: bool  # may give items (admins)
    items: int
    showcase: ItemView | None
    week: WeekView


@dataclass(frozen=True, kw_only=True)
class DropsView:
    found: list[ItemView]  # the items just found (none: nothing new)
    week: WeekView


@dataclass(frozen=True, kw_only=True)
class PlayerView:
    id: str
    name: str | None
    you: bool
    can_trade: bool
    items: int
    showcase: ItemView | None


@dataclass(frozen=True, kw_only=True)
class TradeView:
    id: str
    sender: str
    sender_name: str | None
    recipient: str
    recipient_name: str | None
    give: list[ItemView]  # the sender's items
    take: list[ItemView]  # the recipient's items
    message: str
    status: TradeStatus
    available: bool  # every item is still where it was and out of its hold: it can be accepted
    created_at: datetime
    updated_at: datetime
    expires_at: datetime


@dataclass(frozen=True, kw_only=True)
class NewTrade:
    to: str
    give: list[str]
    take: list[str]
    message: str = ""


@dataclass(frozen=True, kw_only=True)
class TableView:
    name: str
    kinds: dict[str, float]  # percent
    rarities: dict[str, float]
    editions: dict[str, float]


@dataclass(frozen=True, kw_only=True)
class RuleView:
    source: str
    table: str
    description: str


@dataclass(frozen=True, kw_only=True)
class OddsView:
    """How items are found, in numbers."""

    rules: list[RuleView]
    tables: list[TableView]
    pools: dict[str, dict[str, int]]  # kind -> rarity -> how many items
    trade_hold_days: float
    offer_days: int


@dataclass(frozen=True, kw_only=True)
class Gift:
    to: str
    key: str
    edition: Edition = Edition.BASE
    stake: int | None = None
