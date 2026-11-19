SHELL := /bin/bash
.PHONY: up test-db stack smoke down test lint seed pause kill open status live-check eval fe-install fe-gen fe-dev fe-test fe-lint fe-build stack-e2e e2e tf-check deploy-check db-start db-stop screenshots

PHOEBE_DEV_PASSWORD ?= larkspur-demo
PHOEBE_PORT ?= 8080
export PHOEBE_PORT
export PHOEBE_DEV_PASSWORD
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
		hash="$$(uv run python -m phoebe.auth "$$PHOEBE_DEV_PASSWORD")" || exit 1; \
		printf "PHOEBE_PASSWORD_HASH='%s'\n" "$$hash" > .env; \
	fi
	docker compose up -d --build --wait db api || { docker compose logs --tail 50 api; exit 1; }
	@echo "waiting for http://localhost:$(PHOEBE_PORT)/api/health"
	@for i in $$(seq 1 60); do \
		curl -fsS -o /dev/null http://localhost:$(PHOEBE_PORT)/api/health && exit 0; \
		sleep 1; \
	done; echo "api did not become healthy in 60s" >&2; docker compose logs --tail 50 api; exit 1
	docker compose exec -T api python -m phoebe migrate
	docker compose exec -T api python -m phoebe seed

smoke:
	@PHOEBE_URL=$${PHOEBE_URL:-http://localhost:$(PHOEBE_PORT)} backend/scripts/smoke.sh

down:
	docker compose down

test: test-db
	uv run pytest backend/tests

# Also lints .github/workflows with a pinned, checksum-verified actionlint (cached after the first run).
lint:
	uv run ruff check . && uv run ruff format --check . && uv run pyright
	ci/actionlint.sh

# Kill-switch state lives in data/control.json. When the api container is up it
# reads its own copy, so run the command inside it; otherwise use the host.
control = if docker compose ps --status running -q api 2>/dev/null | grep -q .; then \
		docker compose exec -T api python -m phoebe control $(1); \
	else uv run python -m phoebe control $(1); fi

seed:
	uv run python -m phoebe.seed

pause:
	@$(call control,chat_paused)

kill:
	@$(call control,closed)

open:
	@$(call control,open)

status:
	@$(call control,status)

# Restart an env after its database was stopped (spend limit): starts the Aurora
# cluster, waits for it, then reopens the demo browse-only (chat paused). OPEN=1
# reopens fully. Owner-run; it spends money.
db-start:
	@[ -n "$(ENV)" ] || { echo "usage: make db-start ENV=staging|production [OPEN=1]" >&2; exit 2; }
	bash ci/db-start.sh $(ENV) $(if $(OPEN),--open)

# Park an env's database while it is idle (usually staging): closes the demo,
# then stops the Aurora cluster. Undo with make db-start ENV=...
db-stop:
	@[ -n "$(ENV)" ] || { echo "usage: make db-stop ENV=staging|production" >&2; exit 2; }
	bash ci/db-stop.sh $(ENV)

# Owner-gated live AWS check (costs money). NOT part of `make test` or CI.
# Needs PHOEBE_LIVE_DATABASE_URL (database name ending in _live) and the
# PHOEBE_* AI settings; see infra/ai/README.md.
live-check:
	uv run python backend/scripts/live_chat_check.py

# Owner-run chat evals (costs money; asks first unless YES=1). Same env as
# live-check, plus MODEL, CASES, REPEAT. See docs/development.md "Evals".
eval:
	MODEL="$(MODEL)" CASES="$(CASES)" REPEAT="$(REPEAT)" YES="$(YES)" uv run python -m phoebe.evals.run

# Frontend (run from frontend/; Node version in frontend/.nvmrc).
fe-install:
	cd frontend && npm ci

fe-gen:
	cd frontend && npx openapi-typescript openapi.json -o src/api/schema.ts

fe-dev:
	cd frontend && npm run dev

fe-test:
	cd frontend && npx vitest run

# Also fails if regenerating the schema would change src/api/schema.ts
# (openapi-typescript prints to stdout when no -o is given).
fe-lint:
	cd frontend && npx tsc -b --noEmit && npx eslint . && npx prettier --check .
	cd frontend && npx openapi-typescript openapi.json 2>/dev/null | diff -u src/api/schema.ts - \
		|| { echo "src/api/schema.ts is stale: run make fe-gen" >&2; exit 1; }

fe-build:
	cd frontend && npm run build

# Offline Terraform checks: no backend, no AWS calls (tests use mock providers).
TF_ROOTS := infra/ai infra/app infra/bootstrap
tf-check:
	terraform fmt -check -recursive infra
	@set -e; for root in $(TF_ROOTS); do \
		echo "== $$root"; \
		terraform -chdir=$$root init -backend=false -input=false >/dev/null; \
		terraform -chdir=$$root validate; \
		terraform -chdir=$$root test; \
	done
	node --test 'infra/app/functions/*.test.js'

# The stack with the login, chat and upload caps raised for the Playwright suite (it logs
# in once per test across five browser projects). Plain `make stack` restores the defaults.
stack-e2e:
	PHOEBE_LOGIN_PER_IP_WINDOW=100000 PHOEBE_CHAT_GLOBAL_DAY=100000 PHOEBE_UPLOADS_GLOBAL_DAY=100000 \
		$(MAKE) stack

# Cross-browser end to end against the running stack (`make stack-e2e` first).
e2e:
	cd frontend && npm run build && npx playwright test

# Owner-run: the README demo GIF from staging (costs about a cent of Bedrock).
# PHOEBE_CAPTURE_URL picks another environment. See docs/development.md.
screenshots:
	@test -n "$$PHOEBE_CAPTURE_PASSWORD" || { echo "Set PHOEBE_CAPTURE_PASSWORD (the staging demo password)." >&2; exit 2; }
	cd frontend && PHOEBE_DEV_PASSWORD="$$PHOEBE_CAPTURE_PASSWORD" npx playwright test -c playwright.capture.config.ts
	frontend/capture/to-gif.sh frontend/capture-output/demo.webm docs/images/demo.gif

# Offline checks for the CodeBuild scripts (ci/): syntax, shellcheck when installed, and
# the pytest suite that drives them with stubbed aws/terraform/docker/npm/curl.
deploy-check:
	@for f in ci/*.sh; do bash -n "$$f" || exit 1; done
	@if command -v shellcheck >/dev/null; then shellcheck -x ci/*.sh; \
	elif [ -n "$$CI" ]; then echo "shellcheck is required in CI" >&2; exit 1; \
	else echo "warning: shellcheck not installed; skipping (required in CI)" >&2; fi
	uv run pytest ci/tests -q
