"""Stand-ins for the game API, the clock, ids and randomness."""

from __future__ import annotations

import hashlib
import random
from datetime import UTC, datetime, timedelta

from balatro_items.application.dto import CasinoEvent, Player
from balatro_items.application.errors import GameApiUnavailable
from balatro_items.domain import (
    CONSUMABLE_RARITY,
    ENHANCEMENTS,
    SEALS,
    Kind,
    Rarity,
    RunRecord,
    Template,
    playing_cards,
)
from balatro_items.infrastructure.feed import LocalFeed

# a Wednesday
T0 = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)

JOKERS = {Rarity.COMMON: ["j_joker", "j_greedy_joker", "j_lusty_joker", "j_wrathful_joker"],
          Rarity.UNCOMMON: ["j_four_fingers", "j_mime"], Rarity.RARE: ["j_dna", "j_blueprint"],
          Rarity.LEGENDARY: ["j_caino", "j_perkeo"]}
CONSUMABLES = {Kind.TAROT: ["c_magician", "c_empress", "c_hermit", "c_fool"],
               Kind.PLANET: ["c_pluto", "c_mercury", "c_earth", "c_eris"],
               Kind.SPECTRAL: ["c_familiar", "c_aura", "c_hex", "c_soul"]}
CARDS = [("S_A", "Ace of Spades"), ("H_K", "King of Hearts"), ("D_2", "2 of Diamonds"), ("C_T", "10 of Clubs")]


class FakeCatalog:
    def __init__(self) -> None:
        self.down = False

    def templates(self) -> list[Template]:
        if self.down:
            raise GameApiUnavailable("down")
        out = [Template(kind=Kind.JOKER, key=k, name=k.removeprefix("j_").replace("_", " ").title(), rarity=r,
                        sprite={"atlas": "Joker", "pos": {"x": i, "y": int(r)}})
               for r, keys in JOKERS.items() for i, k in enumerate(keys)]
        out += [Template(kind=kind, key=k, name=k.removeprefix("c_").replace("_", " ").title(),
                         rarity=CONSUMABLE_RARITY.get(k, Rarity.COMMON),
                         sprite={"atlas": "Tarot", "pos": {"x": i, "y": 0}})
                for kind, keys in CONSUMABLES.items() for i, k in enumerate(keys)]
        fronts = ((k, name, {"atlas": "cards_1", "pos": {"x": i, "y": 0}}) for i, (k, name) in enumerate(CARDS))
        out += playing_cards(fronts, {"atlas": "centers", "pos": {"x": 1, "y": 0}},
                             {e: {"atlas": "centers", "pos": {"x": i, "y": 1}} for i, e in enumerate(ENHANCEMENTS)},
                             {s: {"atlas": "centers", "pos": {"x": i, "y": 4}} for i, s in enumerate(SEALS)})
        return out


class FakeRuns:
    def __init__(self) -> None:
        self.by_player: dict[str, list[RunRecord]] = {}
        self.down = False
        self.calls = 0

    def add(self, player: str, run_id: str, *, deck: str = "b_red", stake: int = 1, won: bool = False,
            finished: bool = True, ante: int = 1, counted: bool = True, at: datetime = T0) -> RunRecord:
        r = RunRecord(id=run_id, deck=deck, stake=stake, won=won, finished=finished, ante=ante, counted=counted,
                      ended_at=at)
        self.by_player.setdefault(player, []).append(r)
        return r

    def runs(self, player: Player) -> list[RunRecord]:
        self.calls += 1
        if self.down:
            raise GameApiUnavailable("down")
        return list(self.by_player.get(player.id, []))


class Clock:
    def __init__(self, t: datetime = T0) -> None:
        self.t = t

    def now(self) -> datetime:
        return self.t

    def advance(self, **kw: float) -> None:
        self.t += timedelta(**kw)


class Ids:
    def __init__(self) -> None:
        self.n = 0

    def new_id(self) -> str:
        self.n += 1
        return f"id{self.n:04d}"


class Seeds:
    """Server seeds anyone can guess: tests only."""

    def __init__(self) -> None:
        self.n = 0

    def seed(self) -> str:
        self.n += 1
        return hashlib.sha256(f"seed{self.n}".encode()).hexdigest()


def rng(seed: int = 1) -> random.Random:
    return random.Random(seed)


class RecordingFeed(LocalFeed):
    """The real feed, keeping a copy of every event it publishes."""

    def __init__(self) -> None:
        super().__init__()
        self.published: list[CasinoEvent] = []

    def publish(self, event: CasinoEvent) -> None:
        self.published.append(event)
        super().publish(event)

    def games(self) -> list[tuple[str, str]]:
        """(game id, status) of each game event."""
        return [(e.data.id, e.data.status.value) for e in self.published if e.type == "game"]

    def clear(self) -> None:
        self.published.clear()
