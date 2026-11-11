"""Both stores answer the same (PostgreSQL ones need BALATRO_ITEMS_TEST_DATABASE_URL)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from balatro_items.domain import (
    OFFER_LIFETIME,
    Edition,
    Entry,
    Game,
    GameStatus,
    Item,
    Kind,
    Mode,
    PlayerRecord,
    Rarity,
    Side,
    Trade,
    TradeStatus,
    Transfer,
)
from balatro_items.infrastructure.persistence import MemoryStore
from tests.api.test_casino import ALICE, BOB, check_draw, gift, out_of_hold, ready
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


def test_staked_items_and_games_won(store) -> None:  # type: ignore[no-untyped-def]
    with store.unit() as u:
        u.save_player(player("p1", "Alice"))
        u.add_item(item("i1", "p1"))
    with store.unit() as u:
        it = u.items(["i1"], lock=True)["i1"]
        assert it.staked is None
        it.staked = "g1"
        u.save_item(it)
        u.add_transfer(Transfer(item="i1", from_owner="p2", to_owner="p1", at=T0, game="g1"))
    with store.unit() as u:
        i1 = u.item("i1")
        assert i1 is not None and i1.staked == "g1" and not i1.tradable(T0 + timedelta(days=30))
        assert [(t.trade, t.game) for t in u.transfers("i1")] == [(None, "g1")]
        assert u.items_of("p1")[0].staked == "g1"


def test_casino_games(store) -> None:  # type: ignore[no-untyped-def]
    def entry(p: str, *items: str, minutes: int = 0) -> Entry:
        return Entry(player=p, items=items, value=100 * len(items), seed=f"seed-{p}",
                     at=T0 + timedelta(minutes=minutes))

    def game(gid: str, mode: Mode, *entries: Entry, minutes: int = 0) -> Game:
        at = T0 + timedelta(minutes=minutes)
        return Game(id=gid, mode=mode, status=GameStatus.OPEN, side=Side.MULT if mode is Mode.COINFLIP else None,
                    entries=list(entries), server_seed=f"secret-{gid}", created_at=at, updated_at=at)

    with store.unit() as u:
        assert u.open_jackpot(lock=True) is None
        u.add_game(game("g1", Mode.COINFLIP, entry("p1", "i1", "i2")))
        jackpot = game("g2", Mode.JACKPOT, entry("p1", "i3"), entry("p2", "i4", minutes=1), minutes=1)
        jackpot.closes_at = T0 + timedelta(minutes=2)
        u.add_game(jackpot)
        done = game("g3", Mode.COINFLIP, entry("p2", "i5"), entry("p3", "i6"), minutes=2)
        done.status, done.roll, done.winner = GameStatus.DONE, 150, "p3"
        u.add_game(done)
    with store.unit() as u:
        g1 = u.game("g1", lock=True)
        assert g1 is not None and g1.side is Side.MULT and g1.server_seed == "secret-g1" and g1.closes_at is None
        assert g1.entries == [entry("p1", "i1", "i2")] and g1.value == 200 and g1.roll is None
        assert u.game("nope") is None
        assert [g.id for g in u.games(Mode.COINFLIP, GameStatus.OPEN, None, 10)] == ["g1"]
        assert [g.id for g in u.games(Mode.COINFLIP, GameStatus.OPEN, "p1", 10)] == ["g1"]
        assert u.games(Mode.COINFLIP, GameStatus.OPEN, "p2", 10) == []
        assert [g.id for g in u.games(None, GameStatus.DONE, "p3", 10)] == ["g3"]
        j = u.open_jackpot(lock=True)
        assert j is not None and j.id == "g2" and j.players == ["p1", "p2"] and j.closes_at == T0 + timedelta(minutes=2)
        j.entries.append(entry("p1", "i7", minutes=3))
        j.status, j.roll, j.winner, j.updated_at = GameStatus.DONE, 42, "p1", T0 + timedelta(minutes=3)
        u.save_game(j)
    with store.unit() as u:
        assert u.open_jackpot() is None
        j = u.game("g2")
        assert j is not None and j.status is GameStatus.DONE and (j.roll, j.winner) == (42, "p1")
        assert len(j.entries) == 3
        assert [g.id for g in u.games(None, GameStatus.DONE, None, 10)] == ["g2", "g3"]
        assert [g.id for g in u.games(Mode.JACKPOT, GameStatus.DONE, "p2", 1)] == ["g2"]


def test_the_casino_on_postgres(pg) -> None:  # type: ignore[no-untyped-def]
    w = make_world(store=pg())
    c = w.client
    ready(w)
    a, b, a2, b2 = gift(w, "alice"), gift(w, "bob", "j_greedy_joker"), gift(w, "alice"), gift(w, "bob")
    out_of_hold(w)
    flip = c.post("/v1/casino/coinflips", headers=ALICE, json={"items": [a]}).json()
    done = c.post(f"/v1/casino/coinflips/{flip['id']}/join", headers=BOB, json={"items": [b]}).json()
    check_draw(done)
    assert {c.get(f"/v1/items/{i}", headers=BOB).json()["item"]["owner"] for i in (a, b)} == {done["winner"]}
    c.post("/v1/casino/jackpot", headers=ALICE, json={"items": [a2]})
    pot = c.post("/v1/casino/jackpot", headers=BOB, json={"items": [b2]}).json()
    w.clock.advance(seconds=61)
    last = c.get("/v1/casino/jackpot", headers=ALICE).json()["last"]
    assert last["id"] == pot["id"]
    check_draw(last)
    assert [g["id"] for g in c.get("/v1/casino/games?player=alice", headers=BOB).json()] == [pot["id"], done["id"]]
