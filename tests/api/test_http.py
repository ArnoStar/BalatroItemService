"""The whole service over HTTP, with the identity service's tokens."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from tests.conftest import World, make_world
from tests.tokens import token

ALICE = {"Authorization": f"Bearer {token(sub='alice', name='Alice')}"}
BOB = {"Authorization": f"Bearer {token(sub='bob', name='Bob')}"}
CAROL = {"Authorization": f"Bearer {token(sub='carol', name='Carol')}"}
ADMIN = {"Authorization": f"Bearer {token(sub='ada', name='Ada', roles=['admin'])}"}


def win(w: World, player: str, run_id: str, **kw: Any) -> None:
    w.runs.add(player, run_id, won=True, ante=8, finished=False, at=w.clock.now(), **kw)


def find(w: World, who: dict[str, str]) -> list[dict[str, Any]]:
    """The coins the player's runs have earned since they last looked."""
    w.clock.advance(seconds=10)  # (runs are read at most every few seconds)
    r = w.client.post("/v1/me/drops", headers=who)
    assert r.status_code == 200, r.text
    earned: list[dict[str, Any]] = r.json()["earned"]
    return earned


def coins(w: World, who: dict[str, str]) -> int:
    balance: int = w.client.get("/v1/me", headers=who).json()["coins"]
    return balance


def open_booster(w: World, who: dict[str, str], booster: str = "joker_standard_normal",
                 picks: list[int] | None = None) -> list[dict[str, Any]]:
    """Buys a booster and chooses its first cards: the items they became."""
    r = w.client.post(f"/v1/boosters/{booster}/buy", headers=who)
    assert r.status_code == 201, r.text
    pack = r.json()
    r = w.client.post(f"/v1/packs/{pack['id']}/choose", headers=who,
                      json={"picks": picks if picks is not None else list(range(pack["picks"]))})
    assert r.status_code == 200, r.text
    items: list[dict[str, Any]] = r.json()["items"]
    return items


def test_sign_in_is_needed_but_for_health_odds_and_boosters(world: World) -> None:
    c = world.client
    assert c.get("/health").json()["auth"] == "required"
    r = c.get("/v1/me")
    assert r.status_code == 401 and r.json()["code"] == "unauthenticated"
    odds = c.get("/v1/odds").json()
    assert len(odds["boosters"]) == 45 and len(odds["tables"]) == 15 and len(odds["rules"]) == 4
    assert odds["pools"]["joker"] == {"common": 4, "uncommon": 2, "rare": 2, "legendary": 2}
    assert odds["pools"]["card"] == {"common": 4, "uncommon": 48, "rare": 128}
    assert odds["trade_hold_days"] == 7 and odds["market_min_price"] == 1
    planets = next(t for t in odds["tables"] if t["kind"] == "planet" and t["tier"] == "standard")
    assert "legendary" not in planets["rarities"] and planets["editions"] == {"base": 99.98, "negative": 0.02}
    boosters = c.get("/v1/boosters").json()
    mega = next(b for b in boosters if b["id"] == "spectral_premium_mega")
    assert (mega["choices"], mega["picks"], mega["price"], mega["art"]) == (4, 2, 1200, "p_spectral_mega_1")
    assert mega["rarities"] == {"uncommon": 75.0, "rare": 23.5, "legendary": 1.5}


def test_coins_are_earned_by_playing_once(world: World) -> None:
    c = world.client
    me = c.get("/v1/me", headers=ALICE).json()
    assert me["items"] == 0 and me["coins"] == 0 and not me["can_trade"] and me["week"]["week"] == "2026-W46"
    assert find(world, ALICE) == []  # nothing played yet
    world.runs.add("alice", "r1", ante=4)
    earned = find(world, ALICE)
    assert earned == [{"source": "week:2026-W46:play", "reason": "weekly", "coins": 100, "run": "r1"}]
    assert find(world, ALICE) == []  # once
    me = c.get("/v1/me", headers=ALICE).json()
    assert me["coins"] == 100 and me["week"]["weekly_earned"] and not me["week"]["weekly_win_earned"]
    # a win: the week's win, and the deck's first win (a White Stake win has no stake milestone)
    win(world, "alice", "r2", stake=1)
    world.clock.advance(seconds=10)
    r = c.post("/v1/me/drops", headers=ALICE).json()
    assert sorted(e["reason"] for e in r["earned"]) == ["first_deck_win", "weekly_win"]
    assert r["coins"] == 500 and r["balance"] == 600
    assert c.get("/v1/me", headers=ALICE).json()["can_trade"]
    # next week: the weekly coins again
    world.clock.advance(days=7)
    world.runs.add("alice", "r3", ante=3, at=world.clock.now())
    assert [e["reason"] for e in find(world, ALICE)] == ["weekly"]
    history = c.get("/v1/me/coins", headers=ALICE).json()
    assert history["balance"] == 700
    assert [(m["amount"], m["balance"]) for m in history["moves"]] == [(100, 700), (250, 600), (250, 350), (100, 100)]


def test_boosters_make_items_from_the_cards_chosen(world: World) -> None:
    c = world.client
    win(world, "alice", "r1", stake=2)
    find(world, ALICE)
    assert coins(world, ALICE) == 850
    r = c.post("/v1/boosters/card_boosted_mega/buy", headers=ALICE)
    assert r.status_code == 201, r.text
    pack = r.json()
    assert pack["status"] == "open" and pack["picks"] == 2 and len(pack["choices"]) == 4 and pack["items"] == []
    assert pack["price"] == 500 and pack["booster"]["art"] == "p_standard_mega_1"
    assert coins(world, ALICE) == 350
    assert all(ch["kind"] == "card" and ch["edition"] != "negative" and ch["odds"] > 0 for ch in pack["choices"])
    assert len({ch["variant"] for ch in pack["choices"]}) == 4
    # the same cards when coming back to it; nobody else sees it
    assert c.get(f"/v1/packs/{pack['id']}", headers=ALICE).json()["choices"] == pack["choices"]
    assert [p["id"] for p in c.get("/v1/me/packs", headers=ALICE).json()] == [pack["id"]]
    assert c.get("/v1/me", headers=ALICE).json()["packs"] == 1
    assert c.get(f"/v1/packs/{pack['id']}", headers=BOB).status_code == 404
    r = c.post(f"/v1/packs/{pack['id']}/choose", headers=ALICE, json={"picks": [1]})
    assert r.status_code == 422 and r.json()["code"] == "invalid_pick"
    r = c.post(f"/v1/packs/{pack['id']}/choose", headers=ALICE, json={"picks": [2, 0]})
    assert r.status_code == 200, r.text
    opened = r.json()
    assert opened["status"] == "opened" and opened["chosen"] == [2, 0]
    items = opened["items"]
    assert [(i["key"], i["enhancement"], i["seal"], i["edition"]) for i in items] == [
        (pack["choices"][k]["key"], pack["choices"][k]["enhancement"], pack["choices"][k]["seal"],
         pack["choices"][k]["edition"]) for k in (2, 0)]
    assert all(i["source"] == "booster" and i["booster"] == "card_boosted_mega" and i["serial"] == 1
               and not i["tradable"] and i["sprite"] for i in items)
    r = c.post(f"/v1/packs/{pack['id']}/choose", headers=ALICE, json={"picks": [1, 3]})
    assert r.status_code == 409 and r.json()["code"] == "pack_opened"
    assert c.get("/v1/me/packs", headers=ALICE).json() == []
    assert len(c.get("/v1/me/items", headers=ALICE).json()) == 2
    # not enough coins: nothing bought
    r = c.post("/v1/boosters/joker_premium_mega/buy", headers=ALICE)
    assert r.status_code == 409 and r.json()["code"] == "not_enough_coins"
    assert coins(world, ALICE) == 350 and c.get("/v1/me/packs", headers=ALICE).json() == []
    assert c.post("/v1/boosters/nope/buy", headers=ALICE).status_code == 404
    assert c.get("/v1/me/coins", headers=ALICE).json()["moves"][0] == {
        "amount": -500, "balance": 350, "reason": "booster", "ref": pack["id"], "at": "2026-11-11T12:00:10Z"}


def ready_to_trade(w: World) -> tuple[str, str]:
    """Alice and Bob have won and have one item each, out of its hold."""
    win(w, "alice", "a1", deck="b_blue")
    win(w, "bob", "b1", deck="b_green")
    find(w, ALICE)
    find(w, BOB)
    a = open_booster(w, ALICE)[0]["id"]
    b = open_booster(w, BOB)[0]["id"]
    w.clock.advance(days=8)
    return a, b


def test_a_trade(world: World) -> None:
    c = world.client
    a, b = ready_to_trade(world)
    r = c.post("/v1/trades", headers=ALICE, json={"to": "bob", "give": [a], "take": [b], "message": "swap?"})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["status"] == "pending" and t["available"] and t["sender_name"] == "Alice" and t["recipient_name"] == "Bob"
    assert [i["id"] for i in t["give"]] == [a] and [i["id"] for i in t["take"]] == [b]
    assert [x["id"] for x in c.get("/v1/trades?box=incoming", headers=BOB).json()] == [t["id"]]
    assert c.get("/v1/trades?box=incoming", headers=ALICE).json() == []
    # only Bob accepts; Carol doesn't even see it
    r = c.post(f"/v1/trades/{t['id']}/accept", headers=ALICE)
    assert r.status_code == 403 and r.json()["code"] == "not_allowed"
    assert c.get(f"/v1/trades/{t['id']}", headers=CAROL).status_code == 404
    c.put("/v1/me/showcase", headers=ALICE, json={"item": a})
    r = c.post(f"/v1/trades/{t['id']}/accept", headers=BOB)
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert c.get(f"/v1/items/{a}", headers=CAROL).json()["item"]["owner"] == "bob"
    detail = c.get(f"/v1/items/{b}", headers=CAROL).json()
    assert detail["item"]["owner"] == "alice" and not detail["item"]["tradable"]
    assert [(h["from_name"], h["to_name"]) for h in detail["history"]] == [(None, "Bob"), ("Bob", "Alice")]
    assert detail["history"][1]["trade"] == t["id"] and detail["history"][1]["price"] is None
    assert c.get("/v1/me", headers=ALICE).json()["showcase"] is None  # not hers any more
    # the trade hold: not again for a week
    r = c.post("/v1/trades", headers=ALICE, json={"to": "bob", "give": [b]})
    assert r.status_code == 409 and r.json()["code"] == "item_locked"
    r = c.post(f"/v1/trades/{t['id']}/decline", headers=BOB)
    assert r.status_code == 409 and r.json()["code"] == "trade_closed"


def test_an_offer_whose_items_moved_cant_be_accepted(world: World) -> None:
    c = world.client
    a, b = ready_to_trade(world)
    first = c.post("/v1/trades", headers=ALICE, json={"to": "bob", "give": [a]}).json()
    second = c.post("/v1/trades", headers=ALICE, json={"to": "bob", "give": [a], "take": [b]}).json()
    assert c.post(f"/v1/trades/{first['id']}/accept", headers=BOB).status_code == 200
    assert not c.get(f"/v1/trades/{second['id']}", headers=BOB).json()["available"]
    r = c.post(f"/v1/trades/{second['id']}/accept", headers=BOB)
    assert r.status_code == 409 and r.json()["code"] == "items_moved"
    assert c.get(f"/v1/items/{b}", headers=BOB).json()["item"]["owner"] == "bob"  # nothing moved


def test_decline_cancel_and_expiry(world: World) -> None:
    c = world.client
    a, b = ready_to_trade(world)
    t1 = c.post("/v1/trades", headers=ALICE, json={"to": "bob", "give": [a]}).json()
    assert c.post(f"/v1/trades/{t1['id']}/cancel", headers=BOB).status_code == 403
    assert c.post(f"/v1/trades/{t1['id']}/decline", headers=BOB).json()["status"] == "declined"
    t2 = c.post("/v1/trades", headers=ALICE, json={"to": "bob", "take": [b]}).json()
    assert c.post(f"/v1/trades/{t2['id']}/cancel", headers=ALICE).json()["status"] == "cancelled"
    t3 = c.post("/v1/trades", headers=ALICE, json={"to": "bob", "give": [a]}).json()
    world.clock.advance(days=15)
    assert c.get(f"/v1/trades/{t3['id']}", headers=BOB).json()["status"] == "expired"
    assert c.post(f"/v1/trades/{t3['id']}/accept", headers=BOB).status_code == 409


def test_trading_opens_after_a_first_win(world: World) -> None:
    c = world.client
    win(world, "alice", "a1")
    find(world, ALICE)
    a = open_booster(world, ALICE)[0]["id"]
    world.runs.add("carol", "c1", ante=5)
    find(world, CAROL)
    open_booster(world, CAROL, "planet_standard_normal")  # Carol has an item but no win
    world.clock.advance(days=8)
    r = c.post("/v1/trades", headers=ALICE, json={"to": "carol", "give": [a]})
    assert r.status_code == 403 and r.json()["code"] == "trading_locked"
    r = c.post("/v1/trades", headers=CAROL, json={"to": "alice", "take": [a]})
    assert r.status_code == 403 and r.json()["code"] == "trading_locked"
    r = c.post("/v1/trades", headers=ALICE, json={"to": "nobody", "give": [a]})
    assert r.status_code == 404 and r.json()["code"] == "player_not_found"
    r = c.post("/v1/trades", headers=ALICE, json={"to": "alice", "give": [a]})
    assert r.status_code == 422 and r.json()["code"] == "invalid_trade"


def test_players_and_showcases(world: World) -> None:
    c = world.client
    world.runs.add("alice", "r1", ante=4)
    find(world, ALICE)
    a = open_booster(world, ALICE, "tarot_standard_normal")[0]["id"]
    c.get("/v1/me", headers=BOB)
    r = c.put("/v1/me/showcase", headers=BOB, json={"item": a})
    assert r.status_code == 409 and r.json()["code"] == "not_owner"
    assert c.put("/v1/me/showcase", headers=ALICE, json={"item": a}).json()["showcase"]["id"] == a
    p = c.get("/v1/players/alice", headers=BOB).json()
    assert p["name"] == "Alice" and p["items"] == 1 and p["showcase"]["id"] == a and not p["you"]
    assert [x["id"] for x in c.get("/v1/players/alice/items", headers=BOB).json()] == [a]
    assert [x["id"] for x in c.get("/v1/players?q=al", headers=BOB).json()] == ["alice"]
    assert c.get("/v1/players/nobody", headers=BOB).status_code == 404
    assert c.put("/v1/me/showcase", headers=ALICE, json={"item": None}).json()["showcase"] is None


def test_admins_give_items_and_coins(world: World) -> None:
    c = world.client
    c.get("/v1/me", headers=BOB)
    body = {"to": "bob", "key": "j_perkeo", "edition": "negative", "stake": 8}
    r = c.post("/v1/admin/gifts", headers=ALICE, json=body)
    assert r.status_code == 403 and r.json()["code"] == "not_admin"
    r = c.post("/v1/admin/gifts", headers=ADMIN, json=body)
    assert r.status_code == 201, r.text
    assert r.json()["source"] == "gift" and r.json()["owner"] == "bob" and r.json()["edition"] == "negative"
    assert c.post("/v1/admin/gifts", headers=ADMIN, json={**body, "key": "j_nope"}).status_code == 422
    assert c.post("/v1/admin/gifts", headers=ADMIN, json={**body, "to": "nobody"}).status_code == 404
    card = {"to": "bob", "key": "S_A", "edition": "polychrome", "enhancement": "m_glass", "seal": "Red"}
    r = c.post("/v1/admin/gifts", headers=ADMIN, json=card)
    assert r.status_code == 201, r.text
    assert (r.json()["variant"], r.json()["rarity"], r.json()["name"]) == ("S_A+m_glass+Red", 3, "Ace of Spades")
    # only the upgrades the game gives: no negative playing card, no holographic tarot
    r = c.post("/v1/admin/gifts", headers=ADMIN, json={**card, "edition": "negative"})
    assert r.status_code == 422 and r.json()["code"] == "unknown_item"
    r = c.post("/v1/admin/gifts", headers=ADMIN, json={"to": "bob", "key": "c_fool", "edition": "holographic"})
    assert r.status_code == 422
    assert c.post("/v1/admin/gifts", headers=ADMIN, json={"to": "bob", "key": "c_fool", "edition": "negative"}
                  ).status_code == 201
    r = c.post("/v1/admin/coins", headers=ADMIN, json={"to": "bob", "coins": 300, "note": "a prize"})
    assert r.status_code == 201 and r.json()["balance"] == 300
    assert c.post("/v1/admin/coins", headers=ALICE, json={"to": "bob", "coins": 300}).status_code == 403
    r = c.post("/v1/admin/coins", headers=ADMIN, json={"to": "bob", "coins": -500})
    assert r.status_code == 409 and r.json()["code"] == "not_enough_coins"
    assert c.post("/v1/admin/coins", headers=ADMIN, json={"to": "bob", "coins": -300}).json()["balance"] == 0


def test_items_still_show_when_the_catalog_is_down(world: World) -> None:
    world.runs.add("alice", "r1", ante=4)
    find(world, ALICE)
    open_booster(world, ALICE)
    world.catalog.down = True
    items = world.client.get("/v1/me/items", headers=ALICE).json()
    assert items[0]["name"] == items[0]["key"] and items[0]["odds"] == 0


def test_without_sign_in_everyone_is_one_player_and_an_admin() -> None:
    w = make_world(signed_in=False)
    me = w.client.get("/v1/me").json()
    assert me["id"] == "anonymous" and me["admin"]
    w.clock.advance(days=1)
    assert w.client.get("/health").json()["auth"] == "off"
    assert timedelta(days=1)  # (the clock moved; nothing else to see)
