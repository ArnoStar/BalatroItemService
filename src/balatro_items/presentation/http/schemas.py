"""Request bodies.  (Responses are the application's dataclasses.)"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from balatro_items.application.dto import CoinGift, Gift, NewBet, NewListing, NewTrade
from balatro_items.domain import (
    ENHANCEMENTS,
    MAX_CHANCE,
    MAX_PRICE,
    MAX_SIDE,
    MAX_STAKE,
    MIN_CHANCE,
    MIN_PRICE,
    SEALS,
    Edition,
    Side,
)

ItemIds = list[str]


class ShowcaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: str | None = Field(None, description="One of your items, shown on your title screen and profile; "
                                               "null: the game's own card")


class TradeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str = Field(description="The player the offer is made to (their account id)")
    give: ItemIds = Field(default_factory=list, max_length=MAX_SIDE, description="Your items")
    take: ItemIds = Field(default_factory=list, max_length=MAX_SIDE, description="Their items")
    message: str = Field("", max_length=280)

    def to_dto(self) -> NewTrade:
        return NewTrade(to=self.to, give=self.give, take=self.take, message=self.message)


class GiftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str = Field(description="The player's account id (they have used the items once)")
    key: str = Field(description="A card of the game's catalog: a joker, tarot, planet or spectral card (j_joker, "
                                 "c_fool ...), or a playing card (S_A ...)")
    edition: Edition = Edition.BASE
    stake: int | None = Field(None, ge=1, le=8, description="A stake sticker (1 White ... 8 Gold)")
    enhancement: str | None = Field(None, pattern=f"^({'|'.join(ENHANCEMENTS)})$", description="A playing card's")
    seal: str | None = Field(None, pattern=f"^({'|'.join(SEALS)})$", description="A playing card's")

    def to_dto(self) -> Gift:
        return Gift(to=self.to, key=self.key, edition=self.edition, stake=self.stake, enhancement=self.enhancement,
                    seal=self.seal)


class CoinGiftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str = Field(description="The player's account id (they have used the items once)")
    coins: int = Field(description="Coins to give (negative: to take back, down to 0)")
    note: str = Field("", max_length=200, description="What for (in their coins' history)")

    def to_dto(self) -> CoinGift:
        return CoinGift(to=self.to, coins=self.coins, note=self.note)


class PickRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    picks: list[int] = Field(min_length=1, max_length=4, description="The cards chosen: their indexes in the pack")


class ListingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: str = Field(description="Your item (out of its trade hold, not staked)")
    price: int = Field(ge=MIN_PRICE, le=MAX_PRICE, description="Coins")

    def to_dto(self) -> NewListing:
        return NewListing(item=self.item, price=self.price)


class BetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: ItemIds = Field(min_length=1, max_length=MAX_STAKE,
                           description="Your items to stake (out of their trade hold, not staked elsewhere)")
    seed: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{1,64}$",
                             description="Your seed for the draw (provably fair: GET /v1/casino/rules); none: a "
                                         "random one")

    def to_dto(self) -> NewBet:
        return NewBet(items=self.items, seed=self.seed)


class CoinflipRequest(BetRequest):
    side: Side = Field(Side.CHIPS, description="Your side of the coin; the other player gets the other")
    opponent: str | None = Field(None, max_length=200, description="A challenge: the only player (account id) "
                                                                   "who may join; none: anyone")

    def to_dto(self) -> NewBet:
        return NewBet(items=self.items, seed=self.seed, side=self.side, opponent=self.opponent)


class DiceRequest(BetRequest):
    chance: int = Field(50, ge=MIN_CHANCE, le=MAX_CHANCE,
                        description="Your chance, in percent: the other player's items must be worth what makes it so")
    opponent: str | None = Field(None, max_length=200, description="A challenge: the only player (account id) "
                                                                   "who may join; none: anyone")

    def to_dto(self) -> NewBet:
        return NewBet(items=self.items, seed=self.seed, chance=self.chance, opponent=self.opponent)
