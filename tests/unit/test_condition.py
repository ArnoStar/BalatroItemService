"""An item's condition (how well kept its card is) and its value (its card, upgrades and condition)."""

from __future__ import annotations

from balatro_items.domain import (
    Edition,
    Kind,
    Rarity,
    condition_at,
    condition_cdf,
    grade,
    mint_value,
    roll_condition,
    roll_condition_between,
    worth,
)
from tests.fakes import rng


def test_good_conditions_are_rare_and_the_best_close_to_impossible() -> None:
    r = rng(4)
    rolls = [roll_condition(r) for _ in range(200_000)]
    assert all(0 <= c <= 1 for c in rolls)
    share = lambda x: sum(1 for c in rolls if c >= x) / len(rolls)  # noqa: E731
    assert 0.24 < sorted(rolls)[len(rolls) // 2] < 0.27  # most cards are worn
    assert 0.04 < share(0.6) < 0.048  # good: 1 in 23
    assert 0.0012 < share(0.8) < 0.0026  # really good: 1 in 537
    assert share(0.95) <= 5 / len(rolls)  # the best: 1 in 449,000
    # the published odds
    assert abs((1 - condition_cdf(0.6)) - 0.0439) < 0.001
    assert 1 / (1 - condition_cdf(0.95)) > 400_000


def test_the_inverse_and_a_condition_within_bounds() -> None:
    for c in (0.0, 0.1, 0.256, 0.6, 0.93):
        assert abs(condition_at(condition_cdf(c)) - c) < 1e-5
    r = rng(1)
    for _ in range(500):
        c = roll_condition_between(r, 0.7, 0.72)
        assert 0.7 <= c <= 0.72


def test_grades() -> None:
    assert [grade(c) for c in (0.0, 0.05, 0.2, 0.3, 0.5, 0.7, 0.9, 0.97, 0.995, 1.0)] == [
        "ruined", "ruined", "battered", "worn", "played", "fine", "excellent", "mint", "pristine", "pristine"]


def test_values_follow_the_card_its_upgrades_and_its_condition() -> None:
    joker = mint_value(Kind.JOKER, Rarity.COMMON, Edition.BASE)
    assert joker == 150
    assert mint_value(Kind.JOKER, Rarity.COMMON, Edition.FOIL) == 3 * joker
    assert mint_value(Kind.JOKER, Rarity.LEGENDARY, Edition.NEGATIVE) == 300_000
    assert mint_value(Kind.PLANET, Rarity.COMMON, Edition.NEGATIVE) == 40 * 60  # a negative consumable: rarer still
    plain = mint_value(Kind.CARD, Rarity.COMMON, Edition.BASE)
    glass_red = mint_value(Kind.CARD, Rarity.RARE, Edition.POLYCHROME, "m_glass", "Red")
    assert plain == 30 and glass_red == round(400 * 10 * 1.35 * 1.4)
    rare = mint_value(Kind.JOKER, Rarity.RARE, Edition.BASE)
    assert mint_value(Kind.JOKER, Rarity.RARE, Edition.BASE, stake=8) > rare
    assert worth(1500, 0.5) == 750 and worth(150, 0.001) == 1  # (at least a coin)
