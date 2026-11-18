"""The market: players sell their items to other players, for the coins they ask.

A player lists an item at a price (``MIN_PRICE`` to ``MAX_PRICE`` coins);
another player buys it, all at once: the coins go from the buyer to the seller
and the item from the seller to the buyer, or nothing moves. The seller may
take the item off the market until then. The market makes no item and keeps
no coin (no house, no cut).

It plays by the trade rules: both players must have won a counted run (a new
account can't pass coins or items along), only items out of their trade hold
are listed, and an item bought starts its hold. A listed item stays its
seller's, but can't be traded, staked nor listed again until it is sold or
taken off.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from .errors import InvalidListing, ItemsMoved, ListingClosed, NotParticipant
from .items import Item

MIN_PRICE = 1
MAX_PRICE = 1_000_000_000
MAX_LISTINGS = 50  # a player's items on the market at once


class ListingStatus(StrEnum):
    OPEN = "open"  # for sale
    SOLD = "sold"
    CANCELLED = "cancelled"  # taken off by its seller


@dataclass(kw_only=True)
class Listing:
    id: str
    seller: str
    item: str
    price: int  # coins
    status: ListingStatus
    created_at: datetime
    updated_at: datetime
    buyer: str | None = None


def check_price(price: int) -> None:
    if not MIN_PRICE <= price <= MAX_PRICE:
        raise InvalidListing(f"a price is from {MIN_PRICE:,} to {MAX_PRICE:,} coins")


def take_off(listing: Listing, item: Item | None, player: str, now: datetime) -> None:
    """The seller takes their item off the market."""
    if listing.seller != player:
        raise NotParticipant("only its seller takes an item off the market")
    if listing.status is not ListingStatus.OPEN:
        raise ListingClosed(f"this listing is {listing.status.value}")
    listing.status = ListingStatus.CANCELLED
    listing.updated_at = now
    if item is not None and item.listed == listing.id:
        item.listed = None


def sell(listing: Listing, item: Item | None, buyer: str, now: datetime, hold: timedelta) -> str:
    """The buyer takes the item (their coins are the application's to move, in the same transaction). Returns the
    seller."""
    if listing.status is not ListingStatus.OPEN:
        raise ListingClosed(f"this listing is {listing.status.value}")
    if buyer == listing.seller:
        raise InvalidListing("an item on the market is bought by another player")
    if item is None or item.owner != listing.seller or item.listed != listing.id:
        raise ItemsMoved("this item isn't for sale any more")
    listing.status = ListingStatus.SOLD
    listing.buyer = buyer
    listing.updated_at = now
    item.owner = buyer
    item.listed = None
    item.acquired_at = now
    item.tradable_at = now + hold
    return listing.seller
