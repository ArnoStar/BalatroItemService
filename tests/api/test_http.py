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
    w.clock.advance(seconds=10)  # (runs are read at most every few seconds)
    r = w.client.post("/v1/me/drops", headers=who)
    assert r.status_code == 200, r.text
    found: list[dict[str, Any]] = r.json()["found"]
    return found


def test_sign_in_is_needed_but_for_health_and_odds(world: World) -> None:
    c = world.client
    assert c.get("/health").json()["auth"] == "required"
    r = c.get("/v1/me")
    assert r.status_code == 401 and r.json()["code"] == "unauthenticated"
    odds = c.get("/v1/odds").json()
    assert [t["name"] for t in odds["tables"]] == ["standard", "boosted", "premium"]
    assert odds["pools"]["joker"] == {"common": 4, "uncommon": 2, "rare": 2, "legendary": 2}
    assert odds["trade_hold_days"] == 7 and len(odds["rules"]) == 4


def test_items_are_found_by_playing_once(world: World) -> None:
    c = world.client
    me = c.get("/v1/me", headers=ALICE).json()
    assert me["items"] == 0 and not me["can_trade"] and me["week"]["week"] == "2026-W46"
    assert find(world, ALICE) == []  # nothing played yet
    world.runs.add("alice", "r1", ante=4)
    found = find(world, ALICE)
    assert len(found) == 1
    item = found[0]
    assert item["owner"] == "alice" and item["owner_name"] == "Alice" and item["source"] == "weekly"
    assert item["source_run"] == "r1" and item["serial"] == 1 and item["minted"] == 1 and item["odds"] > 1
    assert item["name"] and item["sprite"] and not item["tradable"]
    assert find(world, ALICE) == []  # once
    me = c.get("/v1/me", headers=ALICE).json()
    assert me["items"] == 1 and me["week"]["weekly_found"] and not me["week"]["weekly_win_found"]
    # a win: the week's win, and the deck's first win (a White Stake win has no stake milestone)
    win(world, "alice", "r2", stake=1)
    found = find(world, ALICE)
    assert sorted(i["source"] for i in found) == ["first_deck_win", "weekly_win"]
    assert all(i["stake"] == 1 for i in found)
    assert c.get("/v1/me", headers=ALICE).json()["can_trade"]
    # next week: another weekly item
    world.clock.advance(days=7)
    world.runs.add("alice", "r3", ante=3, at=world.clock.now())
    assert [i["source"] for i in find(world, ALICE)] == ["weekly"]
    assert len(c.get("/v1/me/items", headers=ALICE).json()) == 4


def test_the_game_api_down_finds_nothing_and_says_so(world: World) -> None:
    world.runs.down = True
    world.clock.advance(seconds=10)
    r = world.client.post("/v1/me/drops", headers=ALICE)
    assert r.status_code == 503 and r.json()["code"] == "game_api_unavailable"


def test_runs_are_not_read_too_often(world: World) -> None:
    find(world, ALICE)
    calls = world.runs.calls
    world.client.post("/v1/me/drops", headers=ALICE)
    assert world.runs.calls == calls


def ready_to_trade(w: World) -> tuple[str, str]:
    """Alice and Bob have won and have one item each, out of its hold."""
    win(w, "alice", "a1", deck="b_blue")
    win(w, "bob", "b1", deck="b_green")
    a = find(w, ALICE)[0]["id"]
    b = find(w, BOB)[0]["id"]
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
    a = find(world, ALICE)[0]["id"]
    world.runs.add("carol", "c1", ante=5)
    find(world, CAROL)  # Carol has an item but no win
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
    a = find(world, ALICE)[0]["id"]
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


def test_admins_give_items(world: World) -> None:
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


def test_items_still_show_when_the_catalog_is_down(world: World) -> None:
    world.runs.add("alice", "r1", ante=4)
    find(world, ALICE)
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
