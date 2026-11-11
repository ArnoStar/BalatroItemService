"""The casino: players stake items against each other, and the winner takes them all.

Two games, both between players only: the casino makes no item and keeps none
(no house, no cut), so it changes who has items, never how many there are.

- **Coinflip**: a player stakes some items on a side (Chips or Mult); another
  player matches them with items worth about as much (``COINFLIP_MARGIN``
  percent more or less), and the coin is flipped at once.
- **Jackpot**: one pot at a time, which anyone adds items to; once two players
  are in, it is drawn a while later (``wait``, the service's setting).

A player's chance is the value of their items over the value of the pot. An
item's value is its odds, one in how many drops of the standard table it is
(``drops.odds``), so a rarer item weighs more. It is fixed when it is staked.

**Provably fair.** Each game has a secret server seed whose SHA-256 is shown
from the start, and each entry brings its player's seed. The draw is
``HMAC-SHA256(key=server seed, message="<game id>:<seed of entry 1>:<seed of entry 2>...")``:
its first 13 hex digits ``h`` give the roll, ``h * value of the pot // 16**13``
(an integer below the pot's value), and the entry whose part of the pot covers
it wins (the entries' values laid end to end, in order). The server seed is
shown once the game is over: anyone can check the draw, and nobody, players or
server, could steer it (the server chose its seed before the players chose
theirs, and they didn't know it).

A staked item stays its owner's, but can't change hands (nor be staked again)
until its game ends; then the items the winner takes start their trade hold.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from .errors import GameClosed, InvalidBet, ItemsMoved, NotParticipant
from .items import Item

MAX_STAKE = 10  # items in one entry
COINFLIP_MARGIN = 10  # percent: what the second player's items may be worth more or less than the first's
MAX_OPEN_COINFLIPS = 5  # a player's coinflips waiting for another player
JACKPOT_MAX_PLAYERS = 10
JACKPOT_MAX_ITEMS = 50
MAX_SEED = 64
ROLL_DIGITS = 13  # the hex digits of the HMAC the roll is made of (52 bits)
ROLL_SPAN = 1 << (4 * ROLL_DIGITS)  # 16 ** ROLL_DIGITS
SEED_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


class Mode(StrEnum):
    COINFLIP = "coinflip"
    JACKPOT = "jackpot"


class Side(StrEnum):
    """A coinflip's sides: the game's two scoring colours."""

    CHIPS = "chips"
    MULT = "mult"


class GameStatus(StrEnum):
    OPEN = "open"  # taking entries
    DONE = "done"  # drawn: the winner has every item
    CANCELLED = "cancelled"  # its only player took their items back


@dataclass(frozen=True, kw_only=True)
class Entry:
    """A player's items in a game (a player may have several entries in a jackpot)."""

    player: str
    items: tuple[str, ...]
    value: int  # the items' value when they were staked
    seed: str  # the player's seed for the draw
    at: datetime


@dataclass(kw_only=True)
class Game:
    id: str
    mode: Mode
    status: GameStatus
    side: Side | None  # a coinflip's first player's side (the other player has the other)
    entries: list[Entry]
    server_seed: str  # secret until the game is over (``seed_hash`` is shown from the start)
    created_at: datetime
    updated_at: datetime
    closes_at: datetime | None = None  # when a jackpot is drawn (set once two players are in)
    roll: int | None = None  # the draw: the point of the pot that won, below its value
    winner: str | None = None

    @property
    def seed_hash(self) -> str:
        return seed_hash(self.server_seed)

    @property
    def value(self) -> int:
        return sum(e.value for e in self.entries)

    @property
    def players(self) -> list[str]:
        """Who is in, in the order they came."""
        return list(dict.fromkeys(e.player for e in self.entries))

    @property
    def items(self) -> list[str]:
        return [i for e in self.entries for i in e.items]

    def due(self, now: datetime) -> bool:
        """A jackpot whose time has come: draw it."""
        return self.status is GameStatus.OPEN and self.closes_at is not None and now >= self.closes_at


def seed_hash(server_seed: str) -> str:
    return hashlib.sha256(server_seed.encode()).hexdigest()


def roll(server_seed: str, game_id: str, seeds: Sequence[str], value: int) -> int:
    """The draw: a point of the pot, from 0 to ``value`` (excluded)."""
    message = ":".join([game_id, *seeds]).encode()
    digest = hmac.new(server_seed.encode(), message, hashlib.sha256).hexdigest()
    return int(digest[:ROLL_DIGITS], 16) * value // ROLL_SPAN


def parts(entries: Sequence[Entry]) -> list[tuple[int, int]]:
    """Each entry's part of the pot: from low (included) to high (excluded), in order."""
    out: list[tuple[int, int]] = []
    low = 0
    for e in entries:
        out.append((low, low + e.value))
        low += e.value
    return out


def winner_of(entries: Sequence[Entry], point: int) -> str:
    for e, (low, high) in zip(entries, parts(entries), strict=True):
        if low <= point < high:
            return e.player
    raise ValueError(f"{point} is outside the pot")


def check_bet(ids: Sequence[str], seed: str) -> None:
    """What a stake must be, whatever the items are."""
    if not ids:
        raise InvalidBet("stake at least one item")
    if len(ids) > MAX_STAKE:
        raise InvalidBet(f"at most {MAX_STAKE} items at once")
    if len(set(ids)) != len(ids):
        raise InvalidBet("an item is in the stake twice")
    if not 1 <= len(seed) <= MAX_SEED or not set(seed) <= SEED_CHARACTERS:
        raise InvalidBet(f"a seed is 1 to {MAX_SEED} letters, digits, - or _")


def coinflip_range(value: int) -> tuple[int, int]:
    """What the second player's items must be worth (both included) against items worth ``value``."""
    return (value * (100 - COINFLIP_MARGIN) + 99) // 100, value * (100 + COINFLIP_MARGIN) // 100


def check_join(game: Game, player: str) -> None:
    """Whether the player may join this coinflip (before their items are staked)."""
    if game.status is not GameStatus.OPEN:
        raise GameClosed(f"this coinflip is {game.status.value}")
    if player in game.players:
        raise NotParticipant("this coinflip is yours: another player joins it")


def join_coinflip(game: Game, entry: Entry) -> None:
    """The second player's entry (draw the game then)."""
    check_join(game, entry.player)
    low, high = coinflip_range(game.value)
    if not low <= entry.value <= high:
        raise InvalidBet(f"the items must be worth {low} to {high} together (yours: {entry.value})")
    game.entries.append(entry)
    game.updated_at = entry.at


def join_jackpot(game: Game, entry: Entry, wait: timedelta) -> None:
    """An entry in the pot; the second player starts the countdown to the draw."""
    if game.status is not GameStatus.OPEN or game.due(entry.at):
        raise GameClosed("this pot is closed: the next one is open")
    if entry.player not in game.players and len(game.players) >= JACKPOT_MAX_PLAYERS:
        raise InvalidBet(f"the pot has its {JACKPOT_MAX_PLAYERS} players: wait for the next one")
    if len(game.items) + len(entry.items) > JACKPOT_MAX_ITEMS:
        raise InvalidBet(f"the pot holds at most {JACKPOT_MAX_ITEMS} items")
    game.entries.append(entry)
    game.updated_at = entry.at
    if game.closes_at is None and len(game.players) >= 2:
        game.closes_at = entry.at + wait


def draw(game: Game, now: datetime) -> None:
    if game.status is not GameStatus.OPEN:
        raise GameClosed(f"this game is {game.status.value}")
    if len(game.players) < 2:
        raise InvalidBet("a game is drawn between two players or more")
    game.roll = roll(game.server_seed, game.id, [e.seed for e in game.entries], game.value)
    game.winner = winner_of(game.entries, game.roll)
    game.status = GameStatus.DONE
    game.updated_at = now


def cancel(game: Game, player: str, now: datetime) -> None:
    """The game's only player takes their items back (a coinflip nobody joined, a pot nobody else is in)."""
    if game.status is not GameStatus.OPEN:
        raise GameClosed(f"this game is {game.status.value}")
    if game.players != [player]:
        raise NotParticipant("only a game's only player can take their items back")
    game.status = GameStatus.CANCELLED
    game.updated_at = now


def pay_out(game: Game, items: Mapping[str, Item], now: datetime, hold: timedelta) -> list[tuple[Item, str]]:
    """Ends a drawn or cancelled game: every item is unstaked, and the winner takes the other
    players' (they start their trade hold). Returns each moved item with its former owner."""
    if game.status is GameStatus.OPEN:
        raise GameClosed("this game isn't over")
    moved: list[tuple[Item, str]] = []
    for e in game.entries:
        for i in e.items:
            item = items.get(i)
            if item is None or item.owner != e.player or item.staked != game.id:
                raise ItemsMoved(f"item {i!r} has left game {game.id!r}")  # (never: staked items don't move)
            item.staked = None
            if game.status is GameStatus.DONE and game.winner is not None and e.player != game.winner:
                moved.append((item, item.owner))
                item.owner = game.winner
                item.acquired_at = now
                item.tradable_at = now + hold
    return moved
