"""The market's rules: prices, selling, taking off."""

from __future__ import annotations

from datetime import timedelta

import pytest

from balatro_items.domain import (
    Edition,
    InvalidListing,
    Item,
    ItemLocked,
    ItemsMoved,
    Kind,
    Listing,
    ListingClosed,
    ListingStatus,
    NotParticipant,
    Rarity,
    check_items,
    check_price,
    sell,
    take_off,
)
from tests.fakes import T0

HOLD = timedelta(days=7)


def item(owner: str = "alice", listed: str | None = "l1") -> Item:
    return Item(id="i1", kind=Kind.CARD, key="S_A", edition=Edition.FOIL, rarity=Rarity.RARE, stake=None, serial=1,
                owner=owner, source="booster", source_run=None, created_at=T0, acquired_at=T0, tradable_at=T0,
                enhancement="m_glass", seal="Red", listed=listed)


def listing() -> Listing:
    return Listing(id="l1", seller="alice", item="i1", price=500, status=ListingStatus.OPEN, created_at=T0,
                   updated_at=T0)


def test_prices() -> None:
    check_price(1)
    check_price(1_000_000_000)
    for bad in (0, -5, 1_000_000_001):
        with pytest.raises(InvalidListing):
            check_price(bad)


def test_a_listed_item_cant_change_hands_otherwise() -> None:
    it = item()
    assert not it.tradable(T0 + timedelta(days=30))
    with pytest.raises(ItemLocked):
        check_items("alice", ["i1"], {"i1": it}, T0, moved=False)
    with pytest.raises(ItemsMoved):
        check_items("alice", ["i1"], {"i1": it}, T0, moved=True)


def test_a_sale_moves_the_item_and_starts_its_hold() -> None:
    x, it = listing(), item()
    later = T0 + timedelta(hours=1)
    assert sell(x, it, "bob", later, HOLD) == "alice"
    assert (x.status, x.buyer, x.updated_at) == (ListingStatus.SOLD, "bob", later)
    assert (it.owner, it.listed, it.acquired_at, it.tradable_at) == ("bob", None, later, later + HOLD)
    with pytest.raises(ListingClosed):
        sell(x, it, "carol", later, HOLD)


def test_what_cant_be_bought() -> None:
    with pytest.raises(InvalidListing):
        sell(listing(), item(), "alice", T0, HOLD)  # one's own
    with pytest.raises(ItemsMoved):
        sell(listing(), item(owner="carol"), "bob", T0, HOLD)
    with pytest.raises(ItemsMoved):
        sell(listing(), None, "bob", T0, HOLD)


def test_taking_off() -> None:
    x, it = listing(), item()
    with pytest.raises(NotParticipant):
        take_off(x, it, "bob", T0)
    take_off(x, it, "alice", T0)
    assert x.status is ListingStatus.CANCELLED and it.listed is None
    with pytest.raises(ListingClosed):
        take_off(x, it, "alice", T0)
