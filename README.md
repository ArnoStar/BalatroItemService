# BalatroItemService

Collectible **items** for Balatro in the browser
([BalatroFrontEnd](https://github.com/ArnoStar/BalatroFrontEnd)): the game's
jokers and tags, each with one of the game's editions (base, foil,
holographic, polychrome, negative), linked to the player's account.

- They are **found by playing**, a few at a time (below): none can be farmed,
  so even a common one is worth something.
- Each has a **rarity** (the game's joker rarities: common, uncommon, rare,
  legendary), an edition, a **serial number** among the items of its kind and
  edition (#1 was the first found), and, when it was found by winning, the
  **stake** it was won at (the game's stake sticker). `odds` says how rare it
  is: one in N drops.
- Players **trade** them: an offer of some items for some of another
  player's, accepted all at once.
- They **change nothing in a run**. The game shows the player's chosen item
  (their *showcase*) on the title screen in place of the Ace, with its
  edition's shader, and reveals new items when the player comes back to the
  title screen; the portal shows inventories, profiles and trades.

## How items are found

The service reads the player's runs from the game API (with their own access
token). Only **counted** runs earn items: not seeded, no challenge, no debug
help. Each grant is given once per player, ever:

| Grant | When | Table |
|---|---|---|
| `weekly` | each week (from Monday 00:00 UTC): the first counted run that ends at ante 3 or later, or wins | standard |
| `weekly_win` | each week: the first counted win | boosted |
| `first_deck_win` | the first counted win with each deck | boosted |
| `first_stake_win` | the first counted win at each stake from Red to Black; Gold | boosted; premium |

So a player finds at most two items a week, plus one for each deck and stake
they win with for the first time. Past weeks earn nothing; past wins earn
their milestones. An admin may also give an item (`gift`: events, prizes).

Each item is rolled on its table (`GET /v1/odds` has the numbers):

| | standard | boosted | premium |
|---|---|---|---|
| kind | joker 85%, tag 15% | joker 85%, tag 15% | joker |
| rarity | common 70%, uncommon 25%, rare 4.5%, legendary 0.5% | 50 / 35 / 13 / 2% | uncommon 40%, rare 50%, legendary 10% |
| edition | base 85%, foil 8%, holographic 4.5%, polychrome 2%, negative 0.5% | 70 / 14 / 9 / 5 / 2% | foil 40%, holo 30%, poly 20%, negative 10% |

then one item of that kind and rarity, all equally likely. Tags have no rarity
in the game: the Negative and Polychrome tags are rare here, Holographic,
Foil, Rare, Ethereal, Double and Voucher uncommon, the others common.

## Trading

- `POST /v1/trades {to, give, take, message}`: your items for theirs (either
  side may be empty). The other player accepts, declines, or lets it expire
  (14 days); you may cancel it.
- **Both players must have won a counted run**, so new accounts can't pass
  items along.
- **Trade hold:** an item that changes hands, or is found, can't change hands
  again for 7 days (`BALATRO_ITEMS_TRADE_HOLD_DAYS`).
- An accepted offer moves every item at once, or none if one has moved since
  (`409 items_moved`). Every change of hands stays in the item's history.
- At most 10 items on each side, and 20 open offers per player.

## Endpoints

The site serves the service at `/items/` (the portal's nginx); here are its
own paths. With sign-in on, every route but `/health` and `/v1/odds` needs an
access token from the identity service.

| | |
|---|---|
| `GET /health` | `{status, version, auth}` |
| `GET /v1/odds` | the grants, the tables, how many jokers and tags each rarity has, the trade hold |
| `GET /v1/me` | you: can you trade, are you an admin, your item count and showcase, this week's drops |
| `POST /v1/me/drops` | find the items your runs have earned (`found`: the new ones). The game calls it on the title screen |
| `GET /v1/me/items` | your items, newest first |
| `PUT /v1/me/showcase` | `{item}`: the item on your title screen and profile (`null`: the game's Ace) |
| `GET /v1/items/{id}` | an item and its history (who found it, every trade) |
| `GET /v1/players?q=` | players by the start of their name |
| `GET /v1/players/{id}` | a player's showcase and item count |
| `GET /v1/players/{id}/items` | a player's items (inventories are public) |
| `GET /v1/trades?box=all\|incoming\|outgoing` | your trades |
| `POST /v1/trades` | make an offer |
| `GET /v1/trades/{id}` | one of your trades (`available`: it can still be accepted) |
| `POST /v1/trades/{id}/accept`, `/decline`, `/cancel` | answer an offer made to you, or cancel yours |
| `POST /v1/admin/gifts` | `{to, key, edition, stake}`: give an item (the admin role, or `BALATRO_ITEMS_ADMINS`) |

Errors are problem details with a stable `code`: `item_not_found`,
`player_not_found`, `trade_not_found`, `invalid_trade`, `not_owner`,
`item_locked`, `items_moved`, `trade_closed`, `trading_locked`,
`not_allowed`, `too_many_offers`, `not_admin`, `unknown_item`,
`game_api_unavailable`, `unauthenticated`. Interactive docs at `/docs`.

An item, as every answer has it:

```
{id, kind: joker|tag, key: "j_blueprint", name: "Blueprint", edition, rarity: 1-4,
 stake: 1-8|null, serial, minted, odds, owner, owner_name, source, source_run,
 found_at, acquired_at, tradable_at, tradable, sprite: {atlas, pos: {x, y}, soul_pos}}
```

## Settings

| Variable | Default | |
|---|---|---|
| `BALATRO_ITEMS_DATABASE_URL` | `postgresql://items:items@127.0.0.1:55435/items` (`make db`) | PostgreSQL, or `memory` |
| `BALATRO_ITEMS_API_URL` | `http://127.0.0.1:8000` | the game API (its runs and catalog) |
| `BALATRO_ITEMS_TRADE_HOLD_DAYS` | `7` | |
| `BALATRO_ITEMS_ADMINS` | none | account ids that may give items, besides the admin role |
| `BALATRO_ITEMS_AUTH_JWKS_URL` | unset (sign-in off) | the identity service's `/.well-known/jwks.json` |
| `BALATRO_ITEMS_AUTH_ISSUER` | | required with the JWKS URL: the identity service's `PUBLIC_URL` |
| `BALATRO_ITEMS_AUTH_AUDIENCE` | `balatro` | |
| `BALATRO_ITEMS_CORS_ORIGINS` | `*` | |
| `BALATRO_ITEMS_HOST`, `BALATRO_ITEMS_PORT` | `127.0.0.1`, `8004` | for `balatro-items` |

Without sign-in everyone is the same player, and an admin.

## Development

```
make install && make db && make run     # http://127.0.0.1:8004/docs, no sign-in (the API on :8000)
make run-auth                           # with the identity service on :8001
make check                              # tests (PostgreSQL ones on make db's database), ruff, mypy
```

`make dev` in BalatroFrontEnd runs the whole site with this service.

## Deployment

Like the other services: `.github/workflows/ci-cd.yml` runs the checks (with a
PostgreSQL service) on every push to `main` and `dev`; a push to `main` copies
the code to the server and restarts the `items` service of BalatroFrontEnd's
compose file (once that file has it). The `DEPLOY_*` secrets are the same as
in the other repositories (BalatroFrontEnd's README, Deployment). On the
server, set `ITEMS_DB_PASSWORD` in BalatroFrontEnd's `.env`.

## Code

Clean architecture, as BalatroWebAPI (`AGENTS.md`):

```
src/balatro_items/
  domain/           Item, Trade and their rules; drops.py: the grants, tables, rolls and odds
  application/      use cases, DTOs, ports (the store's Unit, the game API, the clock, ids)
  infrastructure/   auth (the identity service's tokens), game_api (runs, catalog), persistence (PostgreSQL, memory)
  presentation/     http (FastAPI)
  bootstrap.py, config.py, main.py
```
