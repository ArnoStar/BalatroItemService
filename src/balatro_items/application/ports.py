"""What the use cases need from the outside world."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol

from balatro_items.domain import (
    Edition,
    Game,
    GameStatus,
    Item,
    Mode,
    PlayerRecord,
    RunRecord,
    Template,
    Trade,
    Transfer,
)

from .dto import Player


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
        """Newest first."""
        ...

    def add_item(self, item: Item) -> Item:
        """Stores a new item and gives it its serial number."""
        ...

    def save_item(self, item: Item) -> None: ...

    def minted(self, key: str, edition: Edition) -> int:
        """How many items of this key and edition have been found."""
        ...

    def add_transfer(self, t: Transfer) -> None: ...

    def transfers(self, item_id: str) -> builtins.list[Transfer]:
        """Oldest first."""
        ...

    def claims(self, owner: str) -> set[str]: ...

    def claim(self, owner: str, source: str, item_id: str, run: str | None, at: datetime) -> bool:
        """Records that the player got this grant; False if they already had."""
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

    def games(self, mode: Mode | None, status: GameStatus, player: str | None, limit: int) -> builtins.list[Game]:
        """Games in this status (of this mode, with this player), the last changed first."""
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
