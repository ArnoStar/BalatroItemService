"""The upgrade: a player puts one item in, aiming at an item worth so many times more; the house rolls.

The one casino game played against the house, at the owner's request
(2026-11-19): the item put in is gone whatever happens. With a multiplier M
(from ``MIN_MULTIPLIER`` to ``MAX_MULTIPLIER``) the chance to win is

    chance = 95% / M        (an item worth 100 aimed at x2: 47.5%)

and a win makes a new item worth M times the item's value, ``PRIZE_MARGIN``
more or less (``prize_range``). On average a player gets 95% of what they put
in: the house's 5% is coins' worth of items gone, which keeps items scarce.

The prize is drawn as a card is found (``prizes``): every card and edition is
as likely as on its kind's standard table, weighed by how likely a condition
puts its value in the range; its condition is then drawn within that range.

**Provably fair**, as the other games: the player's next server seed is
committed to (its SHA-256 shown) before they play, and the roll is the
casino's (``casino.roll``) on a million: ``roll = h * 1,000,000 // 16**13``,
``h`` the first 13 hex digits of HMAC-SHA256(server seed, "<upgrade id>:<seed>").
A roll below ``chance_ppm`` wins.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from .boosters import Pools, Random, table
from .casino import roll as casino_roll
from .casino import seed_hash
from .condition import DIGITS, condition_cdf, roll_condition_between
from .errors import InvalidBet
from .items import EDITIONS, Edition, Kind, Template
from .value import mint_value

EDGE = 0.95  # what a player gets back on average
PRIZE_MARGIN = 0.05  # the prize is worth the target, this much more or less
MIN_MULTIPLIER = 1.0
MAX_MULTIPLIER = 100.0
ROLL_SPAN_PPM = 1_000_000


@dataclass(kw_only=True)
class Upgrade:
    id: str
    player: str
    item: str  # the item put in (gone)
    item_value: int
    multiplier: float  # x1.00 ... x100.00
    chance_ppm: int  # parts per million: a roll below wins
    target: int  # the value aimed at
    low: int  # the prize's value: from low to high (both included)
    high: int
    server_seed: str
    seed: str  # the player's
    roll: int  # parts per million
    created_at: datetime
    prize: str | None = None  # the item won
    prize_value: int | None = None

    @property
    def won(self) -> bool:
        return self.roll < self.chance_ppm

    @property
    def seed_hash(self) -> str:
        return seed_hash(self.server_seed)


def check_multiplier(multiplier: float) -> float:
    if not math.isfinite(multiplier) or not MIN_MULTIPLIER <= multiplier <= MAX_MULTIPLIER:
        raise InvalidBet(f"an upgrade aims at x{MIN_MULTIPLIER:g} to x{MAX_MULTIPLIER:g} the item's value")
    return round(multiplier, 2)


def chance_ppm(multiplier: float) -> int:
    """The chance to win, in parts per million: 95% / multiplier."""
    return math.floor(EDGE * ROLL_SPAN_PPM / multiplier)


def prize_range(value: int, multiplier: float) -> tuple[int, int, int]:
    """(target, low, high): the value aimed at, and the prize's bounds."""
    target = max(1, round(value * multiplier))
    return target, max(1, math.ceil(target * (1 - PRIZE_MARGIN))), max(1, math.floor(target * (1 + PRIZE_MARGIN)))


def upgrade_roll(server_seed: str, upgrade_id: str, seed: str) -> int:
    return casino_roll(server_seed, upgrade_id, [seed], ROLL_SPAN_PPM)


@dataclass(frozen=True, kw_only=True)
class Prize:
    """A card and edition an upgrade may give, its weight, and the conditions that put it in the range."""

    template: Template
    edition: Edition
    mint: int
    low: float  # its condition, from low to high
    high: float
    weight: float


def prizes(pools: Pools, low: int, high: int) -> list[Prize]:
    """Every card and edition whose value can be between ``low`` and ``high``: weighed by how likely it is on its
    kind's standard table, times how likely a condition puts it there (kinds equally)."""
    out: list[Prize] = []
    kinds = [k for k in Kind if pools.by_kind.get(k)]
    for kind in kinds:
        t = table(kind)
        chances = pools.chances(t)
        total = sum(w for e, w in t.editions.items() if e in EDITIONS[kind])
        for rarity, pool in pools.by_kind[kind].items():
            p_card = chances.get(rarity, 0.0) / len(pool)
            if p_card <= 0:
                continue
            for template in pool:
                for edition, w in t.editions.items():
                    if w <= 0 or edition not in EDITIONS[kind]:
                        continue
                    mint = mint_value(kind, rarity, edition, template.enhancement, template.seal)
                    c_low = math.ceil(low / mint * 10**DIGITS) / 10**DIGITS
                    c_high = min(1.0, math.floor(high / mint * 10**DIGITS) / 10**DIGITS)
                    if c_low > c_high:
                        continue
                    mass = condition_cdf(c_high) - condition_cdf(c_low)
                    weight = p_card * (w / total) * mass / len(kinds)
                    if weight > 0:
                        out.append(Prize(template=template, edition=edition, mint=mint, low=c_low, high=c_high,
                                         weight=weight))
    return out


def pick_prize(candidates: Iterable[Prize], rng: Random) -> tuple[Prize, float]:
    """A prize, as likely as its weight, and its condition (within its range)."""
    listed = list(candidates)
    x = rng.random() * sum(p.weight for p in listed)
    chosen = listed[-1]
    for p in listed:
        x -= p.weight
        if x < 0:
            chosen = p
            break
    return chosen, roll_condition_between(rng, chosen.low, chosen.high)
