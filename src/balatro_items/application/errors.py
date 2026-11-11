"""Errors of the application (who may call what, and the services it needs)."""

from __future__ import annotations

from balatro_items.domain import DomainError


class NotAuthenticated(DomainError):
    code = "unauthenticated"


class AuthUnavailable(DomainError):
    code = "auth_unavailable"


class NotAdmin(DomainError):
    code = "not_admin"


class GameApiUnavailable(DomainError):
    """The game API (runs, catalog) can't be reached."""

    code = "game_api_unavailable"


class UnknownTemplate(DomainError):
    code = "unknown_item"
