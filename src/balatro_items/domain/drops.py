"""How items are found: only by playing, a few at a time, so none can be farmed.

A player's counted runs (not seeded, no challenge, no debug help: the game API
decides) earn **grants**, each at most once per player:

- ``week:<ISO week>:play``: the first counted run finished this week that reached
  ante 3 (or won). One item a week, from the standard table.
- ``week:<ISO week>:win``: the first counted win this week. One more, from the
  boosted table.
- ``deck:<deck>``: the first counted win with each deck (15 decks): boosted.
- ``stake:<n>``: the first counted win at each stake from Red (2) to Gold (8):
  boosted, and the premium table for Gold.

So a player finds at most two items a week, plus one for each new deck and
stake they win with; nothing else gives items (an admin's ``gift`` aside). An
item from a win carries the stake it was won at. Past weeks don't earn
anything, past wins do (their milestones).

Each grant rolls its item on a table: the kind (joker or tag), the rarity (the
game's joker rarities), the item among those of that rarity, and the edition.
``odds`` says how rare an item and edition are on the standard table (one in N
drops), which is what makes an item more valuable than another.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from .items import Edition, Kind, Rarity, Template

WEEKLY_MIN_ANTE = 3
FIRST_STAKE = 2  # stake milestones start at Red: a first win is already a deck milestone
GOLD_STAKE = 8


@dataclass(frozen=True, kw_only=True)
class DropTable:
    name: str
    kinds: Mapping[Kind, float]
    rarities: Mapping[Rarity, float]
    editions: Mapping[Edition, float]


STANDARD = DropTable(
    name="standard",
    kinds={Kind.JOKER: 85, Kind.TAG: 15},
    rarities={Rarity.COMMON: 70, Rarity.UNCOMMON: 25, Rarity.RARE: 4.5, Rarity.LEGENDARY: 0.5},
    editions={Edition.BASE: 85, Edition.FOIL: 8, Edition.HOLOGRAPHIC: 4.5, Edition.POLYCHROME: 2,
              Edition.NEGATIVE: 0.5},
)
BOOSTED = DropTable(
    name="boosted",
    kinds={Kind.JOKER: 85, Kind.TAG: 15},
    rarities={Rarity.COMMON: 50, Rarity.UNCOMMON: 35, Rarity.RARE: 13, Rarity.LEGENDARY: 2},
    editions={Edition.BASE: 70, Edition.FOIL: 14, Edition.HOLOGRAPHIC: 9, Edition.POLYCHROME: 5, Edition.NEGATIVE: 2},
)
PREMIUM = DropTable(
    name="premium",
    kinds={Kind.JOKER: 100},
    rarities={Rarity.UNCOMMON: 40, Rarity.RARE: 50, Rarity.LEGENDARY: 10},
    editions={Edition.FOIL: 40, Edition.HOLOGRAPHIC: 30, Edition.POLYCHROME: 20, Edition.NEGATIVE: 10},
)
TABLES = (STANDARD, BOOSTED, PREMIUM)


@dataclass(frozen=True, kw_only=True)
class RunRecord:
    """A run as the game API lists it."""

    id: str
    deck: str
    stake: int
    won: bool
    finished: bool  # game over
    ante: int
    counted: bool  # counts for statistics: not seeded, no challenge, no debug commands
    ended_at: datetime  # when it was last played


@dataclass(frozen=True, kw_only=True)
class Grant:
    source: str  # the claim's key: one grant of each per player, ever
    reason: str  # weekly, weekly_win, first_deck_win, first_stake_win
    table: DropTable
    run: str | None
    stake: int | None  # the stake sticker of an item from a win


def week_of(t: datetime) -> str:
    year, week, _ = t.astimezone(UTC).isocalendar()
    return f"{year}-W{week:02d}"


def next_week(now: datetime) -> datetime:
    """When the next week's drops open (Monday 00:00 UTC)."""
    d = now.astimezone(UTC)
    monday = (d - timedelta(days=d.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday + timedelta(days=7)


def earned(runs: Iterable[RunRecord], claimed: set[str], now: datetime) -> list[Grant]:
    """The grants the player's runs have earned and not claimed yet, oldest first."""
    counted = sorted((r for r in runs if r.counted), key=lambda r: r.ended_at)
    grants: list[Grant] = []
    week = week_of(now)
    this_week = [r for r in counted if week_of(r.ended_at) == week]
    play = next((r for r in this_week if r.won or (r.finished and r.ante >= WEEKLY_MIN_ANTE)), None)
    if play is not None:
        grants.append(Grant(source=f"week:{week}:play", reason="weekly", table=STANDARD, run=play.id,
                            stake=play.stake if play.won else None))
    win = next((r for r in this_week if r.won), None)
    if win is not None:
        grants.append(Grant(source=f"week:{week}:win", reason="weekly_win", table=BOOSTED, run=win.id,
                            stake=win.stake))
    decks: set[str] = set()
    stakes: set[int] = set()
    for r in counted:
        if not r.won:
            continue
        if r.deck not in decks:
            decks.add(r.deck)
            grants.append(Grant(source=f"deck:{r.deck}", reason="first_deck_win", table=BOOSTED, run=r.id,
                                stake=r.stake))
        for s in range(FIRST_STAKE, r.stake + 1):
            # (a win at a stake is a win at every stake below it too: the game's own rule for stake stickers)
            if s not in stakes:
                stakes.add(s)
                grants.append(Grant(source=f"stake:{s}", reason="first_stake_win",
                                    table=PREMIUM if s == GOLD_STAKE else BOOSTED, run=r.id, stake=r.stake))
    return [g for g in grants if g.source not in claimed]


class Random(Protocol):
    def random(self) -> float: ...


def _weighted[T](weights: Mapping[T, float], rng: Random) -> T:
    items = [(k, w) for k, w in weights.items() if w > 0]
    total = sum(w for _, w in items)
    x = rng.random() * total
    for k, w in items:
        x -= w
        if x < 0:
            return k
    return items[-1][0]


def pools(templates: Iterable[Template]) -> dict[Kind, dict[Rarity, list[Template]]]:
    out: dict[Kind, dict[Rarity, list[Template]]] = {}
    for t in templates:
        out.setdefault(t.kind, {}).setdefault(t.rarity, []).append(t)
    for by_rarity in out.values():
        for pool in by_rarity.values():
            pool.sort(key=lambda t: t.key)
    return out


def _chances(table: DropTable, by_kind: dict[Kind, dict[Rarity, list[Template]]]) -> dict[Kind, dict[Rarity, float]]:
    """The chance of each kind and rarity on the table, among those that exist."""
    kinds = {k: w for k, w in table.kinds.items() if by_kind.get(k)}
    total_k = sum(kinds.values())
    out: dict[Kind, dict[Rarity, float]] = {}
    for kind, wk in kinds.items():
        rarities = {r: w for r, w in table.rarities.items() if by_kind[kind].get(r)}
        if not rarities:  # (the table has none of this kind's rarities: the closest lower one)
            lower = sorted((r for r in by_kind[kind] if r <= max(table.rarities)), reverse=True)
            rarities = {lower[0]: 1.0} if lower else {}
        total_r = sum(rarities.values())
        out[kind] = {r: (wk / total_k) * (w / total_r) for r, w in rarities.items()}
    return out


def roll(table: DropTable, templates: Sequence[Template], rng: Random) -> tuple[Template, Edition]:
    """An item found on this table."""
    by_kind = pools(templates)
    chances = _chances(table, by_kind)
    flat = {(k, r): p for k, rs in chances.items() for r, p in rs.items()}
    kind, rarity = _weighted(flat, rng)
    pool = by_kind[kind][rarity]
    template = pool[min(len(pool) - 1, int(rng.random() * len(pool)))]
    return template, _weighted(table.editions, rng)


def odds(template: Template, edition: Edition, templates: Sequence[Template], table: DropTable = STANDARD) -> int:
    """One in how many drops of the table is this item with this edition (0: it can't drop there)."""
    by_kind = pools(templates)
    p_rarity = _chances(table, by_kind).get(template.kind, {}).get(template.rarity, 0.0)
    pool = by_kind.get(template.kind, {}).get(template.rarity, [])
    p_edition = table.editions.get(edition, 0) / sum(table.editions.values())
    p = p_rarity / max(1, len(pool)) * p_edition
    return round(1 / p) if p > 0 else 0
