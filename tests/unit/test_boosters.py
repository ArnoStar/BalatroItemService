"""What coins buy: the boosters, the tables their cards are rolled on, packs and the player's choice."""

from __future__ import annotations

from collections import Counter

import pytest

from balatro_items.domain import (
    BOOSTERS,
    EDITIONS,
    RETIRED_TAG_COINS,
    Edition,
    InvalidPick,
    Kind,
    Pack,
    PackOpened,
    PackStatus,
    Pools,
    Rarity,
    Size,
    Tier,
    choose,
    roll_pack,
    table,
    variant,
)
from tests.fakes import T0, FakeCatalog, rng


def pools() -> Pools:
    return Pools(FakeCatalog().templates())


def test_every_kind_has_every_tier_in_every_size() -> None:
    assert len(BOOSTERS) == 5 * 3 * 3
    for kind in Kind:
        for tier in Tier:
            normal, jumbo, mega = (BOOSTERS[f"{kind.value}_{tier.value}_{s.value}"] for s in Size)
            assert (normal.choices, normal.picks) == (2, 1)
            assert (jumbo.choices, jumbo.picks) == (4, 1)
            assert (mega.choices, mega.picks) == (4, 2)
            assert normal.price < jumbo.price < mega.price
            assert mega.art.startswith("p_") and mega.art.endswith("_mega_1")
    assert BOOSTERS["joker_standard_normal"].price == 100 and BOOSTERS["joker_premium_mega"].price == 2000
    assert BOOSTERS["card_standard_normal"].art == "p_standard_normal_1"
    assert BOOSTERS["tarot_boosted_jumbo"].art == "p_arcana_jumbo_1"


def test_each_kind_gets_only_the_editions_the_game_gives_it() -> None:
    for (kind, _), t in ((k, table(*k)) for k in ((kind, tier) for kind in Kind for tier in Tier)):
        assert set(e for e, w in t.editions.items() if w > 0) <= EDITIONS[kind]
    assert Edition.NEGATIVE not in EDITIONS[Kind.CARD]
    for kind in (Kind.TAROT, Kind.PLANET, Kind.SPECTRAL):
        assert EDITIONS[kind] == {Edition.BASE, Edition.NEGATIVE}
        for tier in Tier:  # negative: really rarely
            assert table(kind, tier).editions[Edition.NEGATIVE] <= 0.3


def test_rolls_follow_the_table() -> None:
    p, r = pools(), rng(7)
    rolls = [p.roll(table(Kind.JOKER), r) for _ in range(100000)]
    assert all(t.kind is Kind.JOKER for t, _ in rolls)
    rarities = Counter(t.rarity for t, _ in rolls)
    assert rarities[Rarity.COMMON] > rarities[Rarity.UNCOMMON] > rarities[Rarity.RARE] > rarities[Rarity.LEGENDARY] > 0
    assert 0.865 < rarities[Rarity.COMMON] / len(rolls) < 0.895
    editions = Counter(e for _, e in rolls)
    assert editions[Edition.BASE] > editions[Edition.FOIL] > editions[Edition.HOLOGRAPHIC] > editions[
        Edition.POLYCHROME] > editions[Edition.NEGATIVE] > 0
    # premium: never common, an edition about half the time
    premium = [p.roll(table(Kind.JOKER, Tier.PREMIUM), r) for _ in range(2000)]
    assert all(t.rarity >= Rarity.UNCOMMON for t, _ in premium)
    assert 0.5 < sum(1 for _, e in premium if e is not Edition.BASE) / len(premium) < 0.6


def test_playing_cards_have_their_upgrades() -> None:
    p, r = pools(), rng(3)
    rolls = [p.roll(table(Kind.CARD, Tier.BOOSTED), r) for _ in range(5000)]
    assert all(e is not Edition.NEGATIVE for _, e in rolls)
    plain = [t for t, _ in rolls if t.rarity is Rarity.COMMON]
    assert plain and all(t.enhancement is None and t.seal is None for t in plain)
    both = [t for t, _ in rolls if t.rarity is Rarity.RARE]
    assert both and all(t.enhancement and t.seal for t in both)
    assert {t.enhancement for t in both} >= {"m_glass", "m_steel"} and {t.seal for t in both} >= {"Gold", "Red"}
    stone = next(t for t in p.by_variant.values() if t.enhancement == "m_stone")
    assert stone.sprite is not None and stone.sprite["front"] is None  # (the game hides a Stone Card's rank)
    glass = p.by_variant[variant("S_A", "m_glass", "Red")]
    assert glass.sprite is not None and glass.sprite["front"] and glass.sprite["seal"]


def test_consumables_rarely_negative_and_the_soul_legendary() -> None:
    p, r = pools(), rng(5)
    rolls = [p.roll(table(Kind.SPECTRAL, Tier.PREMIUM), r) for _ in range(40000)]
    souls = sum(1 for t, _ in rolls if t.key == "c_soul")
    assert 0.012 < souls / len(rolls) < 0.018  # legendary: 1.5% of the premium table
    negatives = sum(1 for _, e in rolls if e is Edition.NEGATIVE)
    assert 0.0018 < negatives / len(rolls) < 0.0042  # 0.3%
    assert all(t.rarity is not Rarity.COMMON for t, _ in rolls)


def test_odds_say_what_is_rarer() -> None:
    p = pools()
    common, legendary = p.by_variant["j_joker"], p.by_variant["j_caino"]
    assert p.odds(common, Edition.BASE) < p.odds(common, Edition.NEGATIVE) < p.odds(legendary, Edition.NEGATIVE)
    # 88% common, 4 commons here, 96% base: 1 in 1 / (0.88 / 4 * 0.96)
    assert p.odds(common, Edition.BASE) == round(1 / (0.88 / 4 * 0.96))
    assert p.odds(common, Edition.BASE, table(Kind.JOKER, Tier.PREMIUM)) == 0  # can't be rolled there
    assert p.odds(p.by_variant["c_fool"], Edition.BASE, table(Kind.JOKER)) == 0  # another kind's table
    # a planet has no legendary: the others share its part
    eris = p.by_variant["c_eris"]
    assert p.odds(eris, Edition.BASE) == round(1 / (1.4 / 99.9 * 0.9998))
    assert p.odds(eris, Edition.HOLOGRAPHIC) == 0
    assert p.odds(p.by_variant["S_A+m_glass+Red"], Edition.POLYCHROME) > p.odds(p.by_variant["S_A"], Edition.FOIL)


def test_a_pack_shows_each_card_once() -> None:
    p, r = pools(), rng(11)
    for _ in range(300):
        cards = roll_pack(BOOSTERS["planet_standard_jumbo"], p, r)
        assert len(cards) == 4 and all(c.kind is Kind.PLANET for c in cards)
        commons = [c.key for c in cards if c.rarity is Rarity.COMMON]
        assert len(commons) == len(set(commons)) or len(commons) > 2  # (2 commons only: once each while it can)


def test_choosing() -> None:
    p, r = pools(), rng(2)
    booster = BOOSTERS["card_premium_mega"]
    pack = Pack(id="p1", owner="alice", booster=booster.id, price=booster.price, picks=booster.picks,
                choices=roll_pack(booster, p, r), status=PackStatus.OPEN, created_at=T0)
    for bad in ([0], [0, 0], [0, 4], [0, 1, 2]):
        with pytest.raises(InvalidPick):
            choose(pack, bad, T0)
    assert choose(pack, [3, 1], T0) == [pack.choices[3], pack.choices[1]]
    assert pack.status is PackStatus.OPENED and pack.chosen == (3, 1) and pack.opened_at == T0
    with pytest.raises(PackOpened):
        choose(pack, [0, 2], T0)


def test_the_tags_were_given_back_at_their_value() -> None:
    """A tag's value was its odds on the standard table of its time: tags 15% of the drops, then its rarity among the
    tags' (common 70, uncommon 25, rare 4.5), one of its rarity's tags (16, 6, 2), its edition."""
    rarities = {Rarity.COMMON: (70, 16), Rarity.UNCOMMON: (25, 6), Rarity.RARE: (4.5, 2)}
    editions = {Edition.BASE: 85, Edition.FOIL: 8, Edition.HOLOGRAPHIC: 4.5, Edition.POLYCHROME: 2,
                Edition.NEGATIVE: 0.5}
    for (rarity, edition), coins in RETIRED_TAG_COINS.items():
        weight, pool = rarities[rarity]
        assert coins == round(1 / (0.15 * weight / 99.5 / pool * editions[edition] / 100))
    assert len(RETIRED_TAG_COINS) == 15
