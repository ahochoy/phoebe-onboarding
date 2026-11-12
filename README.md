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

## Configuration

Settings are `PHOEBE_*` environment variables. Every default works offline: nothing below calls AWS unless you change it. These settings were added for AI chat and spend safety; the base settings (`PHOEBE_DATABASE_URL`, `PHOEBE_PASSWORD_HASH`, sessions, cookies, paths) are unchanged.

| Variable | Default | Purpose |
|---|---|---|
| `PHOEBE_EMBEDDER` | `hash` | Embedder: `hash` (offline, deterministic) or `titan` (Bedrock Titan v2). The database records which embedder built its vectors; the API refuses to start on a mismatch. |
| `PHOEBE_AWS_REGION` | `us-east-2` | Region for every AWS client (Bedrock, DynamoDB). |
| `PHOEBE_MAX_CHUNKS_PER_DOCUMENT` | `400` | Indexing fails a document that would produce more chunks than this. |
| `PHOEBE_LIMITS_BACKEND` | `memory` | Cap counters: `memory` (per process) or `dynamodb` (uses `PHOEBE_STATE_TABLE`). |
| `PHOEBE_CONTROL_BACKEND` | `file` | Kill switch store: `file` (`PHOEBE_CONTROL_FILE`) or `dynamodb` (`PHOEBE_STATE_TABLE`). |
| `PHOEBE_CONTROL_FILE` | `data/control.json` | Kill switch file for the `file` backend (missing means `open`). |
| `PHOEBE_STATE_TABLE` | (unset) | DynamoDB table for counters and the kill switch. AWS only. |
| `PHOEBE_KILL_SWITCH_CACHE_SECONDS` | `5` | How long the API caches the kill switch state. |
| `PHOEBE_CHAT_PER_SESSION_HOUR` | `30` | Chat and search requests per session per hour (429 `session_chat_limit`). |
| `PHOEBE_CHAT_GLOBAL_DAY` | `300` | Chat and search requests across all sessions per day (429 `global_chat_limit`). |
| `PHOEBE_UPLOADS_PER_SESSION_DAY` | `5` | Uploads and links per session per day (429 `session_upload_limit`). |
| `PHOEBE_UPLOADS_GLOBAL_DAY` | `50` | Uploads and links across all sessions per day (429 `global_upload_limit`). |
| `PHOEBE_LOGIN_PER_IP_WINDOW` | `10` | Login attempts per client IP per window (429 `too_many_attempts`). |
| `PHOEBE_LOGIN_WINDOW_SECONDS` | `900` | Login throttle window, in seconds. |
| `PHOEBE_CLIENT_IP_HEADER` | (unset) | Header that carries the client IP behind a proxy; unset uses the socket peer. |
| `PHOEBE_QUESTION_MAX_CHARS` | `1000` | Longest accepted chat question, after trimming (422 `invalid_request`). |
| `PHOEBE_HISTORY_EXCHANGES` | `3` | Earlier question/answer pairs given to the rewriter and the answer model. |
| `PHOEBE_HISTORY_TURN_MAX_CHARS` | `2000` | Each history turn is truncated to this length. |
| `PHOEBE_ANSWER_MAX_TOKENS` | `700` | `max_tokens` for the answer model. |
| `PHOEBE_ANSWER_MAX_CHARS` | `6000` | An answer longer than this is stopped and refused (`verification_failed`). |
| `PHOEBE_REFUSAL_MIN_SIMILARITY` | (per embedder) | Top similarity below which chat refuses with `no_support`; unset uses 0.05 for `hash` and 0.25 for `titan`. |
| `PHOEBE_ANSWER_BACKEND` | `extractive` | Answer model: `extractive` (offline, quotes the best passage) or `harness` (Bedrock AgentCore harness). |
| `PHOEBE_HARNESS_ARN` | (unset) | Harness ARN, required for the `harness` backend. AWS only. |
| `PHOEBE_REWRITER_BACKEND` | `heuristic` | Query rewriter: `heuristic` (offline) or `bedrock`. |
| `PHOEBE_REWRITE_MODEL_ID` | `us.amazon.nova-micro-v1:0` | Bedrock model for the `bedrock` rewriter. AWS only. |
| `PHOEBE_REWRITE_MAX_TOKENS` | `64` | `max_tokens` for the rewriter. |
| `PHOEBE_GUARDRAIL_ID` | (unset) | Bedrock guardrail id; with `PHOEBE_GUARDRAIL_VERSION` it turns on input and output checks. AWS only. |
| `PHOEBE_GUARDRAIL_VERSION` | (unset) | Bedrock guardrail version. AWS only. |

## Design

See [`docs/superpowers/specs/2026-11-09-phoebe-design.md`](docs/superpowers/specs/2026-11-09-phoebe-design.md).
