# Spend-limit mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phoebe degrades to browse-only before the AWS spend limit stops Aurora, shows an offline screen (not a 500) when it is stopped, emails the owner both times, and comes back with one command.

**Architecture:** The existing account-wide budget (raised to $30, 70%) keeps driving the budget Lambda's `chat_paused`; the frontend shows a spend banner for it. A new EventBridge rule on the cluster's "stopped" event (infra/bootstrap, owner-applied) invokes the same budget Lambda, which sets `closed`, and an alerts SNS topic that emails the owner. The API maps the Data API's stopped-cluster error to `503 database_stopped`. `make db-start ENV=…` starts the cluster, waits, and reopens; `ci/deploy.sh` refuses to run against a stopped cluster.

**Tech Stack:** Python 3.14 / FastAPI / boto3 (moto in tests), React + TypeScript (Vitest), Terraform (tftest, aws provider), bash (`ci/tests` stub harness).

**Spec:** `docs/superpowers/specs/2026-11-17-spend-limit-mode-design.md`

## Global Constraints

- AWS: us-east-2 only for everything in this plan (EventBridge, SNS, Lambda, RDS). No us-east-1 resources, no cross-Region actions.
- Nothing starts the cluster or sets `open` automatically. Only `ci/db-start.sh` (run by the owner) does either.
- The owner's email never appears in the repository, a committed tfvars file, a test, or a log: it comes only from `TF_VAR_alert_email` at owner apply time.
- Logs carry metadata only (event ids, states), never SNS or event bodies.
- Budget: `monthly_budget_usd` default `30`; notification threshold `70` (PERCENTAGE, ACTUAL).
- Banner copy (exact): `Chat and uploads are paused to keep this demo within its spending limit. Everything else works as usual.`
- Offline copy for `database_stopped` reuses the `demo_closed` text exactly: `The Phoebe demo is temporarily offline. Please check back later.`
- New error code: `database_stopped` (HTTP 503).
- RDS event: `detail-type` `RDS DB Cluster Event`, `EventID` `RDS-EVENT-0150` (DB cluster stopped). Confirm the id against https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/USER_Events.Messages.html before committing Task 4; if it differs, use the documented "DB cluster stopped" id and note it in the commit.
- Names: rule `phoebe-<env>-db-stopped`, topic `phoebe-alerts`, restart script `ci/db-start.sh`, make target `db-start` with `ENV=staging|production`.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A stopped-cluster error in the middle of a request that already started a transaction: the handler must still answer 503 `database_stopped`, not 500 (Task 1 test `test_stopped_cluster_maps_to_database_stopped` covers a plain call; add `..._inside_transaction`).
2. The EventBridge invocation arriving while the state is `chat_paused` or `open`: it must end `closed` either way, and a second delivery (EventBridge is at-least-once) must be harmless (Task 2 `test_db_stopped_event_closes_from_any_state`, `test_db_stopped_event_is_idempotent`).
3. `db-start` when the cluster is already `available` (owner runs it twice, or AWS's 7-day auto-start beat them): it must not call `start-db-cluster`, and must still reopen (Task 6 `test_db_start_skips_start_when_available`).
4. `db-start` when the cluster is `stopping`: `start-db-cluster` fails on that state, so the script must wait for `stopped` first or exit with a clear "still stopping, run again shortly" message, never reopen a stopped cluster (Task 6 `test_db_start_refuses_while_stopping`).
5. A rate-limit reason (`global_chat_limit`) together with `chat_paused`: the banner shows, and the pill does not show a second message (Task 3 `shows only the banner when paused and capped`).

---

### Task 1: API answers 503 `database_stopped` for a stopped cluster

**Files:**
- Modify: `backend/src/phoebe/db.py` (add `DatabaseStopped`)
- Modify: `backend/src/phoebe/db_data_api.py` (map the error code)
- Modify: `backend/src/phoebe/api/app.py` (handler)
- Modify: `frontend/openapi.json`, `frontend/src/api/schema.ts` only if error codes are enumerated there (`make fe-gen`; `make fe-lint` says if stale)
- Test: `backend/tests/test_data_api.py`, `backend/tests/test_api_app.py` (or wherever the existing `database_unavailable` 503 test lives; `grep -rn database_unavailable backend/tests`)

**Interfaces:**
- Produces: `class DatabaseStopped(DatabaseUnavailable)` in `phoebe.db` (subclass, so the worker's `_TRANSIENT` retry and every existing `except DatabaseUnavailable` still apply). API error code `database_stopped`.

- [ ] **Step 1: Write the failing tests**
  - `test_stopped_cluster_maps_to_database_stopped`: a stubbed rds-data client raises `ClientError` with code `InvalidResourceStateException` (message `"The instance db-X is in stopped state..."`); `DataApiDatabase.fetch(...)` raises `DatabaseStopped`, with no retry (the stub is called once).
  - `test_stopped_cluster_maps_to_database_stopped_inside_transaction`: same, inside a transaction.
  - API: a route whose DB call raises `DatabaseStopped` returns `503` and `{"detail": "database_stopped"}`; one raising plain `DatabaseUnavailable` still returns `database_unavailable`.
- [ ] **Step 2: Run them, expect FAIL** — `PHOEBE_TEST_DATABASE_URL=postgresql://postgres:phoebe@localhost:5433/phoebe_test uv run pytest backend/tests/test_data_api.py -k stopped -v`
- [ ] **Step 3: Implement.** In `db_data_api.py` add `_STOPPED = "InvalidResourceStateException"`, checked before `_OUTAGE`, raising `DatabaseStopped("stopped") from None` after a `_log.warning("database stopped op=%s", op)`. In `app.py` register `@app.exception_handler(DatabaseStopped)` returning `_error(503, "database_stopped")` with a route-only warning log, like the existing handler.
- [ ] **Step 4: Run `make test`, expect all pass; `make lint` clean.**
- [ ] **Step 5: Commit** `feat(api): a stopped database answers 503 database_stopped`

### Task 2: The budget Lambda closes the demo on the cluster-stopped event

**Files:**
- Modify: `backend/src/phoebe/lambdas/budget.py`
- Modify: `backend/src/phoebe/control.py` only if a helper is wanted; `DynamoDBControlStore.set("closed")` is enough
- Test: `backend/tests/test_control.py`

**Interfaces:**
- Consumes: the EventBridge event shape `{"source": "aws.rds", "detail-type": "RDS DB Cluster Event", "detail": {"EventID": "RDS-EVENT-0150", "SourceIdentifier": "phoebe-<env>", ...}}`.
- Produces: `handler(event, context) -> {"state": "closed"}` for that event; unchanged `{"state": ...}` for SNS `Records`.

- [ ] **Step 1: Write the failing tests** (moto, same fixtures as `test_budget_handler_sets_chat_paused`)
  - `test_db_stopped_event_closes_from_any_state`: parametrize the starting state over `open`, `chat_paused`, `closed`; after the handler, `get() == "closed"` and the return is `{"state": "closed"}`.
  - `test_db_stopped_event_is_idempotent`: two deliveries, still `closed`.
  - `test_db_stopped_event_logs_metadata_only`: the event carries `"Message": "SECRET"` in `detail`; the log has the EventID and source identifier, never `SECRET`.
  - `test_unrelated_event_changes_nothing`: an event with `source: aws.rds` but another EventID leaves the state as it was and returns its current state.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** In `handler`, if `event.get("source") == "aws.rds"`: when `detail.EventID == "RDS-EVENT-0150"`, `store.set("closed")`; log `db event id=%s source=%s`; return the state. Otherwise keep the SNS path. Update the module docstring: it now also closes on a stopped cluster; it still never sets `open`.
- [ ] **Step 4: `make test`, `make lint`.**
- [ ] **Step 5: Commit** `feat(budget): close the demo when the database stops`

### Task 3: Spend banner for `chat_paused`; offline screen for `database_stopped`

**Files:**
- Create: `frontend/src/components/SpendBanner.tsx`, `frontend/src/components/SpendBanner.test.tsx`
- Modify: `frontend/src/state/status.ts` (split `limited` into `paused` and `capped`)
- Modify: `frontend/src/components/StatusPill.tsx` (show only for `capped && !paused`)
- Modify: the page shell that renders `Header` on every page (render `<SpendBanner />` above the header content; find it with `grep -rn "<Header" frontend/src`)
- Modify: `frontend/src/lib/messages.ts` (`database_stopped` → the `demo_closed` text; `chat_paused` keeps its current copy for API errors)
- Modify: `frontend/src/pages/Landing.tsx` (`closed` also when `me.error.code === "database_stopped"`; a login that fails with `database_stopped` switches to the offline panel)
- Test: `frontend/src/state/status.test.ts` (if present), `StatusPill.test.tsx`, `Landing.test.tsx`, `client.test.ts`

**Interfaces:**
- Produces: `useStatus()` returns `{ status, paused: boolean, capped: boolean, limited: boolean, chatAvailable, uploadAvailable, refresh }`, where `paused = status.state === "chat_paused"`, `capped = reasons ∩ CAP_REASONS ≠ ∅`, `limited = paused || capped` (kept for existing callers).

- [ ] **Step 1: Write the failing tests**
  - `SpendBanner` `shows the spend copy while paused`: status `{state: "chat_paused", reasons: ["chat_paused"], ...}` renders `role="status"` with the exact banner copy.
  - `SpendBanner` `renders nothing when open or only capped`.
  - `StatusPill` `shows only the banner when paused and capped`: status `chat_paused` with `global_chat_limit`: banner present, pill absent.
  - `StatusPill` `still shows the pill for a cap alone`: `open` + `session_chat_limit`: pill present, banner absent.
  - `Landing` `shows the offline panel when me fails with database_stopped`, and `switches to the offline panel when login returns database_stopped`.
  - `messageFor(new ApiError(503, "database_stopped"))` equals the `demo_closed` text.
- [ ] **Step 2: `make fe-test`, expect FAIL.**
- [ ] **Step 3: Implement.** Banner: full-width strip above the header, Larkspur warn tokens like the pill (`border-warn/50 bg-amber-50 text-warn`, `Info` icon), `role="status"`, text wraps on phones; no dismiss button (it clears when the state does).
- [ ] **Step 4: `make fe-test`, `make fe-lint`; `make e2e` still 18 passed (limits.spec.ts asserts the pill on `make pause`: change its assertion to the banner copy in this task, since pause is `chat_paused`).**
- [ ] **Step 5: Commit** `feat(web): spend banner when paused; offline screen when the database is stopped`

### Task 4: Budget and alerts in infra/bootstrap

**Files:**
- Modify: `infra/bootstrap/variables.tf` (`monthly_budget_usd` default 30; new `alert_email`)
- Modify: `infra/bootstrap/budget.tf` (threshold 70; production budget emails `alert_email`)
- Create: `infra/bootstrap/alerts.tf` (topic, email subscription, topic policy, per-env rule and targets)
- Test: `infra/bootstrap/tests/bootstrap.tftest.hcl`

**Interfaces:**
- Produces: rule ARN `arn:aws:events:us-east-2:<account>:rule/phoebe-<env>-db-stopped` (Task 5 grants it), topic `phoebe-alerts`.

- [ ] **Step 1: Write the failing tftest runs**
  - `budget_threshold_and_amount`: both budgets have `limit_amount = "30"` and one notification at `threshold = 70`, `ACTUAL`.
  - `alert_email_optional`: with `alert_email = null`, no email subscription and no `subscriber_email_addresses`; with `"owner@example.com"`, the production budget notification lists it and `aws_sns_topic_subscription.alert_email` exists with protocol `email`.
  - `db_stopped_rules`: for each env, `aws_cloudwatch_event_rule.db_stopped[env]` pattern decodes to `source ["aws.rds"]`, `detail-type ["RDS DB Cluster Event"]`, `detail.EventID ["RDS-EVENT-0150"]`, `detail.SourceIdentifier ["phoebe-<env>"]`; two targets: `arn:aws:lambda:us-east-2:<acct>:function:phoebe-<env>-budget` and the alerts topic.
  - `alerts_topic_policy`: allows only `events.amazonaws.com` `sns:Publish`, conditioned on `aws:SourceArn` equal to the two rule ARNs.
- [ ] **Step 2: `make tf-check`, expect FAIL.**
- [ ] **Step 3: Implement.** `alert_email`: `type = string`, `default = null`, `sensitive = true`, validation `null or contains "@"`. Target the Lambda by its constructed ARN (the function is created by infra/app; EventBridge accepts the ARN before it exists). The email target uses an `input_transformer` that sends only `"Phoebe <env>: database stopped (EventID <id>). Run make db-start ENV=<env> when the spend limit allows."`.
- [ ] **Step 4: `make tf-check` passes.**
- [ ] **Step 5: Commit** `feat(bootstrap): $30 budget at 70%, alert email, db-stopped rule`

### Task 5: Let the rule invoke the budget Lambda (infra/app)

**Files:**
- Modify: `infra/app/budget.tf`
- Test: `infra/app/tests/app.tftest.hcl`

- [ ] **Step 1: Failing tftest** `budget_events_permission`: `aws_lambda_permission.budget_events` has `principal = "events.amazonaws.com"`, `action = "lambda:InvokeFunction"`, `source_arn = "arn:aws:events:us-east-2:<acct>:rule/phoebe-<env>-db-stopped"`, function the env's budget Lambda.
- [ ] **Step 2: `make tf-check`, expect FAIL.**
- [ ] **Step 3: Implement** next to `aws_lambda_permission.budget_sns`. The deploy role already has `lambda:AddPermission`; no bootstrap IAM change.
- [ ] **Step 4: `make tf-check` passes.**
- [ ] **Step 5: Commit** `feat(app): allow the db-stopped rule to invoke the budget Lambda`

### Task 6: `make db-start` and the deploy pre-check

**Files:**
- Create: `ci/db-start.sh`
- Modify: `Makefile` (`db-start:` runs `bash ci/db-start.sh $(ENV)`; add to `.PHONY`)
- Modify: `ci/deploy.sh` (pre-check before `invoke_ops migrate`)
- Modify: `infra/app/README.md` (replace the "start it by hand" recovery line from the rollout notes with `make db-start`; one paragraph on the spend-limit mode)
- Test: `ci/tests/test_deploy_scripts.py`

**Interfaces:**
- `ci/db-start.sh <staging|production>`: cluster `phoebe-<env>`, table `phoebe-<env>-state`, region `us-east-2`. Reopen = `aws dynamodb put-item --table-name phoebe-<env>-state --item '{"pk":{"S":"control"},"state":{"S":"open"}}'` (the `DynamoDBControlStore._KEY` item).

- [ ] **Step 1: Failing tests** (Harness stubs `aws`)
  - `test_db_start_starts_waits_then_reopens`: status `stopped` → calls in order `rds describe-db-clusters`, `rds start-db-cluster --db-cluster-identifier phoebe-production`, `rds wait db-cluster-available`, `dynamodb put-item` with the open item; every call has `--region us-east-2`.
  - `test_db_start_skips_start_when_available`: status `available` → no `start-db-cluster`, still `put-item`.
  - `test_db_start_refuses_while_stopping`: status `stopping` → exits non-zero, message contains `still stopping`, no `put-item`.
  - `test_db_start_rejects_bad_env`: `dev`, no args → usage error, no `aws` calls.
  - `test_deploy_stops_when_cluster_stopped`: status `stopped` → `ci/deploy.sh` exits non-zero with `run make db-start ENV=staging`, and no `lambda invoke` happened.
  - `test_deploy_proceeds_when_available`: existing migrate-before-seed order unchanged.
- [ ] **Step 2: `make deploy-check`, expect FAIL.**
- [ ] **Step 3: Implement.** Status via `aws rds describe-db-clusters --db-cluster-identifier phoebe-<env> --query 'DBClusters[0].Status' --output text --region us-east-2`. In `deploy.sh`, `stopped|stopping` dies with `database is stopped (spend limit?): run make db-start ENV=<env>, then re-run`; any other status continues (`available`, and `starting`, which migrate's resume retry handles). The deploy roles already have `rds:Describe*`.
- [ ] **Step 4: `make deploy-check`, `make lint` (shellcheck via actionlint path if configured).**
- [ ] **Step 5: Commit** `feat(ops): make db-start, and deploys refuse a stopped database`

### Task 7: Owner rollout (not code)

- [ ] Merge; staging deploys (Tasks 1–3, 5).
- [ ] Owner: `cd infra/bootstrap && TF_VAR_alert_email=<their email> terraform plan -out=alerts.plan`, review (2 budgets updated, topic + subscription + policy, 2 rules, 4 targets added), apply; confirm the SNS subscription email.
- [ ] Release a `v*` tag for production (Tasks 1–3, 5 reach production).
- [ ] Verify on staging with the owner's go: `make pause`-equivalent for staging (`aws dynamodb put-item ... chat_paused`) shows the banner; set `open` again. Do not stop a cluster to test the rule unless the owner asks (it closes the demo and needs `make db-start`).
