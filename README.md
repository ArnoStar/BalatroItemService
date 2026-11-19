# BalatroItemService

Collectible **items** for Balatro in the browser
([BalatroFrontEnd](https://github.com/ArnoStar/BalatroFrontEnd)): the game's
cards, each with the upgrades the game gives such a card, linked to the
player's account.

- **Jokers**, with an edition: base, foil, holographic, polychrome, negative.
- **Tarot, planet and spectral cards**: base, or (really rarely) negative.
- **Playing cards**: an enhancement (Bonus, Mult, Wild, Glass, Steel, Stone,
  Gold, Lucky), a seal (Gold, Red, Blue, Purple) and an edition but negative.

Playing earns **coins** (below: none can be farmed); coins buy **boosters**,
packs of cards to choose from, and items other players sell on the
**market**. Each item has a **rarity** (common, uncommon, rare, legendary), a
**condition** (how well kept its card is, below), a **value** in coins (its
card, upgrades and condition, below), a **serial number** among the items of
its card, upgrades and edition (#1 was the first made), and `odds`: how rare
it is to find, one in N cards of its kind's standard table.
Jokers found by winning before boosters carry the **stake** they were won at.

- Players **trade** items (an offer of some items for some of another
  player's), **sell** them on the market, and **stake** them in the
  **casino**: coinflips, dice and a jackpot, player against player, provably
  fair and live (below). Its own front end is BalatroCasino, at `/casino/`.
- Items **change nothing in a run**. The game shows the player's chosen item
  (their *showcase*) on the title screen in place of the Ace, with its
  upgrades and the game's shaders, and tells the player the coins their runs
  earned when they come back to the title screen; the portal has the shop,
  the market, inventories, profiles and trades.

## Coins

The service reads the player's runs from the game API (with their own access
token). Only **counted** runs earn coins: not seeded, no challenge, no debug
help. Each grant is given once per player, ever:

| Grant | When | Coins |
|---|---|---|
| `weekly` | each week (from Monday 00:00 UTC): the first counted run that ends at ante 3 or later, or wins | 100 |
| `weekly_win` | each week: the first counted win | 250 |
| `first_deck_win` | the first counted win with each deck | 250 |
| `first_stake_win` | the first counted win at each stake from Red to Black; Gold | 250; 1,000 |

So a player earns at most 350 coins a week, plus some for each deck and stake
they win with for the first time. Past weeks earn nothing; past wins earn
their milestones. Each grant is worth a normal booster of the table it used to
roll an item on (before boosters, each grant gave an item; grants claimed then
keep their items and earn no coins). An admin may also give coins (`gift`:
events, prizes). `GET /v1/me/coins` has a player's balance and where every
coin came from or went.

Coins only change hands on the market: nothing else makes or moves them.

## Boosters

A booster is one kind of card, one **tier** and one **size**, as the game's
packs (and drawn as them: Buffoon, Arcana, Celestial, Spectral and Standard
packs):

| Size | Cards shown | Chosen | Price |
|---|---|---|---|
| normal | 2 | 1 | the kind's price |
| jumbo | 4 | 1 | x1.5 |
| mega | 4 | 2 | x2 |

| Kind | standard | boosted (x2.5) | premium (x10) |
|---|---|---|---|
| jokers, playing cards | 100 | 250 | 1,000 |
| spectral cards | 60 | 150 | 600 |
| tarot, planet cards | 40 | 100 | 400 |

Buying one opens a **pack**: its cards are rolled at once and kept (coming
back to it shows the same cards, `GET /v1/me/packs`), then the player chooses
and only the cards chosen become items (numbered then). A pack never shows the
same card twice. Each card is rolled on its kind's table for the tier
(`GET /v1/odds` has every number):

| | standard | boosted | premium |
|---|---|---|---|
| rarity | common 88%, uncommon 10.5%, rare 1.4%, legendary 0.1% | 75 / 20 / 4.5 / 0.5% | uncommon 75%, rare 23.5%, legendary 1.5% |
| joker edition | base 96%, foil 2.8%, holographic 1%, polychrome 0.18%, negative 0.02% | 88 / 7.5 / 3.5 / 0.85 / 0.15% | 45 / 35 / 15 / 4.5 / 0.5% |
| tarot, planet, spectral | negative 0.02% | 0.08% | 0.3% |
| playing card edition | base 97%, foil 2.2%, holographic 0.7%, polychrome 0.1% | 90 / 6.5 / 2.8 / 0.7% | 50 / 33 / 13.5 / 3.5% |

(Since 2026-11-19: every chance of a better card was cut, by about three to
twenty times; a premium booster no longer promises an edition.)

then one card of that kind and rarity, all equally likely (a kind without a
rarity shares its part among the others). Rarities: jokers have the game's;
a playing card is common plain, uncommon with an enhancement or a seal, rare
with both; tarot, planet and spectral cards have none in the game, so here The
Soul and Black Hole are legendary, the secret planets (Planet X, Ceres, Eris),
The Fool, The Wheel of Fortune, Judgement, Wraith, Ectoplasm, Ankh and Hex
rare, a few more uncommon (`domain/items.py`, `CONSUMABLE_RARITY`), the
others common.

Tags were items until boosters came: each was given back to its owner in
coins, its value then (its odds on the standard table of that time, from 178
coins for a common tag to 58,963 for a negative rare one), its open casino
game called off and its pending offers cancelled (migration 4).

## Condition

Every item has a condition from 0 (ruined) to 1 (pristine), drawn when its
card is shown (a booster's card is shown with it, before the player
chooses): `P(condition >= x) = (1 - x^3.5)^5`. Half the cards are above 56%;
a really good one is rare but within reach, the best close to impossible:

| condition | grade | one card in |
|---|---|---|
| 0-10% | ruined | (0.16% of the cards) |
| 10-25% | battered | |
| 25-45% | worn | |
| 45-60% | played | 1.4 (45% or more) |
| 60-80% | fine | 2.5 |
| 80-95% | excellent | 21 |
| 95-99% | mint | 8,300 |
| 99-100% | pristine | 20 million |

(Until 2026-11-19 the curve was harsher, `(1 - x^1.5)^5`, a median of 26%:
migration 7 moved every condition drawn on it to `(1 - x^3)^5.2`, a median
of 50%, each keeping its rank, then migration 8 drew every item's condition
again on that curve: a fresh start for every item made before. The same day
the owner found it still a bit harsh: migration 9 moved every condition to
this curve, each keeping its rank, then migration 11 drew every item's
condition again on it, another fresh start.)

The front ends draw it: faded and yellowed colours, grime, scratches, frayed
edges and, once badly worn, a crease (each item its own); a pristine card is
spotless. The items made before conditions got one at random, drawn the same
way (migration 5).

## Value

An item's **mint value** is what its card would be worth in perfect
condition: its kind and rarity (a joker 150, 400, 1,500, 12,000 coins from
common to legendary; a tarot, planet or spectral card 40, 100, 350, 6,000; a
playing card 30, 100, 400), times its edition (foil x3, holographic x5,
polychrome x10, negative x25; a negative tarot, planet or spectral card,
rarer still, x60), a playing card's enhancement (Glass, Steel x1.35, Lucky
x1.3, Gold x1.25, Wild x1.1, Stone x0.9) and seal (Red x1.4, Gold x1.3, Blue,
Purple x1.15), and a joker's stake sticker (+4% a stake above White). Its
**value** is its mint value times its condition, at least 1 coin
(`domain/value.py`): what the casino stakes it at and the market shows next
to a price.

## The market

- `POST /v1/market {item, price}`: your item for sale, from 1 to
  1,000,000,000 coins. Another player buys it at once (`POST
  /v1/market/{id}/buy`): their coins to you, the item to them, all at once or
  nothing (`409 not_enough_coins`). You may take it off until then.
- **The same rules as trades**: both players must have won a counted run, only
  items out of their trade hold are listed, and an item bought starts its hold.
  A listed item can't be traded, staked nor listed again until it is sold or
  taken off. At most 50 items on the market per player.
- The market keeps no coin and makes no item (no house, no cut).
  `GET /v1/market/sales?variant=&edition=` has what such an item sold for.

## Trading

- `POST /v1/trades {to, give, take, message}`: your items for theirs (either
  side may be empty). The other player accepts, declines, or lets it expire
  (14 days); you may cancel it.
- **Both players must have won a counted run**, so new accounts can't pass
  items along.
- **Trade hold:** an item that changes hands, or is found, can't change hands
  again for 7 days (`BALATRO_ITEMS_TRADE_HOLD_DAYS`), unless it was won in the
  casino (below). Migration 10 ended every hold running on 2026-11-19, once,
  at the owner's request.
- An accepted offer moves every item at once, or none if one has moved since
  (`409 items_moved`). Every change of hands stays in the item's history.
- At most 10 items on each side, and 20 open offers per player.

## The casino

Three games, between players only: the winner takes every item of the game.
The casino has no items of its own and takes no cut, so it changes who has
items, never how many there are.

- **Coinflip**: stake up to 10 items on a side, Chips or Mult. Another player
  matches them with items worth as much, 10% more or less (`join_min` to
  `join_max`), and the coin is flipped at once. Until then you may take your
  items back. At most 5 open coinflips per player.
- **Dice**: the same duel, at the chance you choose, from 5% to 95%. The other
  player's items must be worth what makes it so: against your items worth 100
  at 25%, theirs are worth 300 (10% more or less), and they have the other 75%.
  The first part of the pot is yours: a roll under your items' value wins. A
  long shot stakes little against much; a safe bet much against little. At
  most 5 open dice games per player.
- **Jackpot**: one pot at a time. Put up to 10 items in at once (50 items and
  10 players at most); when a second player is in, the pot is drawn 60 seconds
  later (`BALATRO_ITEMS_JACKPOT_SECONDS`). Alone in it, you may take your items
  back.
- **Challenges**: a coinflip or a dice game may name the only player who may
  join it (`opponent`): a friend, or the player you just played. Everyone may
  still watch it, as every game.

**Value and chance.** An item is worth its value (above: its card, upgrades
and condition). Your chance is the value of your items over the value of
the pot. The values are fixed when the items are staked.

**The same rules as trades.** Only players with a counted win may play, only
items out of their trade hold may be staked. The items you win start no hold
(the owner's choice, 2026-11-19; before, a week): what you win may be staked,
traded or sold again at once. A staked item
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

**Live.** `GET /v1/casino/live` is a stream of server-sent events: `hello`
first, with everything the casino shows (the coinflips and dice games waiting,
the pot, the last draws, the rules), then `game` each time a game is made,
joined and drawn, cancelled, or a pot takes an entry (the game as
`/v1/casino/games/{id}` has it). It ends with `expired` when the access token
expires and `reset` when the client falls behind: open another. The streams
live in the service's memory: **run one process** (a second would need a
shared feed first, such as PostgreSQL's LISTEN/NOTIFY).

**Numbers.** `GET /v1/casino/players/{id}/stats` sums up a player's games that
are over (their last 5,000): games, wins, the value staked, won from others
and lost (`net`), by game, their biggest pot and their least likely win.
`GET /v1/casino/leaderboard?period=day|week|all` has the most value won (net)
and staked, the biggest pots and the least likely wins.

**The upgrade** (against the house, the one exception). Put one item in (out
of its trade hold) and aim at an item worth so many times more, from x1 to
x100: the chance is 95% over the multiplier (an item worth 100 aimed at x2:
47.5%). Your item is gone whatever happens; a win makes you a new item worth
the target, 5% more or less, with no trade hold, drawn as a card is found
(each card and edition as likely as on its kind's standard table, weighed by
how likely a condition puts it in the range; its condition drawn there). On
average you get 95% of
what you put in. Provably fair: `GET /v1/casino/upgrades/seed` shows the
SHA-256 of your next upgrade's server seed before you play; the upgrade shows
the seed, and `roll = h * 1,000,000 // 16**13` (h as above, message
`"<upgrade id>:<your seed>"`) wins below `chance_ppm`. Live as `upgrade`
events.

`BALATRO_ITEMS_CASINO=off` closes the casino: nothing can be staked
(`403 casino_closed`), staked items can still be taken back, and a pot that is
counting down is still drawn.

## Endpoints

The site serves the service at `/items/` (the portal's nginx); here are its
own paths. With sign-in on, every route but `/health`, `/v1/odds`, `/v1/boosters` and
`/v1/casino/rules` needs an access token from the identity service.

| | |
|---|---|
| `GET /health` | `{status, version, auth}` |
| `GET /v1/odds` | the grants, the boosters, the tables, how many cards each kind and rarity has, the trade hold, the market's limits |
| `GET /v1/me` | you: can you trade, are you an admin, your items, coins and open packs, your showcase, this week's coins |
| `POST /v1/me/drops` | earn the coins your runs have earned (`earned`: the new grants, `balance`). The game calls it on the title screen |
| `GET /v1/me/coins` | your coins and their history (the last first) |
| `GET /v1/me/items` | your items, newest first |
| `GET /v1/boosters` | what coins buy: each booster's kind, tier, size, price, art and chances |
| `POST /v1/boosters/{id}/buy` | buy one: a pack, its cards rolled at once |
| `GET /v1/me/packs?status=open\|opened` | your packs |
| `GET /v1/packs/{id}` | one of your packs |
| `POST /v1/packs/{id}/choose` | `{picks: [index ...]}`: the cards you choose become your items |
| `GET /v1/market?kind=&rarity=&edition=&q=&seller=&sort=newest\|price\|-price&limit=&offset=` | items for sale |
| `POST /v1/market` | `{item, price}`: sell an item |
| `GET /v1/market/sales?variant=&edition=&kind=` | the last sales |
| `GET /v1/market/{id}` | a listing (`available`: it can be bought now) |
| `POST /v1/market/{id}/buy`, `/cancel` | buy it, or take yours off |
| `GET /v1/me/listings?box=selling\|sold\|bought\|all` | your market |
| `PUT /v1/me/showcase` | `{item}`: the item on your title screen and profile (`null`: the game's Ace) |
| `GET /v1/items/{id}` | an item and its history (who found it, every trade) |
| `GET /v1/players?q=` | players by the start of their name |
| `GET /v1/players/{id}` | a player's showcase and item count |
| `GET /v1/players/{id}/items` | a player's items (inventories are public) |
| `GET /v1/trades?box=all\|incoming\|outgoing` | your trades |
| `POST /v1/trades` | make an offer |
| `GET /v1/trades/{id}` | one of your trades (`available`: it can still be accepted) |
| `POST /v1/trades/{id}/accept`, `/decline`, `/cancel` | answer an offer made to you, or cancel yours |
| `POST /v1/admin/gifts` | `{to, key, edition, stake, enhancement, seal, condition}`: give an item (the admin role, or `BALATRO_ITEMS_ADMINS`) |
| `POST /v1/admin/coins` | `{to, coins, note}`: give coins (negative: take them back, down to 0) |
| `GET /v1/casino/rules` | is the casino open, its limits, the dice's chances, the jackpot's countdown |
| `GET /v1/casino/live` | the casino, live (server-sent events: `hello`, then `game`) |
| `GET /v1/casino/coinflips` | the coinflips waiting for a player (challenges too), newest first |
| `POST /v1/casino/coinflips` | `{items, side: chips\|mult, seed, opponent}`: stake items on a coinflip (`opponent`: a challenge) |
| `POST /v1/casino/coinflips/{id}/join` | `{items, seed}`: match it; the coin is flipped at once |
| `POST /v1/casino/coinflips/{id}/cancel` | take back your coinflip's items (nobody joined) |
| `GET /v1/casino/dice` | the dice games waiting for a player, newest first |
| `POST /v1/casino/dice` | `{items, chance: 5-95, seed, opponent}`: stake items at the chance you choose |
| `POST /v1/casino/dice/{id}/join` | `{items, seed}`: take the other side; rolled at once |
| `POST /v1/casino/dice/{id}/cancel` | take back your dice game's items (nobody joined) |
| `GET /v1/casino/jackpot` | `{round, last, now}`: the pot taking items, the last one drawn, the service's time |
| `POST /v1/casino/jackpot` | `{items, seed}`: put items in the pot |
| `POST /v1/casino/jackpot/leave` | take back your items (nobody else is in the pot) |
| `GET /v1/casino/games?player=&mode=&limit=&before=` | games that are over, the last first (`before`: the next page) |
| `GET /v1/casino/games/{id}` | a game: its entries (each with its items, value, chance, part of the pot and seed), `seed_hash`, `chance` and `opponent` (a dice game, a challenge), and once over `server_seed`, `roll`, `winner` |
| `GET /v1/casino/players/{id}/stats` | a player's casino numbers |
| `GET /v1/casino/upgrades/seed` | the SHA-256 of your next upgrade's server seed |
| `GET /v1/casino/upgrades/preview?item=&multiplier=` | an upgrade's chance, the prize's range, the likeliest prizes |
| `POST /v1/casino/upgrades` | `{item, multiplier, seed}`: upgrade an item (it is gone; a win makes a new one) |
| `GET /v1/casino/upgrades?of=&limit=&before=`, `/upgrades/{id}` | the last upgrades, an upgrade |
| `GET /v1/casino/leaderboard?period=day\|week\|all` | the casino's best over a period |

Errors are problem details with a stable `code`: `item_not_found`,
`player_not_found`, `trade_not_found`, `invalid_trade`, `not_owner`,
`item_locked`, `items_moved`, `trade_closed`, `trading_locked`,
`not_allowed`, `too_many_offers`, `not_admin`, `unknown_item`,
`game_not_found`, `invalid_bet`, `game_closed`, `too_many_games`,
`casino_closed`, `not_enough_coins`, `booster_not_found`, `pack_not_found`,
`pack_opened`, `invalid_pick`, `listing_not_found`, `invalid_listing`,
`listing_closed`, `too_many_listings`, `game_api_unavailable`,
`unauthenticated`. Interactive docs at `/docs`.

An item, as every answer has it:

```
{id, kind: joker|tarot|planet|spectral|card, key: "j_blueprint" | "c_fool" | "S_A", name: "Blueprint", edition,
 rarity: 1-4, enhancement: "m_glass"|null, seal: "Red"|null, variant: "S_A+m_glass+Red", stake: 1-8|null,
 condition: 0-1, grade: "worn", mint_value, value, serial,
 minted, odds, owner, owner_name, source: booster|gift|..., source_run, booster, found_at, acquired_at, tradable_at,
 tradable, staked: <game id>|null, listed: <listing id>|null, price: <coins>|null,
 sprite: {atlas, pos: {x, y}, soul_pos, overlay, front, seal}}
```

A playing card's sprite is its center (the enhancement, or the blank card),
its `front` (the rank and suit: none for a Stone Card) and its `seal`; The
Soul's `overlay` is its gem.

## Settings

| Variable | Default | |
|---|---|---|
| `BALATRO_ITEMS_DATABASE_URL` | `postgresql://items:items@127.0.0.1:55435/items` (`make db`) | PostgreSQL, or `memory` |
| `BALATRO_ITEMS_API_URL` | `http://127.0.0.1:8000` | the game API (its runs and catalog) |
| `BALATRO_ITEMS_TRADE_HOLD_DAYS` | `7` | not for items won in the casino |
| `BALATRO_ITEMS_CASINO` | `on` | `off`: nothing can be staked in the casino |
| `BALATRO_ITEMS_JACKPOT_SECONDS` | `60` | from the second player in the pot to its draw |
| `BALATRO_ITEMS_HEARTBEAT` | `20` | seconds between a live stream's keep-alive comments |
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
  domain/           Item, Trade and their rules; drops.py: the grants (coins); boosters.py: the boosters, tables,
                    rolls, odds, packs; condition.py; value.py; market.py: listings, sales; casino.py: the coinflip, the dice,
                    the jackpot, challenges, the draw, the tallies
  application/      use cases, DTOs, ports (the store's Unit, the game API, the clock, ids)
  infrastructure/   auth (the identity service's tokens), game_api (runs, catalog), persistence (PostgreSQL, memory),
                    feed (the casino's live streams, in memory)
  presentation/     http (FastAPI)
  bootstrap.py, config.py, main.py
```
