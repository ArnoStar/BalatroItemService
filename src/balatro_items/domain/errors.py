"""Errors of the domain.  Each has a stable ``code`` that clients can rely on."""

from __future__ import annotations


class DomainError(Exception):
    code = "domain_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ItemNotFound(DomainError):
    code = "item_not_found"

    def __init__(self, item_id: str) -> None:
        super().__init__(f"no item {item_id!r}")


class PlayerNotFound(DomainError):
    code = "player_not_found"

    def __init__(self, player_id: str) -> None:
        super().__init__(f"no player {player_id!r} has items")


class TradeNotFound(DomainError):
    code = "trade_not_found"

    def __init__(self, trade_id: str) -> None:
        super().__init__(f"no trade {trade_id!r}")


class InvalidTrade(DomainError):
    """An offer that can't be made: no items, too many, the same player twice ..."""

    code = "invalid_trade"


class NotOwner(DomainError):
    """An item in an offer isn't its side's."""

    code = "not_owner"


class ItemLocked(DomainError):
    """An item is still in its trade hold (it changed hands recently)."""

    code = "item_locked"


class TradingLocked(DomainError):
    """A player can't trade before their first counted win."""

    code = "trading_locked"


class TradeClosed(DomainError):
    """The offer was accepted, declined, cancelled or has expired."""

    code = "trade_closed"


class ItemsMoved(DomainError):
    """An item of the offer has changed hands (or is held) since it was made."""

    code = "items_moved"


class TooManyOffers(DomainError):
    code = "too_many_offers"


class NotParticipant(DomainError):
    """The caller may not do this to this trade (accept their own offer ...)."""

    code = "not_allowed"
