from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from balatro_items.application.dto import CasinoRulesView, GameView, JackpotView
from balatro_items.domain import Mode
from balatro_items.presentation.http.deps import CurrentPlayer, Uses
from balatro_items.presentation.http.schemas import BetRequest, CoinflipRequest

router = APIRouter(prefix="/v1/casino", tags=["casino"])


@router.get("/rules", response_model=CasinoRulesView, summary="The casino's rules, in numbers")
def rules(uses: Uses) -> CasinoRulesView:
    """Is it open, how many items a stake holds, a coinflip's margin, the jackpot's countdown. Public.

    **Provably fair.** Each game has a secret server seed whose SHA-256 (``seed_hash``) is shown from
    the start; each entry has its player's seed. The draw is
    ``HMAC-SHA256(key=server_seed, message="<game id>:<seed of entry 1>:<seed of entry 2>...")``: its
    first 13 hex digits ``h`` give ``roll = h * value // 16**13``, and the entry whose part of the pot
    (``low`` to ``high``, ``high`` excluded) holds the roll wins. ``server_seed`` is shown once the
    game is over, so anyone can check the draw."""
    return uses.casino_rules()


@router.get("/coinflips", response_model=list[GameView], summary="The coinflips waiting for a player")
def coinflips(player: CurrentPlayer, uses: Uses) -> list[GameView]:
    return uses.coinflips(player)


@router.post("/coinflips", response_model=GameView, status_code=status.HTTP_201_CREATED,
             summary="Stake items on a coinflip")
def create_coinflip(body: CoinflipRequest, player: CurrentPlayer, uses: Uses) -> GameView:
    """Your items wait for another player to match them (``join_min`` to ``join_max``: what theirs must be
    worth); you may take them back until then. You need a first win, and at most 5 open coinflips."""
    return uses.create_coinflip(player, body.to_dto())


@router.post("/coinflips/{game_id}/join", response_model=GameView, summary="Match a coinflip: flip the coin")
def join_coinflip(game_id: str, body: BetRequest, player: CurrentPlayer, uses: Uses) -> GameView:
    """Your items must be worth ``join_min`` to ``join_max`` together. The coin is flipped at once: the
    winner takes every item (``winner``), which starts its trade hold."""
    return uses.join_coinflip(player, game_id, body.to_dto())


@router.post("/coinflips/{game_id}/cancel", response_model=GameView, summary="Take back your coinflip's items")
def cancel_coinflip(game_id: str, player: CurrentPlayer, uses: Uses) -> GameView:
    return uses.cancel_coinflip(player, game_id)


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
          limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[GameView]:
    return uses.casino_history(player, of, mode, limit)


@router.get("/games/{game_id}", response_model=GameView, summary="A casino game")
def game(game_id: str, player: CurrentPlayer, uses: Uses) -> GameView:
    return uses.game(player, game_id)
