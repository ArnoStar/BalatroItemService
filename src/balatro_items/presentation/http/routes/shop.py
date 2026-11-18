"""Coins, the boosters they buy and the packs bought, the market."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from balatro_items.application.dto import BoosterView, CoinMoveView, CoinsView, ListingView, PackView
from balatro_items.domain import Edition, Kind, PackStatus, Rarity
from balatro_items.presentation.http.deps import CurrentPlayer, Uses
from balatro_items.presentation.http.schemas import CoinGiftRequest, ListingRequest, PickRequest

router = APIRouter(prefix="/v1", tags=["shop"])


@router.get("/me/coins", response_model=CoinsView, summary="Your coins and where they came from")
def my_coins(player: CurrentPlayer, uses: Uses,
             limit: Annotated[int, Query(ge=1, le=500)] = 100) -> CoinsView:
    return uses.coins(player, limit)


@router.get("/boosters", response_model=list[BoosterView], summary="What coins buy")
def boosters(uses: Uses) -> list[BoosterView]:
    """Every booster: its kind of card, tier (the table its cards are rolled on), size (cards shown and chosen),
    price, and a card's chances. Public."""
    return uses.boosters()


@router.post("/boosters/{booster_id}/buy", response_model=PackView, status_code=status.HTTP_201_CREATED,
             summary="Buy a booster: a pack to choose from")
def buy_booster(booster_id: str, player: CurrentPlayer, uses: Uses) -> PackView:
    """Takes its price from your coins and rolls its cards at once: they stay the same until you choose
    (``POST /v1/packs/{id}/choose``)."""
    return uses.buy_booster(player, booster_id)


@router.get("/me/packs", response_model=list[PackView], summary="Your packs, newest first")
def my_packs(player: CurrentPlayer, uses: Uses,
             status_: Annotated[PackStatus | None,
                                Query(alias="status", description="none: every pack")] = PackStatus.OPEN,
             limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[PackView]:
    return uses.packs(player, status_, limit)


@router.get("/packs/{pack_id}", response_model=PackView, summary="One of your packs")
def pack(pack_id: str, player: CurrentPlayer, uses: Uses) -> PackView:
    return uses.pack(player, pack_id)


@router.post("/packs/{pack_id}/choose", response_model=PackView, summary="Choose your cards")
def choose(pack_id: str, body: PickRequest, player: CurrentPlayer, uses: Uses) -> PackView:
    """As many cards as the booster gives (``picks``): they become your items (``items``), the others are gone."""
    return uses.choose(player, pack_id, body.picks)


@router.get("/market", response_model=list[ListingView], summary="Items for sale")
def market(player: CurrentPlayer, uses: Uses,
           kind: Kind | None = None, rarity: Rarity | None = None, edition: Edition | None = None,
           q: Annotated[str, Query(max_length=60, description="a card's name (the game's English one) or key")] = "",
           seller: str | None = None,
           sort: Annotated[str, Query(pattern=r"^(newest|price|-price)$")] = "newest",
           limit: Annotated[int, Query(ge=1, le=200)] = 50,
           offset: Annotated[int, Query(ge=0, le=100_000)] = 0) -> list[ListingView]:
    return uses.market(player, kind=kind, rarity=rarity, edition=edition, q=q, seller=seller, sort=sort, limit=limit,
                       offset=offset)


@router.post("/market", response_model=ListingView, status_code=status.HTTP_201_CREATED, summary="Sell an item")
def create_listing(body: ListingRequest, player: CurrentPlayer, uses: Uses) -> ListingView:
    """Your item (out of its trade hold), for the coins you ask: another player buys it at once. Until then it
    can't be traded nor staked; take it off with ``POST /v1/market/{id}/cancel``."""
    return uses.create_listing(player, body.to_dto())


@router.get("/market/sales", response_model=list[ListingView], summary="The last sales")
def market_sales(player: CurrentPlayer, uses: Uses,
                 variant: Annotated[str | None, Query(max_length=60, description="a card and its upgrades "
                                                                                  "(S_A+m_glass+Red)")] = None,
                 edition: Edition | None = None, kind: Kind | None = None,
                 limit: Annotated[int, Query(ge=1, le=200)] = 20) -> list[ListingView]:
    return uses.market_sales(player, variant_=variant, edition=edition, kind=kind, limit=limit)


@router.get("/me/listings", response_model=list[ListingView], summary="Your market")
def my_listings(player: CurrentPlayer, uses: Uses,
                box: Annotated[str, Query(pattern=r"^(selling|sold|bought|all)$")] = "selling",
                limit: Annotated[int, Query(ge=1, le=200)] = 100,
                offset: Annotated[int, Query(ge=0, le=100_000)] = 0) -> list[ListingView]:
    """``selling``: your items for sale; ``sold``, ``bought``; ``all``: everything you sold, bought or took off."""
    return uses.my_listings(player, box, limit, offset)


@router.get("/market/{listing_id}", response_model=ListingView, summary="A listing")
def listing(listing_id: str, player: CurrentPlayer, uses: Uses) -> ListingView:
    return uses.listing(player, listing_id)


@router.post("/market/{listing_id}/buy", response_model=ListingView, summary="Buy an item")
def buy_listing(listing_id: str, player: CurrentPlayer, uses: Uses) -> ListingView:
    """Your coins to the seller, the item to you (its trade hold starts): all at once, or nothing."""
    return uses.buy_listing(player, listing_id)


@router.post("/market/{listing_id}/cancel", response_model=ListingView, summary="Take your item off the market")
def cancel_listing(listing_id: str, player: CurrentPlayer, uses: Uses) -> ListingView:
    return uses.cancel_listing(player, listing_id)


@router.post("/admin/coins", response_model=CoinMoveView, status_code=status.HTTP_201_CREATED,
             summary="Give coins (admins)")
def give_coins(body: CoinGiftRequest, player: CurrentPlayer, uses: Uses) -> CoinMoveView:
    """For events and prizes (negative: takes them back, down to 0): the only way to make coins outside the
    grants."""
    return uses.give_coins(player, body.to_dto())
