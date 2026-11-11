"""Both stores answer the same (PostgreSQL ones need BALATRO_ITEMS_TEST_DATABASE_URL)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from balatro_items.domain import OFFER_LIFETIME, Edition, Item, Kind, PlayerRecord, Rarity, Trade, TradeStatus, Transfer
from balatro_items.infrastructure.persistence import MemoryStore
from tests.conftest import make_world
from tests.fakes import T0
from tests.tokens import token


@pytest.fixture(params=["memory", "postgres"])
def store(request):  # type: ignore[no-untyped-def]
    return MemoryStore() if request.param == "memory" else request.getfixturevalue("pg")()


def player(pid: str, name: str) -> PlayerRecord:
    return PlayerRecord(id=pid, name=name, has_won=False, showcase=None, created_at=T0)


def item(iid: str, owner: str, key: str = "j_joker", edition: Edition = Edition.BASE, at=T0) -> Item:  # type: ignore[no-untyped-def]
    return Item(id=iid, kind=Kind.JOKER, key=key, edition=edition, rarity=Rarity.COMMON, stake=3, serial=0,
                owner=owner, source="weekly", source_run="r1", created_at=at, acquired_at=at, tradable_at=at)


def test_players(store) -> None:  # type: ignore[no-untyped-def]
    with store.unit() as u:
        u.save_player(player("p1", "Alice"))
        u.save_player(player("p2", "alfred"))
        u.save_player(player("p3", "Bob"))
    with store.unit() as u:
        p = u.player("p1", lock=True)
        assert p is not None and p.name == "Alice" and not p.has_won
        p.has_won, p.showcase, p.synced_at = True, "i1", T0
        u.save_player(p)
        assert [x.id for x in u.find_players("AL", 10)] == ["p2", "p1"]
        assert u.find_players("%", 10) == [] and u.player("nobody") is None
    with store.unit() as u:
        p = u.player("p1")
        assert p is not None and p.has_won and p.showcase == "i1" and p.synced_at == T0


def test_items_serials_and_history(store) -> None:  # type: ignore[no-untyped-def]
    with store.unit() as u:
        u.save_player(player("p1", "Alice"))
        u.save_player(player("p2", "Bob"))
        a = u.add_item(item("i1", "p1"))
        b = u.add_item(item("i2", "p1", at=T0 + timedelta(minutes=1)))
        c = u.add_item(item("i3", "p2", edition=Edition.NEGATIVE))
        assert (a.serial, b.serial, c.serial) == (1, 2, 1)
        assert u.minted("j_joker", Edition.BASE) == 2 and u.minted("j_joker", Edition.FOIL) == 0
        u.add_transfer(Transfer(item="i1", from_owner=None, to_owner="p1", at=T0))
    with store.unit() as u:
        assert [i.id for i in u.items_of("p1")] == ["i2", "i1"]
        got = u.items(["i1", "i3", "nope"], lock=True)
        assert set(got) == {"i1", "i3"} and got["i3"].edition is Edition.NEGATIVE and got["i1"].stake == 3
        it = got["i1"]
        it.owner, it.acquired_at, it.tradable_at = "p2", T0 + timedelta(hours=1), T0 + timedelta(days=7)
        u.save_item(it)
        u.add_transfer(Transfer(item="i1", from_owner="p1", to_owner="p2", at=T0 + timedelta(hours=1), trade="t1"))
    with store.unit() as u:
        i1 = u.item("i1")
        assert i1 is not None and i1.owner == "p2" and i1.tradable_at == T0 + timedelta(days=7)
        assert [(t.from_owner, t.to_owner, t.trade) for t in u.transfers("i1")] == [(None, "p1", None),
                                                                                     ("p1", "p2", "t1")]


def test_claims_are_once(store) -> None:  # type: ignore[no-untyped-def]
    with store.unit() as u:
        assert u.claim("p1", "deck:b_red", "i1", "r1", T0)
        assert not u.claim("p1", "deck:b_red", "i2", "r2", T0)
        assert u.claim("p2", "deck:b_red", "i3", "r3", T0)
    with store.unit() as u:
        assert u.claims("p1") == {"deck:b_red"} and u.claims("nobody") == set()


def test_a_failed_unit_changes_nothing(store) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(RuntimeError), store.unit() as u:
        u.save_player(player("p1", "Alice"))
        raise RuntimeError("boom")
    with store.unit() as u:
        assert u.player("p1") is None


def test_trades(store) -> None:  # type: ignore[no-untyped-def]
    def t(tid: str, sender: str, recipient: str, minutes: int) -> Trade:
        at = T0 + timedelta(minutes=minutes)
        return Trade(id=tid, sender=sender, recipient=recipient, give=("i1",), take=("i2", "i3"), message="hi",
                     status=TradeStatus.PENDING, created_at=at, updated_at=at, expires_at=at + OFFER_LIFETIME)

    with store.unit() as u:
        u.add_trade(t("t1", "p1", "p2", 0))
        u.add_trade(t("t2", "p2", "p1", 1))
        u.add_trade(t("t3", "p1", "p3", 2))
    with store.unit() as u:
        assert [x.id for x in u.trades_of("p1", "all", 10)] == ["t3", "t2", "t1"]
        assert [x.id for x in u.trades_of("p1", "incoming", 10)] == ["t2"]
        assert [x.id for x in u.trades_of("p1", "outgoing", 1)] == ["t3"]
        assert u.pending_from("p1", T0) == 2 and u.pending_from("p1", T0 + OFFER_LIFETIME + timedelta(hours=1)) == 0
        x = u.trade("t1", lock=True)
        assert x is not None and x.take == ("i2", "i3") and x.message == "hi"
        x.close(TradeStatus.DECLINED, T0 + timedelta(hours=1))
        u.save_trade(x)
    with store.unit() as u:
        x = u.trade("t1")
        assert x is not None and x.status is TradeStatus.DECLINED and u.pending_from("p1", T0) == 1


def test_the_whole_service_on_postgres(pg) -> None:  # type: ignore[no-untyped-def]
    w = make_world(store=pg())
    alice = {"Authorization": f"Bearer {token(sub='alice', name='Alice')}"}
    w.runs.add("alice", "r1", won=True, ante=8, stake=3, at=w.clock.now())
    w.clock.advance(seconds=10)
    found = w.client.post("/v1/me/drops", headers=alice).json()["found"]
    assert sorted(i["source"] for i in found) == ["first_deck_win", "first_stake_win", "first_stake_win", "weekly",
                                                   "weekly_win"]
    w.clock.advance(seconds=10)
    assert w.client.post("/v1/me/drops", headers=alice).json()["found"] == []
    assert len(w.client.get("/v1/me/items", headers=alice).json()) == 5
