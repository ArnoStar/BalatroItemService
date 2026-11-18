"""What the use cases need from the outside world."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol

from balatro_items.domain import (
    CoinMove,
    Edition,
    Game,
    GameStatus,
    Item,
    Listing,
    Mode,
    Pack,
    PackStatus,
    PlayerRecord,
    RunRecord,
    Template,
    Trade,
    Transfer,
    Upgrade,
)

from .dto import CasinoEvent, ListingQuery, Player


class Unit(Protocol):
    """One transaction on the store: everything done in it happens together or not at all.
    ``lock``: keep the rows for this transaction (others wait)."""

    def player(self, player_id: str, lock: bool = False) -> PlayerRecord | None: ...

    def save_player(self, p: PlayerRecord) -> None: ...

    def find_players(self, query: str, limit: int) -> list[PlayerRecord]:
        """Players whose name starts with ``query`` (case ignored), by name."""
        ...

    def item(self, item_id: str) -> Item | None: ...

    def items(self, ids: Sequence[str], lock: bool = False) -> dict[str, Item]: ...

    def items_of(self, owner: str) -> builtins.list[Item]:
        """Their items (not those destroyed), newest first."""
        ...

    def add_item(self, item: Item) -> Item:
        """Stores a new item and gives it its serial number (among its variant's and edition's)."""
        ...

    def save_item(self, item: Item) -> None:
        """Its owner, acquired_at, tradable_at, staked and listed."""
        ...

    def minted(self, variant: str, edition: Edition) -> int:
        """How many items of this variant (items.variant) and edition have been made."""
        ...

    def add_transfer(self, t: Transfer) -> None: ...

    def transfers(self, item_id: str) -> builtins.list[Transfer]:
        """Oldest first."""
        ...

    def claims(self, owner: str) -> set[str]: ...

    def claim(self, owner: str, source: str, run: str | None, at: datetime, coins: int) -> bool:
        """Records that the player got this grant (its coins); False if they already had."""
        ...

    def add_coins(self, player: str, amount: int, reason: str, ref: str | None, at: datetime) -> int:
        """Adds (or, negative, takes) coins and records the move; returns the balance. Raises NotEnoughCoins
        (and changes nothing) if the balance would go below 0. The player's record must exist."""
        ...

    def coin_moves(self, player: str, limit: int) -> builtins.list[CoinMove]:
        """The last first."""
        ...

    def pack(self, pack_id: str, lock: bool = False) -> Pack | None: ...

    def add_pack(self, p: Pack) -> None: ...

    def save_pack(self, p: Pack) -> None: ...

    def packs_of(self, owner: str, status: PackStatus | None, limit: int) -> builtins.list[Pack]:
        """Newest first."""
        ...

    def listing(self, listing_id: str, lock: bool = False) -> Listing | None: ...

    def add_listing(self, listing: Listing) -> None:
        """(An item has one open listing at most.)"""
        ...

    def save_listing(self, listing: Listing) -> None: ...

    def listings(self, q: ListingQuery) -> builtins.list[Listing]:
        """Listings in ``q.status`` that match the query, in its order (``q.offset`` skipped, ``q.limit`` at most)."""
        ...

    def open_listings_of(self, seller: str) -> int: ...

    def add_upgrade(self, up: Upgrade) -> None: ...

    def upgrade(self, upgrade_id: str) -> Upgrade | None: ...

    def upgrades(self, player: str | None, limit: int, before: datetime | None = None) -> builtins.list[Upgrade]:
        """The last first (``before``: older than this)."""
        ...

    def trade(self, trade_id: str, lock: bool = False) -> Trade | None: ...

    def add_trade(self, t: Trade) -> None: ...

    def save_trade(self, t: Trade) -> None: ...

    def trades_of(self, player: str, box: str, limit: int) -> builtins.list[Trade]:
        """``box``: incoming, outgoing or all; newest first."""
        ...

    def pending_from(self, sender: str, now: datetime) -> int: ...

    def game(self, game_id: str, lock: bool = False) -> Game | None: ...

    def add_game(self, g: Game) -> None: ...

    def save_game(self, g: Game) -> None: ...

    def open_jackpot(self, lock: bool = False) -> Game | None:
        """The pot taking items. ``lock``: no other unit gets the jackpot until this one ends (even
        when there is none: this unit may open it)."""
        ...

    def games(self, mode: Mode | None, status: GameStatus, player: str | None, limit: int,
              since: datetime | None = None, before: datetime | None = None) -> builtins.list[Game]:
        """Games in this status (of this mode, with this player, last changed from ``since`` and before
        ``before``), the last changed first."""
        ...


class Store(Protocol):
    def unit(self) -> AbstractContextManager[Unit]: ...


class RunSource(Protocol):
    """The game API's list of the player's runs."""

    def runs(self, player: Player) -> list[RunRecord]:
        """Raises GameApiUnavailable."""
        ...


class Catalog(Protocol):
    """The game's jokers and tags (from the game API's catalog)."""

    def templates(self) -> list[Template]:
        """Raises GameApiUnavailable."""
        ...


class Authenticator(Protocol):
    @property
    def required(self) -> bool: ...

    def authenticate(self, token: str | None) -> Player: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new_id(self) -> str: ...


class SeedSource(Protocol):
    def seed(self) -> str:
        """A new secret nobody can guess (a casino game's server seed): 64 hex digits."""
        ...


class FeedSubscription(Protocol):
    """One open live stream of the casino."""

    async def next(self, timeout: float) -> CasinoEvent | None:
        """The next event, or None when nothing came in ``timeout`` seconds. Raises EOFError once closed (a stream
        that doesn't keep up is closed: its client opens another and reloads)."""
        ...

    def close(self) -> None: ...


class CasinoFeed(Protocol):
    """The casino's live streams, in this process (one process: the feed is in memory)."""

    def publish(self, event: CasinoEvent) -> None:
        """To every open stream (from any thread)."""
        ...

    def subscribe(self) -> FeedSubscription:
        """A new stream (called on the event loop that will read it)."""
        ...
