"""What the use cases take and return: plain dataclasses, serialized as they
are by the HTTP layer (field names are the JSON names)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from balatro_items.domain import Edition, GameStatus, Kind, Mode, Rarity, Side, TradeStatus


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
    tradable: bool  # out of its trade hold and not staked
    staked: str | None  # the casino game it is staked in (it can't change hands until the game ends)
    sprite: dict[str, Any] | None = None  # the game's sprite: {atlas, pos: {x, y}, soul_pos}


@dataclass(frozen=True, kw_only=True)
class TransferView:
    from_player: str | None  # None: found
    from_name: str | None
    to_player: str
    to_name: str | None
    at: datetime
    trade: str | None
    game: str | None  # the casino game it was won in


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


@dataclass(frozen=True, kw_only=True)
class NewBet:
    items: list[str]
    seed: str | None = None  # the player's seed for the draw (None: a random one)
    side: Side | None = None  # a new coinflip's side (None: Chips)


@dataclass(frozen=True, kw_only=True)
class EntryView:
    player: str
    player_name: str | None
    items: list[ItemView]
    value: int  # the items' value (their odds) when they were staked
    chance: float  # percent of the pot
    low: int  # its part of the pot: from low (included) to high (excluded); the roll in it wins
    high: int
    seed: str  # the player's seed
    at: datetime


@dataclass(frozen=True, kw_only=True)
class GameView:
    id: str
    mode: Mode
    status: GameStatus  # open, done, cancelled
    side: Side | None  # a coinflip's first player's side (the second has the other)
    entries: list[EntryView]  # in the order they came
    value: int  # the pot
    seed_hash: str  # SHA-256 of the server seed: shown from the start
    server_seed: str | None  # shown once the game is over
    roll: int | None  # the draw: the point of the pot that won (below value)
    winner: str | None
    winner_name: str | None
    join_min: int | None  # an open coinflip: what the other player's items must be worth together
    join_max: int | None
    created_at: datetime
    updated_at: datetime
    closes_at: datetime | None  # when a jackpot is drawn (set once two players are in)


@dataclass(frozen=True, kw_only=True)
class JackpotView:
    round: GameView | None  # the pot taking items (None: the next item opens one)
    last: GameView | None  # the last pot drawn
    now: datetime  # the service's time (count down to round.closes_at with it)


@dataclass(frozen=True, kw_only=True)
class CasinoRulesView:
    open: bool  # False: nothing can be staked (staked items can still be taken back)
    max_items: int  # in one stake
    coinflip_margin: int  # percent: a coinflip's second player's items are worth this much more or less
    max_open_coinflips: int  # a player's coinflips waiting for another player
    jackpot_seconds: float  # from the second player in the pot to its draw
    jackpot_max_players: int
    jackpot_max_items: int
    trade_hold_days: float  # the items won start it
