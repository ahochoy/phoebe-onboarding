.PHONY: up test lint seed

up:
	docker compose up -d db

test:
	uv run pytest backend/tests

lint:
	uv run ruff check . && uv run pyright

seed:
	uv run python -m phoebe.seed
