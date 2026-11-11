# BalatroItemService: `make` lists the commands.
#
# Alone:            make install && make db && make run   (http://127.0.0.1:8004, docs at /docs)
# With sign-in:     make run-auth                          (the identity service on :8001: its `make run`)
# Everything:       make dev in ../BalatroFrontEnd         (the whole site, each part from its repository)
.DEFAULT_GOAL := help
.PHONY: help install db run run-auth check test lint typecheck docker

STACK := ../BalatroFrontEnd/docker-compose.yml
PORT ?= 8004
TEST_DATABASE ?= postgresql://items:items@127.0.0.1:55435/items
# the identity service run locally: the tokens' issuer (its PUBLIC_URL) and where its keys are
IDENTITY_URL ?= http://localhost:8001
IDENTITY_JWKS ?= http://127.0.0.1:8001/.well-known/jwks.json

help:
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

install: ## dependencies
	uv sync

db: ## the PostgreSQL the service and the tests use (items-db of the game's compose file, 127.0.0.1:55435)
	docker compose -f $(STACK) up -d --wait items-db

run: ## serve on :8004 without sign-in (everyone is one player, and an admin), reloading on changes
	uv run uvicorn balatro_items.main:app --reload --port $(PORT)

run-auth: ## the same, with sign-in: tokens of the identity service at IDENTITY_URL; BALATRO_ITEMS_ADMINS give items
	BALATRO_ITEMS_AUTH_JWKS_URL=$(IDENTITY_JWKS) \
	BALATRO_ITEMS_AUTH_ISSUER=$(IDENTITY_URL) \
	uv run uvicorn balatro_items.main:app --reload --port $(PORT)

check: test lint typecheck ## everything CI runs (tests, ruff, mypy)

test: ## the tests (the PostgreSQL ones on `make db`'s database)
	BALATRO_ITEMS_TEST_DATABASE_URL=$${BALATRO_ITEMS_TEST_DATABASE_URL:-$(TEST_DATABASE)} uv run pytest

lint: ## ruff
	uv run ruff check src tests

typecheck: ## mypy --strict
	uv run mypy

docker: ## this service in Docker, from the game's compose file (http://127.0.0.1:8004)
	docker compose -f $(STACK) up -d --build items
