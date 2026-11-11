"""Stand-ins for the game API, the clock, ids and randomness."""

from __future__ import annotations

import hashlib
import random
from datetime import UTC, datetime, timedelta

from balatro_items.application.dto import Player
from balatro_items.application.errors import GameApiUnavailable
from balatro_items.domain import TAG_RARITY, Kind, Rarity, RunRecord, Template

# a Wednesday
T0 = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)

JOKERS = {Rarity.COMMON: ["j_joker", "j_greedy_joker", "j_lusty_joker", "j_wrathful_joker"],
          Rarity.UNCOMMON: ["j_four_fingers", "j_mime"], Rarity.RARE: ["j_dna", "j_blueprint"],
          Rarity.LEGENDARY: ["j_caino", "j_perkeo"]}
TAGS = ["tag_economy", "tag_negative", "tag_foil", "tag_d_six"]


class FakeCatalog:
    def __init__(self) -> None:
        self.down = False

    def templates(self) -> list[Template]:
        if self.down:
            raise GameApiUnavailable("down")
        out = [Template(kind=Kind.JOKER, key=k, name=k.removeprefix("j_").replace("_", " ").title(), rarity=r,
                        sprite={"atlas": "Joker", "pos": {"x": i, "y": int(r)}})
               for r, keys in JOKERS.items() for i, k in enumerate(keys)]
        out += [Template(kind=Kind.TAG, key=k, name=k.removeprefix("tag_").title() + " Tag",
                         rarity=TAG_RARITY.get(k, Rarity.COMMON), sprite={"atlas": "tags", "pos": {"x": i, "y": 0}})
                for i, k in enumerate(TAGS)]
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
