from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from balatro_items.application.use_cases import UseCases
from balatro_items.bootstrap import build_use_cases
from balatro_items.config import Settings
from balatro_items.infrastructure.auth import JwtAuthenticator
from balatro_items.infrastructure.persistence import MemoryStore, PostgresStore
from balatro_items.presentation.http import create_app
from tests.fakes import Clock, FakeCatalog, FakeRuns, Ids, Seeds, rng
from tests.tokens import AUDIENCE, ISSUER, FixedKeys

# a PostgreSQL database the tests may use (each test gets its own schema, dropped
# after it); without it the PostgreSQL tests are skipped. `make test` sets it to
# the database of `make db`.
PG_URL = os.environ.get("BALATRO_ITEMS_TEST_DATABASE_URL")


@dataclass
class World:
    uses: UseCases
    runs: FakeRuns
    catalog: FakeCatalog
    clock: Clock
    client: TestClient


def make_world(store: object | None = None, signed_in: bool = True, **settings: Any) -> World:
    runs, catalog, clock = FakeRuns(), FakeCatalog(), Clock()
    auth = JwtAuthenticator(FixedKeys(), ISSUER, AUDIENCE) if signed_in else None
    uses = build_use_cases(Settings(database="memory", admins=("root",), **settings), store=store or MemoryStore(),  # type: ignore[arg-type]
                           catalog=catalog, runs=runs, clock=clock, ids=Ids(), rng=rng(), seeds=Seeds(),
                           authenticator=auth)
    return World(uses=uses, runs=runs, catalog=catalog, clock=clock, client=TestClient(create_app(uses)))


@pytest.fixture
def world() -> World:
    return make_world()


@pytest.fixture
def pg() -> Iterator[Callable[[], PostgresStore]]:
    if not PG_URL:
        pytest.skip("BALATRO_ITEMS_TEST_DATABASE_URL is not set")
    schema = f"test_{uuid.uuid4().hex[:12]}"
    made: list[PostgresStore] = []

    def make() -> PostgresStore:
        made.append(PostgresStore(PG_URL, schema=schema))  # type: ignore[arg-type]
        return made[-1]

    yield make
    for s in made:
        s.close()
    with psycopg.connect(PG_URL, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
