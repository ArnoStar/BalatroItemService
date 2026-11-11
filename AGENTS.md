# AGENTS.md

Rules for anyone (human or agent) changing this repository. `README.md`
describes the service.

## What this project is

The players' collectible items of Balatro in the browser: jokers and tags with
the game's editions, linked to their accounts, found by playing and traded
between players. **An item changes nothing in a run**: the game shows it (the
title screen, the profile), it never plays it.

## Rules

1. **Items can't be farmed.** They are found only through the grants of
   `domain/drops.py` (each once per player, read from the game API's counted
   runs) and an admin's gift. Never add another way to make an item, and never
   let a client say what it has earned: the service reads the runs itself.
2. **Scarcity is the point.** A new grant, a better table or shorter trade hold
   changes the value of every item already found. Change them only on purpose,
   say so in the README's "How items are found", and keep `GET /v1/odds` true.
3. **All or nothing.** Every change happens in one store transaction (`Unit`):
   a trade moves all its items or none, a grant is claimed with its item. Read
   rows that will change with `lock=True` (items in a trade, a player's sync).
4. **Items keep their history.** Every change of hands is a `Transfer`; serial
   numbers never change and are never reused.
5. **The game API decides what a run is** (counted, won, its deck and stake).
   The service reads it with the player's own token and never writes to it.
6. **Randomness is the system's** (`infrastructure/system.py`): nobody may
   predict or replay a drop. Tests use a seeded generator.

## Architecture

```
domain  <-  application  <-  infrastructure, presentation  <-  bootstrap, main
```

`tests/test_architecture.py` enforces it. DTOs are
`@dataclass(frozen=True, kw_only=True)`; requests are pydantic models in
`presentation/http/schemas.py`; errors are domain exceptions with a `code`,
mapped in `presentation/http/errors.py`.

## Changes

- **A new grant or table:** `domain/drops.py` (and `RULES` in
  `application/use_cases.py`), with unit tests in `tests/unit/test_drops.py`.
- **A new kind of item:** `Kind`, the catalog adapter
  (`infrastructure/game_api.py`), the game (`BalatroFrontEnd`,
  `entities/item`) and the portal (`entities/item`) draw it.
- **The schema:** add a migration at the end of `MIGRATIONS`; never edit a
  released one. Test both stores (`tests/integration/test_stores.py`).

## Commands

```
make install   make db   make run   make run-auth   make check
```

Before committing, `make check` must pass. ruff (line length 120), mypy --strict.
