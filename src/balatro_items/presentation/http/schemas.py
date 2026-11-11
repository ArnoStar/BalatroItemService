"""Request bodies.  (Responses are the application's dataclasses.)"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from balatro_items.application.dto import Gift, NewTrade
from balatro_items.domain import MAX_SIDE, Edition

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
    key: str = Field(description="A joker or tag key of the game's catalog (j_joker, tag_negative ...)")
    edition: Edition = Edition.BASE
    stake: int | None = Field(None, ge=1, le=8, description="A stake sticker (1 White ... 8 Gold)")

    def to_dto(self) -> Gift:
        return Gift(to=self.to, key=self.key, edition=self.edition, stake=self.stake)
