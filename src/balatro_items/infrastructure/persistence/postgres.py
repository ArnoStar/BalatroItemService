"""Everything kept in PostgreSQL.

A unit is a transaction; ``lock=True`` reads rows FOR UPDATE, so two trades of
the same items, or two syncs of the same player, wait for each other. Serial
numbers come from a counter row per key and edition. The schema comes from the
numbered ``MIGRATIONS`` (each applied once, in order, under a lock); never
change a released one: add one.
"""

from __future__ import annotations

import builtins
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from psycopg import Connection, sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolTimeout

from balatro_items.domain import (
    Edition,
    Entry,
    Game,
    GameStatus,
    Item,
    Kind,
    Mode,
    PlayerRecord,
    Rarity,
    Side,
    Trade,
    TradeStatus,
    Transfer,
)

MIGRATIONS: tuple[str, ...] = (
    # 1: players, items, their history, the grants claimed, trades
    """
    CREATE TABLE players (
        id TEXT PRIMARY KEY,
        name TEXT,
        has_won BOOLEAN NOT NULL,
        showcase TEXT,
        created_at TIMESTAMPTZ NOT NULL,
        synced_at TIMESTAMPTZ
    );
    CREATE INDEX players_name ON players (lower(name) text_pattern_ops);
    CREATE TABLE serials (
        key TEXT NOT NULL,
        edition TEXT NOT NULL,
        last INTEGER NOT NULL,
        PRIMARY KEY (key, edition)
    );
    CREATE TABLE items (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        key TEXT NOT NULL,
        edition TEXT NOT NULL,
        rarity SMALLINT NOT NULL,
        stake SMALLINT,
        serial INTEGER NOT NULL,
        owner TEXT NOT NULL REFERENCES players (id),
        source TEXT NOT NULL,
        source_run TEXT,
        created_at TIMESTAMPTZ NOT NULL,
        acquired_at TIMESTAMPTZ NOT NULL,
        tradable_at TIMESTAMPTZ NOT NULL,
        UNIQUE (key, edition, serial)
    );
    CREATE INDEX items_owner ON items (owner, acquired_at DESC);
    CREATE TABLE transfers (
        seq BIGSERIAL PRIMARY KEY,
        item TEXT NOT NULL REFERENCES items (id),
        from_owner TEXT,
        to_owner TEXT NOT NULL,
        at TIMESTAMPTZ NOT NULL,
        trade TEXT
    );
    CREATE INDEX transfers_item ON transfers (item, seq);
    CREATE TABLE claims (
        owner TEXT NOT NULL,
        source TEXT NOT NULL,
        item TEXT NOT NULL,
        run TEXT,
        at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (owner, source)
    );
    CREATE TABLE trades (
        id TEXT PRIMARY KEY,
        sender TEXT NOT NULL,
        recipient TEXT NOT NULL,
        give TEXT[] NOT NULL,
        take TEXT[] NOT NULL,
        message TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL
    );
    CREATE INDEX trades_sender ON trades (sender, created_at DESC);
    CREATE INDEX trades_recipient ON trades (recipient, created_at DESC);
    CREATE INDEX trades_items ON trades USING GIN ((give || take));
    """,
    # 2: the casino: its games, the items staked in them, the items won
    """
    ALTER TABLE items ADD COLUMN staked TEXT;
    ALTER TABLE transfers ADD COLUMN game TEXT;
    CREATE TABLE games (
        id TEXT PRIMARY KEY,
        mode TEXT NOT NULL,
        status TEXT NOT NULL,
        side TEXT,
        entries JSONB NOT NULL,
        players TEXT[] NOT NULL,
        server_seed TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        closes_at TIMESTAMPTZ,
        roll BIGINT,
        winner TEXT
    );
    CREATE INDEX games_status ON games (status, mode, updated_at DESC);
    CREATE INDEX games_players ON games USING GIN (players);
    CREATE UNIQUE INDEX games_one_jackpot ON games (mode) WHERE mode = 'jackpot' AND status = 'open';
    """,
)

ITEM_COLUMNS = ("id", "kind", "key", "edition", "rarity", "stake", "serial", "owner", "source", "source_run",
                "created_at", "acquired_at", "tradable_at", "staked")
SELECT_ITEMS = sql.SQL("SELECT {} FROM items").format(sql.SQL(", ").join(sql.Identifier(c) for c in ITEM_COLUMNS))
SELECT_TRADES = ("SELECT id, sender, recipient, give, take, message, status, created_at, updated_at, expires_at "
                 "FROM trades")
GAME_COLUMNS = ("id", "mode", "status", "side", "entries", "players", "server_seed", "created_at", "updated_at",
                "closes_at", "roll", "winner")
SELECT_GAMES = sql.SQL("SELECT {} FROM games").format(sql.SQL(", ").join(sql.Identifier(c) for c in GAME_COLUMNS))


class DatabaseUnavailable(RuntimeError):
    """The database doesn't answer when the service starts."""


def where(url: str) -> str:
    """The database's address, without the password."""
    try:
        d = conninfo_to_dict(url)
    except Exception:
        return "(an unreadable URL)"
    return f"{d.get('host', 'localhost')}:{d.get('port', 5432)}/{d.get('dbname', '')}"


def _item(r: DictRow) -> Item:
    return Item(id=r["id"], kind=Kind(r["kind"]), key=r["key"], edition=Edition(r["edition"]),
                rarity=Rarity(r["rarity"]), stake=r["stake"], serial=r["serial"], owner=r["owner"],
                source=r["source"], source_run=r["source_run"], created_at=r["created_at"],
                acquired_at=r["acquired_at"], tradable_at=r["tradable_at"], staked=r["staked"])


def _player(r: DictRow) -> PlayerRecord:
    return PlayerRecord(id=r["id"], name=r["name"], has_won=r["has_won"], showcase=r["showcase"],
                        created_at=r["created_at"], synced_at=r["synced_at"])


def _trade(r: DictRow) -> Trade:
    return Trade(id=r["id"], sender=r["sender"], recipient=r["recipient"], give=tuple(r["give"]),
                 take=tuple(r["take"]), message=r["message"], status=TradeStatus(r["status"]),
                 created_at=r["created_at"], updated_at=r["updated_at"], expires_at=r["expires_at"])


def _game(r: DictRow) -> Game:
    entries = [Entry(player=e["player"], items=tuple(e["items"]), value=int(e["value"]), seed=e["seed"],
                     at=datetime.fromisoformat(e["at"])) for e in r["entries"]]
    return Game(id=r["id"], mode=Mode(r["mode"]), status=GameStatus(r["status"]),
                side=Side(r["side"]) if r["side"] else None, entries=entries, server_seed=r["server_seed"],
                created_at=r["created_at"], updated_at=r["updated_at"], closes_at=r["closes_at"], roll=r["roll"],
                winner=r["winner"])


def _game_row(g: Game) -> dict[str, Any]:
    entries = [{"player": e.player, "items": list(e.items), "value": e.value, "seed": e.seed, "at": e.at.isoformat()}
               for e in g.entries]
    return {"id": g.id, "mode": g.mode.value, "status": g.status.value, "side": g.side.value if g.side else None,
            "entries": Jsonb(entries), "players": g.players, "server_seed": g.server_seed, "created_at": g.created_at,
            "updated_at": g.updated_at, "closes_at": g.closes_at, "roll": g.roll, "winner": g.winner}


class PostgresUnit:
    def __init__(self, conn: Connection[DictRow]) -> None:
        self.c = conn

    def player(self, player_id: str, lock: bool = False) -> PlayerRecord | None:
        row = self.c.execute("SELECT * FROM players WHERE id = %s" + (" FOR UPDATE" if lock else ""),
                             (player_id,)).fetchone()
        return _player(row) if row else None

    def save_player(self, p: PlayerRecord) -> None:
        self.c.execute(
            "INSERT INTO players (id, name, has_won, showcase, created_at, synced_at) VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, has_won = EXCLUDED.has_won, "
            "showcase = EXCLUDED.showcase, synced_at = EXCLUDED.synced_at",
            (p.id, p.name, p.has_won, p.showcase, p.created_at, p.synced_at))

    def find_players(self, query: str, limit: int) -> list[PlayerRecord]:
        pattern = query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = self.c.execute("SELECT * FROM players WHERE lower(name) LIKE %s ORDER BY lower(name) LIMIT %s",
                              (pattern, limit)).fetchall()
        return [_player(r) for r in rows]

    def item(self, item_id: str) -> Item | None:
        row = self.c.execute(SELECT_ITEMS + sql.SQL(" WHERE id = %s"), (item_id,)).fetchone()
        return _item(row) if row else None

    def items(self, ids: Sequence[str], lock: bool = False) -> dict[str, Item]:
        if not ids:
            return {}
        q = SELECT_ITEMS + sql.SQL(" WHERE id = ANY(%s) ORDER BY id") + sql.SQL(" FOR UPDATE" if lock else "")
        return {r["id"]: _item(r) for r in self.c.execute(q, (list(ids),)).fetchall()}

    def items_of(self, owner: str) -> builtins.list[Item]:
        q = SELECT_ITEMS + sql.SQL(" WHERE owner = %s ORDER BY acquired_at DESC, id DESC")
        return [_item(r) for r in self.c.execute(q, (owner,)).fetchall()]

    def add_item(self, item: Item) -> Item:
        row = self.c.execute(
            "INSERT INTO serials (key, edition, last) VALUES (%s, %s, 1) "
            "ON CONFLICT (key, edition) DO UPDATE SET last = serials.last + 1 RETURNING last",
            (item.key, item.edition.value)).fetchone()
        assert row is not None
        item.serial = row["last"]
        values: dict[str, Any] = {c: getattr(item, c) for c in ITEM_COLUMNS}
        values.update(kind=item.kind.value, edition=item.edition.value, rarity=int(item.rarity))
        self.c.execute(sql.SQL("INSERT INTO items ({}) VALUES ({})").format(
            sql.SQL(", ").join(sql.Identifier(c) for c in ITEM_COLUMNS),
            sql.SQL(", ").join(sql.Placeholder(c) for c in ITEM_COLUMNS)), values)
        return item

    def save_item(self, item: Item) -> None:
        self.c.execute("UPDATE items SET owner = %s, acquired_at = %s, tradable_at = %s, staked = %s WHERE id = %s",
                       (item.owner, item.acquired_at, item.tradable_at, item.staked, item.id))

    def minted(self, key: str, edition: Edition) -> int:
        row = self.c.execute("SELECT last FROM serials WHERE key = %s AND edition = %s",
                             (key, edition.value)).fetchone()
        return int(row["last"]) if row else 0

    def add_transfer(self, t: Transfer) -> None:
        self.c.execute("INSERT INTO transfers (item, from_owner, to_owner, at, trade, game) "
                       "VALUES (%s, %s, %s, %s, %s, %s)", (t.item, t.from_owner, t.to_owner, t.at, t.trade, t.game))

    def transfers(self, item_id: str) -> builtins.list[Transfer]:
        rows = self.c.execute("SELECT item, from_owner, to_owner, at, trade, game FROM transfers WHERE item = %s "
                              "ORDER BY seq", (item_id,)).fetchall()
        return [Transfer(item=r["item"], from_owner=r["from_owner"], to_owner=r["to_owner"], at=r["at"],
                         trade=r["trade"], game=r["game"]) for r in rows]

    def claims(self, owner: str) -> set[str]:
        return {r["source"] for r in self.c.execute("SELECT source FROM claims WHERE owner = %s", (owner,))}

    def claim(self, owner: str, source: str, item_id: str, run: str | None, at: datetime) -> bool:
        cur = self.c.execute("INSERT INTO claims (owner, source, item, run, at) VALUES (%s, %s, %s, %s, %s) "
                             "ON CONFLICT (owner, source) DO NOTHING", (owner, source, item_id, run, at))
        return cur.rowcount == 1

    def trade(self, trade_id: str, lock: bool = False) -> Trade | None:
        row = self.c.execute(SELECT_TRADES + " WHERE id = %s" + (" FOR UPDATE" if lock else ""),
                             (trade_id,)).fetchone()
        return _trade(row) if row else None

    def add_trade(self, t: Trade) -> None:
        self.c.execute(
            "INSERT INTO trades (id, sender, recipient, give, take, message, status, created_at, updated_at, "
            "expires_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (t.id, t.sender, t.recipient, list(t.give), list(t.take), t.message, t.status.value, t.created_at,
             t.updated_at, t.expires_at))

    def save_trade(self, t: Trade) -> None:
        self.c.execute("UPDATE trades SET status = %s, updated_at = %s WHERE id = %s",
                       (t.status.value, t.updated_at, t.id))

    def trades_of(self, player: str, box: str, limit: int) -> builtins.list[Trade]:
        cond = {"incoming": "recipient = %(p)s", "outgoing": "sender = %(p)s"}.get(
            box, "(sender = %(p)s OR recipient = %(p)s)")
        rows = self.c.execute(SELECT_TRADES + f" WHERE {cond} ORDER BY created_at DESC, id DESC LIMIT %(n)s",
                              {"p": player, "n": limit}).fetchall()
        return [_trade(r) for r in rows]

    def pending_from(self, sender: str, now: datetime) -> int:
        row = self.c.execute("SELECT count(*) AS n FROM trades WHERE sender = %s AND status = 'pending' "
                             "AND expires_at > %s", (sender, now)).fetchone()
        return int(row["n"]) if row else 0

    def game(self, game_id: str, lock: bool = False) -> Game | None:
        q = SELECT_GAMES + sql.SQL(" WHERE id = %s") + sql.SQL(" FOR UPDATE" if lock else "")
        row = self.c.execute(q, (game_id,)).fetchone()
        return _game(row) if row else None

    def add_game(self, g: Game) -> None:
        self.c.execute(sql.SQL("INSERT INTO games ({}) VALUES ({})").format(
            sql.SQL(", ").join(sql.Identifier(c) for c in GAME_COLUMNS),
            sql.SQL(", ").join(sql.Placeholder(c) for c in GAME_COLUMNS)), _game_row(g))

    def save_game(self, g: Game) -> None:
        self.c.execute("UPDATE games SET status = %(status)s, entries = %(entries)s, players = %(players)s, "
                       "updated_at = %(updated_at)s, closes_at = %(closes_at)s, roll = %(roll)s, winner = %(winner)s "
                       "WHERE id = %(id)s", _game_row(g))

    def open_jackpot(self, lock: bool = False) -> Game | None:
        if lock:  # (also when there is none: then this unit may open it)
            self.c.execute("SELECT pg_advisory_xact_lock(hashtext('balatro_items.jackpot'))")
        q = SELECT_GAMES + sql.SQL(" WHERE mode = 'jackpot' AND status = 'open'") + sql.SQL(
            " FOR UPDATE" if lock else "")
        row = self.c.execute(q).fetchone()
        return _game(row) if row else None

    def games(self, mode: Mode | None, status: GameStatus, player: str | None, limit: int) -> builtins.list[Game]:
        cond = [sql.SQL("status = %(status)s")]
        if mode is not None:
            cond.append(sql.SQL("mode = %(mode)s"))
        if player is not None:
            cond.append(sql.SQL("players @> ARRAY[%(player)s]::text[]"))
        q = SELECT_GAMES + sql.SQL(" WHERE ") + sql.SQL(" AND ").join(cond) + sql.SQL(
            " ORDER BY updated_at DESC, id DESC LIMIT %(n)s")
        rows = self.c.execute(q, {"status": status.value, "mode": mode.value if mode else None, "player": player,
                                  "n": limit}).fetchall()
        return [_game(r) for r in rows]


class PostgresStore:
    """``url``: postgresql://user:password@host/db.  ``schema``: keep the tables in this
    schema (made if needed).  ``connect_timeout``: how long to wait for the database at
    start (seconds) before raising DatabaseUnavailable."""

    def __init__(self, url: str, schema: str | None = None, max_connections: int = 10,
                 connect_timeout: float = 30) -> None:
        def configure(conn: Connection[Any]) -> None:
            conn.execute("SET TIME ZONE 'UTC'")
            if schema:
                conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            conn.commit()

        if schema:
            with Connection.connect(url, autocommit=True) as conn:
                conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
        self._pool: ConnectionPool[Connection[DictRow]] = ConnectionPool(
            url, min_size=1, max_size=max_connections, configure=configure, open=False,
            kwargs={"row_factory": dict_row}, connection_class=Connection[DictRow])
        try:
            self._pool.open(wait=True, timeout=connect_timeout)
        except PoolTimeout:
            self._pool.close()
            raise DatabaseUnavailable(
                f"PostgreSQL at {where(url)} doesn't answer (BALATRO_ITEMS_DATABASE_URL). In Docker, the "
                "items-db service of BalatroFrontEnd's docker-compose.yml is this service's database") from None
        self.migrate()

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def unit(self) -> Iterator[PostgresUnit]:
        with self._pool.connection() as conn, conn.transaction():
            yield PostgresUnit(conn)

    def migrate(self) -> None:
        with self._pool.connection() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('balatro_items.migrations'))")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, "
                         "applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
            row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations").fetchone()
            done = row["v"] if row else 0
            for version, script in enumerate(MIGRATIONS, 1):
                if version > done:
                    conn.execute(script.encode())
                    conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
