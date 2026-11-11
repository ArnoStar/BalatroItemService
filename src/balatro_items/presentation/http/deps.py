"""FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from balatro_items.application.dto import Player
from balatro_items.application.use_cases import UseCases

bearer = HTTPBearer(auto_error=False, description="an access token from the identity service")


def use_cases(request: Request) -> UseCases:
    uc: UseCases = request.app.state.use_cases
    return uc


Uses = Annotated[UseCases, Depends(use_cases)]


def current_player(uses: Uses,
                   credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Player:
    return uses.authenticate(credentials.credentials if credentials else None)


CurrentPlayer = Annotated[Player, Depends(current_player)]
