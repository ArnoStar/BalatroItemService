"""Trades: a player offers some of their items for some of another's.

The other player accepts (the items change hands at once, all or none),
declines, or lets it expire; the sender may cancel it until then. Both must
have won a counted run (a new account can't pass items along), and every
item must be out of its trade hold: an item that changes hands can't again
for a while (``hold``), so items can't be funnelled through accounts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from .errors import InvalidTrade, ItemLocked, ItemsMoved, NotOwner, TradeClosed
from .items import Item

MAX_SIDE = 10  # items on each side of an offer
MAX_PENDING = 20  # a player's open offers
OFFER_LIFETIME = timedelta(days=14)
MAX_MESSAGE = 280


class TradeStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(kw_only=True)
class Trade:
    id: str
    sender: str
    recipient: str
    give: tuple[str, ...]  # the sender's items
    take: tuple[str, ...]  # the recipient's items
    message: str
    status: TradeStatus
    created_at: datetime
    updated_at: datetime
    expires_at: datetime

    def status_at(self, now: datetime) -> TradeStatus:
        if self.status is TradeStatus.PENDING and now >= self.expires_at:
            return TradeStatus.EXPIRED
        return self.status

    def close(self, status: TradeStatus, now: datetime) -> None:
        if self.status_at(now) is not TradeStatus.PENDING:
            raise TradeClosed(f"this offer is {self.status_at(now).value}")
        self.status = status
        self.updated_at = now


def check_offer(sender: str, recipient: str, give: Sequence[str], take: Sequence[str], message: str) -> None:
    """What an offer must be, whatever the items are."""
    if sender == recipient:
        raise InvalidTrade("an offer is made to another player")
    if not give and not take:
        raise InvalidTrade("an offer has at least one item")
    if len(give) > MAX_SIDE or len(take) > MAX_SIDE:
        raise InvalidTrade(f"at most {MAX_SIDE} items on each side")
    if len(set(give)) != len(give) or len(set(take)) != len(take) or set(give) & set(take):
        raise InvalidTrade("an item is in the offer twice")
    if len(message) > MAX_MESSAGE:
        raise InvalidTrade(f"the message is at most {MAX_MESSAGE} characters")


def check_items(owner: str, ids: Sequence[str], items: dict[str, Item], now: datetime, *, moved: bool) -> None:
    """Each item is ``owner``'s and out of its trade hold (``moved``: say that the offer is out of date)."""
    for i in ids:
        item = items.get(i)
        if item is None or item.owner != owner:
            if moved:
                raise ItemsMoved("an item of this offer has changed hands since")
            raise NotOwner(f"item {i!r} isn't this player's")
        if not item.tradable(now):
            if moved:
                raise ItemsMoved("an item of this offer has changed hands since: it is in its trade hold")
            raise ItemLocked(f"item {i!r} can be traded from {item.tradable_at.isoformat()}")


def swap(trade: Trade, items: dict[str, Item], now: datetime, hold: timedelta) -> list[tuple[Item, str]]:
    """Accepts the offer: every item changes hands (checked first: all or none). Returns
    each moved item with its former owner."""
    check_items(trade.sender, trade.give, items, now, moved=True)
    check_items(trade.recipient, trade.take, items, now, moved=True)
    trade.close(TradeStatus.ACCEPTED, now)
    moved: list[tuple[Item, str]] = []
    for ids, to in ((trade.give, trade.recipient), (trade.take, trade.sender)):
        for i in ids:
            item = items[i]
            moved.append((item, item.owner))
            item.owner = to
            item.acquired_at = now
            item.tradable_at = now + hold
    return moved
