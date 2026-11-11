SHELL := /bin/bash
.PHONY: up test-db stack smoke down test lint seed

PHOEBE_DEV_PASSWORD ?= larkspur-demo
PHOEBE_PORT ?= 8080
export PHOEBE_PORT
# DB tests run against their own database so they never wipe the stack's seed.
PHOEBE_TEST_DATABASE_URL ?= postgresql://postgres:phoebe@localhost:5433/phoebe_test
export PHOEBE_TEST_DATABASE_URL

up:
	docker compose up -d --wait db

test-db: up
	docker compose exec -T db psql -U postgres -tAc "select 1 from pg_database where datname = 'phoebe_test'" | grep -q 1 \
		|| docker compose exec -T db createdb -U postgres phoebe_test

stack:
	@if [ ! -f .env ]; then \
		echo "writing .env (password from PHOEBE_DEV_PASSWORD)"; \
		hash="$$(uv run python -m phoebe.auth "$(PHOEBE_DEV_PASSWORD)")" || exit 1; \
		printf "PHOEBE_PASSWORD_HASH='%s'\n" "$$hash" > .env; \
	fi
	docker compose up -d --build --wait db api || { docker compose logs --tail 50 api; exit 1; }
	@echo "waiting for http://localhost:$(PHOEBE_PORT)/api/health"
	@for i in $$(seq 1 60); do \
		curl -fsS -o /dev/null http://localhost:$(PHOEBE_PORT)/api/health && exit 0; \
		sleep 1; \
	done; echo "api did not become healthy in 60s" >&2; docker compose logs --tail 50 api; exit 1
	docker compose exec api python -m phoebe migrate
	docker compose exec api python -m phoebe seed

smoke:
	PHOEBE_URL=$${PHOEBE_URL:-http://localhost:$(PHOEBE_PORT)} PHOEBE_DEV_PASSWORD=$(PHOEBE_DEV_PASSWORD) backend/scripts/smoke.sh

down:
	docker compose down

test: test-db
	uv run pytest backend/tests

lint:
	uv run ruff check . && uv run ruff format --check . && uv run pyright

seed:
	uv run python -m phoebe.seed
