"""The upgrade over HTTP: an item put in against the house, provably fair."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from tests.api.test_casino import gift, out_of_hold, ready
from tests.api.test_http import ALICE, BOB, CAROL
from tests.conftest import World, make_world


def check_roll(up: dict[str, Any], seed_hash: str) -> None:
    """What anyone can check: the server seed committed to, the roll, the outcome."""
    assert hashlib.sha256(up["server_seed"].encode()).hexdigest() == up["seed_hash"] == seed_hash
    h = int(hmac.new(up["server_seed"].encode(), f"{up['id']}:{up['seed']}".encode(), hashlib.sha256).hexdigest()[:13],
            16)
    assert up["roll"] == h * 1_000_000 // 16**13
    assert up["won"] == (up["roll"] < up["chance_ppm"])


def test_rules_and_a_preview(world: World) -> None:
    c = world.client
    rules = c.get("/v1/casino/rules").json()
    assert (rules["upgrade_edge"], rules["upgrade_margin"], rules["upgrade_max_multiplier"]) == (95, 5, 100)
    ready(world)
    a = gift(world, "alice", "j_blueprint", condition=0.5)
    value = c.get(f"/v1/items/{a}", headers=ALICE).json()["item"]["value"]
    p = c.get(f"/v1/casino/upgrades/preview?item={a}&multiplier=2", headers=BOB).json()
    assert (p["value"], p["target"], p["chance"]) == (value, 2 * value, 47.5)
    assert p["low"] == round(2 * value * 0.95) and p["possible"] and p["examples"]
    assert all(e["mint_value"] * e["condition_low"] >= p["low"] - 1 for e in p["examples"])
    assert c.get(f"/v1/casino/upgrades/preview?item={a}&multiplier=101", headers=BOB).status_code == 422


def test_an_upgrade_won_and_one_lost(world: World) -> None:
    c = world.client
    ready(world)
    items = [gift(world, "alice", "j_blueprint", condition=0.5) for _ in range(6)]
    out_of_hold(world)
    c.put("/v1/me/showcase", headers=ALICE, json={"item": items[0]})
    outcomes = []
    for i, m in zip(items, (1.0, 1.0, 1.0, 100.0, 100.0, 100.0), strict=True):
        seed_hash = c.get("/v1/casino/upgrades/seed", headers=ALICE).json()["seed_hash"]
        r = c.post("/v1/casino/upgrades", headers=ALICE, json={"item": i, "multiplier": m, "seed": "lucky"})
        assert r.status_code == 201, r.text
        up = r.json()
        check_roll(up, seed_hash)
        assert up["player_name"] == "Alice" and up["item"]["id"] == i and up["item"]["destroyed_in"] == up["id"]
        # the item put in is gone, whatever happens
        detail = c.get(f"/v1/items/{i}", headers=CAROL).json()["item"]
        assert detail["destroyed_at"] and not detail["tradable"]
        if up["won"]:
            prize = up["prize"]
            assert up["low"] <= prize["value"] == up["prize_value"] <= up["high"]
            assert prize["owner"] == "alice" and prize["source"] == "upgrade" and prize["tradable"]  # (no hold)
        else:
            assert up["prize"] is None
        outcomes.append(up["won"])
    assert outcomes[:3] == [True, True, True] or sum(outcomes[:3]) >= 2  # (95% each)
    mine = {x["id"] for x in c.get("/v1/me/items", headers=ALICE).json()}
    assert not mine & set(items)
    assert c.get("/v1/me", headers=ALICE).json()["showcase"] is None
    assert [x["item"]["id"] for x in c.get("/v1/casino/upgrades?of=alice", headers=BOB).json()] == items[::-1]
    # a destroyed item can't be put in again, nor traded
    r = c.post("/v1/casino/upgrades", headers=ALICE, json={"item": items[0], "multiplier": 2})
    assert r.status_code == 409 and r.json()["code"] == "not_owner"
    r = c.post("/v1/trades", headers=ALICE, json={"to": "bob", "give": [items[0]]})
    assert r.status_code == 409
    assert ("upgrade", items[0]) in [(e.type, e.data.item.id) for e in world.feed.published if e.type == "upgrade"]


def test_what_cant_be_upgraded(world: World) -> None:
    c = world.client
    ready(world)
    a = gift(world, "alice")
    r = c.post("/v1/casino/upgrades", headers=ALICE, json={"item": a, "multiplier": 2})
    assert r.status_code == 409 and r.json()["code"] == "item_locked"  # in its trade hold
    out_of_hold(world)
    r = c.post("/v1/casino/upgrades", headers=BOB, json={"item": a, "multiplier": 2})
    assert r.status_code == 409 and r.json()["code"] == "not_owner"
    r = c.post("/v1/casino/upgrades", headers=ALICE, json={"item": a, "multiplier": 100})
    assert r.status_code in (201, 422)  # (a common joker x100: possible only if some card is worth that much)
    closed = make_world(casino=False)
    ready(closed)
    b = gift(closed, "alice")
    out_of_hold(closed)
    r = closed.client.post("/v1/casino/upgrades", headers=ALICE, json={"item": b, "multiplier": 2})
    assert r.status_code == 403 and r.json()["code"] == "casino_closed"
