"""The upgrade's rules: its chance, the prize's range, the prizes and the roll."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from balatro_items.domain import (
    InvalidBet,
    Pools,
    chance_ppm,
    check_multiplier,
    pick_prize,
    prize_range,
    prizes,
    upgrade_roll,
    worth,
)
from tests.fakes import FakeCatalog, rng


def test_the_chance_is_95_percent_over_the_multiplier() -> None:
    assert chance_ppm(1) == 950_000
    assert chance_ppm(2) == 475_000  # an item worth 100 aimed at x2: 47.5%
    assert chance_ppm(100) == 9_500
    for bad in (0.99, 100.01, float("nan"), float("inf")):
        with pytest.raises(InvalidBet):
            check_multiplier(bad)
    assert check_multiplier(2.345) == 2.35


def test_the_prize_is_worth_the_target_5_percent_more_or_less() -> None:
    assert prize_range(100, 2) == (200, 190, 210)
    assert prize_range(37, 1.5) == (56, 54, 58)
    assert prize_range(1, 1) == (1, 1, 1)


def test_prizes_are_in_the_range_and_as_likely_as_cards_are() -> None:
    pools = Pools(FakeCatalog().templates())
    r = rng(3)
    for value, m in ((100, 2), (40, 1), (500, 10), (30, 3.5)):
        _, low, high = prize_range(value, m)
        found = prizes(pools, low, high)
        assert found
        for _ in range(200):
            prize, condition = pick_prize(found, r)
            assert prize.low <= condition <= prize.high
            assert low <= worth(prize.mint, condition) <= high
    # nothing is worth a billion
    assert prizes(pools, 950_000_000, 1_050_000_000) == []


def test_the_roll_is_the_casinos_on_a_million() -> None:
    server, seed = "s" * 64, "mine"
    h = int(hmac.new(server.encode(), b"up1:mine", hashlib.sha256).hexdigest()[:13], 16)
    assert upgrade_roll(server, "up1", seed) == h * 1_000_000 // 16**13
