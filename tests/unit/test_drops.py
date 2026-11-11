"""How items are found: the grants runs earn, and the tables they roll on."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from balatro_items.domain import (
    BOOSTED,
    PREMIUM,
    STANDARD,
    Edition,
    Kind,
    Rarity,
    RunRecord,
    earned,
    next_week,
    odds,
    roll,
    week_of,
)
from tests.fakes import T0, FakeCatalog, rng


def run(run_id: str, **kw: object) -> RunRecord:
    base: dict[str, object] = {"deck": "b_red", "stake": 1, "won": False, "finished": True, "ante": 1,
                               "counted": True, "ended_at": T0}
    base.update(kw)
    return RunRecord(id=run_id, **base)  # type: ignore[arg-type]


def sources(runs: list[RunRecord], claimed: set[str] | None = None) -> list[str]:
    return [g.source for g in earned(runs, claimed or set(), T0)]


def test_weeks() -> None:
    assert week_of(T0) == "2026-W46"
    assert next_week(T0).isoformat() == "2026-11-16T00:00:00+00:00"


def test_a_lost_run_earns_the_weekly_item_from_ante_3() -> None:
    assert sources([run("a", ante=2)]) == []
    assert sources([run("a", ante=3, finished=False)]) == []  # still being played
    assert sources([run("a", ante=2), run("b", ante=3)]) == ["week:2026-W46:play"]
    g = earned([run("b", ante=5)], set(), T0)[0]
    assert g.run == "b" and g.table is STANDARD and g.stake is None and g.reason == "weekly"


def test_runs_that_dont_count_earn_nothing() -> None:
    assert sources([run("a", ante=8, won=True, stake=8, counted=False)]) == []


def test_last_weeks_runs_earn_nothing_but_their_wins_milestones() -> None:
    old = T0 - timedelta(days=7)
    assert sources([run("a", ante=5, ended_at=old)]) == []
    assert sources([run("a", won=True, ante=8, stake=3, ended_at=old)]) == ["deck:b_red", "stake:2", "stake:3"]


def test_a_win() -> None:
    grants = earned([run("w", won=True, ante=8, stake=2, deck="b_blue", finished=False)], set(), T0)
    assert [g.source for g in grants] == ["week:2026-W46:play", "week:2026-W46:win", "deck:b_blue", "stake:2"]
    assert [g.table for g in grants] == [STANDARD, BOOSTED, BOOSTED, BOOSTED]
    assert all(g.stake == 2 for g in grants)  # each item from a win carries its stake
    # each grant once: what is claimed isn't earned again, and later wins don't repeat milestones
    claimed = {g.source for g in grants}
    later = run("w2", won=True, ante=8, stake=2, deck="b_blue", ended_at=T0 + timedelta(hours=1))
    assert sources([run("w", won=True, ante=8, stake=2, deck="b_blue"), later], claimed) == []


def test_gold_stake_is_premium_and_every_stake_below_counts() -> None:
    grants = earned([run("g", won=True, ante=8, stake=8, ended_at=T0 - timedelta(days=30))], set(), T0)
    assert [g.source for g in grants] == ["deck:b_red", *(f"stake:{s}" for s in range(2, 9))]
    assert grants[-1].table is PREMIUM and all(g.table is BOOSTED for g in grants[:-1])


def test_rolls_follow_the_table() -> None:
    templates = FakeCatalog().templates()
    r = rng(7)
    rolls = [roll(STANDARD, templates, r) for _ in range(20000)]
    kinds = Counter(t.kind for t, _ in rolls)
    assert 0.83 < kinds[Kind.JOKER] / len(rolls) < 0.87
    rarities = Counter(t.rarity for t, _ in rolls if t.kind is Kind.JOKER)
    assert rarities[Rarity.COMMON] > rarities[Rarity.UNCOMMON] > rarities[Rarity.RARE] > rarities[Rarity.LEGENDARY] > 0
    editions = Counter(e for _, e in rolls)
    assert editions[Edition.BASE] > editions[Edition.FOIL] > editions[Edition.HOLOGRAPHIC] > editions[
        Edition.POLYCHROME] > editions[Edition.NEGATIVE] > 0
    # the premium table: never common, never base
    premium = [roll(PREMIUM, templates, r) for _ in range(2000)]
    assert all(t.rarity >= Rarity.UNCOMMON and e is not Edition.BASE and t.kind is Kind.JOKER for t, e in premium)


def test_odds_say_what_is_rarer() -> None:
    templates = FakeCatalog().templates()
    by_key = {t.key: t for t in templates}
    common, legendary = by_key["j_joker"], by_key["j_caino"]
    assert odds(common, Edition.BASE, templates) < odds(common, Edition.NEGATIVE, templates)
    assert odds(common, Edition.NEGATIVE, templates) < odds(legendary, Edition.NEGATIVE, templates)
    # 85% jokers, 70% common, 4 commons here, 85% base: 1 in 1 / (0.85 * 0.7 / 4 * 0.85)
    assert odds(common, Edition.BASE, templates) == round(1 / (0.85 * 0.7 / 4 * 0.85))
    assert odds(common, Edition.BASE, templates, PREMIUM) == 0  # can't drop there
