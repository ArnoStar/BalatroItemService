"""The casino: players stake items against each other, and the winner takes them all.

Three games, all between players only: the casino makes no item and keeps
none (no house, no cut), so it changes who has items, never how many there are.

- **Coinflip**: a player stakes some items on a side (Chips or Mult); another
  player matches them with items worth about as much (``COINFLIP_MARGIN``
  percent more or less), and the coin is flipped at once.
- **Dice**: the same duel, but the first player chooses their chance
  (``MIN_CHANCE`` to ``MAX_CHANCE`` percent): the second player's items must be
  worth what makes it so (``join_range``), and the roll decides at once. A long
  shot stakes little against much; a safe bet stakes much against little.
- **Jackpot**: one pot at a time, which anyone adds items to; once two players
  are in, it is drawn a while later (``wait``, the service's setting).

A coinflip or a dice game may be a **challenge**: only the player it names may
join it (everyone may still watch it, as every game).

A player's chance is the value of their items over the value of the pot. An
item's value is its odds, one in how many cards of its kind's standard table
it is (``boosters.Pools.odds``: its value in coins), so a rarer item weighs
more. It is fixed when it is staked.

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
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from .errors import GameClosed, InvalidBet, ItemsMoved, NotParticipant
from .items import Item

MAX_STAKE = 10  # items in one entry
COINFLIP_MARGIN = 10  # percent: what a duel's second player's items may be worth more or less than asked
MAX_OPEN_COINFLIPS = 5  # a player's coinflips waiting for another player (and as many dice games)
MIN_CHANCE = 5  # percent: the chances a dice game's first player may choose
MAX_CHANCE = 95
JACKPOT_MAX_PLAYERS = 10
JACKPOT_MAX_ITEMS = 50
MAX_SEED = 64
ROLL_DIGITS = 13  # the hex digits of the HMAC the roll is made of (52 bits)
ROLL_SPAN = 1 << (4 * ROLL_DIGITS)  # 16 ** ROLL_DIGITS
SEED_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


class Mode(StrEnum):
    COINFLIP = "coinflip"
    JACKPOT = "jackpot"
    DICE = "dice"


DUELS = frozenset({Mode.COINFLIP, Mode.DICE})  # two players: the first stakes, the second matches


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
    opponent: str | None = None  # a challenge: the only player who may join (a coinflip or a dice game)
    chance: int | None = None  # a dice game: the first player's chance, in percent (the second has the rest)

    @property
    def asked(self) -> int:
        """The first player's chance (percent) a duel's second player must match: a dice game's, else half."""
        return self.chance if self.chance is not None else 50

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


def join_range(value: int, chance: int = 50) -> tuple[int, int]:
    """What a duel's second player's items must be worth (both included) against the first's, worth ``value``,
    for the first to have ``chance`` percent of the pot: ``value * (100 - chance) / chance``, ``COINFLIP_MARGIN``
    percent more or less."""
    rest = 100 - chance
    return ((value * rest * (100 - COINFLIP_MARGIN) + chance * 100 - 1) // (chance * 100),
            value * rest * (100 + COINFLIP_MARGIN) // (chance * 100))


def coinflip_range(value: int) -> tuple[int, int]:
    """What the second player's items must be worth (both included) against items worth ``value``."""
    return join_range(value, 50)


def check_chance(chance: int) -> None:
    """A dice game's chance, as its first player chooses it."""
    if not MIN_CHANCE <= chance <= MAX_CHANCE:
        raise InvalidBet(f"a dice game's chance is {MIN_CHANCE} to {MAX_CHANCE} percent")


def check_challenge(player: str, opponent: str | None) -> None:
    """A duel's first player names who may join it (None: anyone)."""
    if opponent is not None and opponent == player:
        raise InvalidBet("challenge another player, not yourself")


def check_join(game: Game, player: str) -> None:
    """Whether the player may join this duel (before their items are staked)."""
    if game.status is not GameStatus.OPEN:
        raise GameClosed(f"this game is {game.status.value}")
    if player in game.players:
        raise NotParticipant("this game is yours: another player joins it")
    if game.opponent is not None and player != game.opponent:
        raise NotParticipant("this game is a challenge to another player")


def join_duel(game: Game, entry: Entry) -> None:
    """A coinflip's or dice game's second entry (draw the game then): worth what the first player's chance asks."""
    check_join(game, entry.player)
    low, high = join_range(game.value, game.asked)
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


@dataclass(kw_only=True)
class Tally:
    """A player's games that are over (``tally``)."""

    player: str
    games: int = 0
    wins: int = 0
    staked: int = 0  # the value of the items they put in
    won: int = 0  # the value they took from the other players
    lost: int = 0  # the value of their items the other players took
    by_mode: dict[Mode, tuple[int, int]] = field(default_factory=dict)  # games, wins
    biggest: Game | None = None  # their biggest pot won
    luckiest: Game | None = None  # their least likely win

    @property
    def net(self) -> int:
        return self.won - self.lost


def stake_of(game: Game, player: str) -> int:
    """The value a player put in a game."""
    return sum(e.value for e in game.entries if e.player == player)


def winner_chance(game: Game) -> float:
    """The share of the pot the winner had (0 to 1)."""
    return stake_of(game, game.winner) / game.value if game.winner and game.value else 0.0


def tally(games: Sequence[Game]) -> dict[str, Tally]:
    """Each player's numbers over these games (the drawn ones count)."""
    out: dict[str, Tally] = {}
    for g in games:
        if g.status is not GameStatus.DONE:
            continue
        for p in g.players:
            t = out.setdefault(p, Tally(player=p))
            staked = stake_of(g, p)
            won = g.winner == p
            t.games += 1
            t.staked += staked
            n, w = t.by_mode.get(g.mode, (0, 0))
            t.by_mode[g.mode] = (n + 1, w + int(won))
            if won:
                t.wins += 1
                t.won += g.value - staked
                if t.biggest is None or g.value > t.biggest.value:
                    t.biggest = g
                if t.luckiest is None or winner_chance(g) < winner_chance(t.luckiest):
                    t.luckiest = g
            else:
                t.lost += staked
    return out
