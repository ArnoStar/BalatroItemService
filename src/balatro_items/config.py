"""Settings, from BALATRO_ITEMS_* environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

# the database of `make db` (BalatroFrontEnd's docker-compose.yml, service items-db)
DEFAULT_DATABASE = "postgresql://items:items@127.0.0.1:55435/items"


@dataclass(frozen=True)
class Settings:
    database: str = DEFAULT_DATABASE  # a PostgreSQL URL, or "memory" (everything is lost when the service stops)
    api_url: str = "http://127.0.0.1:8000"  # the game API (BalatroWebAPI), without /api/v1
    cors_origins: tuple[str, ...] = ("*",)
    admins: tuple[str, ...] = ()  # account ids that may give items, besides the admin role
    trade_hold_days: float = 7  # an item that changes hands (or is found) can't again for this long
    casino: bool = True  # False: nothing can be staked in the casino (staked items can still be taken back)
    jackpot_seconds: float = 60  # from the second player in the jackpot to its draw
    # sign-in with the identity service: on when the JWKS URL is set; then the issuer is required too
    auth_jwks_url: str | None = None
    auth_issuer: str | None = None
    auth_audience: str = "balatro"

    def __post_init__(self) -> None:
        if self.database != "memory" and not self.database.startswith(("postgresql://", "postgres://")):
            raise ValueError("BALATRO_ITEMS_DATABASE_URL is a postgresql:// URL or 'memory'")
        if self.auth_jwks_url and not self.auth_issuer:
            raise ValueError("BALATRO_ITEMS_AUTH_ISSUER is required with BALATRO_ITEMS_AUTH_JWKS_URL")
        if self.trade_hold_days < 0:
            raise ValueError("BALATRO_ITEMS_TRADE_HOLD_DAYS can't be negative")
        if self.jackpot_seconds <= 0:
            raise ValueError("BALATRO_ITEMS_JACKPOT_SECONDS is more than 0")

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Settings:
        d = cls()

        def items(name: str) -> tuple[str, ...]:
            return tuple(x.strip() for x in env.get(name, "").split(",") if x.strip())

        return cls(
            database=env.get("BALATRO_ITEMS_DATABASE_URL") or d.database,
            api_url=env.get("BALATRO_ITEMS_API_URL") or d.api_url,
            cors_origins=items("BALATRO_ITEMS_CORS_ORIGINS") or d.cors_origins,
            admins=items("BALATRO_ITEMS_ADMINS"),
            trade_hold_days=float(env.get("BALATRO_ITEMS_TRADE_HOLD_DAYS", d.trade_hold_days)),
            casino=env.get("BALATRO_ITEMS_CASINO", "on").strip().lower() not in ("off", "0", "false", "no"),
            jackpot_seconds=float(env.get("BALATRO_ITEMS_JACKPOT_SECONDS", d.jackpot_seconds)),
            auth_jwks_url=env.get("BALATRO_ITEMS_AUTH_JWKS_URL") or None,
            auth_issuer=(env.get("BALATRO_ITEMS_AUTH_ISSUER") or "").rstrip("/") or None,
            auth_audience=env.get("BALATRO_ITEMS_AUTH_AUDIENCE") or d.auth_audience,
        )
