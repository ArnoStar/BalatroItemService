"""The game API (BalatroWebAPI): the player's runs, read with their own access
token (the API checks it), and the catalog of jokers and tags."""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from balatro_items.application.dto import Player
from balatro_items.application.errors import GameApiUnavailable
from balatro_items.domain import TAG_RARITY, Kind, Rarity, RunRecord, Template

log = logging.getLogger(__name__)

PAGE = 200
MAX_PAGES = 10  # the 2000 most recent runs
CATALOG_TTL = 3600.0


class GameApi:
    """``base``: the API's address (http://api:8000 in the stack), without /api/v1."""

    def __init__(self, base: str, timeout: float = 10) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout
        self._catalog: list[Template] | None = None
        self._catalog_at = 0.0
        self._lock = threading.Lock()

    def _get(self, path: str, token: str | None = None) -> Any:
        req = urllib.request.Request(f"{self.base}/api/v1{path}", headers={"Accept": "application/json"})
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            log.warning("the game API didn't answer %s: %s", path, exc)
            raise GameApiUnavailable("the game's server can't be reached, try again") from exc

    def runs(self, player: Player) -> list[RunRecord]:
        out: list[RunRecord] = []
        for page in range(MAX_PAGES):
            rows = self._get(f"/games?limit={PAGE}&offset={page * PAGE}", player.token)
            for r in rows:
                s = r.get("settings") or {}
                out.append(RunRecord(id=r["id"], deck=str(s.get("deck") or ""), stake=int(s.get("stake") or 1),
                                     won=bool(r.get("won")), finished=r.get("phase") == "game_over",
                                     ante=int(r.get("ante") or 0), counted=bool(r.get("counted")),
                                     ended_at=datetime.fromisoformat(r["updated_at"])))
            if len(rows) < PAGE:
                break
        return out

    def templates(self) -> list[Template]:
        with self._lock:
            if self._catalog is not None and time.monotonic() - self._catalog_at < CATALOG_TTL:
                return self._catalog
        try:
            cat = self._get("/catalog")
        except GameApiUnavailable:
            if self._catalog is not None:
                return self._catalog  # (an old copy is better than none)
            raise
        templates = [Template(kind=Kind.JOKER, key=j["key"], name=j["name"], rarity=Rarity(int(j.get("rarity") or 1)),
                              sprite=j.get("sprite")) for j in cat.get("jokers", [])]
        templates += [Template(kind=Kind.TAG, key=t["key"], name=t["name"],
                               rarity=TAG_RARITY.get(t["key"], Rarity.COMMON), sprite=t.get("sprite"))
                      for t in cat.get("tags", [])]
        with self._lock:
            self._catalog, self._catalog_at = templates, time.monotonic()
        return templates
