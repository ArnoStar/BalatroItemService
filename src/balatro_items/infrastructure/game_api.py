"""The game API (BalatroWebAPI): the player's runs, read with their own access
token (the API checks it), and the catalog of the cards items are: jokers,
tarot, planet and spectral cards, playing cards with their upgrades."""

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
from balatro_items.domain import CONSUMABLE_RARITY, Kind, Rarity, RunRecord, Template, playing_cards

log = logging.getLogger(__name__)

PAGE = 200
MAX_PAGES = 10  # the 2000 most recent runs
CATALOG_TTL = 3600.0
# The Soul's gem, drawn over the card (G.shared_soul: P_CENTERS.soul's sprite)
SOUL_OVERLAY = {"atlas": "centers", "pos": {"x": 0, "y": 1}}


def templates_of(cat: dict[str, Any]) -> list[Template]:
    """The catalog's cards as items' templates."""
    out = [Template(kind=Kind.JOKER, key=j["key"], name=j["name"], rarity=Rarity(int(j.get("rarity") or 1)),
                    sprite=j.get("sprite")) for j in cat.get("jokers", [])]
    for kind, field in ((Kind.TAROT, "tarots"), (Kind.PLANET, "planets"), (Kind.SPECTRAL, "spectrals")):
        for c in cat.get(field, []):
            sprite = c.get("sprite")
            if c["key"] == "c_soul" and sprite:
                sprite = {**sprite, "overlay": SOUL_OVERLAY}
            out.append(Template(kind=kind, key=c["key"], name=c["name"],
                                rarity=CONSUMABLE_RARITY.get(c["key"], Rarity.COMMON), sprite=sprite))
    enhancements = {e["key"]: e.get("sprite") for e in cat.get("enhancements", [])}
    seals = {s["key"]: s.get("sprite") for s in cat.get("seals", [])}
    base: dict[str, object] = {"atlas": "centers", "pos": {"x": 1, "y": 0}}  # c_base: the blank card
    out += playing_cards(((c["key"], c["name"], c.get("sprite")) for c in cat.get("cards", [])), base, enhancements,
                         seals)
    return out


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
        templates = templates_of(cat)
        with self._lock:
            self._catalog, self._catalog_at = templates, time.monotonic()
        return templates
