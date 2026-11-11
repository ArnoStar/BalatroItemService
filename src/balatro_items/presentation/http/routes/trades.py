from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, status

from balatro_items.application.dto import TradeView
from balatro_items.presentation.http.deps import CurrentPlayer, Uses
from balatro_items.presentation.http.schemas import TradeRequest

router = APIRouter(prefix="/v1/trades", tags=["trades"])


@router.get("", response_model=list[TradeView], summary="Your trades, newest first")
def trades(player: CurrentPlayer, uses: Uses,
           box: Annotated[Literal["all", "incoming", "outgoing"], Query()] = "all") -> list[TradeView]:
    return uses.trades(player, box)


@router.post("", response_model=TradeView, status_code=status.HTTP_201_CREATED, summary="Make an offer")
def create(body: TradeRequest, player: CurrentPlayer, uses: Uses) -> TradeView:
    """Your items (``give``) for theirs (``take``); either side may be empty (a gift, or a
    request). Both players must have won a counted run, and every item must be out of its trade
    hold. The offer stays open for 14 days."""
    return uses.create_trade(player, body.to_dto())


@router.get("/{trade_id}", response_model=TradeView, summary="A trade of yours")
def get(trade_id: str, player: CurrentPlayer, uses: Uses) -> TradeView:
    return uses.trade(player, trade_id)


@router.post("/{trade_id}/accept", response_model=TradeView, summary="Accept an offer made to you")
def accept(trade_id: str, player: CurrentPlayer, uses: Uses) -> TradeView:
    """Every item changes hands at once (or none, ``409 items_moved``, if one has moved since),
    and starts its trade hold."""
    return uses.accept(player, trade_id)


@router.post("/{trade_id}/decline", response_model=TradeView, summary="Decline an offer made to you")
def decline(trade_id: str, player: CurrentPlayer, uses: Uses) -> TradeView:
    return uses.decline(player, trade_id)


@router.post("/{trade_id}/cancel", response_model=TradeView, summary="Cancel your offer")
def cancel(trade_id: str, player: CurrentPlayer, uses: Uses) -> TradeView:
    return uses.cancel(player, trade_id)
