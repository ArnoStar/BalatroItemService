# AGENTS.md

Rules for anyone (human or agent) changing this repository. `README.md`
describes the service.

## What this project is

The players' collectible items of Balatro in the browser: the game's cards
(jokers, tarot, planet and spectral cards, playing cards) with the upgrades
the game gives them, linked to their accounts. Playing earns coins, coins buy
boosters (the only source of items), and items are traded between players,
sold to each other on the market and staked against each other in the
casino. **An item changes nothing in a run**: the game shows it (the title
screen, the profile), it never plays it.

## Rules

1. **Coins and items can't be farmed.** Coins are earned only through the
   grants of `domain/drops.py` (each once per player, read from the game API's
   counted runs) and an admin's gift; items are made only from boosters bought
   with those coins (`domain/boosters.py`) and an admin's gift. Never add
   another way to make a coin or an item, and never let a client say what it
   has earned: the service reads the runs itself.
2. **Scarcity is the point.** A new grant, more coins, a cheaper booster, a
   better table or a shorter trade hold changes the value of every item already
   made. Change them only on purpose, say so in the README ("Coins",
   "Boosters"), and keep `GET /v1/odds` true. An item only has the upgrades the
   game can give its kind of card (`EDITIONS`, `ENHANCEMENTS`, `SEALS`).
3. **All or nothing.** Every change happens in one store transaction (`Unit`):
   a trade moves all its items or none, a grant is claimed with its coins, a
   pack is paid with its cards, a sale moves the coins and the item together.
   Read rows that will change with `lock=True` (items in a trade, a player's
   sync, a pack, a listing). Coins change only through `Unit.add_coins`, which
   never lets a balance go below 0.
4. **Items and coins keep their history.** Every change of hands is a
   `Transfer`, every coin in or out a `CoinMove`; serial numbers never change
   and are never reused.
5. **The game API decides what a run is** (counted, won, its deck and stake).
   The service reads it with the player's own token and never writes to it.
6. **Randomness is the system's** (`infrastructure/system.py`): nobody may
   predict or replay a drop, nor guess a casino game's server seed. Tests use
   a seeded generator.
7. **The casino and the market only move items (and coins) between players**
   (`domain/casino.py`, `domain/market.py`). They make no item or coin and keep
   none (no house, no cut); they play by the trade rules (a first win, the
   trade hold); staked or listed items can't change hands any other way until
   their game ends or they are sold or taken off, and items won or bought are
   `Transfer`s with the game or the listing. Draws are
   provably fair: never show a server seed before its game is over, and never
   change how a roll is computed (games already played must still check out).
   A new game is a duel or a pot drawn the same way; a challenge only limits
   who may join.
8. **One process.** The casino's live streams (`infrastructure/feed.py`) are
   in memory. Running two processes needs a shared feed first (for example
   PostgreSQL LISTEN/NOTIFY): don't just add workers. Use cases publish a game
   only once its transaction is done.

## Architecture

```
domain  <-  application  <-  infrastructure, presentation  <-  bootstrap, main
```

`tests/test_architecture.py` enforces it. DTOs are
`@dataclass(frozen=True, kw_only=True)`; requests are pydantic models in
`presentation/http/schemas.py`; errors are domain exceptions with a `code`,
mapped in `presentation/http/errors.py`.

## Changes

- **A new grant:** `domain/drops.py` (and `RULES` in
  `application/use_cases.py`), with unit tests in `tests/unit/test_drops.py`.
- **A new booster, table or price:** `domain/boosters.py`, with unit tests in
  `tests/unit/test_boosters.py`; the portal's shop shows `GET /v1/boosters`.
- **A new kind of item:** `Kind`, `EDITIONS`, the catalog adapter
  (`infrastructure/game_api.py`), `BOOSTERS`, and the front ends draw it: the
  game (`BalatroFrontEnd`, `pages/main-menu`), the portal and the casino
  (`entities/item`).
- **A casino game or limit:** `domain/casino.py`, with unit tests in
  `tests/unit/test_casino.py`; keep the README's "The casino" and
  `GET /v1/casino/rules` true, publish its changes to the live feed, and show
  it in BalatroCasino.
- **The schema:** add a migration at the end of `MIGRATIONS`; never edit a
  released one. Test both stores (`tests/integration/test_stores.py`).

## Commands

```
make install   make db   make run   make run-auth   make check
```

Before committing, `make check` must pass. ruff (line length 120), mypy --strict.
