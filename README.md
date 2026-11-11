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
- Players **stake** them in the **casino**: coinflips and a jackpot, player
  against player, provably fair (below). The casino makes no item and keeps
  none.
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

## The casino

Two games, between players only: the winner takes every item of the game. The
casino has no items of its own and takes no cut, so it changes who has items,
never how many there are.

- **Coinflip**: stake up to 10 items on a side, Chips or Mult. Another player
  matches them with items worth as much, 10% more or less (`join_min` to
  `join_max`), and the coin is flipped at once. Until then you may take your
  items back. At most 5 open coinflips per player.
- **Jackpot**: one pot at a time. Put up to 10 items in at once (50 items and
  10 players at most); when a second player is in, the pot is drawn 60 seconds
  later (`BALATRO_ITEMS_JACKPOT_SECONDS`). Alone in it, you may take your items
  back.

**Value and chance.** An item is worth its odds: one in how many drops of the
standard table it is (`odds`, so a Negative legendary weighs far more than a
common joker). Your chance is the value of your items over the value of the
pot. The values are fixed when the items are staked.

**The same rules as trades.** Only players with a counted win may play, only
items out of their trade hold may be staked, and the items you win start
their hold (7 days): what you win can't be staked again at once. A staked item
stays yours but can't be traded or staked elsewhere until its game ends; if it
is on your title screen and you lose it, the title screen gets the game's card
back.

**Provably fair.** Each game has a secret *server seed*; its SHA-256
(`seed_hash`) is shown from the start. Each entry has its player's *seed*
(sent with the stake, or a random one). The draw is

```
h    = first 13 hex digits of HMAC-SHA256(key = server_seed, message = "<game id>:<seed 1>:<seed 2>...")
roll = int(h, 16) * value // 16**13
```

and the entry whose part of the pot holds the roll wins (each entry's `low`
to `high`, `high` excluded: the entries' values laid end to end, in order).
`server_seed` is shown once the game is over, so anyone can check the hash and
the draw (the portal does, in the browser). Nobody could steer it: the server
chose its seed before the players chose theirs, and they couldn't know it.

`BALATRO_ITEMS_CASINO=off` closes the casino: nothing can be staked
(`403 casino_closed`), staked items can still be taken back, and a pot that is
counting down is still drawn.

## Endpoints

The site serves the service at `/items/` (the portal's nginx); here are its
own paths. With sign-in on, every route but `/health`, `/v1/odds` and
`/v1/casino/rules` needs an access token from the identity service.

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
| `GET /v1/casino/rules` | is the casino open, its limits, the jackpot's countdown |
| `GET /v1/casino/coinflips` | the coinflips waiting for a player, newest first |
| `POST /v1/casino/coinflips` | `{items, side: chips\|mult, seed}`: stake items on a coinflip |
| `POST /v1/casino/coinflips/{id}/join` | `{items, seed}`: match it; the coin is flipped at once |
| `POST /v1/casino/coinflips/{id}/cancel` | take back your coinflip's items (nobody joined) |
| `GET /v1/casino/jackpot` | `{round, last, now}`: the pot taking items, the last one drawn, the service's time |
| `POST /v1/casino/jackpot` | `{items, seed}`: put items in the pot |
| `POST /v1/casino/jackpot/leave` | take back your items (nobody else is in the pot) |
| `GET /v1/casino/games?player=&mode=&limit=` | games that are over, the last first |
| `GET /v1/casino/games/{id}` | a game: its entries (each with its items, value, chance, part of the pot and seed), `seed_hash`, and once over `server_seed`, `roll`, `winner` |

Errors are problem details with a stable `code`: `item_not_found`,
`player_not_found`, `trade_not_found`, `invalid_trade`, `not_owner`,
`item_locked`, `items_moved`, `trade_closed`, `trading_locked`,
`not_allowed`, `too_many_offers`, `not_admin`, `unknown_item`,
`game_not_found`, `invalid_bet`, `game_closed`, `too_many_games`,
`casino_closed`, `game_api_unavailable`, `unauthenticated`. Interactive docs at `/docs`.

An item, as every answer has it:

```
{id, kind: joker|tag, key: "j_blueprint", name: "Blueprint", edition, rarity: 1-4,
 stake: 1-8|null, serial, minted, odds, owner, owner_name, source, source_run,
 found_at, acquired_at, tradable_at, tradable, staked: <game id>|null, sprite: {atlas, pos: {x, y}, soul_pos}}
```

## Settings

| Variable | Default | |
|---|---|---|
| `BALATRO_ITEMS_DATABASE_URL` | `postgresql://items:items@127.0.0.1:55435/items` (`make db`) | PostgreSQL, or `memory` |
| `BALATRO_ITEMS_API_URL` | `http://127.0.0.1:8000` | the game API (its runs and catalog) |
| `BALATRO_ITEMS_TRADE_HOLD_DAYS` | `7` | |
| `BALATRO_ITEMS_CASINO` | `on` | `off`: nothing can be staked in the casino |
| `BALATRO_ITEMS_JACKPOT_SECONDS` | `60` | from the second player in the pot to its draw |
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
  domain/           Item, Trade and their rules; drops.py: the grants, tables, rolls and odds;
                    casino.py: the coinflip, the jackpot, the draw
  application/      use cases, DTOs, ports (the store's Unit, the game API, the clock, ids)
  infrastructure/   auth (the identity service's tokens), game_api (runs, catalog), persistence (PostgreSQL, memory)
  presentation/     http (FastAPI)
  bootstrap.py, config.py, main.py
```
