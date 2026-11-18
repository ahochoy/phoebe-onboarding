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

## Frontend

The web app lives in `frontend/` (Vite, React, TypeScript). It needs Node 22 (`frontend/.nvmrc`).

```sh
make fe-install   # npm ci
make stack        # the API the app talks to
make fe-dev       # Vite dev server on http://localhost:5173, proxying /api to the stack
make fe-test      # unit and component tests (Vitest)
make fe-lint      # tsc, ESLint, Prettier, and a stale-schema check
make fe-build     # production build into frontend/dist
```

The dev server and `vite preview` proxy `/api` to `http://localhost:$PHOEBE_PORT` (default 8080). Log in with the dev password (`PHOEBE_DEV_PASSWORD`, default `larkspur-demo`).

### End-to-end tests

The Playwright suite drives the built app against the real local stack, with axe accessibility checks, in five browser projects: `chromium`, `firefox`, `webkit`, `mobile-safari` (iPhone 15) and `mobile-chrome` (Pixel 8). It covers each critical journey once, in the browsers where it can fail differently; logic and API behaviour live in the Vitest and pytest suites. Each test's tag picks its projects (see `frontend/playwright.config.ts`): `@all` (login and session), `@desktop` (keyboard-only journey), `@mobile` (bottom tabs and sheets), `@journey` and `@axe` (one desktop and one phone), `@once` (chromium only).

```sh
(cd frontend && npx playwright install chromium firefox webkit)   # once
make stack-e2e   # the stack with the login, chat and upload caps raised for the suite
make e2e         # build, serve with `vite preview` on :4173, run every project
```

- `make stack-e2e` is `make stack` with higher caps: the suite logs in once per test, which the default login throttle (10 per IP per 15 minutes) would block. Run plain `make stack` afterwards to go back to the defaults.
- Set `PHOEBE_PORT` for both commands if the API is not on 8080. Playwright reads the password from `PHOEBE_DEV_PASSWORD`, which the Makefile exports.
- The kill-switch test (`e2e/limits.spec.ts`) runs `make pause`, `make kill` and `make open`. It runs once, in chromium, after every other test, and always leaves the demo `open`; a global setup also reopens it before each run.
- Every test logs in to its own sandbox and wipes it when done. The report lands in `frontend/playwright-report/`.
- The offline stack (extractive answers, hash embeddings) answers nearly every question with a citation, so refusals are covered by the pytest and component tests, not here.
- Playwright runs locally for now; it joins CI in Plan 5.

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
| `PHOEBE_QUESTION_MAX_CHARS` | `1000` | Longest accepted chat question, after trimming (422 `invalid_request`). Must be 1 to 4000 (max 4000, the request body cap). |
| `PHOEBE_HISTORY_EXCHANGES` | `3` | Earlier question/answer pairs given to the rewriter and the answer model. |
| `PHOEBE_HISTORY_TURN_MAX_CHARS` | `2000` | Each history turn is truncated to this length. |
| `PHOEBE_ANSWER_MAX_TOKENS` | `700` | `max_tokens` for the answer model. |
| `PHOEBE_ANSWER_MAX_CHARS` | `6000` | An answer longer than this is stopped and refused (`verification_failed`, code 1204). |
| `PHOEBE_REFUSAL_MIN_SIMILARITY` | (per embedder) | Top similarity below which chat refuses with `no_support`; unset uses 0.05 for `hash` and 0.25 for `titan`. |
| `PHOEBE_ANSWER_BACKEND` | `extractive` | Answer model: `extractive` (offline, quotes the best passage), `converse` (Haiku 4.5 through Bedrock ConverseStream; what staging and production run), or `harness` (the Bedrock AgentCore harness; the rollback path). `converse` requires the guardrail settings. |
| `PHOEBE_ANSWER_MODEL_ID` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Inference profile the `converse` backend calls. It sends `backend/prompts/answer.txt` as the system prompt, temperature 0.1 and `PHOEBE_ANSWER_MAX_TOKENS`, with no tools. AWS only. |
| `PHOEBE_HARNESS_ARN` | (unset) | Harness ARN, required for the `harness` backend. AWS only. |
| `PHOEBE_REWRITER_BACKEND` | `heuristic` | Query rewriter: `heuristic` (offline) or `bedrock`. |
| `PHOEBE_REWRITE_MODEL_ID` | `us.amazon.nova-micro-v1:0` | Bedrock model for the `bedrock` rewriter. AWS only. |
| `PHOEBE_REWRITE_MAX_TOKENS` | `64` | `max_tokens` for the rewriter. |
| `PHOEBE_GUARDRAIL_ID` | (unset) | Bedrock guardrail id; with `PHOEBE_GUARDRAIL_VERSION` it turns on input and output checks. AWS only. |
| `PHOEBE_GUARDRAIL_VERSION` | (unset) | Bedrock guardrail version. AWS only. |

## Chat refusal codes

When Phoebe refuses, the visitor sees a short message with a numeric code in
parentheses, and the `done` event's `reason` field carries the same code. The
internal reason name appears only in the API logs (`refused=<reason>`). The
leading digit groups codes: 1xxx answer quality, 2xxx safety, 3xxx
availability. The source of truth is `backend/src/phoebe/chat/refusals.py`.

| Code | Reason | When |
|------|--------|------|
| 1001 | `no_support` | Search found nothing relevant, or the model answered NO_ANSWER. The message ("I couldn't find that in your onboarding documents.") shows no code. |
| 1204 | `verification_failed` | The answer failed the citation check or ran past `PHOEBE_ANSWER_MAX_CHARS`. |
| 2307 | `blocked` | The guardrail blocked the question or the answer. |
| 3115 | `model_unavailable` | The embedding, answer or guardrail model call failed. |

## Evals

`make eval` runs a fixed question set (`backend/evals/questions.yaml`, about 30
cases) through the real chat pipeline and grades every answer without an AI
judge: answered or refused with the right code, which documents it cites or
must never cite or offer, and the facts it must contain. It is owner-run from
a terminal, never in CI, and it **costs money**: it prints the number of calls
and an estimated cost, then asks before calling AWS (`YES=1` skips the
question). Every run spends from the account's shared spend limit, and at 70%
of the budget the demo pauses chat.

```sh
make eval                          # the production Haiku harness only
make eval MODEL=all                # haiku, haiku-direct and every candidate
make eval MODEL=haiku,glm-5.3 CASES=list,fact REPEAT=3
```

- **Environment:** the same as `make live-check`: `PHOEBE_LIVE_DATABASE_URL` (a database whose name ends in `_live`; it is migrated and seeded) and the live `PHOEBE_*` AI settings. It runs the app in-process and never touches staging or production.
- **Models:**
  - `haiku` is the production harness.
  - `haiku-direct` sends Haiku 4.5 through the same direct Bedrock ConverseStream call as the candidates. It is a control: it shows how far that call shifts results from the harness.
  - The candidates are `kimi-k3.1` (sent no temperature, which it rejects) and `gpt-oss-120b`. `glm-5.3` is defined but left out of `MODEL=all`: the account cannot call it ("not available for this account"). It still runs by name.
  - Each answer-model call's raw output is saved in the results file (`raw`), so a refused answer shows why, for example a paragraph with no `[Pn]` label.
  - Prices live in `backend/src/phoebe/evals/candidates.py`, with their source and date. A price the Bedrock pricing page does not list is shown as "price unknown", never guessed.
- **Isolation:** every case logs in fresh, so it gets its own session and history. Follow-up questions play their earlier turns for real.
- **Output:** a table per model (passed, failed, flaky, forbidden hits, refusal accuracy, latency, cost per answer, and pass counts by category), then one line per failing check. The full answers go to `backend/evals/results/<time>-<model>.jsonl`, which is git-ignored.
- **Verdict (quality first):** a candidate qualifies only if, on the same run:
  1. it passes at least as many cases as `haiku`;
  2. it has zero forbidden citations and leaks;
  3. it has no more flaky cases than `haiku`.

  The cheapest qualifier wins, and latency breaks a tie. Otherwise the verdict is "keep Haiku 4.5". A switch still goes through a real staging harness and an `infra/ai` change.

## Design

See [`docs/superpowers/specs/2026-11-09-phoebe-design.md`](docs/superpowers/specs/2026-11-09-phoebe-design.md).
