"""The FastAPI application."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from balatro_items import __version__
from balatro_items.application.use_cases import UseCases

from . import errors
from .routes import casino, items, meta, trades

DESCRIPTION = """
Collectible items of Balatro: jokers and tags with the game's editions,
linked to the players' accounts. They are found by playing (a few a week,
and one for each new deck and stake won: `GET /v1/odds`), shown on the title
screen and profile, traded between players, and staked in the casino
(coinflips and a jackpot, between players only). They change nothing in a run.

With sign-in on, every route but `/health` and `/v1/odds` needs an access
token from the identity service.
"""


log = logging.getLogger(__name__)

SETTLE_EVERY = 2.0  # seconds: how often the jackpot is drawn when its time has come (if nobody looks at it)


async def settle_casino(use_cases: UseCases, every: float) -> None:
    while True:
        try:
            await asyncio.to_thread(use_cases.settle_casino)
        except Exception:
            log.exception("the jackpot couldn't be drawn")
        await asyncio.sleep(every)


def create_app(use_cases: UseCases, cors_origins: Sequence[str] = ("*",)) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(settle_casino(use_cases, SETTLE_EVERY))
        yield
        task.cancel()

    app = FastAPI(title="Balatro items", version=__version__, description=DESCRIPTION, lifespan=lifespan)
    app.state.use_cases = use_cases
    app.add_middleware(CORSMiddleware, allow_origins=list(cors_origins), allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["Location", "WWW-Authenticate"])
    errors.install(app)
    app.include_router(meta.router)
    app.include_router(items.router)
    app.include_router(trades.router)
    app.include_router(casino.router)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("docs")

    return app
