from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from balatro_items.application.dto import DropsView, ItemDetail, ItemView, MeView, PlayerView
from balatro_items.presentation.http.deps import CurrentPlayer, Uses
from balatro_items.presentation.http.schemas import GiftRequest, ShowcaseRequest

router = APIRouter(prefix="/v1", tags=["items"])


@router.get("/me", response_model=MeView, summary="You: your items, your showcase, this week's drops")
def me(player: CurrentPlayer, uses: Uses) -> MeView:
    return uses.me(player)


@router.post("/me/drops", response_model=DropsView, summary="Find the items your runs have earned")
def find_items(player: CurrentPlayer, uses: Uses) -> DropsView:
    """Reads your runs from the game's server and gives the items they have earned (GET /v1/odds
    says how): each at most once. ``found`` is empty when there is nothing new. The game calls it
    when you come back to the title screen."""
    return uses.sync(player)


@router.get("/me/items", response_model=list[ItemView], summary="Your items, newest first")
def my_items(player: CurrentPlayer, uses: Uses) -> list[ItemView]:
    return uses.my_items(player)


@router.put("/me/showcase", response_model=MeView, summary="Show one of your items")
def set_showcase(body: ShowcaseRequest, player: CurrentPlayer, uses: Uses) -> MeView:
    """The item on your title screen (in place of the game's Ace) and on your profile."""
    return uses.showcase(player, body.item)


@router.get("/items/{item_id}", response_model=ItemDetail, summary="An item and who has had it")
def item(item_id: str, player: CurrentPlayer, uses: Uses) -> ItemDetail:
    return uses.item(player, item_id)


@router.get("/players", response_model=list[PlayerView], summary="Players by name")
def find_players(player: CurrentPlayer, uses: Uses,
                 q: Annotated[str, Query(min_length=1, max_length=40, description="the start of a name")]
                 ) -> list[PlayerView]:
    return uses.find_players(player, q)


@router.get("/players/{player_id}", response_model=PlayerView, summary="A player's showcase")
def player_view(player_id: str, player: CurrentPlayer, uses: Uses) -> PlayerView:
    return uses.player(player, player_id)


@router.get("/players/{player_id}/items", response_model=list[ItemView], summary="A player's items")
def player_items(player_id: str, player: CurrentPlayer, uses: Uses) -> list[ItemView]:
    """Inventories are public: what one could ask for in a trade."""
    return uses.player_items(player, player_id)


@router.post("/admin/gifts", response_model=ItemView, status_code=status.HTTP_201_CREATED,
             summary="Give an item (admins)")
def give(body: GiftRequest, player: CurrentPlayer, uses: Uses) -> ItemView:
    """For events and prizes: the only way to make an item outside the drops. Its source says
    ``gift``."""
    return uses.give(player, body.to_dto())
