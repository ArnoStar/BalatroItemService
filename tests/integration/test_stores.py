"""Both stores answer the same (PostgreSQL ones need BALATRO_ITEMS_TEST_DATABASE_URL)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from psycopg.types.json import Jsonb

from balatro_items.application.dto import ListingQuery
from balatro_items.domain import (
    OFFER_LIFETIME,
    Choice,
    Edition,
    Entry,
    Game,
    GameStatus,
    Item,
    Kind,
    Listing,
    ListingStatus,
    Mode,
    NotEnoughCoins,
    Pack,
    PackStatus,
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
                owner=owner, source="weekly", source_run="r1", created_at=at, acquired_at=at, tradable_at=at,
                condition=0.25)


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
        assert u.claim("p1", "deck:b_red", "r1", T0, 250)
        assert not u.claim("p1", "deck:b_red", "r2", T0, 250)
        assert u.claim("p2", "deck:b_red", "r3", T0, 250)
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
    earned = w.client.post("/v1/me/drops", headers=alice).json()["earned"]
    assert sorted(e["reason"] for e in earned) == ["first_deck_win", "first_stake_win", "first_stake_win", "weekly",
                                                    "weekly_win"]
    w.clock.advance(seconds=10)
    assert w.client.post("/v1/me/drops", headers=alice).json()["earned"] == []
    assert w.client.get("/v1/me", headers=alice).json()["coins"] == 1100
    for booster in ("card_boosted_mega", "spectral_standard_jumbo", "joker_standard_normal"):
        pack = w.client.post(f"/v1/boosters/{booster}/buy", headers=alice).json()
        r = w.client.post(f"/v1/packs/{pack['id']}/choose", headers=alice, json={"picks": list(range(pack["picks"]))})
        assert r.status_code == 200, r.text
    items = w.client.get("/v1/me/items", headers=alice).json()
    assert len(items) == 4 and {i["kind"] for i in items} == {"card", "spectral", "joker"}
    assert w.client.get("/v1/me", headers=alice).json()["coins"] == 1100 - 500 - 90 - 100


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
        # a period, and the page before a game
        later = T0 + timedelta(minutes=3)
        assert [g.id for g in u.games(None, GameStatus.DONE, None, 10, since=later)] == ["g2"]
        assert [g.id for g in u.games(None, GameStatus.DONE, None, 10, before=later)] == ["g3"]
        # a dice game, a challenge
        dice = game("g4", Mode.DICE, entry("p1", "i8"), minutes=4)
        dice.chance, dice.opponent = 15, "p2"
        u.add_game(dice)
    with store.unit() as u:
        d = u.game("g4")
        assert d is not None and d.mode is Mode.DICE and (d.chance, d.opponent, d.side) == (15, "p2", None)
        assert d.asked == 15 and u.game("g1").asked == 50  # type: ignore[union-attr]
        assert [g.id for g in u.games(Mode.DICE, GameStatus.OPEN, None, 10)] == ["g4"]


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
    assert c.get("/v1/casino/players/alice/stats", headers=BOB).json()["games"] == 2
    assert c.get("/v1/casino/leaderboard?period=day", headers=BOB).json()["games"] == 2
    check_draw(last)
    assert [g["id"] for g in c.get("/v1/casino/games?player=alice", headers=BOB).json()] == [pot["id"], done["id"]]


def test_coins_and_their_history(store) -> None:  # type: ignore[no-untyped-def]
    with store.unit() as u:
        u.save_player(player("p1", "Alice"))
        assert u.add_coins("p1", 250, "weekly_win", "week:2026-W46:win", T0) == 250
        assert u.add_coins("p1", -100, "booster", "pack1", T0 + timedelta(minutes=1)) == 150
    with pytest.raises(NotEnoughCoins), store.unit() as u:
        u.add_coins("p1", -151, "booster", "pack2", T0)
    with store.unit() as u:
        p = u.player("p1")
        assert p is not None and p.coins == 150
        p.name = "Alicia"
        u.save_player(p)  # (saving a player never changes their coins)
        p.coins = 9999
        u.save_player(p)
        assert [(m.amount, m.balance, m.reason, m.ref) for m in u.coin_moves("p1", 10)] == [
            (-100, 150, "booster", "pack1"), (250, 250, "weekly_win", "week:2026-W46:win")]
    with store.unit() as u:
        p = u.player("p1")
        assert p is not None and p.coins == 150 and p.name == "Alicia"


def test_playing_cards_are_numbered_by_their_upgrades(store) -> None:  # type: ignore[no-untyped-def]
    def card(iid: str, enhancement: str | None, seal: str | None) -> Item:
        it = item(iid, "p1", key="S_A")
        it.kind, it.enhancement, it.seal = Kind.CARD, enhancement, seal
        return it

    with store.unit() as u:
        u.save_player(player("p1", "Alice"))
        serials = [u.add_item(card(f"i{n}", e, s)).serial
                   for n, (e, s) in enumerate([(None, None), ("m_glass", None), ("m_glass", "Red"), (None, None),
                                               ("m_glass", "Red")])]
        assert serials == [1, 1, 1, 2, 2]
        assert u.minted("S_A", Edition.BASE) == 2 and u.minted("S_A+m_glass+Red", Edition.BASE) == 2
        assert u.minted("S_A+m_glass", Edition.BASE) == 1
    with store.unit() as u:
        it = u.item("i2")
        assert it is not None and (it.enhancement, it.seal, it.variant) == ("m_glass", "Red", "S_A+m_glass+Red")
        assert it.condition == 0.25


def test_packs(store) -> None:  # type: ignore[no-untyped-def]
    choices = [Choice(kind=Kind.CARD, key="S_A", rarity=Rarity.RARE, edition=Edition.FOIL, enhancement="m_gold",
                      seal="Blue", condition=0.123456),
               Choice(kind=Kind.CARD, key="H_K", rarity=Rarity.COMMON, edition=Edition.BASE)]
    with store.unit() as u:
        u.add_pack(Pack(id="k1", owner="p1", booster="card_standard_normal", price=100, picks=1, choices=choices,
                        status=PackStatus.OPEN, created_at=T0))
        u.add_pack(Pack(id="k2", owner="p1", booster="joker_standard_normal", price=100, picks=1, choices=[],
                        status=PackStatus.OPEN, created_at=T0 + timedelta(minutes=1)))
    with store.unit() as u:
        k = u.pack("k1", lock=True)
        assert k is not None and k.choices == choices and k.status is PackStatus.OPEN and k.opened_at is None
        k.status, k.chosen, k.items, k.opened_at = PackStatus.OPENED, (0,), ("i9",), T0
        u.save_pack(k)
        assert u.pack("nope") is None
    with store.unit() as u:
        k = u.pack("k1")
        assert k is not None and (k.status, k.chosen, k.items, k.opened_at) == (PackStatus.OPENED, (0,), ("i9",), T0)
        assert [x.id for x in u.packs_of("p1", PackStatus.OPEN, 10)] == ["k2"]
        assert [x.id for x in u.packs_of("p1", None, 10)] == ["k2", "k1"] and u.packs_of("p2", None, 10) == []


def test_listings(store) -> None:  # type: ignore[no-untyped-def]
    def listing(lid: str, seller: str, iid: str, price: int, minutes: int) -> Listing:
        at = T0 + timedelta(minutes=minutes)
        return Listing(id=lid, seller=seller, item=iid, price=price, status=ListingStatus.OPEN, created_at=at,
                       updated_at=at)

    with store.unit() as u:
        u.save_player(player("p1", "Alice"))
        u.save_player(player("p2", "Bob"))
        u.add_item(item("i1", "p1"))
        u.add_item(item("i2", "p1", key="j_blueprint", edition=Edition.NEGATIVE))
        card = item("i3", "p2", key="S_A")
        card.kind, card.enhancement, card.rarity = Kind.CARD, "m_glass", Rarity.UNCOMMON
        u.add_item(card)
        u.add_listing(listing("l1", "p1", "i1", 50, 0))
        u.add_listing(listing("l2", "p1", "i2", 900, 1))
        u.add_listing(listing("l3", "p2", "i3", 300, 2))
    with store.unit() as u:
        def ids(**kw: object) -> list[str]:
            return [x.id for x in u.listings(ListingQuery(**kw))]  # type: ignore[arg-type]

        assert ids() == ["l3", "l2", "l1"]
        assert ids(sort="price") == ["l1", "l3", "l2"] and ids(sort="-price") == ["l2", "l3", "l1"]
        assert ids(sort="price", limit=1, offset=1) == ["l3"]
        assert ids(kind=Kind.CARD) == ["l3"] and ids(edition=Edition.NEGATIVE) == ["l2"]
        assert ids(rarity=Rarity.UNCOMMON) == ["l3"] and ids(keys=("j_joker", "S_A")) == ["l3", "l1"]
        assert ids(variant="S_A+m_glass") == ["l3"] and ids(variant="S_A") == []
        assert ids(seller="p1") == ["l2", "l1"] and u.open_listings_of("p1") == 2
        x = u.listing("l1", lock=True)
        assert x is not None and x.price == 50 and x.buyer is None
        x.status, x.buyer, x.updated_at = ListingStatus.SOLD, "p2", T0 + timedelta(hours=1)
        u.save_listing(x)
    with store.unit() as u:
        assert [x.id for x in u.listings(ListingQuery(status=ListingStatus.SOLD, buyer="p2"))] == ["l1"]
        assert [x.id for x in u.listings(ListingQuery(status=None, player="p2"))] == ["l1", "l3"]
        assert u.open_listings_of("p1") == 1
        u.add_listing(listing("l4", "p1", "i1", 70, 5))  # (sold: it may be listed again)


def test_migration_4_gives_the_tags_back_in_coins(pg) -> None:  # type: ignore[no-untyped-def]
    """A database of the tags' time (migrations 1 to 3): every tag leaves, its owner gets its value in coins, its open
    game is called off and its pending offers cancelled."""
    import psycopg
    from psycopg import sql as pgsql

    from balatro_items.infrastructure.persistence import postgres
    from tests.conftest import PG_URL

    store = pg()  # (the test's schema, migrated: start again from migration 3)
    with store._pool.connection() as conn:
        search_path = conn.execute("SHOW search_path").fetchone()["search_path"]  # type: ignore[index]
    store.close()
    with psycopg.connect(PG_URL, autocommit=True) as conn:  # type: ignore[arg-type]
        conn.execute(pgsql.SQL("SET search_path TO {}").format(pgsql.SQL(search_path)))
        for table in ("schema_migrations", "players", "serials", "items", "transfers", "claims", "trades", "games",
                      "coin_moves", "packs", "listings", "upgrades"):
            conn.execute(pgsql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(pgsql.Identifier(table)))
        conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL "
                     "DEFAULT now())")
        for version, script in enumerate(postgres.MIGRATIONS[:3], 1):
            conn.execute(script.encode())
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
        conn.execute(
            "INSERT INTO players (id, name, has_won, showcase, created_at) VALUES "
            "('p1', 'Alice', true, 't1', %(t)s), ('p2', 'Bob', true, null, %(t)s), ('p3', 'Cy', false, null, %(t)s)",
            {"t": T0})
        rows = [("t1", "tag", "tag_negative", "negative", 3, "p1"), ("t2", "tag", "tag_economy", "base", 1, "p1"),
                ("t3", "tag", "tag_foil", "foil", 2, "p2"), ("j1", "joker", "j_joker", "base", 1, "p2"),
                ("j2", "joker", "j_mime", "foil", 2, "p1"), ("j3", "joker", "j_dna", "base", 3, "p3")]
        for n, (iid, kind, key, edition, rarity, owner) in enumerate(rows):
            conn.execute("INSERT INTO items (id, kind, key, edition, rarity, serial, owner, source, created_at, "
                         "acquired_at, tradable_at) VALUES (%s, %s, %s, %s, %s, %s, %s, 'weekly', %s, %s, %s)",
                         (iid, kind, key, edition, rarity, n + 1, owner, T0, T0, T0))
            conn.execute("INSERT INTO transfers (item, from_owner, to_owner, at) VALUES (%s, null, %s, %s)",
                         (iid, owner, T0))
        # a coinflip with Bob's tag and Alice's joker, open; another of jokers only, open
        conn.execute("INSERT INTO games (id, mode, status, entries, players, server_seed, created_at, updated_at) "
                     "VALUES ('g1', 'coinflip', 'open', '[]', '{p2,p1}', 's', %(t)s, %(t)s), "
                     "('g2', 'coinflip', 'open', '[]', '{p3}', 's', %(t)s, %(t)s)", {"t": T0})
        conn.execute("UPDATE items SET staked = 'g1' WHERE id IN ('t3', 'j2')")
        conn.execute("UPDATE items SET staked = 'g2' WHERE id = 'j3'")
        conn.execute("INSERT INTO trades (id, sender, recipient, give, take, message, status, created_at, updated_at, "
                     "expires_at) VALUES ('tr1', 'p1', 'p2', '{t2}', '{j1}', '', 'pending', %(t)s, %(t)s, %(t)s), "
                     "('tr2', 'p2', 'p3', '{j1}', '{}', '', 'pending', %(t)s, %(t)s, %(t)s)", {"t": T0})
        conn.execute("INSERT INTO claims (owner, source, item, run, at) VALUES ('p1', 'deck:b_red', 't1', 'r1', %s)",
                     (T0,))
    store = postgres.PostgresStore(PG_URL, schema=search_path.strip('"'))  # type: ignore[arg-type]
    try:
        with store.unit() as u:
            assert [i.id for i in u.items_of("p1")] == ["j2"] and [i.id for i in u.items_of("p2")] == ["j1"]
            assert u.item("t1") is None and u.transfers("t1") == []
            alice, bob, cy = u.player("p1"), u.player("p2"), u.player("p3")
            assert alice is not None and bob is not None and cy is not None
            assert (alice.coins, bob.coins, cy.coins) == (58963 + 178, 1990, 0)
            assert alice.showcase is None
            assert sorted((m.amount, m.ref) for m in u.coin_moves("p1", 10)) == [
                (178, "tag_economy:base"), (58963, "tag_negative:negative")]
            assert u.coin_moves("p1", 10)[0].balance == 58963 + 178 and u.coin_moves("p2", 10)[0].reason == "tag_refund"
            g1, g2 = u.game("g1"), u.game("g2")
            assert g1 is not None and g1.status is GameStatus.CANCELLED
            assert g2 is not None and g2.status is GameStatus.OPEN
            assert u.item("j2").staked is None and u.item("j3").staked == "g2"  # type: ignore[union-attr]
            t1, t2 = u.trade("tr1"), u.trade("tr2")
            assert t1 is not None and t1.status is TradeStatus.CANCELLED
            assert t2 is not None and t2.status is TradeStatus.PENDING
            assert u.claims("p1") == {"deck:b_red"}
            # migration 5: every item of before has a condition, at random
            conditions = [i.condition for p in ("p1", "p2", "p3") for i in u.items_of(p)]
            assert conditions and all(0 <= c <= 1 for c in conditions)
    finally:
        store.close()


def test_migration_7_moves_the_conditions_of_before_keeping_their_rank(pg) -> None:  # type: ignore[no-untyped-def]
    """Conditions drawn on the old curve (a = 1.5, b = 5) move to the kinder one (a = 3, b = 5.2): the old median
    becomes the new one, and the order stays."""
    import psycopg
    from psycopg import sql as pgsql

    from balatro_items.infrastructure.persistence import postgres
    from tests.conftest import PG_URL

    store = pg()
    with store._pool.connection() as conn:
        search_path = conn.execute("SHOW search_path").fetchone()["search_path"]  # type: ignore[index]
    store.close()
    with psycopg.connect(PG_URL, autocommit=True) as conn:  # type: ignore[arg-type]
        conn.execute(pgsql.SQL("SET search_path TO {}").format(pgsql.SQL(search_path)))
        conn.execute("INSERT INTO players (id, name, has_won, showcase, created_at) VALUES ('p1', 'A', true, null, %s)",
                     (T0,))
        old = {"i0": 0.0, "i1": 0.1, "i2": 0.256, "i3": 0.6, "i4": 0.8, "i5": 1.0}
        for iid, c in old.items():
            conn.execute("INSERT INTO items (id, kind, key, edition, rarity, serial, owner, source, created_at, "
                         "acquired_at, tradable_at, condition) VALUES (%s, 'joker', 'j_joker', 'base', 1, %s, 'p1', "
                         "'gift', %s, %s, %s, %s)", (iid, int(iid[1:]) + 1, T0, T0, T0, c))
        conn.execute("INSERT INTO packs (id, owner, booster, price, picks, choices, status, created_at) VALUES "
                     "('k1', 'p1', 'joker_standard_normal', 100, 1, %s, 'open', %s)",
                     (Jsonb([{"kind": "joker", "key": "j_joker", "rarity": 1, "edition": "base", "condition": 0.256},
                             {"kind": "joker", "key": "j_mime", "rarity": 2, "edition": "base"}]), T0))
        conn.execute(postgres.MIGRATIONS[6].encode())  # (migration 7 alone: 8 draws them all again after it)
    store = postgres.PostgresStore(PG_URL, schema=search_path.strip('"'))  # type: ignore[arg-type]
    try:
        with store.unit() as u:
            new = {iid: u.item(iid).condition for iid in old}  # type: ignore[union-attr]
            assert new["i0"] == 0.0 and new["i5"] == 1.0
            assert abs(new["i2"] - 0.5) < 0.001  # the old median is the new one
            assert sorted(new, key=new.__getitem__) == list(old)  # the order stays
            assert all(new[i] >= old[i] for i in old)  # kinder
            pack = u.pack("k1")
            assert pack is not None and abs(pack.choices[0].condition - 0.5) < 0.001  # type: ignore[operator]
            assert pack.choices[1].condition is None
    finally:
        store.close()


def test_migration_8_draws_every_items_condition_again(pg) -> None:  # type: ignore[no-untyped-def]
    """Every item gets a new condition, drawn on the curve of then (a = 3, b = 5.2: a median of 50%)."""
    import psycopg
    from psycopg import sql as pgsql

    from balatro_items.infrastructure.persistence import postgres
    from tests.conftest import PG_URL

    store = pg()
    with store._pool.connection() as conn:
        search_path = conn.execute("SHOW search_path").fetchone()["search_path"]  # type: ignore[index]
    store.close()
    with psycopg.connect(PG_URL, autocommit=True) as conn:  # type: ignore[arg-type]
        conn.execute(pgsql.SQL("SET search_path TO {}").format(pgsql.SQL(search_path)))
        conn.execute("INSERT INTO players (id, name, has_won, showcase, created_at) VALUES ('p1', 'A', true, null, %s)",
                     (T0,))
        for n in range(1000):
            conn.execute("INSERT INTO items (id, kind, key, edition, rarity, serial, owner, source, created_at, "
                         "acquired_at, tradable_at, condition) VALUES (%s, 'joker', 'j_joker', 'base', 1, %s, 'p1', "
                         "'gift', %s, %s, %s, 0.123456)", (f"i{n}", n + 1, T0, T0, T0))
        conn.execute(postgres.MIGRATIONS[7].encode())  # (migration 8 alone: 9 moves them all after it)
    store = postgres.PostgresStore(PG_URL, schema=search_path.strip('"'))  # type: ignore[arg-type]
    try:
        with store.unit() as u:
            conditions = sorted(i.condition for i in u.items_of("p1"))
            assert len(conditions) == 1000 and 0.123456 not in conditions
            assert all(0 <= c <= 1 for c in conditions)
            assert 0.45 < conditions[500] < 0.55  # the median: 50%
            assert len(set(conditions)) > 990  # each its own
    finally:
        store.close()


def test_migration_9_moves_the_conditions_a_bit_kinder_keeping_their_rank(pg) -> None:  # type: ignore[no-untyped-def]
    """Conditions drawn on the curve of before (a = 3, b = 5.2) move to the kinder one (a = 3.5, b = 5): the old
    median (50%) becomes the new one (56%), and the order stays."""
    import psycopg
    from psycopg import sql as pgsql

    from balatro_items.domain import condition_at
    from balatro_items.infrastructure.persistence import postgres
    from tests.conftest import PG_URL

    store = pg()
    with store._pool.connection() as conn:
        search_path = conn.execute("SHOW search_path").fetchone()["search_path"]  # type: ignore[index]
    store.close()
    with psycopg.connect(PG_URL, autocommit=True) as conn:  # type: ignore[arg-type]
        conn.execute(pgsql.SQL("SET search_path TO {}").format(pgsql.SQL(search_path)))
        conn.execute("INSERT INTO players (id, name, has_won, showcase, created_at) VALUES ('p1', 'A', true, null, %s)",
                     (T0,))
        old = {"i0": 0.0, "i1": 0.1, "i2": 0.5, "i3": 0.6, "i4": 0.8, "i5": 1.0}
        for iid, c in old.items():
            conn.execute("INSERT INTO items (id, kind, key, edition, rarity, serial, owner, source, created_at, "
                         "acquired_at, tradable_at, condition) VALUES (%s, 'joker', 'j_joker', 'base', 1, %s, 'p1', "
                         "'gift', %s, %s, %s, %s)", (iid, int(iid[1:]) + 1, T0, T0, T0, c))
        conn.execute("INSERT INTO packs (id, owner, booster, price, picks, choices, status, created_at) VALUES "
                     "('k1', 'p1', 'joker_standard_normal', 100, 1, %s, 'open', %s)",
                     (Jsonb([{"kind": "joker", "key": "j_joker", "rarity": 1, "edition": "base", "condition": 0.5},
                             {"kind": "joker", "key": "j_mime", "rarity": 2, "edition": "base"}]), T0))
        conn.execute(postgres.MIGRATIONS[8].encode())  # (migration 9 alone)
    store = postgres.PostgresStore(PG_URL, schema=search_path.strip('"'))  # type: ignore[arg-type]
    try:
        with store.unit() as u:
            new = {iid: u.item(iid).condition for iid in old}  # type: ignore[union-attr]
            assert new["i0"] == 0.0 and new["i5"] == 1.0
            assert abs(new["i2"] - condition_at(0.5)) < 0.001  # the old median is the new one
            assert sorted(new, key=new.__getitem__) == list(old)  # the order stays
            assert all(new[i] >= old[i] for i in old)  # kinder
            pack = u.pack("k1")
            assert pack is not None and abs(pack.choices[0].condition - condition_at(0.5)) < 0.001  # type: ignore[operator]
            assert pack.choices[1].condition is None
    finally:
        store.close()


def test_migration_10_ends_every_trade_hold_once(pg) -> None:  # type: ignore[no-untyped-def]
    """Items in their trade hold may change hands at once; the others keep when theirs ended."""
    from datetime import UTC, datetime

    import psycopg
    from psycopg import sql as pgsql

    from balatro_items.infrastructure.persistence import postgres
    from tests.conftest import PG_URL

    store = pg()
    with store._pool.connection() as conn:
        search_path = conn.execute("SHOW search_path").fetchone()["search_path"]  # type: ignore[index]
    store.close()
    future = datetime(2100, 1, 1, tzinfo=UTC)
    with psycopg.connect(PG_URL, autocommit=True) as conn:  # type: ignore[arg-type]
        conn.execute(pgsql.SQL("SET search_path TO {}").format(pgsql.SQL(search_path)))
        conn.execute("INSERT INTO players (id, name, has_won, showcase, created_at) VALUES ('p1', 'A', true, null, %s)",
                     (T0,))
        for n, until in enumerate((T0, future)):
            conn.execute("INSERT INTO items (id, kind, key, edition, rarity, serial, owner, source, created_at, "
                         "acquired_at, tradable_at, condition) VALUES (%s, 'joker', 'j_joker', 'base', 1, %s, 'p1', "
                         "'gift', %s, %s, %s, 0.5)", (f"i{n}", n + 1, T0, T0, until))
        conn.execute(postgres.MIGRATIONS[9].encode())  # (migration 10 alone)
    store = postgres.PostgresStore(PG_URL, schema=search_path.strip('"'))  # type: ignore[arg-type]
    try:
        with store.unit() as u:
            held, free = u.item("i1"), u.item("i0")
            assert held is not None and free is not None
            assert held.tradable_at <= datetime.now(UTC) and free.tradable_at == T0
    finally:
        store.close()


def test_migration_11_draws_every_items_condition_again(pg) -> None:  # type: ignore[no-untyped-def]
    """Every item gets a new condition, drawn on the curve of now (a = 3.5, b = 5: a median of 56%)."""
    import psycopg
    from psycopg import sql as pgsql

    from balatro_items.domain import condition_at
    from balatro_items.infrastructure.persistence import postgres
    from tests.conftest import PG_URL

    store = pg()
    with store._pool.connection() as conn:
        search_path = conn.execute("SHOW search_path").fetchone()["search_path"]  # type: ignore[index]
    store.close()
    with psycopg.connect(PG_URL, autocommit=True) as conn:  # type: ignore[arg-type]
        conn.execute(pgsql.SQL("SET search_path TO {}").format(pgsql.SQL(search_path)))
        conn.execute("INSERT INTO players (id, name, has_won, showcase, created_at) VALUES ('p1', 'A', true, null, %s)",
                     (T0,))
        for n in range(1000):
            conn.execute("INSERT INTO items (id, kind, key, edition, rarity, serial, owner, source, created_at, "
                         "acquired_at, tradable_at, condition) VALUES (%s, 'joker', 'j_joker', 'base', 1, %s, 'p1', "
                         "'gift', %s, %s, %s, 0.123456)", (f"i{n}", n + 1, T0, T0, T0))
        conn.execute(postgres.MIGRATIONS[10].encode())  # (migration 11 alone)
    store = postgres.PostgresStore(PG_URL, schema=search_path.strip('"'))  # type: ignore[arg-type]
    try:
        with store.unit() as u:
            conditions = sorted(i.condition for i in u.items_of("p1"))
            assert len(conditions) == 1000 and 0.123456 not in conditions
            assert all(0 <= c <= 1 for c in conditions)
            assert abs(conditions[500] - condition_at(0.5)) < 0.05  # the median: 56%
            assert len(set(conditions)) > 990  # each its own
    finally:
        store.close()
