"""The market over HTTP: players sell items to other players, for coins."""

from __future__ import annotations

from typing import Any

from tests.api.test_casino import gift, out_of_hold, ready
from tests.api.test_http import ADMIN, ALICE, BOB, CAROL, coins, find, open_booster
from tests.conftest import World
from tests.tokens import token

DAVE = {"Authorization": f"Bearer {token(sub='dave', name='Dave')}"}


def give_coins(w: World, to: str, n: int) -> None:
    r = w.client.post("/v1/admin/coins", headers=ADMIN, json={"to": to, "coins": n})
    assert r.status_code == 201, r.text


def sell(w: World, who: dict[str, str], item: str, price: int) -> dict[str, Any]:
    r = w.client.post("/v1/market", headers=who, json={"item": item, "price": price})
    assert r.status_code == 201, r.text
    listing: dict[str, Any] = r.json()
    return listing


def test_an_item_sold(world: World) -> None:
    c = world.client
    ready(world)
    a = gift(world, "alice", "j_blueprint", "foil")
    out_of_hold(world)
    before_a, before_b = coins(world, ALICE), coins(world, BOB)
    x = sell(world, ALICE, a, 300)
    assert x["status"] == "open" and x["available"] and x["seller_name"] == "Alice" and x["price"] == 300
    item = x["item"]
    assert item["id"] == a and item["listed"] == x["id"] and item["price"] == 300 and not item["tradable"]
    # for sale: not tradable, not stakeable, not listed twice
    r = c.post("/v1/trades", headers=ALICE, json={"to": "bob", "give": [a]})
    assert r.status_code == 409 and r.json()["code"] == "item_locked"
    r = c.post("/v1/casino/coinflips", headers=ALICE, json={"items": [a]})
    assert r.status_code == 409 and r.json()["code"] == "item_locked"
    assert c.post("/v1/market", headers=ALICE, json={"item": a, "price": 5}).status_code == 409
    # everyone sees it; its seller can't buy it
    found = c.get("/v1/market?kind=joker&sort=price", headers=CAROL).json()
    assert [f["id"] for f in found] == [x["id"]]
    assert c.get("/v1/market?q=blue", headers=CAROL).json()[0]["id"] == x["id"]
    assert c.get("/v1/market?q=nothing+like+it", headers=CAROL).json() == []
    assert c.get("/v1/market?edition=negative", headers=CAROL).json() == []
    r = c.post(f"/v1/market/{x['id']}/buy", headers=ALICE)
    assert r.status_code == 422 and r.json()["code"] == "invalid_listing"
    # Bob buys it: his coins to Alice, the item to him (its hold starts)
    r = c.post(f"/v1/market/{x['id']}/buy", headers=BOB)
    assert r.status_code == 200, r.text
    sold = r.json()
    assert sold["status"] == "sold" and sold["buyer_name"] == "Bob" and not sold["available"]
    assert coins(world, ALICE) == before_a + 300 and coins(world, BOB) == before_b - 300
    detail = c.get(f"/v1/items/{a}", headers=CAROL).json()
    assert detail["item"]["owner"] == "bob" and detail["item"]["listed"] is None and not detail["item"]["tradable"]
    assert (detail["history"][-1]["listing"], detail["history"][-1]["price"]) == (x["id"], 300)
    r = c.post(f"/v1/market/{x['id']}/buy", headers=CAROL)
    assert r.status_code == 409 and r.json()["code"] == "listing_closed"
    assert c.get("/v1/me/coins", headers=ALICE).json()["moves"][0]["reason"] == "market_sale"
    assert c.get("/v1/me/coins", headers=BOB).json()["moves"][0]["reason"] == "market_buy"
    # what it sold for, and each player's market
    sales = c.get("/v1/market/sales?variant=j_blueprint&edition=foil", headers=CAROL).json()
    assert [s["price"] for s in sales] == [300]
    assert c.get("/v1/market/sales?variant=j_blueprint&edition=base", headers=CAROL).json() == []
    assert [s["id"] for s in c.get("/v1/me/listings?box=sold", headers=ALICE).json()] == [x["id"]]
    assert [s["id"] for s in c.get("/v1/me/listings?box=bought", headers=BOB).json()] == [x["id"]]
    assert c.get("/v1/me/listings", headers=ALICE).json() == []
    assert c.get("/v1/market", headers=CAROL).json() == []


def test_not_enough_coins_buys_nothing(world: World) -> None:
    c = world.client
    ready(world)
    a = gift(world, "alice")
    out_of_hold(world)
    x = sell(world, ALICE, a, 1_000_000)
    r = c.post(f"/v1/market/{x['id']}/buy", headers=BOB)
    assert r.status_code == 409 and r.json()["code"] == "not_enough_coins"
    assert c.get(f"/v1/market/{x['id']}", headers=BOB).json()["available"]
    give_coins(world, "bob", 1_000_000)
    assert c.post(f"/v1/market/{x['id']}/buy", headers=BOB).status_code == 200


def test_taken_off(world: World) -> None:
    c = world.client
    ready(world)
    a = gift(world, "alice")
    out_of_hold(world)
    x = sell(world, ALICE, a, 50)
    assert c.post(f"/v1/market/{x['id']}/cancel", headers=BOB).status_code == 403
    r = c.post(f"/v1/market/{x['id']}/cancel", headers=ALICE)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert c.get(f"/v1/items/{a}", headers=ALICE).json()["item"]["tradable"]
    r = c.post(f"/v1/market/{x['id']}/buy", headers=BOB)
    assert r.status_code == 409 and r.json()["code"] == "listing_closed"
    assert [s["status"] for s in c.get("/v1/me/listings?box=all", headers=ALICE).json()] == ["cancelled"]
    sell(world, ALICE, a, 60)  # and again


def test_the_market_plays_by_the_trade_rules(world: World) -> None:
    c = world.client
    world.runs.add("dave", "d1", ante=5)
    find(world, DAVE)
    item = open_booster(world, DAVE)[0]["id"]  # Dave has coins and an item, but no win
    ready(world)
    a = gift(world, "alice")
    r = c.post("/v1/market", headers=ALICE, json={"item": a, "price": 10})
    assert r.status_code == 409 and r.json()["code"] == "item_locked"  # in its trade hold
    out_of_hold(world)
    r = c.post("/v1/market", headers=DAVE, json={"item": item, "price": 10})
    assert r.status_code == 403 and r.json()["code"] == "trading_locked"
    x = sell(world, ALICE, a, 10)
    r = c.post(f"/v1/market/{x['id']}/buy", headers=DAVE)
    assert r.status_code == 403 and r.json()["code"] == "trading_locked"
    r = c.post("/v1/market", headers=BOB, json={"item": a, "price": 10})
    assert r.status_code == 409 and r.json()["code"] == "not_owner"
    for bad in (0, 1_000_000_001):
        assert c.post("/v1/market", headers=ALICE, json={"item": a, "price": bad}).status_code == 422
    assert c.get("/v1/market/nope", headers=BOB).status_code == 404


def test_a_showcased_item_sold_leaves_the_title_screen(world: World) -> None:
    c = world.client
    ready(world)
    a = gift(world, "alice")
    out_of_hold(world)
    c.put("/v1/me/showcase", headers=ALICE, json={"item": a})
    x = sell(world, ALICE, a, 5)
    c.post(f"/v1/market/{x['id']}/buy", headers=BOB)
    assert c.get("/v1/me", headers=ALICE).json()["showcase"] is None
