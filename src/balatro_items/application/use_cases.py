"""The use cases: one class each, taking the caller (``Player``) first.

Items are only found through ``SyncDrops`` (the game API's runs earn them,
domain/drops.py) and an admin's gift, and only change hands through an
accepted trade or a casino game (domain/casino.py). Every change happens in
one store transaction (``Unit``)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from balatro_items.domain import (
    COINFLIP_MARGIN,
    JACKPOT_MAX_ITEMS,
    JACKPOT_MAX_PLAYERS,
    MAX_OPEN_COINFLIPS,
    MAX_PENDING,
    MAX_STAKE,
    OFFER_LIFETIME,
    TABLES,
    DomainError,
    Entry,
    Game,
    GameNotFound,
    GameStatus,
    InvalidBet,
    Item,
    ItemNotFound,
    Mode,
    NotOwner,
    NotParticipant,
    PlayerNotFound,
    PlayerRecord,
    Random,
    Rarity,
    Side,
    Template,
    TooManyGames,
    TooManyOffers,
    Trade,
    TradeNotFound,
    TradeStatus,
    TradingLocked,
    Transfer,
    cancel,
    check_bet,
    check_items,
    check_join,
    check_offer,
    coinflip_range,
    draw,
    earned,
    join_coinflip,
    join_jackpot,
    next_week,
    odds,
    parts,
    pay_out,
    pools,
    roll,
    swap,
    week_of,
)

from .dto import (
    CasinoRulesView,
    DropsView,
    EntryView,
    GameView,
    Gift,
    ItemDetail,
    ItemView,
    JackpotView,
    MeView,
    NewBet,
    NewTrade,
    OddsView,
    Player,
    PlayerView,
    RuleView,
    TableView,
    TradeView,
    TransferView,
    WeekView,
)
from .errors import CasinoClosed, GameApiUnavailable, NotAdmin, UnknownTemplate
from .ports import Authenticator, Catalog, Clock, IdGenerator, RunSource, SeedSource, Store, Unit

log = logging.getLogger(__name__)

SYNC_EVERY = timedelta(seconds=5)  # a player's runs are read at most this often
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


class Views:
    """Items and trades as the clients see them (names and sprites from the catalog)."""

    def __init__(self, deps: Deps) -> None:
        self.deps = deps

    def templates(self) -> list[Template]:
        try:
            return self.deps.catalog.templates()
        except GameApiUnavailable:
            return []  # (shown by key, without odds, until the catalog is back)

    def items(self, u: Unit, items: Sequence[Item]) -> list[ItemView]:
        templates = self.templates()
        by_key = {t.key: t for t in templates}
        names: dict[str, str | None] = {}
        now = self.deps.clock.now()
        out = []
        for it in items:
            if it.owner not in names:
                rec = u.player(it.owner)
                names[it.owner] = rec.name if rec else None
            t = by_key.get(it.key)
            out.append(ItemView(
                id=it.id, kind=it.kind, key=it.key, name=t.name if t else it.key, edition=it.edition, rarity=it.rarity,
                stake=it.stake, serial=it.serial, minted=u.minted(it.key, it.edition),
                odds=odds(t, it.edition, templates) if t else 0, owner=it.owner, owner_name=names[it.owner],
                source=it.source, source_run=it.source_run, found_at=it.created_at, acquired_at=it.acquired_at,
                tradable_at=it.tradable_at, tradable=it.tradable(now), staked=it.staked,
                sprite=t.sprite if t else None))
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
        return WeekView(week=week, weekly_found=f"week:{week}:play" in claims,
                        weekly_win_found=f"week:{week}:win" in claims, next_week_at=next_week(now))

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
                          items=len(u.items_of(rec.id)), showcase=self.views.showcase(u, rec),
                          week=self.views.week(u, rec.id))


class SyncDrops:
    """Reads the player's runs from the game API and gives the items they have earned
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
            with d.store.unit() as u:
                return DropsView(found=[], week=self.views.week(u, player.id))
        runs = d.runs.runs(player)  # (outside the transaction: the game API may be slow)
        templates = d.catalog.templates()
        found: list[Item] = []
        with d.store.unit() as u:
            rec = u.player(player.id, lock=True) or ensure_player(u, player, now)
            rec.has_won = rec.has_won or any(r.won and r.counted for r in runs)
            rec.synced_at = now
            u.save_player(rec)
            for grant in earned(runs, u.claims(player.id), now):
                template, edition = roll(grant.table, templates, d.rng)
                item = Item(id=d.ids.new_id(), kind=template.kind, key=template.key, edition=edition,
                            rarity=template.rarity, stake=grant.stake, serial=0, owner=player.id, source=grant.reason,
                            source_run=grant.run, created_at=now, acquired_at=now, tradable_at=now + d.hold)
                if u.claim(player.id, grant.source, item.id, grant.run, now):
                    found.append(u.add_item(item))
                    u.add_transfer(Transfer(item=item.id, from_owner=None, to_owner=player.id, at=now))
                    log.info("player %s found %s (%s) for %s", player.id, item.key, item.edition, grant.source)
            return DropsView(found=self.views.items(u, found), week=self.views.week(u, player.id))


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
                                    to_name=name(t.to_owner), at=t.at, trade=t.trade, game=t.game)
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
            # (an item shown by its former owner isn't theirs to show any more)
            for pid in (t.sender, t.recipient):
                rec = u.player(pid, lock=True)
                if rec is not None and rec.showcase in items and items[rec.showcase].owner != pid:
                    rec.showcase = None
                    u.save_player(rec)

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
    RuleView(source="weekly", table="standard",
             description="Each week (from Monday, UTC): the first counted run that ends at ante 3 or later, or wins"),
    RuleView(source="weekly_win", table="boosted", description="Each week: the first counted win"),
    RuleView(source="first_deck_win", table="boosted", description="The first counted win with each deck"),
    RuleView(source="first_stake_win", table="boosted",
             description="The first counted win at each stake from Red to Black (Gold: the premium table)"),
]


class GetOdds:
    def __init__(self, deps: Deps) -> None:
        self.deps = deps

    def __call__(self) -> OddsView:
        def pct(w: dict[str, float]) -> dict[str, float]:
            total = sum(w.values())
            return {k: round(100 * v / total, 3) for k, v in w.items()}

        by_kind = pools(Views(self.deps).templates())
        return OddsView(
            rules=RULES,
            tables=[TableView(name=t.name, kinds=pct({k.value: v for k, v in t.kinds.items()}),
                              rarities=pct({Rarity(r).name.lower(): v for r, v in t.rarities.items()}),
                              editions=pct({e.value: v for e, v in t.editions.items()})) for t in TABLES],
            pools={k.value: {Rarity(r).name.lower(): len(p) for r, p in sorted(rs.items())}
                   for k, rs in by_kind.items()},
            trade_hold_days=self.deps.hold.total_seconds() / 86400, offer_days=OFFER_LIFETIME.days)


class GiveItem:
    """An admin's gift (events, prizes): the only way to make an item outside the drops."""

    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def __call__(self, admin: Player, gift: Gift) -> ItemView:
        d = self.deps
        if not is_admin(d, admin):
            raise NotAdmin("only admins give items")
        template = next((t for t in d.catalog.templates() if t.key == gift.key), None)
        if template is None:
            raise UnknownTemplate(f"no joker or tag {gift.key!r}")
        now = d.clock.now()
        with d.store.unit() as u:
            if u.player(gift.to) is None:
                raise PlayerNotFound(gift.to)
            item = u.add_item(Item(
                id=d.ids.new_id(), kind=template.kind, key=template.key, edition=gift.edition, rarity=template.rarity,
                stake=gift.stake, serial=0, owner=gift.to, source="gift", source_run=None, created_at=now,
                acquired_at=now, tradable_at=now + d.hold))
            u.add_transfer(Transfer(item=item.id, from_owner=None, to_owner=gift.to, at=now))
            log.info("admin %s gave %s (%s) to %s", admin.id, item.key, item.edition, gift.to)
            return self.views.item(u, item)


class Casino:
    """What the casino's use cases share: staking items, ending games, showing them
    (domain/casino.py has the games' rules)."""

    def __init__(self, deps: Deps) -> None:
        self.deps, self.views = deps, Views(deps)

    def check_open(self) -> None:
        if not self.deps.casino_open:
            raise CasinoClosed("the casino is closed")

    def stake(self, u: Unit, player: Player, bet: NewBet, game_id: str, templates: Sequence[Template],
              now: datetime) -> Entry:
        """The player's entry: their items (theirs, out of their trade hold) staked in the game, at their value."""
        d = self.deps
        seed = bet.seed or d.seeds.seed()[:16]
        check_bet(bet.items, seed)
        rec = ensure_player(u, player, now)
        if not rec.has_won:
            raise TradingLocked("the casino opens after your first win (a counted run)")
        items = u.items(bet.items, lock=True)
        check_items(player.id, bet.items, items, now, moved=False)
        by_key = {t.key: t for t in templates}
        value = 0
        for i in bet.items:
            item = items[i]
            t = by_key.get(item.key)
            worth = odds(t, item.edition, templates) if t else 0
            if worth <= 0:
                raise InvalidBet(f"item {i!r} has no value for now: try again later")
            value += worth
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
        # (an item shown by its former owner isn't theirs to show any more)
        for pid in game.players:
            rec = u.player(pid, lock=True)
            if rec is not None and rec.showcase in items and items[rec.showcase].owner != pid:
                rec.showcase = None
                u.save_player(rec)
        u.save_game(game)
        if game.status is GameStatus.DONE:
            log.info("%s %s: %s won %d items worth %d", game.mode.value, game.id, game.winner, len(game.items),
                     game.value)

    def jackpot(self, u: Unit, now: datetime) -> Game | None:
        """The pot taking items, after drawing it if its time has come (None: there is none). Holds the
        jackpot until the unit ends."""
        game = u.open_jackpot(lock=True)
        if game is not None and game.due(now):
            draw(game, now)
            self.end(u, game, now)
            return None
        return game

    def settle(self) -> None:
        """Draws the jackpot if its time has come."""
        now = self.deps.clock.now()
        with self.deps.store.unit() as u:
            game = u.open_jackpot()
        if game is not None and game.due(now):
            with self.deps.store.unit() as u:
                self.jackpot(u, now)

    def view(self, u: Unit, game: Game) -> GameView:
        items = {v.id: v for v in self.views.items(u, list(u.items(game.items).values()))}
        names: dict[str, str | None] = {}
        for pid in game.players:
            rec = u.player(pid)
            names[pid] = rec.name if rec else None
        total = game.value
        entries = [EntryView(player=e.player, player_name=names[e.player],
                             items=[items[i] for i in e.items if i in items], value=e.value,
                             chance=round(100 * e.value / total, 2) if total else 0.0, low=low, high=high, seed=e.seed,
                             at=e.at)
                   for e, (low, high) in zip(game.entries, parts(game.entries), strict=True)]
        is_open = game.status is GameStatus.OPEN
        join = coinflip_range(total) if is_open and game.mode is Mode.COINFLIP else None
        return GameView(
            id=game.id, mode=game.mode, status=game.status, side=game.side, entries=entries, value=total,
            seed_hash=game.seed_hash, server_seed=None if is_open else game.server_seed, roll=game.roll,
            winner=game.winner, winner_name=names.get(game.winner) if game.winner else None,
            join_min=join[0] if join else None, join_max=join[1] if join else None, created_at=game.created_at,
            updated_at=game.updated_at, closes_at=game.closes_at)


class CasinoRules:
    def __init__(self, deps: Deps) -> None:
        self.deps = deps

    def __call__(self) -> CasinoRulesView:
        d = self.deps
        return CasinoRulesView(
            open=d.casino_open, max_items=MAX_STAKE, coinflip_margin=COINFLIP_MARGIN,
            max_open_coinflips=MAX_OPEN_COINFLIPS, jackpot_seconds=d.jackpot_wait.total_seconds(),
            jackpot_max_players=JACKPOT_MAX_PLAYERS, jackpot_max_items=JACKPOT_MAX_ITEMS,
            trade_hold_days=d.hold.total_seconds() / 86400)


class OpenCoinflips(Casino):
    """The coinflips waiting for a second player, newest first."""

    def __call__(self, viewer: Player, limit: int = 100) -> list[GameView]:
        with self.deps.store.unit() as u:
            return [self.view(u, g) for g in u.games(Mode.COINFLIP, GameStatus.OPEN, None, limit)]


class CreateCoinflip(Casino):
    def __call__(self, player: Player, bet: NewBet) -> GameView:
        self.check_open()
        d = self.deps
        templates = d.catalog.templates()  # (outside the transaction: the game API may be slow)
        now = d.clock.now()
        with d.store.unit() as u:
            if len(u.games(Mode.COINFLIP, GameStatus.OPEN, player.id, MAX_OPEN_COINFLIPS)) >= MAX_OPEN_COINFLIPS:
                raise TooManyGames(f"at most {MAX_OPEN_COINFLIPS} open coinflips: cancel one first")
            game = Game(id=d.ids.new_id(), mode=Mode.COINFLIP, status=GameStatus.OPEN, side=bet.side or Side.CHIPS,
                        entries=[], server_seed=d.seeds.seed(), created_at=now, updated_at=now)
            game.entries.append(self.stake(u, player, bet, game.id, templates, now))
            u.add_game(game)
            return self.view(u, game)


class JoinCoinflip(Casino):
    """The second player's items: the coin is flipped at once, and the winner takes them all."""

    def __call__(self, player: Player, game_id: str, bet: NewBet) -> GameView:
        self.check_open()
        d = self.deps
        templates = d.catalog.templates()
        now = d.clock.now()
        with d.store.unit() as u:
            game = u.game(game_id, lock=True)
            if game is None or game.mode is not Mode.COINFLIP:
                raise GameNotFound(game_id)
            check_join(game, player.id)
            join_coinflip(game, self.stake(u, player, bet, game.id, templates, now))
            draw(game, now)
            self.end(u, game, now)
            return self.view(u, game)


class CancelCoinflip(Casino):
    """Takes back the items of a coinflip nobody has joined (also when the casino is closed)."""

    def __call__(self, player: Player, game_id: str) -> GameView:
        now = self.deps.clock.now()
        with self.deps.store.unit() as u:
            game = u.game(game_id, lock=True)
            if game is None or game.mode is not Mode.COINFLIP:
                raise GameNotFound(game_id)
            cancel(game, player.id, now)
            self.end(u, game, now)
            return self.view(u, game)


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
        templates = d.catalog.templates()
        now = d.clock.now()
        with d.store.unit() as u:
            game = self.jackpot(u, now)
            if game is None:
                game = Game(id=d.ids.new_id(), mode=Mode.JACKPOT, status=GameStatus.OPEN, side=None, entries=[],
                            server_seed=d.seeds.seed(), created_at=now, updated_at=now)
                u.add_game(game)
            join_jackpot(game, self.stake(u, player, bet, game.id, templates, now), d.jackpot_wait)
            u.save_game(game)
            return self.view(u, game)


class LeaveJackpot(Casino):
    """Takes back your items from a pot nobody else is in (also when the casino is closed)."""

    def __call__(self, player: Player) -> GameView:
        now = self.deps.clock.now()
        with self.deps.store.unit() as u:
            game = self.jackpot(u, now)
            if game is None or player.id not in game.players:
                raise NotParticipant("you have no items in the pot")
            cancel(game, player.id, now)
            self.end(u, game, now)
            return self.view(u, game)


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
    """Games that are over, the last first: everyone's, or one player's."""

    def __call__(self, viewer: Player, player: str | None = None, mode: Mode | None = None,
                 limit: int = 20) -> list[GameView]:
        with self.deps.store.unit() as u:
            return [self.view(u, g) for g in u.games(mode, GameStatus.DONE, player, limit)]


class SettleCasino(Casino):
    """Draws the jackpot when its time has come (the service does it every few seconds, and any look at
    the jackpot does too)."""

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
    casino_rules: CasinoRules
    coinflips: OpenCoinflips
    create_coinflip: CreateCoinflip
    join_coinflip: JoinCoinflip
    cancel_coinflip: CancelCoinflip
    jackpot: GetJackpot
    join_jackpot: JoinJackpot
    leave_jackpot: LeaveJackpot
    game: GetGame
    casino_history: CasinoHistory
    settle_casino: SettleCasino


def build(deps: Deps, authenticator: Authenticator) -> UseCases:
    return UseCases(
        authenticate=Authenticate(authenticator), me=GetMe(deps), sync=SyncDrops(deps), my_items=MyItems(deps),
        player_items=PlayerItems(deps), player=GetPlayer(deps), find_players=FindPlayers(deps), item=GetItem(deps),
        showcase=SetShowcase(deps), create_trade=CreateTrade(deps), trades=ListTrades(deps), trade=GetTrade(deps),
        accept=AcceptTrade(deps), decline=DeclineTrade(deps), cancel=CancelTrade(deps), odds=GetOdds(deps),
        give=GiveItem(deps), casino_rules=CasinoRules(deps), coinflips=OpenCoinflips(deps),
        create_coinflip=CreateCoinflip(deps), join_coinflip=JoinCoinflip(deps), cancel_coinflip=CancelCoinflip(deps),
        jackpot=GetJackpot(deps), join_jackpot=JoinJackpot(deps), leave_jackpot=LeaveJackpot(deps), game=GetGame(deps),
        casino_history=CasinoHistory(deps), settle_casino=SettleCasino(deps))

