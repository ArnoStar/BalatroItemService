"""Offers and how items change hands."""

from __future__ import annotations

from datetime import timedelta

import pytest

from balatro_items.domain import (
    OFFER_LIFETIME,
    Edition,
    InvalidTrade,
    Item,
    ItemLocked,
    ItemsMoved,
    Kind,
    NotOwner,
    Rarity,
    Trade,
    TradeClosed,
    TradeStatus,
    check_items,
    check_offer,
    swap,
)
from tests.fakes import T0

HOLD = timedelta(days=7)


def item(item_id: str, owner: str, tradable_at=T0) -> Item:  # type: ignore[no-untyped-def]
    return Item(id=item_id, kind=Kind.JOKER, key="j_joker", edition=Edition.BASE, rarity=Rarity.COMMON, stake=None,
                serial=1, owner=owner, source="weekly", source_run=None, created_at=T0, acquired_at=T0,
                tradable_at=tradable_at)


def trade(give: tuple[str, ...] = ("a1",), take: tuple[str, ...] = ("b1",)) -> Trade:
    return Trade(id="t", sender="alice", recipient="bob", give=give, take=take, message="", status=TradeStatus.PENDING,
                 created_at=T0, updated_at=T0, expires_at=T0 + OFFER_LIFETIME)


def test_offers() -> None:
    check_offer("alice", "bob", ["a1"], [], "")
    check_offer("alice", "bob", [], ["b1"], "a request")
    for args in (("alice", "alice", ["a1"], []), ("alice", "bob", [], []), ("alice", "bob", ["a1", "a1"], []),
                 ("alice", "bob", [f"x{i}" for i in range(11)], [])):
        with pytest.raises(InvalidTrade):
            check_offer(*args, "")  # type: ignore[arg-type]
    with pytest.raises(InvalidTrade):
        check_offer("alice", "bob", ["a1"], [], "x" * 281)


def test_items_must_be_theirs_and_out_of_their_hold() -> None:
    items = {"a1": item("a1", "alice"), "a2": item("a2", "alice", T0 + timedelta(days=1))}
    check_items("alice", ["a1"], items, T0, moved=False)
    with pytest.raises(NotOwner):
        check_items("bob", ["a1"], items, T0, moved=False)
    with pytest.raises(NotOwner):
        check_items("alice", ["nope"], items, T0, moved=False)
    with pytest.raises(ItemLocked):
        check_items("alice", ["a2"], items, T0, moved=False)


def test_swap_moves_everything_and_starts_the_hold() -> None:
    items = {"a1": item("a1", "alice"), "b1": item("b1", "bob")}
    t = trade()
    later = T0 + timedelta(hours=1)
    moved = swap(t, items, later, HOLD)
    assert sorted((i.id, before, i.owner) for i, before in moved) == [("a1", "alice", "bob"), ("b1", "bob", "alice")]
    assert all(i.tradable_at == later + HOLD and i.acquired_at == later for i in items.values())
    assert t.status is TradeStatus.ACCEPTED
    with pytest.raises(TradeClosed):
        t.close(TradeStatus.DECLINED, later)


def test_nothing_moves_when_an_item_has() -> None:
    items = {"a1": item("a1", "carol"), "b1": item("b1", "bob")}
    t = trade()
    with pytest.raises(ItemsMoved):
        swap(t, items, T0, HOLD)
    assert items["b1"].owner == "bob" and t.status is TradeStatus.PENDING


def test_offers_expire() -> None:
    t = trade()
    assert t.status_at(T0 + OFFER_LIFETIME - timedelta(seconds=1)) is TradeStatus.PENDING
    assert t.status_at(T0 + OFFER_LIFETIME) is TradeStatus.EXPIRED
    with pytest.raises(TradeClosed):
        swap(t, {"a1": item("a1", "alice"), "b1": item("b1", "bob")}, T0 + OFFER_LIFETIME, HOLD)
