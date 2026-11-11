"""Access tokens of the identity service (BalatroIndentityService): RS256
JWTs, checked with the public keys it publishes at ``/.well-known/jwks.json``
(fetched when a token names a key not seen yet, and every few minutes)."""

from __future__ import annotations

import logging
from typing import Protocol

import jwt

from balatro_items.application.dto import Player
from balatro_items.application.errors import AuthUnavailable, NotAuthenticated
from balatro_items.domain import ANONYMOUS_PLAYER

log = logging.getLogger(__name__)


class SigningKeys(Protocol):
    """Where a token's key comes from (``jwt.PyJWKClient``, or a fixed key in tests)."""

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK: ...


class JwtAuthenticator:
    required = True

    def __init__(self, keys: SigningKeys, issuer: str, audience: str, leeway: float = 30) -> None:
        self.keys = keys
        self.issuer = issuer
        self.audience = audience
        self.leeway = leeway  # seconds of clock difference with the identity service

    @classmethod
    def from_jwks_url(cls, url: str, issuer: str, audience: str) -> JwtAuthenticator:
        return cls(jwt.PyJWKClient(url, cache_keys=True, lifespan=300, timeout=5), issuer, audience)

    def authenticate(self, token: str | None) -> Player:
        if not token:
            raise NotAuthenticated("sign in: this server needs an access token (Authorization: Bearer ...)")
        try:
            key = self.keys.get_signing_key_from_jwt(token)
        except jwt.PyJWKClientConnectionError as exc:
            log.warning("could not fetch the identity service's keys: %s", exc)
            raise AuthUnavailable("the sign-in service can't be reached, try again") from exc
        except jwt.PyJWTError as exc:
            raise NotAuthenticated("the access token is invalid") from exc
        try:
            claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=self.audience, issuer=self.issuer,
                                leeway=self.leeway, options={"require": ["exp", "iat", "sub", "iss", "aud"]})
        except jwt.ExpiredSignatureError as exc:
            raise NotAuthenticated("the access token has expired") from exc
        except jwt.PyJWTError as exc:
            raise NotAuthenticated("the access token is invalid") from exc
        if claims.get("typ") != "access":
            raise NotAuthenticated("not an access token")
        name = claims.get("name")
        roles = claims.get("roles")
        roles = frozenset(r for r in roles if isinstance(r, str)) if isinstance(roles, list) else frozenset()
        return Player(id=str(claims["sub"]), name=name if isinstance(name, str) else None, roles=roles, token=token)


class AnonymousAuthenticator:
    """No sign-in: everyone is the same player (development, tests, and the
    front end's frame-by-frame tools)."""

    required = False

    def authenticate(self, token: str | None) -> Player:
        return Player(id=ANONYMOUS_PLAYER)
