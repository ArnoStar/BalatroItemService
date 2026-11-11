"""The casino over HTTP: coinflips and the jackpot, between players, provably fair."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from tests.api.test_http import ADMIN, ALICE, BOB, CAROL, find, win
from tests.conftest import World, make_world

PLAYERS = {"alice": ALICE, "bob": BOB, "carol": CAROL}


def ready(w: World) -> None:
    """Alice, Bob and Carol have won (the casino opens after a first win), and their items are out of their hold."""
    for i, (pid, who) in enumerate(PLAYERS.items()):
        win(w, pid, f"r{i}", deck=f"b_deck{i}")
        find(w, who)


def gift(w: World, to: str, key: str = "j_joker", edition: str = "base") -> str:
    r = w.client.post("/v1/admin/gifts", headers=ADMIN, json={"to": to, "key": key, "edition": edition})
    assert r.status_code == 201, r.text
    item_id: str = r.json()["id"]
    return item_id


def out_of_hold(w: World) -> None:
    w.clock.advance(days=8)


def item(w: World, item_id: str) -> dict[str, Any]:
    detail: dict[str, Any] = w.client.get(f"/v1/items/{item_id}", headers=CAROL).json()
    return detail


def check_draw(game: dict[str, Any]) -> None:
    """What anyone can check once a game is over."""
    seed = game["server_seed"]
    assert hashlib.sha256(seed.encode()).hexdigest() == game["seed_hash"]
    message = ":".join([game["id"], *(e["seed"] for e in game["entries"])]).encode()
    h = int(hmac.new(seed.encode(), message, hashlib.sha256).hexdigest()[:13], 16)
    assert game["roll"] == h * game["value"] // 16**13
    holder = next(e for e in game["entries"] if e["low"] <= game["roll"] < e["high"])
    assert holder["player"] == game["winner"]


def test_rules_are_public() -> None:
    w = make_world()
    rules = w.client.get("/v1/casino/rules").json()
    assert rules["open"] and rules["max_items"] == 10 and rules["coinflip_margin"] == 10
    assert rules["jackpot_seconds"] == 60 and rules["trade_hold_days"] == 7
    assert w.client.get("/v1/casino/coinflips").status_code == 401


def test_a_coinflip(world: World) -> None:
    c = world.client
    ready(world)
    a, b, rich = gift(world, "alice"), gift(world, "bob", "j_greedy_joker"), gift(world, "bob", "j_perkeo", "negative")
    out_of_hold(world)
    r = c.post("/v1/casino/coinflips", headers=ALICE, json={"items": [a], "side": "mult", "seed": "alice-luck"})
    assert r.status_code == 201, r.text
    g = r.json()
    value = item(world, a)["item"]["odds"]
    assert g["status"] == "open" and g["side"] == "mult" and g["value"] == value and g["server_seed"] is None
    assert g["entries"][0]["player_name"] == "Alice" and g["entries"][0]["seed"] == "alice-luck"
    assert g["join_min"] <= value <= g["join_max"] and len(g["seed_hash"]) == 64
    assert [x["id"] for x in c.get("/v1/casino/coinflips", headers=BOB).json()] == [g["id"]]
    # staked: it can't be traded nor staked again
    staked = item(world, a)["item"]
    assert staked["staked"] == g["id"] and not staked["tradable"]
    r = c.post("/v1/trades", headers=ALICE, json={"to": "bob", "give": [a]})
    assert r.status_code == 409 and r.json()["code"] == "item_locked"
    r = c.post("/v1/casino/jackpot", headers=ALICE, json={"items": [a]})
    assert r.status_code == 409 and r.json()["code"] == "item_locked"
    # not one's own, nor with items worth too much (and nothing is staked then)
    r = c.post(f"/v1/casino/coinflips/{g['id']}/join", headers=ALICE, json={"items": [a]})
    assert r.status_code == 403 and r.json()["code"] == "not_allowed"
    r = c.post(f"/v1/casino/coinflips/{g['id']}/join", headers=BOB, json={"items": [rich]})
    assert r.status_code == 422 and r.json()["code"] == "invalid_bet"
    assert item(world, rich)["item"]["staked"] is None
    # the showcase of the one who loses goes back to the game's card
    c.put("/v1/me/showcase", headers=ALICE, json={"item": a})
    c.put("/v1/me/showcase", headers=BOB, json={"item": b})
    r = c.post(f"/v1/casino/coinflips/{g['id']}/join", headers=BOB, json={"items": [b]})
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "done" and done["winner"] in ("alice", "bob") and done["join_min"] is None
    check_draw(done)
    winner, loser = done["winner"], ({"alice", "bob"} - {done["winner"]}).pop()
    theirs = b if winner == "alice" else a
    mine = a if winner == "alice" else b
    assert item(world, mine)["item"]["owner"] == winner and item(world, mine)["item"]["tradable"]
    won = item(world, theirs)
    assert won["item"]["owner"] == winner and won["item"]["staked"] is None and not won["item"]["tradable"]
    assert won["history"][-1]["game"] == done["id"] and won["history"][-1]["to_player"] == winner
    assert c.get("/v1/me", headers=PLAYERS[loser]).json()["showcase"] is None
    assert c.get("/v1/me", headers=PLAYERS[winner]).json()["showcase"]["id"] == mine
    assert c.get("/v1/casino/coinflips", headers=BOB).json() == []
    assert [x["id"] for x in c.get("/v1/casino/games?player=bob", headers=CAROL).json()] == [done["id"]]
    assert c.get("/v1/casino/games?player=carol", headers=CAROL).json() == []
    r = c.post(f"/v1/casino/coinflips/{g['id']}/join", headers=CAROL, json={"items": [rich]})
    assert r.status_code == 409 and r.json()["code"] == "game_closed"


def test_a_coinflip_nobody_joins_is_taken_back(world: World) -> None:
    c = world.client
    ready(world)
    a = gift(world, "carol")
    out_of_hold(world)
    g = c.post("/v1/casino/coinflips", headers=CAROL, json={"items": [a]}).json()
    assert g["side"] == "chips" and g["entries"][0]["seed"]  # (a random seed)
    assert c.post(f"/v1/casino/coinflips/{g['id']}/cancel", headers=BOB).status_code == 403
    r = c.post(f"/v1/casino/coinflips/{g['id']}/cancel", headers=CAROL)
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["server_seed"]
    assert item(world, a)["item"]["tradable"] and item(world, a)["item"]["owner"] == "carol"
    assert c.post(f"/v1/casino/coinflips/{g['id']}/cancel", headers=CAROL).status_code == 409
    assert c.post("/v1/casino/coinflips/nope/cancel", headers=CAROL).status_code == 404


def test_the_jackpot(world: World) -> None:
    c = world.client
    ready(world)
    a, b, c1, c2 = gift(world, "alice"), gift(world, "bob"), gift(world, "carol"), gift(world, "carol", "j_mime")
    out_of_hold(world)
    assert c.get("/v1/casino/jackpot", headers=ALICE).json()["round"] is None
    # alone in the pot: no countdown, and the items can be taken back
    first = c.post("/v1/casino/jackpot", headers=ALICE, json={"items": [a]}).json()
    assert first["status"] == "open" and first["closes_at"] is None
    assert c.post("/v1/casino/jackpot/leave", headers=BOB).status_code == 403
    assert c.post("/v1/casino/jackpot/leave", headers=ALICE).json()["status"] == "cancelled"
    assert item(world, a)["item"]["staked"] is None
    # three players: the second starts the countdown
    pot = c.post("/v1/casino/jackpot", headers=ALICE, json={"items": [a]}).json()
    assert pot["id"] != first["id"]
    world.clock.advance(seconds=5)
    pot = c.post("/v1/casino/jackpot", headers=BOB, json={"items": [b]}).json()
    assert pot["closes_at"] is not None
    pot = c.post("/v1/casino/jackpot", headers=CAROL, json={"items": [c1, c2]}).json()
    assert [e["player"] for e in pot["entries"]] == ["alice", "bob", "carol"]
    assert abs(sum(e["chance"] for e in pot["entries"]) - 100) < 0.05
    assert pot["entries"][2]["value"] > pot["entries"][0]["value"]  # (Mime is uncommon: worth more)
    r = c.post("/v1/casino/jackpot/leave", headers=ALICE)
    assert r.status_code == 403 and r.json()["code"] == "not_allowed"
    state = c.get("/v1/casino/jackpot", headers=ALICE).json()
    assert state["round"]["id"] == pot["id"] and state["last"] is None
    # its time comes: the next look draws it
    world.clock.advance(seconds=60)
    state = c.get("/v1/casino/jackpot", headers=ALICE).json()
    assert state["round"] is None
    done = state["last"]
    assert done["id"] == pot["id"] and done["status"] == "done"
    check_draw(done)
    assert all(item(world, i)["item"]["owner"] == done["winner"] for i in (a, b, c1, c2))
    assert c.get(f"/v1/casino/games/{pot['id']}", headers=BOB).json()["winner"] == done["winner"]
    assert c.get("/v1/casino/games/nope", headers=BOB).status_code == 404


def test_a_due_pot_is_drawn_before_the_next_opens(world: World) -> None:
    c = world.client
    ready(world)
    a, b, a2 = gift(world, "alice"), gift(world, "bob"), gift(world, "alice", "j_lusty_joker")
    out_of_hold(world)
    c.post("/v1/casino/jackpot", headers=ALICE, json={"items": [a]})
    pot = c.post("/v1/casino/jackpot", headers=BOB, json={"items": [b]}).json()
    world.clock.advance(seconds=61)
    world.uses.settle_casino()  # (the service does it every few seconds)
    assert c.get(f"/v1/casino/games/{pot['id']}", headers=BOB).json()["status"] == "done"
    nxt = c.post("/v1/casino/jackpot", headers=ALICE, json={"items": [a2]}).json()
    assert nxt["id"] != pot["id"] and nxt["status"] == "open"


def test_the_casino_opens_after_a_first_win(world: World) -> None:
    c = world.client
    world.runs.add("alice", "r1", ante=5)
    find(world, ALICE)  # an item, but no win
    a = c.get("/v1/me/items", headers=ALICE).json()[0]["id"]
    out_of_hold(world)
    r = c.post("/v1/casino/coinflips", headers=ALICE, json={"items": [a]})
    assert r.status_code == 403 and r.json()["code"] == "trading_locked"
    r = c.post("/v1/casino/jackpot", headers=ALICE, json={"items": [a], "seed": "no:colons"})
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"


def test_items_in_their_hold_or_not_yours_cant_be_staked(world: World) -> None:
    c = world.client
    ready(world)
    a = gift(world, "alice")
    r = c.post("/v1/casino/coinflips", headers=ALICE, json={"items": [a]})
    assert r.status_code == 409 and r.json()["code"] == "item_locked"
    out_of_hold(world)
    r = c.post("/v1/casino/coinflips", headers=BOB, json={"items": [a]})
    assert r.status_code == 409 and r.json()["code"] == "not_owner"


def test_a_closed_casino_takes_nothing_but_gives_back() -> None:
    w = make_world(casino=False)
    ready(w)
    a = gift(w, "alice")
    out_of_hold(w)
    assert not w.client.get("/v1/casino/rules").json()["open"]
    r = w.client.post("/v1/casino/coinflips", headers=ALICE, json={"items": [a]})
    assert r.status_code == 403 and r.json()["code"] == "casino_closed"
    r = w.client.post("/v1/casino/jackpot", headers=ALICE, json={"items": [a]})
    assert r.status_code == 403 and r.json()["code"] == "casino_closed"
