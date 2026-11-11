"""The composition root: picks the adapters and builds the use cases."""

from __future__ import annotations

import logging
from datetime import timedelta

from .application.ports import Authenticator, Catalog, Clock, IdGenerator, RunSource, Store
from .application.use_cases import Deps, UseCases, build
from .config import Settings
from .domain import Random
from .infrastructure.auth import AnonymousAuthenticator, JwtAuthenticator
from .infrastructure.game_api import GameApi
from .infrastructure.persistence import MemoryStore, PostgresStore
from .infrastructure.system import SystemClock, SystemRandom, UuidGenerator

log = logging.getLogger(__name__)


def build_authenticator(settings: Settings) -> Authenticator:
    if settings.auth_jwks_url and settings.auth_issuer:
        return JwtAuthenticator.from_jwks_url(settings.auth_jwks_url, settings.auth_issuer, settings.auth_audience)
    log.warning("sign-in is off (BALATRO_ITEMS_AUTH_JWKS_URL is not set): every caller is the same player, an admin")
    return AnonymousAuthenticator()


def build_store(settings: Settings) -> Store:
    if settings.database == "memory":
        return MemoryStore()
    return PostgresStore(settings.database)


def build_use_cases(settings: Settings, *, store: Store | None = None, catalog: Catalog | None = None,
                    runs: RunSource | None = None, clock: Clock | None = None, ids: IdGenerator | None = None,
                    rng: Random | None = None, authenticator: Authenticator | None = None) -> UseCases:
    auth = authenticator or build_authenticator(settings)
    api = GameApi(settings.api_url) if catalog is None or runs is None else None
    deps = Deps(store=store if store is not None else build_store(settings), catalog=catalog or api,  # type: ignore[arg-type]
                runs=runs or api, clock=clock or SystemClock(), ids=ids or UuidGenerator(),  # type: ignore[arg-type]
                rng=rng or SystemRandom(), hold=timedelta(days=settings.trade_hold_days),
                admins=frozenset(settings.admins), auth_required=auth.required)
    return build(deps, auth)
