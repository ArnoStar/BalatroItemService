"""Items: a card of the game (a joker, a tarot, planet or spectral card, or a
playing card) with the upgrades the game gives such a card, owned by a player.

An item is a collectible. It changes nothing in a run: the game shows it, it
never plays it. It has only the upgrades the game can give its kind of card:

- a **joker**: an edition (foil, holographic, polychrome, negative);
- a **tarot, planet or spectral card**: negative or not (the game makes a
  negative one only rarely: here too);
- a **playing card**: an enhancement (``m_bonus`` ... ``m_lucky``), a seal
  (``Gold``, ``Red``, ``Blue``, ``Purple``) and an edition but negative.

Every item has a condition (condition.py: how well kept its card is, which
its value follows: value.py), and is numbered among the items of the same
card, upgrades and edition
(``serial``: #1 was the first made; ``variant`` names the card and its
upgrades), remembers where it came from (``source``: a booster, a gift, or
before boosters a grant of a run, ``source_run``) and, when it came from a
win, the stake it was won at (``stake``: the game's stake sticker). It can only
change hands again when its trade hold is over (``tradable_at``), and not
while it is staked in a casino game (``staked``: casino.py) or for sale on the
market (``listed``: market.py).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum


class Kind(StrEnum):
    JOKER = "joker"
    TAROT = "tarot"
    PLANET = "planet"
    SPECTRAL = "spectral"
    CARD = "card"  # a playing card


CONSUMABLES = frozenset({Kind.TAROT, Kind.PLANET, Kind.SPECTRAL})


class Edition(StrEnum):
    """The game's editions (Card:set_edition)."""

    BASE = "base"
    FOIL = "foil"
    HOLOGRAPHIC = "holographic"
    POLYCHROME = "polychrome"
    NEGATIVE = "negative"


# the editions the game gives each kind of card (consumables: negative only, through Perkeo; playing cards: never
# negative)
EDITIONS: dict[Kind, frozenset[Edition]] = {
    Kind.JOKER: frozenset(Edition),
    Kind.TAROT: frozenset({Edition.BASE, Edition.NEGATIVE}),
    Kind.PLANET: frozenset({Edition.BASE, Edition.NEGATIVE}),
    Kind.SPECTRAL: frozenset({Edition.BASE, Edition.NEGATIVE}),
    Kind.CARD: frozenset({Edition.BASE, Edition.FOIL, Edition.HOLOGRAPHIC, Edition.POLYCHROME}),
}

# a playing card's upgrades: the game's enhancements (P_CENTER_POOLS.Enhanced) and seals (P_SEALS)
ENHANCEMENTS = ("m_bonus", "m_mult", "m_wild", "m_glass", "m_steel", "m_stone", "m_gold", "m_lucky")
SEALS = ("Gold", "Red", "Blue", "Purple")


class Rarity(IntEnum):
    """The game's joker rarities (the other cards get one here: CONSUMABLE_RARITY, card_rarity)."""

    COMMON = 1
    UNCOMMON = 2
    RARE = 3
    LEGENDARY = 4


# Tarot, planet and spectral cards have no rarity in the game: those it shows less often (the secret planets, The
# Soul and Black Hole) or whose effect is bigger are rarer here. The others are common.
CONSUMABLE_RARITY: dict[str, Rarity] = {
    # tarots
    "c_high_priestess": Rarity.UNCOMMON, "c_emperor": Rarity.UNCOMMON, "c_chariot": Rarity.UNCOMMON,
    "c_justice": Rarity.UNCOMMON, "c_hermit": Rarity.UNCOMMON, "c_hanged_man": Rarity.UNCOMMON,
    "c_death": Rarity.UNCOMMON, "c_temperance": Rarity.UNCOMMON, "c_devil": Rarity.UNCOMMON,
    "c_fool": Rarity.RARE, "c_wheel_of_fortune": Rarity.RARE, "c_judgement": Rarity.RARE,
    # planets: by how rare their hand is
    "c_earth": Rarity.UNCOMMON, "c_mars": Rarity.UNCOMMON, "c_neptune": Rarity.UNCOMMON,
    "c_planet_x": Rarity.RARE, "c_ceres": Rarity.RARE, "c_eris": Rarity.RARE,
    # spectrals
    "c_talisman": Rarity.UNCOMMON, "c_aura": Rarity.UNCOMMON, "c_deja_vu": Rarity.UNCOMMON,
    "c_cryptid": Rarity.UNCOMMON,
    "c_wraith": Rarity.RARE, "c_ectoplasm": Rarity.RARE, "c_ankh": Rarity.RARE, "c_hex": Rarity.RARE,
    "c_soul": Rarity.LEGENDARY, "c_black_hole": Rarity.LEGENDARY,
}


def card_rarity(enhancement: str | None, seal: str | None) -> Rarity:
    """A playing card's rarity: common plain, uncommon with an enhancement or a seal, rare with both."""
    return Rarity(1 + (enhancement is not None) + (seal is not None))


def variant(key: str, enhancement: str | None = None, seal: str | None = None) -> str:
    """The card and its upgrades, as serial numbers count them: ``j_joker``, ``S_A``, ``S_A+m_glass+Red``."""
    return "+".join([key, *(x for x in (enhancement, seal) if x)])


@dataclass(frozen=True, kw_only=True)
class Template:
    """What a booster can give: a card of the game's catalog, with its upgrades (a playing card's)."""

    kind: Kind
    key: str
    name: str
    rarity: Rarity
    sprite: dict[str, object] | None = None  # the catalog's sprite (atlas, pos, soul_pos; a playing card's front, seal)
    enhancement: str | None = None
    seal: str | None = None

    @property
    def variant(self) -> str:
        return variant(self.key, self.enhancement, self.seal)


@dataclass(kw_only=True)
class Item:
    id: str
    kind: Kind
    key: str
    edition: Edition
    rarity: Rarity
    stake: int | None  # the stake of the win it came from (None: not from a win)
    serial: int  # its number among the items of its variant and edition (given when it is stored)
    owner: str
    source: str  # how it was made: booster, gift (before boosters: a run's grant, drops.Grant.reason)
    source_run: str | None
    created_at: datetime
    acquired_at: datetime  # when its owner got it
    tradable_at: datetime  # the end of its trade hold
    condition: float  # how well kept its card is, 0 (ruined) to 1 (pristine): condition.py
    staked: str | None = None  # the casino game it is staked in (it can't change hands until the game ends)
    enhancement: str | None = None  # a playing card's
    seal: str | None = None  # a playing card's
    listed: str | None = None  # its open listing on the market (it can't change hands any other way meanwhile)
    booster: str | None = None  # the booster it came from (boosters.Booster.id)

    @property
    def variant(self) -> str:
        return variant(self.key, self.enhancement, self.seal)

    def tradable(self, now: datetime) -> bool:
        return self.staked is None and self.listed is None and now >= self.tradable_at


@dataclass(frozen=True, kw_only=True)
class Transfer:
    """An item changing hands (``from_owner`` None: it was made)."""

    item: str
    from_owner: str | None
    to_owner: str
    at: datetime
    trade: str | None = None
    game: str | None = None  # the casino game it was won in
    listing: str | None = None  # the market listing it was bought from
    price: int | None = None  # what it was bought for, in coins


@dataclass(kw_only=True)
class PlayerRecord:
    """A player this service has seen: their name (from their tokens), whether
    they may trade (a counted win: the game API says), their showcase and coins."""

    id: str
    name: str | None
    has_won: bool
    showcase: str | None  # the item shown on their title screen and profile
    created_at: datetime
    synced_at: datetime | None = None  # the last time their runs were read
    coins: int = 0  # (read only: coins change through Unit.add_coins, which keeps their history)


@dataclass(frozen=True, kw_only=True)
class CoinMove:
    """Coins coming in (``amount`` > 0) or going out, and the balance after: a player's coins keep their history.
    ``reason``: a grant's (weekly ...), booster, market_buy, market_sale, tag_refund, gift; ``ref``: what it was
    for (the grant, the pack, the listing ...)."""

    player: str
    amount: int
    balance: int
    reason: str
    ref: str | None
    at: datetime


Sprite = dict[str, object]


def playing_cards(cards: Iterable[tuple[str, str, Sprite | None]], base: Sprite | None,
                  enhancements: Mapping[str, Sprite | None], seals: Mapping[str, Sprite | None]) -> list[Template]:
    """Every playing card with every upgrade the game gives one: ``cards`` (key, name, front sprite), the blank
    card's sprite (``base``), the enhancements' and seals' sprites. Each template's sprite is the card's center
    (its enhancement, or the blank card), with its ``front`` (none for a Stone Card: the game hides it) and
    ``seal``."""
    out: list[Template] = []
    for key, name, front in cards:
        for enhancement in (None, *ENHANCEMENTS):
            center = enhancements.get(enhancement) if enhancement else base
            for seal in (None, *SEALS):
                sprite: Sprite = {**(center or {}), "front": None if enhancement == "m_stone" else front,
                                  "seal": seals.get(seal) if seal else None}
                out.append(Template(kind=Kind.CARD, key=key, name=name, rarity=card_rarity(enhancement, seal),
                                    sprite=sprite, enhancement=enhancement, seal=seal))
    return out
