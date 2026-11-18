"""Everything kept in memory (lost when the service stops), for tests and demos.

A unit holds the store's lock and works on a copy of the state, which replaces
the state only when the unit ends without an error: all or nothing, as a
database transaction."""

from __future__ import annotations

import builtins
import copy
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime

from balatro_items.application.dto import ListingQuery
from balatro_items.domain import (
    CoinMove,
    Edition,
    Game,
    GameStatus,
    Item,
    Listing,
    ListingStatus,
    Mode,
    NotEnoughCoins,
    Pack,
    PackStatus,
    PlayerNotFound,
    PlayerRecord,
    Trade,
    TradeStatus,
    Transfer,
)


@dataclass
class _State:
    players: dict[str, PlayerRecord] = field(default_factory=dict)
    items: dict[str, Item] = field(default_factory=dict)
    serials: dict[tuple[str, str], int] = field(default_factory=dict)
    transfers: list[Transfer] = field(default_factory=list)
    claims: dict[str, dict[str, tuple[str | None, datetime, int]]] = field(default_factory=dict)
    trades: dict[str, Trade] = field(default_factory=dict)
    games: dict[str, Game] = field(default_factory=dict)
    coin_moves: list[CoinMove] = field(default_factory=list)
    packs: dict[str, Pack] = field(default_factory=dict)
    listings: dict[str, Listing] = field(default_factory=dict)


class MemoryUnit:
    def __init__(self, state: _State) -> None:
        self.s = state

    def player(self, player_id: str, lock: bool = False) -> PlayerRecord | None:
        p = self.s.players.get(player_id)
        return copy.copy(p) if p else None

    def save_player(self, p: PlayerRecord) -> None:
        saved = self.s.players.get(p.id)
        p = copy.copy(p)
        p.coins = saved.coins if saved else 0  # (coins change only through add_coins)
        self.s.players[p.id] = p

    def find_players(self, query: str, limit: int) -> list[PlayerRecord]:
        q = query.lower()
        found = [p for p in self.s.players.values() if p.name and p.name.lower().startswith(q)]
        return [copy.copy(p) for p in sorted(found, key=lambda p: (p.name or "").lower())[:limit]]

    def item(self, item_id: str) -> Item | None:
        it = self.s.items.get(item_id)
        return copy.copy(it) if it else None

    def items(self, ids: Sequence[str], lock: bool = False) -> dict[str, Item]:
        return {i: copy.copy(self.s.items[i]) for i in ids if i in self.s.items}

    def items_of(self, owner: str) -> builtins.list[Item]:
        mine = [it for it in self.s.items.values() if it.owner == owner]
        return [copy.copy(it) for it in sorted(mine, key=lambda it: (it.acquired_at, it.id), reverse=True)]

    def add_item(self, item: Item) -> Item:
        k = (item.variant, item.edition.value)
        self.s.serials[k] = self.s.serials.get(k, 0) + 1
        item = copy.copy(item)
        item.serial = self.s.serials[k]
        self.s.items[item.id] = item
        return copy.copy(item)

    def save_item(self, item: Item) -> None:
        self.s.items[item.id] = copy.copy(item)

    def minted(self, variant: str, edition: Edition) -> int:
        return self.s.serials.get((variant, edition.value), 0)

    def add_transfer(self, t: Transfer) -> None:
        self.s.transfers.append(t)

    def transfers(self, item_id: str) -> builtins.list[Transfer]:
        return [t for t in self.s.transfers if t.item == item_id]

    def claims(self, owner: str) -> set[str]:
        return set(self.s.claims.get(owner, {}))

    def claim(self, owner: str, source: str, run: str | None, at: datetime, coins: int) -> bool:
        mine = self.s.claims.setdefault(owner, {})
        if source in mine:
            return False
        mine[source] = (run, at, coins)
        return True

    def add_coins(self, player: str, amount: int, reason: str, ref: str | None, at: datetime) -> int:
        p = self.s.players.get(player)
        if p is None:
            raise PlayerNotFound(player)
        if p.coins + amount < 0:
            raise NotEnoughCoins(f"this takes {-amount:,} coins and you have {p.coins:,}")
        p.coins += amount
        self.s.coin_moves.append(CoinMove(player=player, amount=amount, balance=p.coins, reason=reason, ref=ref, at=at))
        return p.coins

    def coin_moves(self, player: str, limit: int) -> builtins.list[CoinMove]:
        return [m for m in reversed(self.s.coin_moves) if m.player == player][:limit]

    def pack(self, pack_id: str, lock: bool = False) -> Pack | None:
        p = self.s.packs.get(pack_id)
        return copy.deepcopy(p) if p else None

    def add_pack(self, p: Pack) -> None:
        self.s.packs[p.id] = copy.deepcopy(p)

    def save_pack(self, p: Pack) -> None:
        self.s.packs[p.id] = copy.deepcopy(p)

    def packs_of(self, owner: str, status: PackStatus | None, limit: int) -> builtins.list[Pack]:
        found = [p for p in self.s.packs.values() if p.owner == owner and (status is None or p.status is status)]
        found.sort(key=lambda p: (p.created_at, p.id), reverse=True)
        return [copy.deepcopy(p) for p in found[:limit]]

    def listing(self, listing_id: str, lock: bool = False) -> Listing | None:
        x = self.s.listings.get(listing_id)
        return copy.copy(x) if x else None

    def add_listing(self, x: Listing) -> None:
        if x.status is ListingStatus.OPEN and any(
                o.item == x.item and o.status is ListingStatus.OPEN for o in self.s.listings.values()):
            raise RuntimeError(f"item {x.item!r} has an open listing")  # (PostgreSQL's unique index)
        self.s.listings[x.id] = copy.copy(x)

    def save_listing(self, x: Listing) -> None:
        self.s.listings[x.id] = copy.copy(x)

    def listings(self, q: ListingQuery) -> builtins.list[Listing]:
        def wanted(x: Listing) -> bool:
            it = self.s.items.get(x.item)
            return (it is not None and (q.status is None or x.status is q.status)
                    and (q.kind is None or it.kind is q.kind) and (q.rarity is None or it.rarity == q.rarity)
                    and (q.edition is None or it.edition is q.edition) and (q.keys is None or it.key in q.keys)
                    and (q.variant is None or it.variant == q.variant) and (q.seller is None or x.seller == q.seller)
                    and (q.buyer is None or x.buyer == q.buyer)
                    and (q.player is None or q.player in (x.seller, x.buyer)))

        found = sorted((x for x in self.s.listings.values() if wanted(x)), key=lambda x: (x.updated_at, x.id),
                       reverse=True)
        if q.sort == "price":
            found.sort(key=lambda x: x.price)
        elif q.sort == "-price":
            found.sort(key=lambda x: -x.price)
        return [copy.copy(x) for x in found[q.offset:q.offset + q.limit]]

    def open_listings_of(self, seller: str) -> int:
        return sum(1 for x in self.s.listings.values() if x.seller == seller and x.status is ListingStatus.OPEN)

    def trade(self, trade_id: str, lock: bool = False) -> Trade | None:
        t = self.s.trades.get(trade_id)
        return copy.copy(t) if t else None

    def add_trade(self, t: Trade) -> None:
        self.s.trades[t.id] = copy.copy(t)

    def save_trade(self, t: Trade) -> None:
        self.s.trades[t.id] = copy.copy(t)

    def trades_of(self, player: str, box: str, limit: int) -> builtins.list[Trade]:
        def wanted(t: Trade) -> bool:
            return ((box in ("all", "incoming") and t.recipient == player)
                    or (box in ("all", "outgoing") and t.sender == player))

        found = sorted((t for t in self.s.trades.values() if wanted(t)), key=lambda t: (t.created_at, t.id),
                       reverse=True)
        return [copy.copy(t) for t in found[:limit]]

    def pending_from(self, sender: str, now: datetime) -> int:
        return sum(1 for t in self.s.trades.values()
                   if t.sender == sender and t.status_at(now) is TradeStatus.PENDING)

    def game(self, game_id: str, lock: bool = False) -> Game | None:
        g = self.s.games.get(game_id)
        return copy.deepcopy(g) if g else None

    def add_game(self, g: Game) -> None:
        self.s.games[g.id] = copy.deepcopy(g)

    def save_game(self, g: Game) -> None:
        self.s.games[g.id] = copy.deepcopy(g)

    def open_jackpot(self, lock: bool = False) -> Game | None:
        g = next((g for g in self.s.games.values() if g.mode is Mode.JACKPOT and g.status is GameStatus.OPEN), None)
        return copy.deepcopy(g) if g else None

    def games(self, mode: Mode | None, status: GameStatus, player: str | None, limit: int,
              since: datetime | None = None, before: datetime | None = None) -> builtins.list[Game]:
        found = [g for g in self.s.games.values() if g.status is status and (mode is None or g.mode is mode)
                 and (player is None or player in g.players) and (since is None or g.updated_at >= since)
                 and (before is None or g.updated_at < before)]
        found.sort(key=lambda g: (g.updated_at, g.id), reverse=True)
        return [copy.deepcopy(g) for g in found[:limit]]


class MemoryStore:
    def __init__(self) -> None:
        self._state = _State()
        self._lock = threading.RLock()

    @contextmanager
    def unit(self) -> Iterator[MemoryUnit]:
        with self._lock:
            work = copy.deepcopy(self._state)
            yield MemoryUnit(work)
            self._state = work
