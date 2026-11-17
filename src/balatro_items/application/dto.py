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
    expires_at: datetime | None = None  # when their access token expires (a live stream ends then)


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
    chance: int | None = None  # a new dice game's chance for its first player, percent (None: 50)
    opponent: str | None = None  # a new coinflip or dice game: a challenge only this player may join


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
    join_min: int | None  # an open coinflip or dice game: what the other player's items must be worth together
    join_max: int | None
    created_at: datetime
    updated_at: datetime
    closes_at: datetime | None  # when a jackpot is drawn (set once two players are in)
    chance: int | None = None  # a dice game: the chance its first player chose, percent (the second has the rest)
    opponent: str | None = None  # a challenge: the only player who may join
    opponent_name: str | None = None


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
    dice_min_chance: int = 5  # percent: the chances a dice game's first player may choose
    dice_max_chance: int = 95


@dataclass(frozen=True, kw_only=True)
class WinView:
    """A game someone won, in a line: a leaderboard's, a player's best."""

    game: str
    mode: Mode
    player: str  # the winner
    player_name: str | None
    value: int  # the pot
    chance: float  # the winner's chance, percent
    players: int
    items: int  # how many items the pot had
    at: datetime


@dataclass(frozen=True, kw_only=True)
class ModeStatsView:
    games: int
    wins: int


@dataclass(frozen=True, kw_only=True)
class CasinoStatsView:
    """A player's games that are over, in numbers (their last ``STATS_GAMES``)."""

    player: str
    name: str | None
    games: int
    wins: int
    staked: int  # the value of the items they put in
    won: int  # the value they took from other players
    lost: int  # the value of their items other players took
    net: int  # won - lost
    modes: dict[str, ModeStatsView]
    biggest: WinView | None  # their biggest pot won
    luckiest: WinView | None  # their least likely win


@dataclass(frozen=True, kw_only=True)
class RankView:
    player: str
    name: str | None
    games: int
    wins: int
    staked: int
    net: int


@dataclass(frozen=True, kw_only=True)
class LeaderboardView:
    """The casino's best over a period: day (the last 24 hours), week (the last 7 days) or all."""

    period: str
    since: datetime | None
    games: int  # games drawn in the period
    value: int  # the value of their pots together
    players: int  # how many players played
    winners: list[RankView]  # the most value won (net), first 10 (winners only)
    stakers: list[RankView]  # the most value staked, first 10
    biggest: list[WinView]  # the biggest pots, first 10
    luckiest: list[WinView]  # the least likely wins, first 10


@dataclass(frozen=True, kw_only=True)
class CasinoSnapshotView:
    """Everything the casino shows at once (a live stream's first event)."""

    coinflips: list[GameView]  # waiting for a second player
    dice: list[GameView]
    jackpot: JackpotView
    recent: list[GameView]  # the last games drawn
    rules: CasinoRulesView


@dataclass(frozen=True)
class CasinoEvent:
    """A change of the casino, live: ``game`` (a GameView: made, joined, drawn, cancelled, a pot's new entry)."""

    type: str
    data: Any
