"""What the use cases take and return: plain dataclasses, serialized as they
are by the HTTP layer (field names are the JSON names)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from balatro_items.domain import (
    Edition,
    GameStatus,
    Kind,
    ListingStatus,
    Mode,
    PackStatus,
    Rarity,
    Side,
    Size,
    Tier,
    TradeStatus,
)


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
    key: str  # the game's key (j_joker, c_fool, a playing card's S_A ...)
    name: str
    edition: Edition
    rarity: Rarity  # 1 Common, 2 Uncommon, 3 Rare, 4 Legendary
    stake: int | None  # the stake of the win it came from (the game's stake sticker); None: not from a win
    serial: int  # its number among the items of its variant and edition (#1: the first made)
    minted: int  # how many items of its variant and edition have been made so far
    odds: int  # one in this many cards of its kind's standard table is this one: how rare it is to find
    owner: str
    owner_name: str | None
    source: str  # booster, gift (before boosters: weekly, weekly_win, first_deck_win, first_stake_win)
    source_run: str | None  # the run it was found in (watchable in the game), before boosters
    found_at: datetime
    acquired_at: datetime  # when its owner got it
    tradable_at: datetime  # the end of its trade hold
    tradable: bool  # out of its trade hold, not staked and not for sale
    staked: str | None  # the casino game it is staked in (it can't change hands until the game ends)
    # the game's sprite: {atlas, pos: {x, y}, soul_pos, overlay}; a playing card's also {front, seal} (each
    # {atlas, pos}; front null for a Stone Card)
    sprite: dict[str, Any] | None = None
    enhancement: str | None = None  # a playing card's (m_bonus ... m_lucky)
    seal: str | None = None  # a playing card's (Gold, Red, Blue, Purple)
    variant: str = ""  # the card and its upgrades, as serial numbers count them (S_A+m_glass+Red)
    listed: str | None = None  # its open listing on the market
    price: int | None = None  # its price there, in coins
    booster: str | None = None  # the booster it came from
    condition: float = 0.0  # how well kept its card is: 0 (ruined) to 1 (pristine)
    grade: str = ""  # its condition's name: ruined, battered, worn, played, fine, excellent, mint, pristine
    mint_value: int = 0  # coins: what it would be worth in perfect condition (its card, edition, upgrades)
    value: int = 0  # coins: its mint value times its condition (what the casino stakes it at)


@dataclass(frozen=True, kw_only=True)
class TransferView:
    from_player: str | None  # None: made (a booster, a gift)
    from_name: str | None
    to_player: str
    to_name: str | None
    at: datetime
    trade: str | None
    game: str | None  # the casino game it was won in
    listing: str | None = None  # the market listing it was bought from
    price: int | None = None  # coins


@dataclass(frozen=True, kw_only=True)
class ItemDetail:
    item: ItemView
    history: list[TransferView]  # oldest first


@dataclass(frozen=True, kw_only=True)
class WeekView:
    week: str  # ISO week (UTC), e.g. 2026-W46
    weekly_earned: bool  # this week's coins for a finished run (ante 3 or more) are earned
    weekly_win_earned: bool  # this week's coins for a win are earned
    weekly_coins: int  # what they are worth
    weekly_win_coins: int
    next_week_at: datetime  # when the next week's coins can be earned


@dataclass(frozen=True, kw_only=True)
class MeView:
    id: str
    name: str | None
    can_trade: bool  # trading (and the market, the casino) open after the first counted win
    admin: bool  # may give items and coins (admins)
    items: int
    coins: int
    packs: int  # packs bought and not chosen from yet
    showcase: ItemView | None
    week: WeekView


@dataclass(frozen=True, kw_only=True)
class EarnedView:
    source: str  # the grant (week:2026-W46:play, deck:b_red ...)
    reason: str  # weekly, weekly_win, first_deck_win, first_stake_win
    coins: int
    run: str | None  # the run that earned it


@dataclass(frozen=True, kw_only=True)
class DropsView:
    earned: list[EarnedView]  # the grants just earned (none: nothing new)
    coins: int  # their coins together
    balance: int  # the player's coins now
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
    kind: Kind
    tier: Tier
    rarities: dict[str, float]  # percent, among the rarities the kind has
    editions: dict[str, float]  # percent


@dataclass(frozen=True, kw_only=True)
class RuleView:
    source: str
    coins: int
    description: str


@dataclass(frozen=True, kw_only=True)
class BoosterView:
    id: str  # <kind>_<tier>_<size>
    kind: Kind
    tier: Tier
    size: Size
    choices: int  # cards shown
    picks: int  # cards chosen
    price: int  # coins
    art: str  # the game's pack it looks like (p_buffoon_mega_1 ...): its sprite is the catalog's
    rarities: dict[str, float]  # percent, a card's chances
    editions: dict[str, float]


@dataclass(frozen=True, kw_only=True)
class OddsView:
    """How coins are earned and what boosters give, in numbers."""

    rules: list[RuleView]
    boosters: list[BoosterView]
    tables: list[TableView]
    pools: dict[str, dict[str, int]]  # kind -> rarity -> how many cards
    trade_hold_days: float
    offer_days: int
    market_min_price: int
    market_max_price: int
    market_max_listings: int


@dataclass(frozen=True, kw_only=True)
class Gift:
    to: str
    key: str
    edition: Edition = Edition.BASE
    stake: int | None = None
    enhancement: str | None = None  # a playing card's
    seal: str | None = None
    condition: float | None = None  # None: drawn as a booster's card's


@dataclass(frozen=True, kw_only=True)
class CoinGift:
    to: str
    coins: int
    note: str = ""


@dataclass(frozen=True, kw_only=True)
class CoinMoveView:
    amount: int  # in (> 0) or out
    balance: int  # after
    reason: str  # weekly, weekly_win, first_deck_win, first_stake_win, booster, market_buy, market_sale,
    # tag_refund, gift
    ref: str | None  # what for: the grant, the pack, the listing, the tag ...
    at: datetime


@dataclass(frozen=True, kw_only=True)
class CoinsView:
    balance: int
    moves: list[CoinMoveView]  # the last first


@dataclass(frozen=True, kw_only=True)
class ChoiceView:
    """A card in a pack."""

    index: int
    kind: Kind
    key: str
    name: str
    rarity: Rarity
    edition: Edition
    enhancement: str | None
    seal: str | None
    variant: str
    odds: int  # as an item's
    minted: int  # how many items of it there are already
    sprite: dict[str, Any] | None = None
    condition: float | None = None  # (None: a pack of before conditions: its card gets one when chosen)
    grade: str | None = None
    mint_value: int = 0
    value: int = 0  # its value as an item (with its condition)


@dataclass(frozen=True, kw_only=True)
class PackView:
    id: str
    booster: BoosterView
    price: int  # the coins it cost
    picks: int
    status: PackStatus
    choices: list[ChoiceView]
    chosen: list[int]  # once opened
    items: list[ItemView]  # the items the cards chosen became
    created_at: datetime
    opened_at: datetime | None


@dataclass(frozen=True, kw_only=True)
class ListingQuery:
    """Which listings: their status, the item's kind, rarity, edition, keys or variant, the seller or buyer; the
    order (``newest``, ``price``: cheapest first, ``-price``) and the page."""

    status: ListingStatus | None = ListingStatus.OPEN  # (None: any)
    kind: Kind | None = None
    rarity: Rarity | None = None
    edition: Edition | None = None
    keys: tuple[str, ...] | None = None  # the item is one of these cards
    variant: str | None = None
    seller: str | None = None
    buyer: str | None = None
    player: str | None = None  # the seller or the buyer
    sort: str = "newest"
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True, kw_only=True)
class ListingView:
    id: str
    seller: str
    seller_name: str | None
    item: ItemView | None  # (None: the item is gone)
    price: int  # coins
    status: ListingStatus
    available: bool  # it can be bought now
    buyer: str | None
    buyer_name: str | None
    created_at: datetime
    updated_at: datetime  # sold or taken off then


@dataclass(frozen=True, kw_only=True)
class NewListing:
    item: str
    price: int


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
    value: int  # the items' value when they were staked
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
