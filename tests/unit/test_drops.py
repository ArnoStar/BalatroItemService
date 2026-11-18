"""How coins are earned: the grants runs earn, each once."""

from __future__ import annotations

from datetime import timedelta

from balatro_items.domain import GOLD_COINS, WEEKLY_COINS, WIN_COINS, RunRecord, earned, next_week, week_of
from tests.fakes import T0


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


def test_a_lost_run_earns_the_weekly_coins_from_ante_3() -> None:
    assert sources([run("a", ante=2)]) == []
    assert sources([run("a", ante=3, finished=False)]) == []  # still being played
    assert sources([run("a", ante=2), run("b", ante=3)]) == ["week:2026-W46:play"]
    g = earned([run("b", ante=5)], set(), T0)[0]
    assert g.run == "b" and g.coins == WEEKLY_COINS and g.reason == "weekly"


def test_runs_that_dont_count_earn_nothing() -> None:
    assert sources([run("a", ante=8, won=True, stake=8, counted=False)]) == []


def test_last_weeks_runs_earn_nothing_but_their_wins_milestones() -> None:
    old = T0 - timedelta(days=7)
    assert sources([run("a", ante=5, ended_at=old)]) == []
    assert sources([run("a", won=True, ante=8, stake=3, ended_at=old)]) == ["deck:b_red", "stake:2", "stake:3"]


def test_a_win() -> None:
    grants = earned([run("w", won=True, ante=8, stake=2, deck="b_blue", finished=False)], set(), T0)
    assert [g.source for g in grants] == ["week:2026-W46:play", "week:2026-W46:win", "deck:b_blue", "stake:2"]
    assert [g.coins for g in grants] == [WEEKLY_COINS, WIN_COINS, WIN_COINS, WIN_COINS]
    # each grant once: what is claimed isn't earned again, and later wins don't repeat milestones
    claimed = {g.source for g in grants}
    later = run("w2", won=True, ante=8, stake=2, deck="b_blue", ended_at=T0 + timedelta(hours=1))
    assert sources([run("w", won=True, ante=8, stake=2, deck="b_blue"), later], claimed) == []


def test_gold_stake_is_worth_most_and_every_stake_below_counts() -> None:
    grants = earned([run("g", won=True, ante=8, stake=8, ended_at=T0 - timedelta(days=30))], set(), T0)
    assert [g.source for g in grants] == ["deck:b_red", *(f"stake:{s}" for s in range(2, 9))]
    assert grants[-1].coins == GOLD_COINS and all(g.coins == WIN_COINS for g in grants[:-1])
