"""The FastAPI application."""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from balatro_items import __version__
from balatro_items.application.use_cases import UseCases

from . import errors
from .routes import items, meta, trades

DESCRIPTION = """
Collectible items of Balatro: jokers and tags with the game's editions,
linked to the players' accounts. They are found by playing (a few a week,
and one for each new deck and stake won: `GET /v1/odds`), shown on the title
screen and profile, and traded between players. They change nothing in a run.

With sign-in on, every route but `/health` and `/v1/odds` needs an access
token from the identity service.
"""


def create_app(use_cases: UseCases, cors_origins: Sequence[str] = ("*",)) -> FastAPI:
    app = FastAPI(title="Balatro items", version=__version__, description=DESCRIPTION)
    app.state.use_cases = use_cases
    app.add_middleware(CORSMiddleware, allow_origins=list(cors_origins), allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["Location", "WWW-Authenticate"])
    errors.install(app)
    app.include_router(meta.router)
    app.include_router(items.router)
    app.include_router(trades.router)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("docs")

    return app
