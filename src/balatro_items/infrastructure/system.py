"""The clock, ids, and the randomness of the drops and of the casino's seeds."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidGenerator:
    def new_id(self) -> str:
        return uuid.uuid4().hex


class SystemRandom:
    """The operating system's randomness: nobody can predict or replay a drop."""

    def __init__(self) -> None:
        self._rng = secrets.SystemRandom()

    def random(self) -> float:
        return self._rng.random()


class SecretSeeds:
    """The casino's server seeds: the operating system's randomness, so nobody can guess one."""

    def seed(self) -> str:
        return secrets.token_hex(32)
