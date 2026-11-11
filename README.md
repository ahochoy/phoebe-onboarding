# Phoebe

Phoebe is an onboarding portal demo for the fictional company Larkspur Labs. A new hire signs in as a seeded persona, sees their onboarding tasks, and asks questions answered from company documents (and from documents or links they add in a private sandbox), using hybrid vector and full-text search. All data is synthetic.

## Local quickstart

Requires Docker, [uv](https://docs.astral.sh/uv/), and `jq`.

```sh
make stack   # build the image, start Postgres + API, migrate, seed
make smoke   # exercise the real HTTP API end to end (prints OK)
make test    # pytest against a separate `phoebe_test` database
make lint    # ruff check, ruff format --check, pyright
make down    # stop the stack
```

- The API listens on `http://localhost:8080` (set `PHOEBE_PORT` if that port is taken).
- The dev password is `larkspur-demo`; override with `PHOEBE_DEV_PASSWORD`. `make stack` writes `.env` with its hash on first run (delete `.env` to regenerate).
- The stack and the test suite share one Postgres container but use different databases (`phoebe` and `phoebe_test`). The test fixtures drop and recreate the schema of the test database only, so `make test` does not wipe the stack's seed.

## Design

See [`docs/superpowers/specs/2026-11-09-phoebe-design.md`](docs/superpowers/specs/2026-11-09-phoebe-design.md).
