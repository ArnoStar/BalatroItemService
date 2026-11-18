"""An item's condition: how well kept its card is, from 0 (ruined) to 1 (pristine).

Every item gets one when it is made (a booster's card when it is shown, a gift,
an upgrade's prize), drawn from a Kumaraswamy distribution (a = 3, b = 5.2):

    P(condition >= x) = (1 - x**a) ** b

so half the cards are above 50% (the median), 60% or more is 1 in 3.5, a
really good one rare but within reach (80%: 1 in 41; 90%: 1 in 878), and the
best close to impossible (95%: 1 in 24,600; 99%: about 1 in 85 million). Its
inverse is closed-form, so it is drawn from one uniform number (the store's
migration 5 drew the conditions of the items made before this way, and
migration 7 moved them to this distribution, each keeping its rank).

(Until 2026-11-19 it was a = 1.5, b = 5: a median of 26%, 80% 1 in 537.)

An item's value is its value in mint condition times its condition
(value.py); the front ends draw the wear (faded colours, grime, scratches,
frayed edges, a crease) the lower it is.
"""

from __future__ import annotations

from typing import Protocol

CONDITION_A = 3.0
CONDITION_B = 5.2
DIGITS = 6  # a condition is kept to the millionth

# the grades shown with a condition: the lowest condition of each
GRADES: tuple[tuple[float, str], ...] = (
    (0.99, "pristine"), (0.95, "mint"), (0.8, "excellent"), (0.6, "fine"), (0.45, "played"), (0.25, "worn"),
    (0.1, "battered"), (0.0, "ruined"),
)


class Random(Protocol):
    def random(self) -> float: ...


def condition_cdf(x: float) -> float:
    """P(condition <= x)."""
    x = min(1.0, max(0.0, x))
    return float(1.0 - (1.0 - x**CONDITION_A) ** CONDITION_B)


def condition_at(u: float) -> float:
    """The condition whose cdf is ``u`` (0 <= u <= 1): the distribution's inverse."""
    u = min(1.0, max(0.0, u))
    return round(float((1.0 - (1.0 - u) ** (1.0 / CONDITION_B)) ** (1.0 / CONDITION_A)), DIGITS)


def roll_condition(rng: Random) -> float:
    return condition_at(rng.random())


def roll_condition_between(rng: Random, low: float, high: float) -> float:
    """A condition drawn from the distribution, but between ``low`` and ``high`` (an upgrade's prize)."""
    a, b = condition_cdf(low), condition_cdf(high)
    c = condition_at(a + (b - a) * rng.random())
    return min(max(c, round(low, DIGITS)), round(high, DIGITS))


def grade(condition: float) -> str:
    return next(name for floor, name in GRADES if condition >= floor)
