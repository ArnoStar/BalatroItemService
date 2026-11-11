from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from balatro_items import __version__
from balatro_items.application.dto import OddsView
from balatro_items.presentation.http.deps import Uses

router = APIRouter(tags=["meta"])


@router.get("/health", summary="Is the service up")
def health(request: Request) -> dict[str, Any]:
    uses = request.app.state.use_cases
    return {"status": "ok", "version": __version__,
            "auth": "required" if uses.authenticate.authenticator.required else "off"}


@router.get("/v1/odds", response_model=OddsView, summary="How items are found, in numbers")
def drop_odds(uses: Uses) -> OddsView:
    """The rules that give items, each table's chances (kind, rarity, edition, in percent), how
    many jokers and tags each rarity has, and the trade hold. Public."""
    return uses.odds()
