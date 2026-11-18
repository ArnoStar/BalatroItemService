"""How coins are earned: only by playing, a few at a time, so none can be farmed.

A player's counted runs (not seeded, no challenge, no debug help: the game API
decides) earn **grants**, each at most once per player, each worth its coins:

- ``week:<ISO week>:play``: the first counted run finished this week that reached
  ante 3 (or won): ``WEEKLY_COINS``.
- ``week:<ISO week>:win``: the first counted win this week: ``WIN_COINS``.
- ``deck:<deck>``: the first counted win with each deck (15 decks): ``WIN_COINS``.
- ``stake:<n>``: the first counted win at each stake from Red (2) to Gold (8):
  ``WIN_COINS``, and ``GOLD_COINS`` for Gold.

Coins buy boosters (boosters.py), and items on the market from other players
(market.py). Past weeks don't earn anything, past wins do (their milestones).

Before boosters, each grant gave an item, rolled on the table its coins now
buy a normal booster of (weekly: standard; wins: boosted; Gold: premium).
Grants claimed then keep their items and earn no coins.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .items import Edition, Rarity

WEEKLY_MIN_ANTE = 3
FIRST_STAKE = 2  # stake milestones start at Red: a first win is already a deck milestone
GOLD_STAKE = 8
WEEKLY_COINS = 100  # a normal standard joker booster
WIN_COINS = 250  # a normal boosted one
GOLD_COINS = 1000  # a normal premium one


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
    coins: int
    run: str | None


def week_of(t: datetime) -> str:
    year, week, _ = t.astimezone(UTC).isocalendar()
    return f"{year}-W{week:02d}"


def next_week(now: datetime) -> datetime:
    """When the next week's grants open (Monday 00:00 UTC)."""
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
        grants.append(Grant(source=f"week:{week}:play", reason="weekly", coins=WEEKLY_COINS, run=play.id))
    win = next((r for r in this_week if r.won), None)
    if win is not None:
        grants.append(Grant(source=f"week:{week}:win", reason="weekly_win", coins=WIN_COINS, run=win.id))
    decks: set[str] = set()
    stakes: set[int] = set()
    for r in counted:
        if not r.won:
            continue
        if r.deck not in decks:
            decks.add(r.deck)
            grants.append(Grant(source=f"deck:{r.deck}", reason="first_deck_win", coins=WIN_COINS, run=r.id))
        for s in range(FIRST_STAKE, r.stake + 1):
            # (a win at a stake is a win at every stake below it too: the game's own rule for stake stickers)
            if s not in stakes:
                stakes.add(s)
                grants.append(Grant(source=f"stake:{s}", reason="first_stake_win",
                                    coins=GOLD_COINS if s == GOLD_STAKE else WIN_COINS, run=r.id))
    return [g for g in grants if g.source not in claimed]


# Tags were items until boosters came (2026-11-18): each was given back in coins, its value then, its odds on the
# standard table of that time (joker 85% / tag 15%; common 70, uncommon 25, rare 4.5 among the tags' rarities, 16
# common tags, 6 uncommon and 2 rare; base 85%, foil 8, holographic 4.5, polychrome 2, negative 0.5). Migration 4 of
# the PostgreSQL store did it.
RETIRED_TAG_COINS: dict[tuple[Rarity, Edition], int] = {
    (Rarity.COMMON, Edition.BASE): 178, (Rarity.COMMON, Edition.FOIL): 1895,
    (Rarity.COMMON, Edition.HOLOGRAPHIC): 3369, (Rarity.COMMON, Edition.POLYCHROME): 7581,
    (Rarity.COMMON, Edition.NEGATIVE): 30324,
    (Rarity.UNCOMMON, Edition.BASE): 187, (Rarity.UNCOMMON, Edition.FOIL): 1990,
    (Rarity.UNCOMMON, Edition.HOLOGRAPHIC): 3538, (Rarity.UNCOMMON, Edition.POLYCHROME): 7960,
    (Rarity.UNCOMMON, Edition.NEGATIVE): 31840,
    (Rarity.RARE, Edition.BASE): 347, (Rarity.RARE, Edition.FOIL): 3685,
    (Rarity.RARE, Edition.HOLOGRAPHIC): 6551, (Rarity.RARE, Edition.POLYCHROME): 14741,
    (Rarity.RARE, Edition.NEGATIVE): 58963,
}
