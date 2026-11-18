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
from .routes import casino, items, meta, shop, trades

DESCRIPTION = """
Collectible items of Balatro: the game's cards (jokers, tarot, planet and
spectral cards, playing cards) with the upgrades the game gives them, linked
to the players' accounts. Playing earns **coins** (a few a week, and some for
each new deck and stake won: `GET /v1/odds`); coins buy **boosters**, packs of
cards to choose from, and items other players sell on the **market**. Items
are shown on the title screen and profile, traded between players, sold, and
staked in the casino (coinflips, dice and a jackpot, between players only;
live at `/v1/casino/live`). They change nothing in a run.

With sign-in on, every route but `/health`, `/v1/odds`, `/v1/boosters` and
`/v1/casino/rules` needs an access token from the identity service.
"""


log = logging.getLogger(__name__)

SETTLE_EVERY = 1.0  # seconds: how often the jackpot is drawn when its time has come (if nobody looks at it)


async def settle_casino(use_cases: UseCases, every: float) -> None:
    while True:
        try:
            await asyncio.to_thread(use_cases.settle_casino)
        except Exception:
            log.exception("the jackpot couldn't be drawn")
        await asyncio.sleep(every)


def create_app(use_cases: UseCases, cors_origins: Sequence[str] = ("*",), heartbeat: float = 20) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(settle_casino(use_cases, SETTLE_EVERY))
        yield
        task.cancel()

    app = FastAPI(title="Balatro items", version=__version__, description=DESCRIPTION, lifespan=lifespan)
    app.state.use_cases = use_cases
    app.state.heartbeat = heartbeat  # seconds between a live stream's keep-alive comments
    app.add_middleware(CORSMiddleware, allow_origins=list(cors_origins), allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["Location", "WWW-Authenticate"])
    errors.install(app)
    app.include_router(meta.router)
    app.include_router(items.router)
    app.include_router(trades.router)
    app.include_router(shop.router)
    app.include_router(casino.router)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("docs")

    return app
