.PHONY: up test lint

up:
	docker compose up -d db

test:
	uv run pytest backend/tests

lint:
	uv run ruff check . && uv run pyright
