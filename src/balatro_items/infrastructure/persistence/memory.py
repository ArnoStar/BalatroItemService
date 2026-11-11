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

from balatro_items.domain import Edition, Item, PlayerRecord, Trade, TradeStatus, Transfer


@dataclass
class _State:
    players: dict[str, PlayerRecord] = field(default_factory=dict)
    items: dict[str, Item] = field(default_factory=dict)
    serials: dict[tuple[str, str], int] = field(default_factory=dict)
    transfers: list[Transfer] = field(default_factory=list)
    claims: dict[str, dict[str, tuple[str, str | None, datetime]]] = field(default_factory=dict)
    trades: dict[str, Trade] = field(default_factory=dict)


class MemoryUnit:
    def __init__(self, state: _State) -> None:
        self.s = state

    def player(self, player_id: str, lock: bool = False) -> PlayerRecord | None:
        p = self.s.players.get(player_id)
        return copy.copy(p) if p else None

    def save_player(self, p: PlayerRecord) -> None:
        self.s.players[p.id] = copy.copy(p)

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
        k = (item.key, item.edition.value)
        self.s.serials[k] = self.s.serials.get(k, 0) + 1
        item = copy.copy(item)
        item.serial = self.s.serials[k]
        self.s.items[item.id] = item
        return copy.copy(item)

    def save_item(self, item: Item) -> None:
        self.s.items[item.id] = copy.copy(item)

    def minted(self, key: str, edition: Edition) -> int:
        return self.s.serials.get((key, edition.value), 0)

    def add_transfer(self, t: Transfer) -> None:
        self.s.transfers.append(t)

    def transfers(self, item_id: str) -> builtins.list[Transfer]:
        return [t for t in self.s.transfers if t.item == item_id]

    def claims(self, owner: str) -> set[str]:
        return set(self.s.claims.get(owner, {}))

    def claim(self, owner: str, source: str, item_id: str, run: str | None, at: datetime) -> bool:
        mine = self.s.claims.setdefault(owner, {})
        if source in mine:
            return False
        mine[source] = (item_id, run, at)
        return True

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
