"""Access tokens as the identity service makes them, signed with a test key."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "http://identity.test"
AUDIENCE = "balatro"

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FixedKeys:
    """Stands in for jwt.PyJWKClient: the identity service's one key."""

    def __init__(self, key: rsa.RSAPrivateKey = KEY) -> None:
        self.jwk = jwt.PyJWK.from_dict({**jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True),
                                        "alg": "RS256", "kid": "test"})

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        return self.jwk


def token(sub: str = "player-1", name: str | None = "Jimbo", key: rsa.RSAPrivateKey = KEY,
          lifetime: timedelta = timedelta(minutes=15), **claims: Any) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {"iss": ISSUER, "aud": AUDIENCE, "sub": sub, "iat": now, "exp": now + lifetime,
                               "typ": "access", **({"name": name} if name else {}), **claims}
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": "test"})
