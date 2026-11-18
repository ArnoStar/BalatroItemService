from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from balatro_items.application.dto import (
    CasinoRulesView,
    CasinoStatsView,
    GameView,
    JackpotView,
    LeaderboardView,
    SeedView,
    UpgradePreviewView,
    UpgradeView,
)
from balatro_items.domain import Mode
from balatro_items.presentation.http.deps import CurrentPlayer, Uses
from balatro_items.presentation.http.schemas import BetRequest, CoinflipRequest, DiceRequest, UpgradeRequest

router = APIRouter(prefix="/v1/casino", tags=["casino"])


@router.get("/rules", response_model=CasinoRulesView, summary="The casino's rules, in numbers")
def rules(uses: Uses) -> CasinoRulesView:
    """Is it open, how many items a stake holds, a duel's margin, the dice's chances, the jackpot's countdown.
    Public.

    **Provably fair.** Each game has a secret server seed whose SHA-256 (``seed_hash``) is shown from
    the start; each entry has its player's seed. The draw is
    ``HMAC-SHA256(key=server_seed, message="<game id>:<seed of entry 1>:<seed of entry 2>...")``: its
    first 13 hex digits ``h`` give ``roll = h * value // 16**13``, and the entry whose part of the pot
    (``low`` to ``high``, ``high`` excluded) holds the roll wins. ``server_seed`` is shown once the
    game is over, so anyone can check the draw."""
    return uses.casino_rules()


@router.get("/coinflips", response_model=list[GameView], summary="The coinflips waiting for a player")
def coinflips(player: CurrentPlayer, uses: Uses) -> list[GameView]:
    """Challenges too: only their ``opponent`` may join them."""
    return uses.coinflips(player)


@router.post("/coinflips", response_model=GameView, status_code=status.HTTP_201_CREATED,
             summary="Stake items on a coinflip")
def create_coinflip(body: CoinflipRequest, player: CurrentPlayer, uses: Uses) -> GameView:
    """Your items wait for another player to match them (``join_min`` to ``join_max``: what theirs must be
    worth), or for the player you challenge (``opponent``); you may take them back until then. You need a first
    win, and at most 5 open coinflips."""
    return uses.create_coinflip(player, body.to_dto())


@router.post("/coinflips/{game_id}/join", response_model=GameView, summary="Match a coinflip: flip the coin")
def join_coinflip(game_id: str, body: BetRequest, player: CurrentPlayer, uses: Uses) -> GameView:
    """Your items must be worth ``join_min`` to ``join_max`` together. The coin is flipped at once: the
    winner takes every item (``winner``), which starts its trade hold."""
    return uses.join_coinflip(player, game_id, body.to_dto())


@router.post("/coinflips/{game_id}/cancel", response_model=GameView, summary="Take back your coinflip's items")
def cancel_coinflip(game_id: str, player: CurrentPlayer, uses: Uses) -> GameView:
    return uses.cancel_coinflip(player, game_id)


@router.get("/dice", response_model=list[GameView], summary="The dice games waiting for a player")
def dice_games(player: CurrentPlayer, uses: Uses) -> list[GameView]:
    """Each with the ``chance`` its first player chose; challenges too (only their ``opponent`` may join)."""
    return uses.dice_games(player)


@router.post("/dice", response_model=GameView, status_code=status.HTTP_201_CREATED,
             summary="Stake items on a dice game, at the chance you choose")
def create_dice(body: DiceRequest, player: CurrentPlayer, uses: Uses) -> GameView:
    """You choose your chance (5 to 95%): the other player's items must be worth what makes it so (``join_min``
    to ``join_max``). The first part of the pot is yours: a roll under your items' value wins. At most 5 open
    dice games; you may take your items back until someone joins."""
    return uses.create_dice(player, body.to_dto())


@router.post("/dice/{game_id}/join", response_model=GameView, summary="Take a dice game's other side: roll")
def join_dice(game_id: str, body: BetRequest, player: CurrentPlayer, uses: Uses) -> GameView:
    """Your items must be worth ``join_min`` to ``join_max`` together: you have the rest of the chance. Rolled at
    once; the winner takes every item."""
    return uses.join_dice(player, game_id, body.to_dto())


@router.post("/dice/{game_id}/cancel", response_model=GameView, summary="Take back your dice game's items")
def cancel_dice(game_id: str, player: CurrentPlayer, uses: Uses) -> GameView:
    return uses.cancel_dice(player, game_id)


@router.get("/jackpot", response_model=JackpotView, summary="The jackpot: the pot, and the last one drawn")
def jackpot(player: CurrentPlayer, uses: Uses) -> JackpotView:
    """``round.closes_at``: when the pot is drawn (once two players are in); count down with ``now``."""
    return uses.jackpot(player)


@router.post("/jackpot", response_model=GameView, summary="Put items in the pot")
def join_jackpot(body: BetRequest, player: CurrentPlayer, uses: Uses) -> GameView:
    """Your chance is your items' value over the pot's. The second player starts the countdown; the
    winner takes every item."""
    return uses.join_jackpot(player, body.to_dto())


@router.post("/jackpot/leave", response_model=GameView, summary="Take back your items from the pot")
def leave_jackpot(player: CurrentPlayer, uses: Uses) -> GameView:
    """Only while nobody else is in it."""
    return uses.leave_jackpot(player)


@router.get("/games", response_model=list[GameView], summary="Games that are over, the last first")
def games(player: CurrentPlayer, uses: Uses,
          of: Annotated[str | None, Query(alias="player", description="only this player's")] = None,
          mode: Annotated[Mode | None, Query()] = None,
          limit: Annotated[int, Query(ge=1, le=100)] = 20,
          before: Annotated[datetime | None, Query(description="older than this (the next page: the last "
                                                               "game's updated_at)")] = None) -> list[GameView]:
    if before is not None and before.tzinfo is None:
        before = before.replace(tzinfo=UTC)
    return uses.casino_history(player, of, mode, limit, before)


@router.get("/games/{game_id}", response_model=GameView, summary="A casino game")
def game(game_id: str, player: CurrentPlayer, uses: Uses) -> GameView:
    return uses.game(player, game_id)


@router.get("/players/{player_id}/stats", response_model=CasinoStatsView, summary="A player's casino numbers")
def player_stats(player_id: str, player: CurrentPlayer, uses: Uses) -> CasinoStatsView:
    """Their games that are over: how many, won, the value staked, won from others and lost (``net``), by game,
    their biggest pot and their least likely win. Public, as their games are."""
    return uses.casino_stats(player, player_id)


@router.get("/leaderboard", response_model=LeaderboardView, summary="The casino's best, over a period")
def leaderboard(player: CurrentPlayer, uses: Uses,
                period: Annotated[str, Query(pattern="^(day|week|all)$",
                                             description="day: the last 24 hours, week: the last 7 days")] = "week",
                ) -> LeaderboardView:
    """The most value won (net) and staked, the biggest pots and the least likely wins; the period's games,
    their value and players."""
    return uses.casino_leaderboard(player, period)


HEADERS = {
    "Cache-Control": "no-cache",
    # nginx (the portal's, and a proxy in front of it) passes each event on at once
    "X-Accel-Buffering": "no",
}


def frame(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(jsonable_encoder(data), separators=(',', ':'))}\n\n"


@router.get("/upgrades/seed", response_model=SeedView, summary="Your next upgrade's server seed, hashed")
def upgrade_seed(player: CurrentPlayer, uses: Uses) -> SeedView:
    """The SHA-256 of the server seed your next upgrade will use: it is shown with the upgrade once made, so that you
    can check its roll."""
    return uses.upgrade_seed(player)


@router.get("/upgrades/preview", response_model=UpgradePreviewView, summary="What an upgrade would be")
def preview_upgrade(player: CurrentPlayer, uses: Uses, item: str,
                    multiplier: Annotated[float, Query(ge=1, le=100)] = 2) -> UpgradePreviewView:
    """The chance (95% over the multiplier), the prize's value range (5% more or less than the target), and the
    likeliest prizes."""
    return uses.preview_upgrade(player, item, multiplier)


@router.post("/upgrades", response_model=UpgradeView, status_code=status.HTTP_201_CREATED,
             summary="Upgrade an item: against the house")
def play_upgrade(body: UpgradeRequest, player: CurrentPlayer, uses: Uses) -> UpgradeView:
    """Your item is gone whatever happens; a roll under the chance makes you a new item worth its value times the
    multiplier, 5% more or less. Provably fair: the server seed was committed to (``GET /v1/casino/upgrades/seed``)."""
    return uses.play_upgrade(player, body.to_dto())


@router.get("/upgrades", response_model=list[UpgradeView], summary="The last upgrades")
def list_upgrades(player: CurrentPlayer, uses: Uses, of: str | None = Query(None, description="a player's"),
                  limit: Annotated[int, Query(ge=1, le=100)] = 20, before: datetime | None = None) -> list[UpgradeView]:
    return uses.upgrades(player, of, limit, before)


@router.get("/upgrades/{upgrade_id}", response_model=UpgradeView, summary="An upgrade")
def get_upgrade(upgrade_id: str, player: CurrentPlayer, uses: Uses) -> UpgradeView:
    return uses.upgrade(player, upgrade_id)


@router.get("/live", summary="The casino, live (server-sent events)",
            responses={200: {"content": {"text/event-stream": {}},
                             "description": "hello (everything: the games waiting, the pot, the last draws, the "
                                            "rules), then game (a game made, joined, drawn, cancelled, or a pot's "
                                            "new entry); ends with expired or reset"}})
async def live(request: Request, player: CurrentPlayer, uses: Uses) -> StreamingResponse:
    """Open it with ``fetch`` and the ``Authorization`` header (an EventSource can't send one). A comment comes
    every few seconds (proxies close idle connections). It ends when the access token expires (``expired``:
    open another with a fresh one) or when it falls behind (``reset``: open another)."""
    sub = uses.casino_subscribe()
    try:
        hello = await run_in_threadpool(uses.casino_snapshot, player)
    except BaseException:
        sub.close()
        raise
    heartbeat: float = request.app.state.heartbeat

    async def frames() -> AsyncIterator[str]:
        try:
            yield frame("hello", hello)
            while True:
                wait = heartbeat
                if player.expires_at is not None:
                    left = (player.expires_at - datetime.now(UTC)).total_seconds()
                    if left <= 0:
                        yield frame("expired", {})
                        return
                    wait = min(wait, left)
                try:
                    event = await sub.next(wait)
                except EOFError:
                    yield frame("reset", {})
                    return
                yield frame(event.type, event.data) if event is not None else ": ping\n\n"
        finally:
            sub.close()

    # (the generator's own cleanup may not run when the client goes away first: the task runs then)
    return StreamingResponse(frames(), media_type="text/event-stream", headers=HEADERS,
                             background=BackgroundTask(sub.close))
