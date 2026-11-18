"""The casino's games: stakes, the draw, who takes what."""

from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta

import pytest

from balatro_items.domain import (
    JACKPOT_MAX_ITEMS,
    JACKPOT_MAX_PLAYERS,
    MAX_CHANCE,
    MIN_CHANCE,
    Edition,
    Entry,
    Game,
    GameClosed,
    GameStatus,
    InvalidBet,
    Item,
    ItemLocked,
    ItemsMoved,
    Kind,
    Mode,
    NotParticipant,
    Rarity,
    Side,
    cancel,
    check_bet,
    check_challenge,
    check_chance,
    check_items,
    coinflip_range,
    draw,
    join_duel,
    join_jackpot,
    join_range,
    parts,
    pay_out,
    seed_hash,
    tally,
    winner_chance,
)
from balatro_items.domain.casino import roll, winner_of
from tests.fakes import T0

HOLD = timedelta(days=7)
WAIT = timedelta(seconds=60)


def item(item_id: str, owner: str, staked: str | None = None) -> Item:
    return Item(id=item_id, kind=Kind.JOKER, key="j_joker", edition=Edition.BASE, rarity=Rarity.COMMON, stake=None,
                serial=1, owner=owner, source="weekly", source_run=None, created_at=T0, acquired_at=T0,
                tradable_at=T0, staked=staked, condition=0.3)


def entry(player: str, value: int, *items: str, seed: str = "s") -> Entry:
    return Entry(player=player, items=items or (f"{player}1",), value=value, seed=seed, at=T0)


def game(mode: Mode = Mode.COINFLIP, *entries: Entry, server_seed: str = "secret") -> Game:
    return Game(id="g1", mode=mode, status=GameStatus.OPEN, side=Side.CHIPS if mode is Mode.COINFLIP else None,
                entries=list(entries), server_seed=server_seed, created_at=T0, updated_at=T0)


def test_the_roll_is_the_published_hmac() -> None:
    digest = hmac.new(b"secret", b"g1:alice-seed:bob-seed", hashlib.sha256).hexdigest()
    assert roll("secret", "g1", ["alice-seed", "bob-seed"], 1000) == int(digest[:13], 16) * 1000 // 16**13
    assert seed_hash("secret") == hashlib.sha256(b"secret").hexdigest()
    assert all(0 <= roll(f"s{i}", "g", ["a"], 7) < 7 for i in range(200))


def test_each_entry_has_its_part_of_the_pot() -> None:
    es = [entry("a", 10), entry("b", 30), entry("c", 60)]
    assert parts(es) == [(0, 10), (10, 40), (40, 100)]
    assert [winner_of(es, p) for p in (0, 9, 10, 39, 40, 99)] == ["a", "a", "b", "b", "c", "c"]
    with pytest.raises(ValueError):
        winner_of(es, 100)


def test_the_chance_is_the_share_of_the_pot() -> None:
    wins = 0
    n = 20000
    for i in range(n):
        g = game(Mode.COINFLIP, entry("a", 25), entry("b", 75), server_seed=f"server-{i}")
        draw(g, T0)
        wins += g.winner == "a"
    assert abs(wins / n - 0.25) < 0.015


def test_stakes() -> None:
    check_bet(["a1"], "my-seed_1")
    for ids, seed in (([], "s"), ([f"x{i}" for i in range(11)], "s"), (["a1", "a1"], "s"), (["a1"], ""),
                      (["a1"], "x" * 65), (["a1"], "a:b"), (["a1"], "é")):
        with pytest.raises(InvalidBet):
            check_bet(ids, seed)


def test_staked_items_cant_change_hands() -> None:
    items = {"a1": item("a1", "alice", staked="g1")}
    with pytest.raises(ItemLocked):
        check_items("alice", ["a1"], items, T0, moved=False)
    with pytest.raises(ItemsMoved):
        check_items("alice", ["a1"], items, T0, moved=True)
    assert not items["a1"].tradable(T0)


def test_a_coinflip_is_matched_within_its_margin() -> None:
    assert coinflip_range(100) == (90, 110)
    assert coinflip_range(121) == (109, 133)
    assert coinflip_range(1) == (1, 1)
    g = game(Mode.COINFLIP, entry("alice", 100))
    with pytest.raises(NotParticipant):
        join_duel(g, entry("alice", 100))
    for value in (89, 111):
        with pytest.raises(InvalidBet):
            join_duel(g, entry("bob", value))
    join_duel(g, entry("bob", 110))
    draw(g, T0)
    assert g.status is GameStatus.DONE and g.winner in ("alice", "bob") and g.roll is not None and 0 <= g.roll < 210
    with pytest.raises(GameClosed):
        join_duel(g, entry("carol", 100))


def test_the_jackpot_counts_down_from_the_second_player() -> None:
    g = game(Mode.JACKPOT, entry("alice", 50))
    join_jackpot(g, entry("alice", 20, "alice2"), WAIT)
    assert g.closes_at is None and g.players == ["alice"]
    with pytest.raises(InvalidBet):
        draw(g, T0)  # alone
    later = T0 + timedelta(seconds=5)
    join_jackpot(g, Entry(player="bob", items=("bob1",), value=30, seed="s", at=later), WAIT)
    assert g.closes_at == later + WAIT and g.value == 100
    join_jackpot(g, entry("carol", 10), WAIT)
    assert g.closes_at == later + WAIT  # (not pushed back)
    assert not g.due(later + WAIT - timedelta(seconds=1)) and g.due(later + WAIT)
    with pytest.raises(GameClosed):
        join_jackpot(g, Entry(player="dan", items=("dan1",), value=1, seed="s", at=later + WAIT), WAIT)


def test_the_jackpot_has_room_for_so_many() -> None:
    g = game(Mode.JACKPOT, *[entry(f"p{i}", 1) for i in range(JACKPOT_MAX_PLAYERS)])
    with pytest.raises(InvalidBet):
        join_jackpot(g, entry("one-more", 1), WAIT)
    join_jackpot(g, entry("p0", 1, "p0-2"), WAIT)  # (a player already in may add items)
    g = game(Mode.JACKPOT, entry("alice", 1, *[f"a{i}" for i in range(JACKPOT_MAX_ITEMS)]))
    with pytest.raises(InvalidBet):
        join_jackpot(g, entry("bob", 1), WAIT)


def test_the_winner_takes_the_others_items() -> None:
    g = game(Mode.JACKPOT, entry("alice", 40, "a1"), entry("bob", 60, "b1", "b2"), entry("alice", 0, "a2"))
    g.roll, g.winner, g.status = 50, "bob", GameStatus.DONE
    owners = {"a": "alice", "b": "bob"}
    items = {i: item(i, owners[i[0]], staked="g1") for i in ("a1", "a2", "b1", "b2")}
    later = T0 + timedelta(hours=1)
    moved = pay_out(g, items, later, HOLD)
    assert sorted((i.id, before) for i, before in moved) == [("a1", "alice"), ("a2", "alice")]
    assert all(i.owner == "bob" and i.staked is None for i in items.values())
    assert items["a1"].tradable_at == later + HOLD and items["b1"].tradable_at == T0  # (bob's own didn't move)


def test_a_cancelled_game_gives_everything_back() -> None:
    g = game(Mode.COINFLIP, entry("alice", 10, "a1"))
    with pytest.raises(NotParticipant):
        cancel(g, "bob", T0)
    items = {"a1": item("a1", "alice", staked="g1")}
    with pytest.raises(GameClosed):
        pay_out(g, items, T0, HOLD)  # (not over)
    cancel(g, "alice", T0)
    assert pay_out(g, items, T0, HOLD) == [] and items["a1"].staked is None and items["a1"].owner == "alice"
    with pytest.raises(GameClosed):
        cancel(g, "alice", T0)
    g = game(Mode.JACKPOT, entry("alice", 10), entry("bob", 10))
    with pytest.raises(NotParticipant):
        cancel(g, "alice", T0)  # (someone else is in)


def test_a_dice_game_is_matched_for_the_chance_asked() -> None:
    assert join_range(100, 50) == (90, 110)  # (a coinflip)
    assert join_range(100, 25) == (270, 330)  # three times as much, 10% more or less
    assert join_range(100, 90) == (10, 12)
    assert join_range(1000, 10) == (8100, 9900)
    check_chance(MIN_CHANCE)
    check_chance(MAX_CHANCE)
    for bad in (MIN_CHANCE - 1, MAX_CHANCE + 1, 0, 100):
        with pytest.raises(InvalidBet):
            check_chance(bad)
    g = game(Mode.DICE, entry("alice", 100))
    g.chance = 25
    with pytest.raises(InvalidBet):
        join_duel(g, entry("bob", 110))  # (a coinflip's match is not enough)
    join_duel(g, entry("bob", 300))
    draw(g, T0)
    assert parts(g.entries) == [(0, 100), (100, 400)]  # (the first part of the pot is the first player's)
    assert g.winner == ("alice" if g.roll is not None and g.roll < 100 else "bob")


def test_the_dice_keep_their_odds() -> None:
    wins, n = 0, 20000
    for i in range(n):
        g = game(Mode.DICE, entry("a", 10), entry("b", 90), server_seed=f"dice-{i}")
        draw(g, T0)
        wins += g.winner == "a"
    assert abs(wins / n - 0.10) < 0.01


def test_a_challenge_is_for_one_player() -> None:
    check_challenge("alice", None)
    check_challenge("alice", "bob")
    with pytest.raises(InvalidBet):
        check_challenge("alice", "alice")
    g = game(Mode.COINFLIP, entry("alice", 100))
    g.opponent = "bob"
    with pytest.raises(NotParticipant):
        join_duel(g, entry("carol", 100))
    join_duel(g, entry("bob", 100))
    assert g.players == ["alice", "bob"]


def test_the_tally_of_a_players_games() -> None:
    def done(gid: str, mode: Mode, winner: str, *entries: Entry) -> Game:
        g = game(mode, *entries)
        g.id, g.status, g.winner, g.roll = gid, GameStatus.DONE, winner, 0
        return g

    games = [
        done("g1", Mode.COINFLIP, "alice", entry("alice", 100), entry("bob", 100)),
        done("g2", Mode.DICE, "alice", entry("alice", 10), entry("bob", 90)),
        done("g3", Mode.JACKPOT, "bob", entry("alice", 50), entry("bob", 30), entry("alice", 20)),
        game(Mode.COINFLIP, entry("alice", 999)),  # (open: doesn't count)
    ]
    t = tally(games)
    alice, bob = t["alice"], t["bob"]
    assert (alice.games, alice.wins, alice.staked, alice.won, alice.lost, alice.net) == (3, 2, 180, 190, 70, 120)
    assert (bob.games, bob.wins, bob.staked, bob.won, bob.lost, bob.net) == (3, 1, 220, 70, 190, -120)
    assert alice.by_mode == {Mode.COINFLIP: (1, 1), Mode.DICE: (1, 1), Mode.JACKPOT: (1, 0)}
    assert alice.biggest is not None and alice.biggest.id == "g1"  # (the biggest pot: 200)
    assert alice.luckiest is not None and alice.luckiest.id == "g2" and winner_chance(alice.luckiest) == 0.1
    assert bob.luckiest is not None and bob.luckiest.id == "g3" and winner_chance(bob.luckiest) == 0.3
