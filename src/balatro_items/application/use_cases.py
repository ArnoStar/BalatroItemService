"""The use cases: one class each, taking the caller (``Player``) first.

Coins are only earned through ``SyncDrops`` (the game API's runs earn them,
domain/drops.py) and an admin's gift; items are only made by ``ChoosePack``
(a booster bought with coins, domain/boosters.py) and an admin's gift. Items
only change hands through an accepted trade, a casino game (domain/casino.py)
or the market (domain/market.py), and coins only through the market. Every
change happens in one store transaction (``Unit``)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from balatro_items.domain import (
    BOOSTERS,
    COINFLIP_MARGIN,
    DUELS,
    EDITIONS,
    GOLD_COINS,
    JACKPOT_MAX_ITEMS,
    JACKPOT_MAX_PLAYERS,
    MAX_CHANCE,
    MAX_LISTINGS,
    MAX_OPEN_COINFLIPS,
    MAX_PENDING,
    MAX_PRICE,
    MAX_STAKE,
    MIN_CHANCE,
    MIN_PRICE,
    OFFER_LIFETIME,
    TABLES,
    WEEKLY_COINS,
    WIN_COINS,
    Booster,
    BoosterNotFound,
    Choice,
    DomainError,
    Edition,
    Entry,
    Game,
    GameNotFound,
    GameStatus,
    InvalidBet,
    InvalidListing,
    Item,
    ItemNotFound,
    Kind,
    Listing,
    ListingNotFound,
    ListingStatus,
    Mode,
    NotOwner,
    NotParticipant,
    Pack,
    PackNotFound,
    PackStatus,
    PlayerNotFound,
    PlayerRecord,
    Pools,
    Random,
    Rarity,
    Side,
    Tally,
    Template,
    TooManyGames,
    TooManyListings,
    TooManyOffers,
    Trade,
    TradeNotFound,
    TradeStatus,
    TradingLocked,
    Transfer,
    cancel,
    check_bet,
    check_challenge,
    check_chance,
    check_items,
    check_join,
    check_offer,
    check_price,
    choose,
    draw,
    earned,
    grade,
    item_mint_value,
    item_value,
    join_duel,
    join_jackpot,
    join_range,
    mint_value,
    next_week,
    parts,
    pay_out,
    roll_condition,
    roll_pack,
    sell,
    swap,
    take_off,
    tally,
    variant,
    week_of,
    winner_chance,
    worth,
)

from .dto import (
    BoosterView,
    CasinoEvent,
    CasinoRulesView,
    CasinoSnapshotView,
    CasinoStatsView,
    ChoiceView,
    CoinGift,
    CoinMoveView,
    CoinsView,
    DropsView,
    EarnedView,
    EntryView,
    GameView,
    Gift,
    ItemDetail,
    ItemView,
    JackpotView,
    LeaderboardView,
    ListingQuery,
    ListingView,
    MeView,
    ModeStatsView,
    NewBet,
    NewListing,
    NewTrade,
    OddsView,
    PackView,
    Player,
    PlayerView,
    RankView,
    RuleView,
    TableView,
    TradeView,
    TransferView,
    WeekView,
    WinView,
)
from .errors import CasinoClosed, GameApiUnavailable, NotAdmin, UnknownTemplate
from .ports import (
    Authenticator,
    CasinoFeed,
    Catalog,
    Clock,
    FeedSubscription,
    IdGenerator,
    RunSource,
    SeedSource,
    Store,
    Unit,
)

log = logging.getLogger(__name__)

SYNC_EVERY = timedelta(seconds=5)  # a player's runs are read at most this often
MAX_OPEN_PACKS = 1000  # (counted up to this many)
ADMIN_ROLES = frozenset({"admin"})


@dataclass(frozen=True)
class Deps:
    store: Store
    catalog: Catalog
    runs: RunSource
    clock: Clock
    ids: IdGenerator
    rng: Random
    seeds: SeedSource
    hold: timedelta  # an item's trade hold after it changes hands (or is found)
    admins: frozenset[str] = frozenset()  # account ids that may give items, besides the admin role
    auth_required: bool = True
    casino_open: bool = True  # False: nothing can be staked
    jackpot_wait: timedelta = timedelta(seconds=60)  # from the second player in the pot to its draw
    feed: CasinoFeed = field(default_factory=lambda: NoFeed())  # the casino's live streams


class NoFeed:
    """No live streams (a Deps made without one)."""

    def publish(self, event: CasinoEvent) -> None:
        pass

    def subscribe(self) -> FeedSubscription:
        raise RuntimeError("this service has no live feed")


def is_admin(deps: Deps, player: Player) -> bool:
    return not deps.auth_required or player.id in deps.admins or bool(player.roles & ADMIN_ROLES)


def ensure_player(u: Unit, player: Player, now: datetime) -> PlayerRecord:
    """The caller's record, made the first time; their name follows their account's."""
    rec = u.player(player.id)
    if rec is None:
        rec = PlayerRecord(id=player.id, name=player.name, has_won=False, showcase=None, created_at=now)
        u.save_player(rec)
    elif player.name and player.name != rec.name:
        rec.name = player.name
        u.save_player(rec)
    return rec


_POOLS: dict[int, tuple[list[Template], Pools]] = {}


def pools_of(templates: list[Template]) -> Pools:
    """The catalog's pools, made once per copy of the catalog (the game API's adapter keeps one for a while)."""
    hit = _POOLS.get(id(templates))
    if hit is not None and hit[0] is templates:
        return hit[1]
    pools = Pools(templates)
    _POOLS.clear()
    _POOLS[id(templates)] = (templates, pools)
    return pools


def percent(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    return {k: round(100 * v / total, 3) for k, v in weights.items()} if total else {}


class Views:
    """Items, packs, listings and trades as the clients see them (names and sprites from the catalog)."""

    def __init__(self, deps: Deps) -> None:
        self.deps = deps

    def pools(self, strict: bool = False) -> Pools:
        """The catalog's cards (``strict``: raise GameApiUnavailable without them; else none, until it is back)."""
        try:
            return pools_of(self.deps.catalog.templates())
        except GameApiUnavailable:
            if strict:
                raise
            return pools_of([])  # (items are shown by key, without odds, until the catalog is back)

    def names(self, u: Unit, ids: Sequence[str | None]) -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        for pid in ids:
            if pid is not None and pid not in out:
                rec = u.player(pid)
                out[pid] = rec.name if rec else None
        return out

    def items(self, u: Unit, items: Sequence[Item]) -> list[ItemView]:
        pools = self.pools()
        names = self.names(u, [it.owner for it in items])
        now = self.deps.clock.now()
        out = []
        for it in items:
            t = pools.by_variant.get(it.variant)
            listing = u.listing(it.listed) if it.listed else None
            out.append(ItemView(
                id=it.id, kind=it.kind, key=it.key, name=t.name if t else it.key, edition=it.edition, rarity=it.rarity,
                stake=it.stake, serial=it.serial, minted=u.minted(it.variant, it.edition),
                odds=pools.odds(t, it.edition) if t else 0, owner=it.owner, owner_name=names[it.owner],
                source=it.source, source_run=it.source_run, found_at=it.created_at, acquired_at=it.acquired_at,
                tradable_at=it.tradable_at, tradable=it.tradable(now), staked=it.staked,
                sprite=t.sprite if t else None, enhancement=it.enhancement, seal=it.seal, variant=it.variant,
                listed=it.listed, price=listing.price if listing else None, booster=it.booster,
                condition=it.condition, grade=grade(it.condition), mint_value=item_mint_value(it),
                value=item_value(it)))
        return out

    def item(self, u: Unit, item: Item) -> ItemView:
        return self.items(u, [item])[0]

    def showcase(self, u: Unit, rec: PlayerRecord) -> ItemView | None:
        item = u.item(rec.showcase) if rec.showcase else None
        return self.item(u, item) if item is not None and item.owner == rec.id else None

    def week(self, u: Unit, player_id: str) -> WeekView:
        now = self.deps.clock.now()
        week = week_of(now)
        claims = u.claims(player_id)
        return WeekView(week=week, weekly_earned=f"week:{week}:play" in claims,
                        weekly_win_earned=f"week:{week}:win" in claims, weekly_coins=WEEKLY_COINS,
                        weekly_win_coins=WIN_COINS, next_week_at=next_week(now))

    def booster(self, b: Booster, pools: Pools) -> BoosterView:
        chances = pools.chances(b.table) or {r: w for r, w in b.table.rarities.items() if w > 0}
        return BoosterView(id=b.id, kind=b.kind, tier=b.tier, size=b.size, choices=b.choices, picks=b.picks,
                           price=b.price, art=b.art,
                           rarities=percent({Rarity(r).name.lower(): w for r, w in chances.items()}),
                           editions=percent({e.value: w for e, w in b.table.editions.items() if w > 0}))

    def choice(self, u: Unit, index: int, c: Choice, pools: Pools) -> ChoiceView:
        v = variant(c.key, c.enhancement, c.seal)
        t = pools.by_variant.get(v)
        mint = mint_value(c.kind, c.rarity, c.edition, c.enhancement, c.seal)
        return ChoiceView(index=index, kind=c.kind, key=c.key, name=t.name if t else c.key, rarity=c.rarity,
                          edition=c.edition, enhancement=c.enhancement, seal=c.seal, variant=v,
                          odds=pools.odds(t, c.edition) if t else 0, minted=u.minted(v, c.edition),
                          sprite=t.sprite if t else None, condition=c.condition,
                          grade=grade(c.condition) if c.condition is not None else None, mint_value=mint,
                          value=worth(mint, c.condition) if c.condition is not None else 0)

    def pack(self, u: Unit, p: Pack) -> PackView:
        pools = self.pools()
        items = u.items(p.items)
        return PackView(
            id=p.id, booster=self.booster(BOOSTERS[p.booster], pools), price=p.price, picks=p.picks, status=p.status,
            choices=[self.choice(u, i, c, pools) for i, c in enumerate(p.choices)], chosen=list(p.chosen),
            items=self.items(u, [items[i] for i in p.items if i in items]), created_at=p.created_at,
            opened_at=p.opened_at)

    def listings(self, u: Unit, listings: Sequence[Listing]) -> list[ListingView]:
        items = u.items([x.item for x in listings])
        views = {v.id: v for v in self.items(u, list(items.values()))}
        names = self.names(u, [p for x in listings for p in (x.seller, x.buyer)])
        out = []
        for x in listings:
            it = items.get(x.item)
            available = (x.status is ListingStatus.OPEN and it is not None and it.owner == x.seller
                         and it.listed == x.id)
            out.append(ListingView(id=x.id, seller=x.seller, seller_name=names[x.seller], item=views.get(x.item),
                                   price=x.price, status=x.status, available=available, buyer=x.buyer,
                                   buyer_name=names[x.buyer] if x.buyer else None, created_at=x.created_at,
                                   updated_at=x.updated_at))
        return out

    def listing(self, u: Unit, x: Listing) -> ListingView:
        return self.listings(u, [x])[0]

    def trade(self, u: Unit, t: Trade) -> TradeView:
        now = self.deps.clock.now()
        items = u.items([*t.give, *t.take])
        status = t.status_at(now)
        available = False
        if status is TradeStatus.PENDING:
            try:
                check_items(t.sender, t.give, items, now, moved=True)
                check_items(t.recipient, t.take, items, now, moved=True)
                available = True
            except DomainError:
                available = False
        views = {v.id: v for v in self.items(u, list(items.values()))}
        sender, recipient = u.player(t.sender), u.player(t.recipient)
        return TradeView(
            id=t.id, sender=t.sender, sender_name=sender.name if sender else None, recipient=t.recipient,
            recipient_name=recipient.name if recipient else None,
            give=[views[i] for i in t.give if i in views], take=[views[i] for i in t.take if i in views],
            message=t.message, status=status, available=available, created_at=t.created_at, updated_at=t.updated_at,
            expires_at=t.expires_at)


def unshow(u: Unit, players: Sequence[str], items: dict[str, Item]) -> None:
    """An item shown by its former owner isn't theirs to show any more: their title screen gets the game's card."""
    for pid in players:
        rec = u.player(pid, lock=True)
        if rec is not None and rec.showcase in items and items[rec.showcase].owner != pid:
            rec.showcase = None
            u.save_player(rec)


class Authenticate:
    def __init__(self, authenticator: Authenticator) -> None:
        self.authenticator = authenticator

    def __call__(self, token: str | None) -> Player:
        return self.authenticator.authenticate(token)


class GetMe:
    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, player: Player) -> MeView:
        with self.deps.store.unit() as u:
            rec = ensure_player(u, player, self.deps.clock.now())
            return MeView(id=rec.id, name=rec.name, can_trade=rec.has_won, admin=is_admin(self.deps, player),
                          items=len(u.items_of(rec.id)), coins=rec.coins,
                          packs=len(u.packs_of(rec.id, PackStatus.OPEN, MAX_OPEN_PACKS)),
                          showcase=self.views.showcase(u, rec), week=self.views.week(u, rec.id))


class SyncDrops:
    """Reads the player's runs from the game API and gives the coins they have earned
    (domain/drops.py): each grant once, ever."""

    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, player: Player) -> DropsView:
        d = self.deps
        now = d.clock.now()
        with d.store.unit() as u:
            rec = ensure_player(u, player, now)
            recent = rec.synced_at is not None and now - rec.synced_at < SYNC_EVERY
            if recent:
                return DropsView(earned=[], coins=0, balance=rec.coins, week=self.views.week(u, player.id))
        runs = d.runs.runs(player)  # (outside the transaction: the game API may be slow)
        got: list[EarnedView] = []
        with d.store.unit() as u:
            rec = u.player(player.id, lock=True) or ensure_player(u, player, now)
            rec.has_won = rec.has_won or any(r.won and r.counted for r in runs)
            rec.synced_at = now
            u.save_player(rec)
            balance = rec.coins
            for grant in earned(runs, u.claims(player.id), now):
                if u.claim(player.id, grant.source, grant.run, now, grant.coins):
                    balance = u.add_coins(player.id, grant.coins, grant.reason, grant.source, now)
                    got.append(EarnedView(source=grant.source, reason=grant.reason, coins=grant.coins, run=grant.run))
                    log.info("player %s earned %d coins for %s", player.id, grant.coins, grant.source)
            return DropsView(earned=got, coins=sum(g.coins for g in got), balance=balance,
                             week=self.views.week(u, player.id))


class MyItems:
    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, player: Player) -> list[ItemView]:
        with self.deps.store.unit() as u:
            ensure_player(u, player, self.deps.clock.now())
            return self.views.items(u, u.items_of(player.id))


class PlayerItems:
    """A player's items: inventories are public, to trade."""

    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, viewer: Player, player_id: str) -> list[ItemView]:
        with self.deps.store.unit() as u:
            if u.player(player_id) is None:
                raise PlayerNotFound(player_id)
            return self.views.items(u, u.items_of(player_id))


class GetPlayer:
    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def view(self, u: Unit, viewer: Player, rec: PlayerRecord) -> PlayerView:
        return PlayerView(id=rec.id, name=rec.name, you=rec.id == viewer.id, can_trade=rec.has_won,
                          items=len(u.items_of(rec.id)), showcase=self.views.showcase(u, rec))

    def __call__(self, viewer: Player, player_id: str) -> PlayerView:
        with self.deps.store.unit() as u:
            rec = u.player(player_id)
            if rec is None:
                raise PlayerNotFound(player_id)
            return self.view(u, viewer, rec)


class FindPlayers:
    def __init__(self, deps: Deps) -> None:
        self.deps, self.get = deps, GetPlayer(deps)

    def __call__(self, viewer: Player, query: str, limit: int = 20) -> list[PlayerView]:
        with self.deps.store.unit() as u:
            return [self.get.view(u, viewer, rec) for rec in u.find_players(query.strip(), limit)]


class GetItem:
    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, viewer: Player, item_id: str) -> ItemDetail:
        with self.deps.store.unit() as u:
            item = u.item(item_id)
            if item is None:
                raise ItemNotFound(item_id)
            names: dict[str, str | None] = {}

            def name(pid: str | None) -> str | None:
                if pid is None:
                    return None
                if pid not in names:
                    rec = u.player(pid)
                    names[pid] = rec.name if rec else None
                return names[pid]

            history = [TransferView(from_player=t.from_owner, from_name=name(t.from_owner), to_player=t.to_owner,
                                    to_name=name(t.to_owner), at=t.at, trade=t.trade, game=t.game,
                                    listing=t.listing, price=t.price)
                       for t in u.transfers(item_id)]
            return ItemDetail(item=self.views.item(u, item), history=history)


class SetShowcase:
    """The item shown on the player's title screen and profile (None: the game's own card)."""

    def __init__(self, deps: Deps) -> None:
        self.deps, self.me = deps, GetMe(deps)

    def __call__(self, player: Player, item_id: str | None) -> MeView:
        with self.deps.store.unit() as u:
            rec = ensure_player(u, player, self.deps.clock.now())
            if item_id is not None:
                item = u.item(item_id)
                if item is None:
                    raise ItemNotFound(item_id)
                if item.owner != player.id:
                    raise NotOwner("only your own items can be shown")
            rec.showcase = item_id
            u.save_player(rec)
        return self.me(player)


class CreateTrade:
    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, player: Player, offer: NewTrade) -> TradeView:
        d = self.deps
        now = d.clock.now()
        check_offer(player.id, offer.to, offer.give, offer.take, offer.message)
        with d.store.unit() as u:
            me = ensure_player(u, player, now)
            them = u.player(offer.to)
            if them is None:
                raise PlayerNotFound(offer.to)
            if not me.has_won:
                raise TradingLocked("trading opens after your first win (a counted run)")
            if not them.has_won:
                raise TradingLocked("this player can't trade yet: trading opens after a first win")
            if u.pending_from(me.id, now) >= MAX_PENDING:
                raise TooManyOffers(f"at most {MAX_PENDING} open offers: cancel one first")
            items = u.items([*offer.give, *offer.take])
            check_items(me.id, offer.give, items, now, moved=False)
            check_items(them.id, offer.take, items, now, moved=False)
            trade = Trade(id=d.ids.new_id(), sender=me.id, recipient=them.id, give=tuple(offer.give),
                          take=tuple(offer.take), message=offer.message.strip(), status=TradeStatus.PENDING,
                          created_at=now, updated_at=now, expires_at=now + OFFER_LIFETIME)
            u.add_trade(trade)
            return self.views.trade(u, trade)


class ListTrades:
    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, player: Player, box: str = "all", limit: int = 100) -> list[TradeView]:
        with self.deps.store.unit() as u:
            return [self.views.trade(u, t) for t in u.trades_of(player.id, box, limit)]


def participant_trade(u: Unit, player: Player, trade_id: str, lock: bool = False) -> Trade:
    """A trade of the caller's; another's is TradeNotFound (don't say it exists)."""
    t = u.trade(trade_id, lock=lock)
    if t is None or player.id not in (t.sender, t.recipient):
        raise TradeNotFound(trade_id)
    return t


class GetTrade:
    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, player: Player, trade_id: str) -> TradeView:
        with self.deps.store.unit() as u:
            return self.views.trade(u, participant_trade(u, player, trade_id))


class _Respond:
    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def _respond(self, player: Player, trade_id: str, act: Callable[[Unit, Trade, datetime], None]) -> TradeView:
        with self.deps.store.unit() as u:
            t = participant_trade(u, player, trade_id, lock=True)
            act(u, t, self.deps.clock.now())
            u.save_trade(t)
            return self.views.trade(u, t)


class AcceptTrade(_Respond):
    """The recipient accepts: every item changes hands at once, or none does."""

    def __call__(self, player: Player, trade_id: str) -> TradeView:
        def accept(u: Unit, t: Trade, now: datetime) -> None:
            if player.id != t.recipient:
                raise NotParticipant("only the player the offer was made to can accept it")
            items = u.items([*t.give, *t.take], lock=True)
            for item, before in swap(t, items, now, self.deps.hold):
                u.save_item(item)
                u.add_transfer(Transfer(item=item.id, from_owner=before, to_owner=item.owner, at=now, trade=t.id))
            unshow(u, (t.sender, t.recipient), items)

        return self._respond(player, trade_id, accept)


class DeclineTrade(_Respond):
    def __call__(self, player: Player, trade_id: str) -> TradeView:
        def decline(_: Unit, t: Trade, now: datetime) -> None:
            if player.id != t.recipient:
                raise NotParticipant("only the player the offer was made to can decline it (the sender cancels)")
            t.close(TradeStatus.DECLINED, now)

        return self._respond(player, trade_id, decline)


class CancelTrade(_Respond):
    def __call__(self, player: Player, trade_id: str) -> TradeView:
        def cancel(_: Unit, t: Trade, now: datetime) -> None:
            if player.id != t.sender:
                raise NotParticipant("only the sender can cancel an offer (the other player declines)")
            t.close(TradeStatus.CANCELLED, now)

        return self._respond(player, trade_id, cancel)


RULES = [
    RuleView(source="weekly", coins=WEEKLY_COINS,
             description="Each week (from Monday, UTC): the first counted run that ends at ante 3 or later, or wins"),
    RuleView(source="weekly_win", coins=WIN_COINS, description="Each week: the first counted win"),
    RuleView(source="first_deck_win", coins=WIN_COINS, description="The first counted win with each deck"),
    RuleView(source="first_stake_win", coins=WIN_COINS,
             description=f"The first counted win at each stake from Red to Black (Gold: {GOLD_COINS} coins)"),
]


class GetOdds:
    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self) -> OddsView:
        pools = self.views.pools()
        tables = []
        for t in TABLES.values():
            chances = pools.chances(t) or {r: w for r, w in t.rarities.items() if w > 0}
            tables.append(TableView(kind=t.kind, tier=t.tier,
                                    rarities=percent({Rarity(r).name.lower(): w for r, w in chances.items()}),
                                    editions=percent({e.value: w for e, w in t.editions.items() if w > 0})))
        return OddsView(
            rules=RULES, boosters=[self.views.booster(b, pools) for b in BOOSTERS.values()], tables=tables,
            pools={k.value: {Rarity(r).name.lower(): n for r, n in rs.items()} for k, rs in pools.counts().items()},
            trade_hold_days=self.deps.hold.total_seconds() / 86400, offer_days=OFFER_LIFETIME.days,
            market_min_price=MIN_PRICE, market_max_price=MAX_PRICE, market_max_listings=MAX_LISTINGS)


class GiveItem:
    """An admin's gift (events, prizes): the only way to make an item outside the boosters."""

    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, admin: Player, gift: Gift) -> ItemView:
        d = self.deps
        if not is_admin(d, admin):
            raise NotAdmin("only admins give items")
        template = self.views.pools(strict=True).by_variant.get(variant(gift.key, gift.enhancement, gift.seal))
        if template is None:
            raise UnknownTemplate(f"no card {variant(gift.key, gift.enhancement, gift.seal)!r}")
        if gift.edition not in EDITIONS[template.kind]:
            raise UnknownTemplate(f"the game makes no {gift.edition.value} {template.kind.value} card")
        now = d.clock.now()
        with d.store.unit() as u:
            if u.player(gift.to) is None:
                raise PlayerNotFound(gift.to)
            item = u.add_item(Item(
                id=d.ids.new_id(), kind=template.kind, key=template.key, edition=gift.edition, rarity=template.rarity,
                stake=gift.stake, serial=0, owner=gift.to, source="gift", source_run=None, created_at=now,
                acquired_at=now, tradable_at=now + d.hold, enhancement=template.enhancement, seal=template.seal,
                condition=gift.condition if gift.condition is not None else roll_condition(d.rng)))
            u.add_transfer(Transfer(item=item.id, from_owner=None, to_owner=gift.to, at=now))
            log.info("admin %s gave %s (%s) to %s", admin.id, item.variant, item.edition, gift.to)
            return self.views.item(u, item)


MAX_GIFT = 10_000_000


class GiveCoins:
    """An admin's gift of coins (events, prizes; negative: takes them back, down to 0): the only way to make
    coins outside the grants."""

    def __init__(self, deps: Deps) -> None:
        self.deps = deps

    def __call__(self, admin: Player, gift: CoinGift) -> CoinMoveView:
        d = self.deps
        if not is_admin(d, admin):
            raise NotAdmin("only admins give coins")
        if gift.coins == 0 or abs(gift.coins) > MAX_GIFT:
            raise InvalidListing(f"a gift is from 1 to {MAX_GIFT:,} coins (or as many taken back)")
        now = d.clock.now()
        with d.store.unit() as u:
            if u.player(gift.to) is None:
                raise PlayerNotFound(gift.to)
            balance = u.add_coins(gift.to, gift.coins, "gift", gift.note.strip()[:200] or None, now)
            log.info("admin %s gave %d coins to %s", admin.id, gift.coins, gift.to)
            return CoinMoveView(amount=gift.coins, balance=balance, reason="gift", ref=gift.note.strip()[:200] or None,
                                at=now)


class MyCoins:
    def __init__(self, deps: Deps) -> None:
        self.deps = deps

    def __call__(self, player: Player, limit: int = 100) -> CoinsView:
        with self.deps.store.unit() as u:
            rec = ensure_player(u, player, self.deps.clock.now())
            return CoinsView(balance=rec.coins, moves=[
                CoinMoveView(amount=m.amount, balance=m.balance, reason=m.reason, ref=m.ref, at=m.at)
                for m in u.coin_moves(player.id, limit)])


class ListBoosters:
    """What coins buy (public)."""

    def __init__(self, deps: Deps) -> None:
        self.views = Views(deps)

    def __call__(self) -> list[BoosterView]:
        pools = self.views.pools()
        return [self.views.booster(b, pools) for b in BOOSTERS.values()]


class BuyBooster:
    """Coins for a pack: its cards are rolled at once (and kept until the player chooses)."""

    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, player: Player, booster_id: str) -> PackView:
        d = self.deps
        booster = BOOSTERS.get(booster_id)
        if booster is None:
            raise BoosterNotFound(booster_id)
        pools = self.views.pools(strict=True)  # (outside the transaction: the game API may be slow)
        if not pools.by_kind.get(booster.kind):
            raise GameApiUnavailable("the game's cards can't be read now, try again")
        now = d.clock.now()
        with d.store.unit() as u:
            ensure_player(u, player, now)
            pack = Pack(id=d.ids.new_id(), owner=player.id, booster=booster.id, price=booster.price,
                        picks=booster.picks, choices=roll_pack(booster, pools, d.rng), status=PackStatus.OPEN,
                        created_at=now)
            u.add_coins(player.id, -booster.price, "booster", pack.id, now)
            u.add_pack(pack)
            log.info("player %s bought %s (%s)", player.id, booster.id, pack.id)
            return self.views.pack(u, pack)


def own_pack(u: Unit, player: Player, pack_id: str, lock: bool = False) -> Pack:
    """A pack of the caller's; another's is PackNotFound (don't say it exists)."""
    p = u.pack(pack_id, lock=lock)
    if p is None or p.owner != player.id:
        raise PackNotFound(pack_id)
    return p


class MyPacks:
    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, player: Player, status: PackStatus | None = PackStatus.OPEN, limit: int = 50) -> list[PackView]:
        with self.deps.store.unit() as u:
            return [self.views.pack(u, p) for p in u.packs_of(player.id, status, limit)]


class GetPack:
    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, player: Player, pack_id: str) -> PackView:
        with self.deps.store.unit() as u:
            return self.views.pack(u, own_pack(u, player, pack_id))


class ChoosePack:
    """The player's choice: the cards chosen become their items (numbered then), the others are gone."""

    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, player: Player, pack_id: str, picks: Sequence[int]) -> PackView:
        d = self.deps
        now = d.clock.now()
        with d.store.unit() as u:
            pack = own_pack(u, player, pack_id, lock=True)
            made: list[str] = []
            for c in choose(pack, picks, now):
                item = u.add_item(Item(
                    id=d.ids.new_id(), kind=c.kind, key=c.key, edition=c.edition, rarity=c.rarity, stake=None,
                    serial=0, owner=player.id, source="booster", source_run=None, created_at=now, acquired_at=now,
                    tradable_at=now + d.hold, enhancement=c.enhancement, seal=c.seal, booster=pack.booster,
                    condition=c.condition if c.condition is not None else roll_condition(d.rng)))
                u.add_transfer(Transfer(item=item.id, from_owner=None, to_owner=player.id, at=now))
                made.append(item.id)
                log.info("player %s chose %s (%s) from %s", player.id, item.variant, item.edition, pack.booster)
            pack.items = tuple(made)
            u.save_pack(pack)
            return self.views.pack(u, pack)


SORTS = ("newest", "price", "-price")


class SearchMarket:
    """The items for sale (public, as inventories are): by kind, rarity, edition, a name (the game's English one or
    the key), the cheapest or newest first."""

    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, viewer: Player, *, kind: Kind | None = None, rarity: Rarity | None = None,
                 edition: Edition | None = None, q: str = "", seller: str | None = None, sort: str = "newest",
                 limit: int = 50, offset: int = 0) -> list[ListingView]:
        if sort not in SORTS:
            raise InvalidListing(f"sort is one of {', '.join(SORTS)}")
        keys: tuple[str, ...] | None = None
        if q.strip():
            needle = q.strip().casefold()
            keys = tuple(sorted({t.key for t in self.views.pools().by_variant.values()
                                 if needle in t.name.casefold() or needle == t.key.casefold()}))
            if not keys:
                return []
        query = ListingQuery(status=ListingStatus.OPEN, kind=kind, rarity=rarity, edition=edition, keys=keys,
                             seller=seller, sort=sort, limit=limit, offset=offset)
        with self.deps.store.unit() as u:
            return self.views.listings(u, u.listings(query))


class MarketSales:
    """The last sales (of one variant and edition: what such an item sells for)."""

    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, viewer: Player, *, variant_: str | None = None, edition: Edition | None = None,
                 kind: Kind | None = None, limit: int = 20) -> list[ListingView]:
        query = ListingQuery(status=ListingStatus.SOLD, variant=variant_, edition=edition, kind=kind, limit=limit)
        with self.deps.store.unit() as u:
            return self.views.listings(u, u.listings(query))


class MyListings:
    """``box``: selling (your items for sale), sold, bought, or all (everything you sold, bought or took off)."""

    BOXES = ("selling", "sold", "bought", "all")

    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, player: Player, box: str = "selling", limit: int = 100, offset: int = 0) -> list[ListingView]:
        if box not in self.BOXES:
            raise InvalidListing(f"box is one of {', '.join(self.BOXES)}")
        query = {
            "selling": ListingQuery(status=ListingStatus.OPEN, seller=player.id, limit=limit, offset=offset),
            "sold": ListingQuery(status=ListingStatus.SOLD, seller=player.id, limit=limit, offset=offset),
            "bought": ListingQuery(status=ListingStatus.SOLD, buyer=player.id, limit=limit, offset=offset),
            "all": ListingQuery(status=None, player=player.id, limit=limit, offset=offset),
        }[box]
        with self.deps.store.unit() as u:
            return self.views.listings(u, u.listings(query))


class GetListing:
    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, viewer: Player, listing_id: str) -> ListingView:
        with self.deps.store.unit() as u:
            x = u.listing(listing_id)
            if x is None:
                raise ListingNotFound(listing_id)
            return self.views.listing(u, x)


class CreateListing:
    """An item for sale, at the seller's price: it can't change hands any other way until it is sold or taken off."""

    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, player: Player, offer: NewListing) -> ListingView:
        d = self.deps
        check_price(offer.price)
        now = d.clock.now()
        with d.store.unit() as u:
            me = ensure_player(u, player, now)
            if not me.has_won:
                raise TradingLocked("the market opens after your first win (a counted run)")
            if u.open_listings_of(me.id) >= MAX_LISTINGS:
                raise TooManyListings(f"at most {MAX_LISTINGS} items on the market at once: take one off first")
            items = u.items([offer.item], lock=True)
            check_items(me.id, [offer.item], items, now, moved=False)
            item = items[offer.item]
            listing = Listing(id=d.ids.new_id(), seller=me.id, item=item.id, price=offer.price,
                              status=ListingStatus.OPEN, created_at=now, updated_at=now)
            item.listed = listing.id
            u.add_listing(listing)
            u.save_item(item)
            return self.views.listing(u, listing)


class CancelListing:
    """The seller takes their item off the market."""

    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, player: Player, listing_id: str) -> ListingView:
        now = self.deps.clock.now()
        with self.deps.store.unit() as u:
            x = u.listing(listing_id, lock=True)
            if x is None:
                raise ListingNotFound(listing_id)
            item = u.items([x.item], lock=True).get(x.item)
            take_off(x, item, player.id, now)
            if item is not None:
                u.save_item(item)
            u.save_listing(x)
            return self.views.listing(u, x)


class BuyListing:
    """The buyer's coins to the seller, the item to the buyer: all at once, or nothing (not enough coins, the item
    gone)."""

    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, player: Player, listing_id: str) -> ListingView:
        d = self.deps
        now = d.clock.now()
        with d.store.unit() as u:
            me = ensure_player(u, player, now)
            x = u.listing(listing_id, lock=True)
            if x is None:
                raise ListingNotFound(listing_id)
            if not me.has_won and x.seller != me.id:
                raise TradingLocked("the market opens after your first win (a counted run)")
            items = u.items([x.item], lock=True)
            item = items.get(x.item)
            seller = sell(x, item, me.id, now, d.hold)
            assert item is not None
            # (both balances in the players' order: two purchases between the same players don't wait on each other)
            for pid in sorted((me.id, seller)):
                if pid == me.id:
                    u.add_coins(me.id, -x.price, "market_buy", x.id, now)
                else:
                    u.add_coins(seller, x.price, "market_sale", x.id, now)
            u.save_item(item)
            u.add_transfer(Transfer(item=item.id, from_owner=seller, to_owner=me.id, at=now, listing=x.id,
                                    price=x.price))
            u.save_listing(x)
            unshow(u, [seller], items)
            log.info("player %s bought %s from %s for %d coins", me.id, item.variant, seller, x.price)
            return self.views.listing(u, x)


class Casino:
    """What the casino's use cases share: staking items, ending games, showing them, and telling the live
    streams (domain/casino.py has the games' rules)."""

    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def check_open(self) -> None:
        if not self.deps.casino_open:
            raise CasinoClosed("the casino is closed")

    def publish(self, views: Sequence[GameView]) -> None:
        """Once their transaction is done: every open live stream hears of the games."""
        for v in views:
            self.deps.feed.publish(CasinoEvent("game", v))

    def stake(self, u: Unit, player: Player, bet: NewBet, game_id: str, pools: Pools, now: datetime) -> Entry:
        """The player's entry: their items (theirs, out of their trade hold) staked in the game, at their value
        (value.py: their card, upgrades and condition)."""
        d = self.deps
        seed = bet.seed or d.seeds.seed()[:16]
        check_bet(bet.items, seed)
        rec = ensure_player(u, player, now)
        if not rec.has_won:
            raise TradingLocked("the casino opens after your first win (a counted run)")
        items = u.items(bet.items, lock=True)
        check_items(player.id, bet.items, items, now, moved=False)
        value = 0
        for i in bet.items:
            item = items[i]
            if item.variant not in pools.by_variant:
                raise InvalidBet(f"item {i!r} has no value for now: try again later")
            value += item_value(item)
            item.staked = game_id
            u.save_item(item)
        return Entry(player=player.id, items=tuple(bet.items), value=value, seed=seed, at=now)

    def end(self, u: Unit, game: Game, now: datetime) -> None:
        """A drawn or cancelled game: its items are unstaked, and the winner takes the others'."""
        items = u.items(game.items, lock=True)
        for item, before in pay_out(game, items, now, self.deps.hold):
            u.add_transfer(Transfer(item=item.id, from_owner=before, to_owner=item.owner, at=now, game=game.id))
        for item in items.values():
            u.save_item(item)
        unshow(u, game.players, items)
        u.save_game(game)
        if game.status is GameStatus.DONE:
            log.info("%s %s: %s won %d items worth %d", game.mode.value, game.id, game.winner, len(game.items),
                     game.value)

    def jackpot(self, u: Unit, now: datetime, out: list[GameView]) -> Game | None:
        """The pot taking items, after drawing it if its time has come (None: there is none; the drawn pot goes
        to ``out``). Holds the jackpot until the unit ends."""
        game = u.open_jackpot(lock=True)
        if game is not None and game.due(now):
            draw(game, now)
            self.end(u, game, now)
            out.append(self.view(u, game))
            return None
        return game

    def settle(self) -> None:
        """Draws the jackpot if its time has come."""
        now = self.deps.clock.now()
        with self.deps.store.unit() as u:
            game = u.open_jackpot()
        if game is not None and game.due(now):
            out: list[GameView] = []
            with self.deps.store.unit() as u:
                self.jackpot(u, now, out)
            self.publish(out)

    def view(self, u: Unit, game: Game) -> GameView:
        items = {v.id: v for v in self.views.items(u, list(u.items(game.items).values()))}
        names: dict[str, str | None] = {}
        for pid in [*game.players, *([game.opponent] if game.opponent else [])]:
            rec = u.player(pid)
            names[pid] = rec.name if rec else None
        total = game.value
        entries = [EntryView(player=e.player, player_name=names[e.player],
                             items=[items[i] for i in e.items if i in items], value=e.value,
                             chance=round(100 * e.value / total, 2) if total else 0.0, low=low, high=high, seed=e.seed,
                             at=e.at)
                   for e, (low, high) in zip(game.entries, parts(game.entries), strict=True)]
        is_open = game.status is GameStatus.OPEN
        join = join_range(total, game.asked) if is_open and game.mode in DUELS and total else None
        return GameView(
            id=game.id, mode=game.mode, status=game.status, side=game.side, entries=entries, value=total,
            seed_hash=game.seed_hash, server_seed=None if is_open else game.server_seed, roll=game.roll,
            winner=game.winner, winner_name=names.get(game.winner) if game.winner else None,
            join_min=join[0] if join else None, join_max=join[1] if join else None, created_at=game.created_at,
            updated_at=game.updated_at, closes_at=game.closes_at, chance=game.chance, opponent=game.opponent,
            opponent_name=names.get(game.opponent) if game.opponent else None)

    def win(self, u: Unit, game: Game, names: dict[str, str | None]) -> WinView:
        winner = game.winner or ""
        if winner not in names:
            rec = u.player(winner)
            names[winner] = rec.name if rec else None
        return WinView(game=game.id, mode=game.mode, player=winner, player_name=names[winner], value=game.value,
                       chance=round(100 * winner_chance(game), 2), players=len(game.players),
                       items=len(game.items), at=game.updated_at)


class CasinoRules:
    def __init__(self, deps: Deps) -> None:
        self.deps = deps

    def __call__(self) -> CasinoRulesView:
        d = self.deps
        return CasinoRulesView(
            open=d.casino_open, max_items=MAX_STAKE, coinflip_margin=COINFLIP_MARGIN,
            max_open_coinflips=MAX_OPEN_COINFLIPS, jackpot_seconds=d.jackpot_wait.total_seconds(),
            jackpot_max_players=JACKPOT_MAX_PLAYERS, jackpot_max_items=JACKPOT_MAX_ITEMS,
            trade_hold_days=d.hold.total_seconds() / 86400, dice_min_chance=MIN_CHANCE, dice_max_chance=MAX_CHANCE)


class OpenDuels(Casino):
    """The coinflips (or dice games) waiting for a second player, newest first; challenges too (``opponent``:
    only they may join)."""

    def __init__(self, deps: Deps, mode: Mode) -> None:
        super().__init__(deps)
        self.mode = mode

    def __call__(self, viewer: Player, limit: int = 100) -> list[GameView]:
        with self.deps.store.unit() as u:
            return [self.view(u, g) for g in u.games(self.mode, GameStatus.OPEN, None, limit)]


class CreateDuel(Casino):
    """A coinflip (its first player's side) or a dice game (its first player's chance): items waiting for a
    second player, or for the player challenged."""

    def __init__(self, deps: Deps, mode: Mode) -> None:
        super().__init__(deps)
        self.mode = mode

    def __call__(self, player: Player, bet: NewBet) -> GameView:
        self.check_open()
        d = self.deps
        chance = None
        if self.mode is Mode.DICE:
            chance = bet.chance if bet.chance is not None else 50
            check_chance(chance)
        check_challenge(player.id, bet.opponent)
        pools = self.views.pools(strict=True)  # (outside the transaction: the game API may be slow)
        now = d.clock.now()
        with d.store.unit() as u:
            if len(u.games(self.mode, GameStatus.OPEN, player.id, MAX_OPEN_COINFLIPS)) >= MAX_OPEN_COINFLIPS:
                raise TooManyGames(f"at most {MAX_OPEN_COINFLIPS} open {self.mode.value} games: cancel one first")
            if bet.opponent is not None:
                them = u.player(bet.opponent)
                if them is None:
                    raise PlayerNotFound(bet.opponent)
                if not them.has_won:
                    raise TradingLocked("this player can't play yet: the casino opens after a first win")
            game = Game(id=d.ids.new_id(), mode=self.mode, status=GameStatus.OPEN,
                        side=(bet.side or Side.CHIPS) if self.mode is Mode.COINFLIP else None, entries=[],
                        server_seed=d.seeds.seed(), created_at=now, updated_at=now, opponent=bet.opponent,
                        chance=chance)
            game.entries.append(self.stake(u, player, bet, game.id, pools, now))
            u.add_game(game)
            view = self.view(u, game)
        self.publish([view])
        return view


class JoinDuel(Casino):
    """The second player's items: the coin is flipped (the dice rolled) at once, and the winner takes them all."""

    def __init__(self, deps: Deps, mode: Mode) -> None:
        super().__init__(deps)
        self.mode = mode

    def __call__(self, player: Player, game_id: str, bet: NewBet) -> GameView:
        self.check_open()
        d = self.deps
        pools = self.views.pools(strict=True)
        now = d.clock.now()
        with d.store.unit() as u:
            game = u.game(game_id, lock=True)
            if game is None or game.mode is not self.mode:
                raise GameNotFound(game_id)
            check_join(game, player.id)
            join_duel(game, self.stake(u, player, bet, game.id, pools, now))
            draw(game, now)
            self.end(u, game, now)
            view = self.view(u, game)
        self.publish([view])
        return view


class CancelDuel(Casino):
    """Takes back the items of a coinflip (dice game) nobody has joined (also when the casino is closed)."""

    def __init__(self, deps: Deps, mode: Mode) -> None:
        super().__init__(deps)
        self.mode = mode

    def __call__(self, player: Player, game_id: str) -> GameView:
        now = self.deps.clock.now()
        with self.deps.store.unit() as u:
            game = u.game(game_id, lock=True)
            if game is None or game.mode is not self.mode:
                raise GameNotFound(game_id)
            cancel(game, player.id, now)
            self.end(u, game, now)
            view = self.view(u, game)
        self.publish([view])
        return view


class GetJackpot(Casino):
    def __call__(self, viewer: Player) -> JackpotView:
        self.settle()
        now = self.deps.clock.now()
        with self.deps.store.unit() as u:
            game = u.open_jackpot()
            last = u.games(Mode.JACKPOT, GameStatus.DONE, None, 1)
            return JackpotView(round=self.view(u, game) if game else None,
                               last=self.view(u, last[0]) if last else None, now=now)


class JoinJackpot(Casino):
    """Items in the pot (the first opens one); the second player starts the countdown to the draw."""

    def __call__(self, player: Player, bet: NewBet) -> GameView:
        self.check_open()
        d = self.deps
        pools = self.views.pools(strict=True)
        now = d.clock.now()
        out: list[GameView] = []
        with d.store.unit() as u:
            game = self.jackpot(u, now, out)
            if game is None:
                game = Game(id=d.ids.new_id(), mode=Mode.JACKPOT, status=GameStatus.OPEN, side=None, entries=[],
                            server_seed=d.seeds.seed(), created_at=now, updated_at=now)
                u.add_game(game)
            join_jackpot(game, self.stake(u, player, bet, game.id, pools, now), d.jackpot_wait)
            u.save_game(game)
            view = self.view(u, game)
            out.append(view)
        self.publish(out)
        return view


class LeaveJackpot(Casino):
    """Takes back your items from a pot nobody else is in (also when the casino is closed)."""

    def __call__(self, player: Player) -> GameView:
        now = self.deps.clock.now()
        out: list[GameView] = []
        with self.deps.store.unit() as u:
            game = self.jackpot(u, now, out)
            if game is None or player.id not in game.players:
                raise NotParticipant("you have no items in the pot")
            cancel(game, player.id, now)
            self.end(u, game, now)
            view = self.view(u, game)
            out.append(view)
        self.publish(out)
        return view


class GetGame(Casino):
    """Any casino game (they are public, as inventories are)."""

    def __call__(self, viewer: Player, game_id: str) -> GameView:
        self.settle()
        with self.deps.store.unit() as u:
            game = u.game(game_id)
            if game is None:
                raise GameNotFound(game_id)
            return self.view(u, game)


class CasinoHistory(Casino):
    """Games that are over, the last first: everyone's, or one player's (``before``: older than this, for the
    next page)."""

    def __call__(self, viewer: Player, player: str | None = None, mode: Mode | None = None,
                 limit: int = 20, before: datetime | None = None) -> list[GameView]:
        with self.deps.store.unit() as u:
            return [self.view(u, g) for g in u.games(mode, GameStatus.DONE, player, limit, before=before)]


STATS_GAMES = 5000  # a player's statistics count their last games, this many at most
LEADERBOARD_GAMES = 20000  # a leaderboard counts the period's last games, this many at most
TOP = 10
PERIODS = {"day": timedelta(days=1), "week": timedelta(days=7), "all": None}


class CasinoStats(Casino):
    """A player's games that are over, in numbers: games, wins, value staked, won and lost, their best wins
    (public, as their games are)."""

    def __call__(self, viewer: Player, player_id: str) -> CasinoStatsView:
        with self.deps.store.unit() as u:
            rec = u.player(player_id)
            if rec is None:
                raise PlayerNotFound(player_id)
            t = tally(u.games(None, GameStatus.DONE, player_id, STATS_GAMES)).get(player_id, Tally(player=player_id))
            names: dict[str, str | None] = {player_id: rec.name}
            return CasinoStatsView(
                player=player_id, name=rec.name, games=t.games, wins=t.wins, staked=t.staked, won=t.won, lost=t.lost,
                net=t.net, modes={m.value: ModeStatsView(games=n, wins=w) for m, (n, w) in t.by_mode.items()},
                biggest=self.win(u, t.biggest, names) if t.biggest else None,
                luckiest=self.win(u, t.luckiest, names) if t.luckiest else None)


class CasinoLeaderboard(Casino):
    """The casino's best players and wins over a period (``PERIODS``)."""

    def __call__(self, viewer: Player, period: str = "week") -> LeaderboardView:
        if period not in PERIODS:
            raise InvalidBet(f"a period is one of {', '.join(PERIODS)}")
        span = PERIODS[period]
        since = self.deps.clock.now() - span if span is not None else None
        with self.deps.store.unit() as u:
            games = u.games(None, GameStatus.DONE, None, LEADERBOARD_GAMES, since=since)
            tallies = list(tally(games).values())
            names: dict[str, str | None] = {}
            for t in tallies:
                rec = u.player(t.player)
                names[t.player] = rec.name if rec else None

            def rank(t: Tally) -> RankView:
                return RankView(player=t.player, name=names[t.player], games=t.games, wins=t.wins, staked=t.staked,
                                net=t.net)

            winners = sorted((t for t in tallies if t.net > 0), key=lambda t: (-t.net, t.player))[:TOP]
            stakers = sorted(tallies, key=lambda t: (-t.staked, t.player))[:TOP]
            biggest = sorted(games, key=lambda g: (-g.value, g.id))[:TOP]
            luckiest = sorted(games, key=lambda g: (winner_chance(g), -g.value, g.id))[:TOP]
            return LeaderboardView(
                period=period, since=since, games=len(games), value=sum(g.value for g in games),
                players=len(tallies), winners=[rank(t) for t in winners], stakers=[rank(t) for t in stakers],
                biggest=[self.win(u, g, names) for g in biggest], luckiest=[self.win(u, g, names) for g in luckiest])


RECENT_GAMES = 12  # a live stream's first event has the last games drawn, this many


class CasinoSnapshot(Casino):
    """Everything the casino shows (a live stream's first event): the games waiting, the pot, the last draws."""

    def __call__(self, viewer: Player) -> CasinoSnapshotView:
        self.settle()
        now = self.deps.clock.now()
        with self.deps.store.unit() as u:
            pot = u.open_jackpot()
            last = u.games(Mode.JACKPOT, GameStatus.DONE, None, 1)
            return CasinoSnapshotView(
                coinflips=[self.view(u, g) for g in u.games(Mode.COINFLIP, GameStatus.OPEN, None, 100)],
                dice=[self.view(u, g) for g in u.games(Mode.DICE, GameStatus.OPEN, None, 100)],
                jackpot=JackpotView(round=self.view(u, pot) if pot else None,
                                    last=self.view(u, last[0]) if last else None, now=now),
                recent=[self.view(u, g) for g in u.games(None, GameStatus.DONE, None, RECENT_GAMES)],
                rules=CasinoRules(self.deps)())


class CasinoSubscribe:
    """A live stream of the casino's changes (its first event: CasinoSnapshot)."""

    def __init__(self, deps: Deps) -> None:
        self.deps = deps

    def __call__(self) -> FeedSubscription:
        return self.deps.feed.subscribe()


class SettleCasino(Casino):
    """Draws the jackpot when its time has come (the service does it every second, and any look at the jackpot
    does too)."""

    def __call__(self) -> None:
        self.settle()


@dataclass(frozen=True)
class UseCases:
    authenticate: Authenticate
    me: GetMe
    sync: SyncDrops
    my_items: MyItems
    player_items: PlayerItems
    player: GetPlayer
    find_players: FindPlayers
    item: GetItem
    showcase: SetShowcase
    create_trade: CreateTrade
    trades: ListTrades
    trade: GetTrade
    accept: AcceptTrade
    decline: DeclineTrade
    cancel: CancelTrade
    odds: GetOdds
    give: GiveItem
    give_coins: GiveCoins
    coins: MyCoins
    boosters: ListBoosters
    buy_booster: BuyBooster
    packs: MyPacks
    pack: GetPack
    choose: ChoosePack
    market: SearchMarket
    market_sales: MarketSales
    my_listings: MyListings
    listing: GetListing
    create_listing: CreateListing
    cancel_listing: CancelListing
    buy_listing: BuyListing
    casino_rules: CasinoRules
    coinflips: OpenDuels
    create_coinflip: CreateDuel
    join_coinflip: JoinDuel
    cancel_coinflip: CancelDuel
    dice_games: OpenDuels
    create_dice: CreateDuel
    join_dice: JoinDuel
    cancel_dice: CancelDuel
    jackpot: GetJackpot
    join_jackpot: JoinJackpot
    leave_jackpot: LeaveJackpot
    game: GetGame
    casino_history: CasinoHistory
    casino_stats: CasinoStats
    casino_leaderboard: CasinoLeaderboard
    casino_snapshot: CasinoSnapshot
    casino_subscribe: CasinoSubscribe
    settle_casino: SettleCasino


def build(deps: Deps, authenticator: Authenticator) -> UseCases:
    return UseCases(
        authenticate=Authenticate(authenticator), me=GetMe(deps), sync=SyncDrops(deps), my_items=MyItems(deps),
        player_items=PlayerItems(deps), player=GetPlayer(deps), find_players=FindPlayers(deps), item=GetItem(deps),
        showcase=SetShowcase(deps), create_trade=CreateTrade(deps), trades=ListTrades(deps), trade=GetTrade(deps),
        accept=AcceptTrade(deps), decline=DeclineTrade(deps), cancel=CancelTrade(deps), odds=GetOdds(deps),
        give=GiveItem(deps), give_coins=GiveCoins(deps), coins=MyCoins(deps), boosters=ListBoosters(deps),
        buy_booster=BuyBooster(deps), packs=MyPacks(deps), pack=GetPack(deps), choose=ChoosePack(deps),
        market=SearchMarket(deps), market_sales=MarketSales(deps), my_listings=MyListings(deps),
        listing=GetListing(deps), create_listing=CreateListing(deps), cancel_listing=CancelListing(deps),
        buy_listing=BuyListing(deps), casino_rules=CasinoRules(deps), coinflips=OpenDuels(deps, Mode.COINFLIP),
        create_coinflip=CreateDuel(deps, Mode.COINFLIP), join_coinflip=JoinDuel(deps, Mode.COINFLIP),
        cancel_coinflip=CancelDuel(deps, Mode.COINFLIP), dice_games=OpenDuels(deps, Mode.DICE),
        create_dice=CreateDuel(deps, Mode.DICE), join_dice=JoinDuel(deps, Mode.DICE),
        cancel_dice=CancelDuel(deps, Mode.DICE), jackpot=GetJackpot(deps), join_jackpot=JoinJackpot(deps),
        leave_jackpot=LeaveJackpot(deps), game=GetGame(deps), casino_history=CasinoHistory(deps),
        casino_stats=CasinoStats(deps), casino_leaderboard=CasinoLeaderboard(deps),
        casino_snapshot=CasinoSnapshot(deps), casino_subscribe=CasinoSubscribe(deps), settle_casino=SettleCasino(deps))
