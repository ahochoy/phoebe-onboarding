# Phoebe Plan 4: Cloud and Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run Phoebe on AWS in two environments, staging and production, with automated delivery:
- Every PR gets a frontend preview.
- Every merge to `main` deploys staging.
- Every `v*` tag deploys production after the owner approves.

**Architecture:**
- **Backend:** the same container image runs every Lambda.
  - The API runs under the Lambda Web Adapter, with a response-streaming function URL.
  - The worker, DLQ, sweeper, budget and ops handlers run under `awslambdaric`.
- **Database:** Aurora Serverless v2 (min 0 ACU), reached only through the RDS Data API by a new `DataApiDatabase` adapter that implements the existing `Database` protocol. There is no VPC.
- **Other stores:** DynamoDB holds sessions, counters and the kill switch (the Plan 2 code). S3 holds uploads and the SPA. SQS and a DLQ carry indexing jobs.
- **Edge:** CloudFront serves the SPA and routes `/api/*` to the function URL. A secret origin header locks the function URL to CloudFront.
- **Terraform:**
  - `infra/bootstrap` holds the delivery machinery. The owner applies it locally.
  - `infra/app` is applied once per environment by CodeBuild.
  - `infra/ai` stays shared and moves to remote state. This replaces the Plan 2 note about moving it into the module with `moved {}` blocks. Its resources have no idle cost and no per-environment data, so one shared copy is simpler.
- **CI split:** GitHub Actions runs tests only. CodeBuild and CodePipeline do every AWS write.

**Tech Stack:**
- Terraform `>= 1.10`, with S3 backend locking via `use_lockfile` and `terraform test` using `mock_provider`. Provider `hashicorp/aws ~> 6.62`.
- AWS: CodeBuild, CodePipeline V2, CodeConnections, ECR, Lambda (arm64, container image), Aurora PostgreSQL Serverless v2 with the Data API, DynamoDB, SQS, S3, CloudFront with OAC and CloudFront Functions, EventBridge Scheduler, Secrets Manager, Budgets and SNS.
- Python: `boto3` (`rds-data`, `s3`, `sqs`) and `awslambdaric`. moto covers S3 and SQS in tests.

**Spec:** `docs/superpowers/specs/2026-11-09-phoebe-design.md`. The sections that apply:
- §5: architecture, including §5.3 (superseded) and the new §5.5 (environments and delivery, owner-decided 2026-11-16).
- §6: security and spend.
- §4.2: the sweeper.

Also read the Plan 4 bullets under all three "Carry-forward notes" sections of `docs/superpowers/plans/2026-11-11-phoebe-roadmap.md`. The "Follow-up: Haiku 5.5" section is **out of scope**.

## Global Constraints

**Region and services**
- Every AWS resource goes in **us-east-2**. CloudFront is global. Budgets are account-level. Nothing is created in any other Region.
- Never use Lambda@Edge. Edge logic uses CloudFront Functions only.
- No cross-Region actions: no replication and no multi-Region keys. The budget's SNS topic and its Lambda subscribers are in us-east-2.
- No custom domain, Route 53 zone or ACM certificate (spec §5.3, superseded).

**Gated actions**
- No AWS resource is created, changed or destroyed without the owner's explicit go-ahead.
- Tasks 1–8 are offline: code, tests and `terraform validate`/`terraform test` with mocked providers only.
- Task 9 is the owner-gated rollout. Every `apply` there follows a shown plan and an explicit approval.

**CI and delivery**
- GitHub Actions jobs get **no AWS credentials** and make no AWS calls.
- Every CodeBuild webhook filter group includes `ACTOR_ACCOUNT_ID` equal to the owner's GitHub user id (a Terraform variable). A PR from a fork must never start a build.

**IAM**
- Deploy roles manage only resources named `phoebe-*`, using the account id and `us-east-2` in ARNs wherever the service allows it.
- Every IAM role created by `infra/app` sets `permissions_boundary = <the bootstrap boundary policy ARN>`.
- The boundary denies:
  - `iam:*` except `iam:PassRole` on `phoebe-*` roles;
  - `organizations:*`;
  - `account:*`;
  - any action outside us-east-2, except the global services CloudFront, IAM read, Budgets and STS.

**Tests and offline defaults**
- Default `Settings` must stay offline. No test may call AWS: use moto, fakes or injected clients.
- `make test`, `make lint`, `make fe-test`, `make fe-lint`, `make fe-build`, `make tf-check` (new) and `make e2e` must be clean at every commit.

**Logs and errors**
- Logs carry metadata only: request id, `log_id(sandbox)`, ids, counts, timings and exception type names. Never question, answer or document text.
- API `detail` stays a snake_case code.

**Data**
- Seed data is synthetic. The owner's email never appears in code, config, tags or logs.

**Git**
- Branch `feat/cloud`.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never work around a blocked command or hook. Stop and report instead.

**Exact names (used across tasks)**
- Environments: `staging` and `production`, shown as `${env}` below. The resource prefix is `phoebe-${env}`.
- Bootstrap resources:
  - State bucket: `phoebe-tfstate-<account_id>`.
  - Shared ECR repo: `phoebe-api`.
  - Connection: `phoebe-github`.
- State keys: `bootstrap.tfstate`, `ai.tfstate`, `app/staging.tfstate` and `app/production.tfstate`.
- Image tag: the full commit SHA. Production deploys by digest only.
- Preview path: `/pr-<n>/`. The S3 prefix is `previews/pr-<n>/` in the staging site bucket.
- Origin secret header: `X-Phoebe-Origin`. Its value lives in Secrets Manager as `phoebe-${env}-origin-secret`.

## Review Focus

These are the five failure modes the spec implies that no feature test would otherwise catch, most likely first. Each has a pinned test in the task named.

1. **The first request after Aurora auto-pauses.** The Data API raises `DatabaseResumingException` for about 15 s. Expected behaviour: the adapter retries with backoff for up to 40 s, the user sees "Getting Phoebe ready…", and the response is not a 500. *Pinned in Task 1* (`test_data_api.py::test_retries_while_resuming`).
2. **A document whose stored text exceeds the Data API's 1 MiB response limit.** Expected behaviour: the viewer still opens. `get_document` pages `full_text` in slices instead of failing. *Pinned in Task 1* (`test_data_api.py::test_large_text_is_fetched_in_slices`).
3. **Someone calls the function URL directly, bypassing CloudFront.** This would let them forge `cloudfront-viewer-address` and skip the login throttle. Expected behaviour: 403 `forbidden` for every path except `/api/health`. *Pinned in Task 2* (`test_origin_guard.py`).
4. **A refresh or deep link inside a preview,** for example `https://<staging>/pr-12/admin/tasks`. Expected behaviour: it serves that preview's `index.html`, not staging's and not a 404. *Pinned in Task 6* (`spa_router.test.js` runs the CloudFront Function code in Node).
5. **A PR opened from a fork of the public repo.** Expected behaviour: no CodeBuild run, so no deploy role ever sees untrusted code. *Pinned in Task 7* (`tests/bootstrap.tftest.hcl` asserts that every webhook filter group has the actor filter).

---

### Task 1: `DataApiDatabase` adapter

**Files:**
- Create: `backend/src/phoebe/db_data_api.py`, `backend/tests/test_data_api.py`
- Modify:
  - `backend/src/phoebe/config.py`: add `db_backend: Literal["psycopg","data_api"] = "psycopg"`, plus `db_cluster_arn`, `db_secret_arn` and `db_name: str = "phoebe"`.
  - `backend/src/phoebe/api/app.py`: add `make_database(settings) -> Database`.
  - `backend/src/phoebe/documents.py`: fetch `full_text` in slices.
  - `backend/src/phoebe/migrate.py`: take an advisory lock.

**Interfaces:**
- Produces:
  - `class DataApiDatabase(Database)` with `__init__(cluster_arn, secret_arn, database, *, client=None, resume_timeout_s=40.0, sleep=time.sleep)`, plus `fetch`, `execute`, `transaction()` and `close()`.
  - `make_database(settings) -> Database` (`PsycopgDatabase` or `DataApiDatabase`).
  - `encode_params(params: Mapping[str, Any]) -> list[dict]`. It is pure and unit-tested.

- [ ] **Step 1: Write the failing tests.** Use a fake `rds-data` client that records calls and returns canned `ExecuteStatement` responses.
  - **`test_named_params_pass_through`:** SQL with `:name` placeholders and `::type` casts is sent unchanged. Each param becomes `{"name":…, "value":{…}}`.
  - **`test_param_types`:**
    - str → `stringValue`; int → `longValue`; float → `doubleValue`; bool → `booleanValue`; None → `isNull: true`.
    - `uuid.UUID` → `stringValue` with `typeHint: "UUID"`.
    - `datetime.date` → `stringValue` "YYYY-MM-DD" with `typeHint: "DATE"`.
    - `datetime.datetime` (timezone-aware) → `typeHint: "TIMESTAMP"`, formatted `YYYY-MM-DD HH:MM:SS.ffffff`.
    - dict/list values that are JSON are passed as `stringValue`.
  - **`test_list_params_become_pg_array_literals`:** `["a","b,c",'d"e']` → `stringValue` `{"a","b,c","d\"e"}`, so the SQL's `::text[]` casts work. `None` stays `isNull`.
  - **`test_rows_decoded_from_json_records`:** the adapter sends `formatRecordsAs="JSON"`. `formattedRecords` comes back as a list of dicts.
  - **`test_execute_returns_number_of_records_updated`**.
  - **`test_transaction_commits_and_rolls_back`:**
    - `BeginTransaction`, then statements carrying the `transactionId`, then `CommitTransaction`.
    - An exception inside the block calls `RollbackTransaction` and re-raises.
  - **`test_retries_while_resuming`** (Review Focus 1): the first two calls raise `DatabaseResumingException` and the third succeeds. The injected `sleep` sees growing delays. A call that is still resuming after `resume_timeout_s` raises `DatabaseUnavailable`.
  - **`test_large_text_is_fetched_in_slices`** (Review Focus 2): `get_document` on a `DataApiDatabase` reads `full_text` with `substr(full_text, :off, 200000)` until a short slice comes back, and returns the joined text. The psycopg path reads it whole, as before.
  - **`test_migrations_take_advisory_lock`:** `apply_migrations` first runs `select pg_advisory_xact_lock(:k)` with a fixed key, in the same transaction as the migration statements, on both backends.
  - **`test_make_database_requires_arns`:** `db_backend="data_api"` without the ARNs raises `RuntimeError`.

- [ ] **Step 2: Run to verify they fail.** Run `make test-db && uv run pytest backend/tests/test_data_api.py -v`. Expect FAIL: the module is missing.

- [ ] **Step 3: Implement.**
  - **Unavailability.** `DatabaseUnavailable` subclasses the error the API layer already maps to a 503. If none exists, add a handler that returns `503 database_unavailable` and add that code to the frontend's `messages.ts` as "Phoebe's database is waking up. Try again in a few seconds."
  - **Placeholder conversion.** `to_pyformat` is not used on the Data API path. The Data API takes `:name` natively, so the SQL is sent as-is.
  - **Retries.** Retry only `DatabaseResumingException` and `StatementTimeoutException` on reads. Never retry inside a transaction after a write.
  - **The uuid index (Plan 1 carry-forward).** Change `id::text = :id` predicates on uuid primary keys to `id = :id::uuid`, so the primary-key index is used. A test asserts that the documents and tasks lookups no longer cast the column.

- [ ] **Step 4: Run to verify they pass.** `make test` and `make lint` must be green. The whole existing suite still runs on psycopg.

- [ ] **Step 5: Commit.** `git commit -m "feat(db): RDS Data API adapter with resume retries and sliced text"`

---

### Task 2: Cloud adapters for the API: blobs, jobs, origin guard, logging, startup checks

**Files:**
- Create:
  - `backend/src/phoebe/storage_s3.py`, `backend/src/phoebe/jobs_sqs.py`, `backend/src/phoebe/api/origin.py`, `backend/src/phoebe/logconfig.py`
  - Tests: `backend/tests/test_storage_s3.py`, `test_jobs_sqs.py`, `test_origin_guard.py`, `test_configured_app.py`
- Modify:
  - `backend/src/phoebe/config.py`:
    - `blob_backend: Literal["local","s3"] = "local"` and `uploads_bucket`
    - `job_backend: Literal["inline","sqs"] = "inline"` and `jobs_queue_url`
    - `origin_secret: str | None = None`
    - `log_level: str = "INFO"`
  - `backend/src/phoebe/api/app.py`: config-driven wiring; mount the origin guard; no `mkdir` when `blob_backend="s3"`.
  - `backend/src/phoebe/api/limits.py`: trust `client_ip_header` only when `origin_secret` is set.
  - `backend/src/phoebe/ingest/pipeline.py`: log `skipped` when the document is deleted mid-index.

**Interfaces:**
- Produces:
  - `S3BlobStore(bucket, *, client=None)`: implements `BlobStore`. A missing key raises the existing not-found error. Transient errors raise `BlobUnavailable`, never `ValueError`.
  - `SqsJobQueue(queue_url, *, client=None)`: `enqueue(document_id)` sends `{"document_id": …}`.
  - `OriginGuard` middleware.
  - `configure_logging(level)`: sets the `phoebe` logger to JSON lines, metadata only.

- [ ] **Step 1: Write the failing tests.**
  - **S3** (moto):
    - Put, get and delete round-trip.
    - `get` of a missing key raises the same exception type `LocalBlobStore` raises.
    - A botocore `EndpointConnectionError` becomes `BlobUnavailable`.
  - **SQS** (moto): `enqueue` puts exactly one message with body `{"document_id": "<id>"}`.
  - **`test_origin_guard.py`** (Review Focus 3), with `origin_secret="s3cr3t"`:
    - No header, or the wrong header: `GET /api/me` and `POST /api/login` return 403 `{"detail":"forbidden"}`.
    - The right header: normal behaviour.
    - `GET /api/health` is always allowed.
    - With `origin_secret=None`, the guard is a no-op, so local dev still works.
    - The comparison uses `hmac.compare_digest`.
  - **`test_client_ip_header_ignored_without_origin_secret`:** with `client_ip_header="cloudfront-viewer-address"` and no `origin_secret`, the throttle keys on the socket peer, not the header.
  - **`test_configured_app.py`:**
    - `create_configured_app()` with S3/SQS/Data API settings (fake clients injected through module-level factories) builds without touching the filesystem.
    - `answer_backend="harness"` without `guardrail_id` or `guardrail_version` raises `RuntimeError`. This is a Plan 2 carry-forward.
    - `configure_logging` makes a `phoebe.*` INFO line reach stdout as JSON.

- [ ] **Step 2: Run to verify they fail.** **Step 3: Implement.** **Step 4: Run to verify they pass.** `make test` and `make lint` must be green.

- [ ] **Step 5: Commit.** `git commit -m "feat(api): S3 blobs, SQS jobs, CloudFront origin guard, JSON logging"`

---

### Task 3: Lambda handlers: worker, DLQ, sweeper, ops

**Files:**
- Create:
  - `backend/src/phoebe/lambdas/__init__.py`, `worker.py`, `dlq.py`, `sweeper.py`, `ops.py`, `runtime.py`
  - Tests: `backend/tests/test_lambdas.py`, `backend/tests/test_sweeper.py`
- Modify:
  - `backend/src/phoebe/budget_handler.py`: move it to `lambdas/budget.py`, keeping a re-export at the old path.
  - `pyproject.toml`: add `awslambdaric`.
  - `backend/Dockerfile`: no change to `CMD`. Each Lambda overrides its command in Terraform.

**Interfaces:**
- Consumes: Task 1 `make_database` and Task 2 adapters.
- Produces handlers. Each one runs `python -m awslambdaric <path>`:
  - `phoebe.lambdas.worker.handler(event, ctx)`
    - Processes SQS records by calling `index_document`.
    - Returns `{"batchItemFailures": [...]}` for records that raised a retryable error.
  - `phoebe.lambdas.dlq.handler`: for each DLQ record, calls `mark_failed(id, "Indexing timed out")`.
  - `phoebe.lambdas.sweeper.handler`: calls `sweep(db, blobs, now)` and returns counts.
  - `phoebe.lambdas.ops.handler(event)`: accepts `{"task": "migrate" | "seed_if_empty" | "status"}`.
    - Any other input returns `{"error":"unknown_task"}`.
    - `seed_if_empty` seeds only when there are no seed groups. It never wipes.
  - `phoebe.lambdas.budget.handler`: unchanged behaviour.
  - `phoebe.lambdas.runtime.deps() -> Deps`: built once per container from env, shared by all handlers.
  - `sweep(db, blobs, now) -> SweepReport(sandboxes, chunks, blobs, stale_docs)`.

- [ ] **Step 1: Write the failing tests.**
  - **`test_sweeper.py`** (DB-backed):
    - Create two sandboxes. One has `last_seen` 25 h ago and owns a document, chunks, `chat_turns` and a blob. The other is fresh.
    - `sweep` removes every row of the old sandbox, its chunks, its `chat_turns`, its overlay rows and its blob. The fresh sandbox is untouched.
    - A `processing` document older than 15 min becomes `failed` with "Indexing timed out". A 2-minute-old one is untouched.
    - Seed rows are never touched.
  - **`test_lambdas.py`:**
    - **Worker:** one good record and one record whose `index_document` raises `EmbeddingUnavailable`. Only the second appears in `batchItemFailures`.
    - **Worker:** a record for a deleted document is acknowledged and logged as `skipped`.
    - **DLQ:** marks the document failed with the exact reason.
    - **Ops:** `migrate` applies migrations. `seed_if_empty` seeds an empty DB and is a no-op on a seeded one. An unknown task is rejected.
    - No handler ever logs record bodies or text.

- [ ] **Step 2: Run to verify they fail.** **Step 3: Implement.** Reuse `reset_session`, `forget_sandbox` and `blob_key_for` for the sweep, so one definition of "a sandbox's data" exists. **Step 4: Run to verify they pass.**

- [ ] **Step 5: Commit.** `git commit -m "feat(lambdas): worker, DLQ, sweeper and ops handlers"`

---

### Task 4: Frontend for cloud: preview base path, first-visit copy, hosted seed sources

**Files:**
- Modify:
  - `frontend/vite.config.ts`: `base` comes from `process.env.PHOEBE_BASE ?? "/"`.
  - `frontend/src/main.tsx` / `routes.tsx`: router `basename` = `import.meta.env.BASE_URL` without the trailing slash.
  - `frontend/src/session/SessionGate.tsx` and `Landing.tsx`.
  - `frontend/src/lib/links.ts`.
  - `backend/seed/manifest.yaml`: `public_url` for the two web seed documents.
  - `frontend/e2e/*`: no change; the default base is still `/`.
- Test: `frontend/src/session/session.test.tsx`, `frontend/src/lib/links.test.ts`, `frontend/src/routes.test.tsx`.

**Interfaces:**
- Produces:
  - A build that works under any base, for example `PHOEBE_BASE=/pr-12/ npm run build`. All asset URLs, router links and `/api` calls resolve correctly.
  - `/api` calls stay absolute at the origin root (`/api/...`), not under the base. Previews share the staging API.

- [ ] **Step 1: Write the failing tests.**
  - **`routes.test.tsx`:** rendered with base `/pr-12/`, navigating to Admin produces `location.pathname === "/pr-12/admin/people"`. Fetches still go to `/api/me`.
  - **`session.test.tsx` (the Plan 3 carry-forward):**
    - A first-time visitor (no `sessionStorage["phoebe.hadSession"]`) who deep-links to `/employee` lands on Landing with **no** "Your session ended…" message.
    - After a login, the marker is set. A later 401 shows the session-ended message.
    - Logout clears the marker.
  - **`links.test.ts`:** `isWebUrl("/seed-sources/benefits.html")` is true (same-origin path). `isWebUrl("//evil.example")` and `isWebUrl("javascript:alert(1)")` are false.
  - **Backend `test_seed.py`:**
    - The `benefits` seed document's `public_url` is `/seed-sources/benefits.html`.
    - The `project-manifest` document's `public_url` is `/seed-sources/project-manifest.txt`.
    - Both files exist in `backend/seed/content/`.

- [ ] **Step 2: Run to verify they fail.** **Step 3: Implement.** **Step 4: Run to verify they pass.** `make fe-test fe-lint fe-build`, `make test` and `make e2e` must all be green.

- [ ] **Step 5: Commit.** `git commit -m "feat(frontend): base-path builds for previews, first-visit copy, hosted seed sources"`

---

### Task 5: `infra/app`: data, compute and storage

**Files:**
- Create:
  - `infra/app/{terraform.tf,variables.tf,data.tf,storage.tf,queue.tf,lambdas.tf,iam.tf,schedule.tf,budget.tf,outputs.tf}`
  - `infra/app/envs/{staging,production}.tfvars`, `infra/app/envs/{staging,production}.s3.tfbackend`
  - `infra/app/tests/app.tftest.hcl`
  - `infra/app/README.md`
- Modify: `Makefile` adds `tf-check`, which runs `terraform fmt -check -recursive infra`, then `validate` and `test` in each root, with `-backend=false` init.

**Interfaces:**
- Consumes:
  - **Variables:**
    - `env`: validated to `staging` or `production`.
    - `image_digest`: `sha256:…`, validated.
    - `boundary_policy_arn`.
    - `ai_state_bucket`.
    - `budget_topic_arn`.
    - `password_hash_secret_arn`, which the owner creates once per env in Task 9.
  - **Remote state:** `infra/ai` outputs, read with `terraform_remote_state`.
- Produces outputs: `api_function_url`, `site_bucket`, `ops_function_name`, `cluster_arn`, `db_secret_arn`, `origin_secret_arn`, `api_role_arn`. Task 6 consumes these.

- [ ] **Step 1: Write the failing `terraform test`** (`mock_provider "aws"`):
  - **Aurora:**
    - The cluster is `aurora-postgresql` with `enable_http_endpoint = true`.
    - `serverlessv2_scaling_configuration` has `min_capacity = 0`, `max_capacity = 2` and `seconds_until_auto_pause = 300`.
    - `storage_encrypted = true`.
    - `deletion_protection` equals `var.env == "production"`.
    - `manage_master_user_password = true`.
    - No public accessibility.
  - **Lambdas:**
    - Every Lambda is `package_type = "Image"` with `architectures = ["arm64"]`.
    - `image_uri` ends with `@${var.image_digest}`.
    - The API Lambda has `reserved_concurrent_executions = 5`. The worker has 2.
    - The function URL has `invoke_mode = "RESPONSE_STREAM"` and `authorization_type = "NONE"`, and is guarded by the origin secret from Task 2.
    - The API env sets `AWS_LWA_INVOKE_MODE=response_stream`, `PHOEBE_DB_BACKEND=data_api`, `PHOEBE_BLOB_BACKEND=s3`, `PHOEBE_JOB_BACKEND=sqs`, `PHOEBE_SESSION_BACKEND=dynamodb`, `PHOEBE_LIMITS_BACKEND=dynamodb`, `PHOEBE_CONTROL_BACKEND=dynamodb`, `PHOEBE_EMBEDDER=titan`, `PHOEBE_ANSWER_BACKEND=harness`, `PHOEBE_REWRITER_BACKEND=bedrock` and `PHOEBE_CLIENT_IP_HEADER=cloudfront-viewer-address`. It also carries the guardrail id and version from `infra/ai`.
    - Secrets are passed as ARNs and read at startup, never as plain env values.
  - **IAM:**
    - Every `aws_iam_role` has `permissions_boundary = var.boundary_policy_arn`.
    - The API role may call Bedrock only on the Titan, Nova Micro and Haiku ARNs and the `infra/ai` harness and guardrail.
    - The API role gets `rds-data` and secret read only on its own cluster and secret.
  - **Storage:**
    - The S3 uploads bucket has every public-access block on, plus SSE.
    - The site bucket has every public-access block on and is reachable only through the CloudFront OAC (Task 6 adds the bucket policy).
    - DynamoDB tables `phoebe-${env}-sessions` and `phoebe-${env}-state` have TTL on `expires_at` and PAY_PER_REQUEST.
  - **Queue:** SQS has a DLQ with `maxReceiveCount = 3` and a visibility timeout of at least 6× the worker timeout.
  - **Schedule:** EventBridge Scheduler runs the sweeper `rate(1 hour)`.
  - **Budget:** the `infra/app` budget subscription attaches the env's budget Lambda to `var.budget_topic_arn`.

- [ ] **Step 2: Run to verify it fails.** Run `make tf-check`. Expect FAIL: the resources are missing.

- [ ] **Step 3: Implement.** Database credentials come from Aurora's managed master-user secret. Bedrock model ARNs follow `infra/ai/main.tf`'s pattern: the foundation-model ARNs in the three profile Regions plus the inference-profile ARNs. This is read-only invoke, not resource creation, which the spec allows.

- [ ] **Step 4: Run to verify it passes.** `make tf-check` must be green.

- [ ] **Step 5: Commit.** `git commit -m "feat(infra): app data, compute and storage per environment"`

---

### Task 6: `infra/app`: CloudFront edge, SPA router, security headers

**Files:**
- Create:
  - `infra/app/edge.tf`
  - `infra/app/functions/spa_router.js`
  - `infra/app/functions/spa_router.test.js`, run with `node --test`
  - Additions to `infra/app/tests/app.tftest.hcl`
- Modify: `Makefile` `tf-check` also runs `node --test infra/app/functions`.

**Interfaces:**
- Produces: output `site_url`, `https://<id>.cloudfront.net`. Task 8 smoke tests and the preview comment use it.

- [ ] **Step 1: Write the failing tests.**
  - **`spa_router.test.js`** (Review Focus 4), loading the function source into Node's `vm`:
    - `/` → `/index.html`.
    - `/employee` and `/admin/tasks` → `/index.html`.
    - `/assets/app.js` → unchanged.
    - `/pr-12/` → `/previews/pr-12/index.html`. `/pr-12/admin/tasks` → `/previews/pr-12/index.html`. `/pr-12/assets/x.js` → `/previews/pr-12/assets/x.js`.
    - `/seed-sources/benefits.html` → unchanged.
    - `/api/...` never reaches this function, because it isn't attached to that behaviour.
  - **`app.tftest.hcl` additions:**
    - The default behaviour (S3 origin with OAC) uses the viewer-request function `spa_router`.
    - The `/api/*` behaviour:
      - targets the function URL origin;
      - sends the custom origin header `X-Phoebe-Origin`;
      - uses the managed `CachingDisabled` cache policy;
      - uses the `AllViewerExceptHostHeader` origin request policy;
      - allows all methods;
      - sets `compress = false`, so SSE isn't buffered.
    - The response headers policy sets:
      - CSP `default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'`;
      - HSTS for 1 year;
      - `X-Content-Type-Options`;
      - `Referrer-Policy: strict-origin-when-cross-origin`.
    - `viewer_protocol_policy = "redirect-to-https"`.
    - `price_class = "PriceClass_100"`.
    - There are no `aliases` and no ACM certificate. The default certificate is used.
    - The site bucket policy allows `s3:GetObject` only to the CloudFront service principal, scoped to this distribution's ARN.

- [ ] **Step 2: Run to verify they fail.** **Step 3: Implement.** Check the CSP against the built app. If a real need appears, such as an inline style from a library, widen only that directive and note it in `infra/app/README.md`. **Step 4: Run to verify they pass.**

- [ ] **Step 5: Commit.** `git commit -m "feat(infra): CloudFront edge with SPA/preview router and security headers"`

---

### Task 7: `infra/bootstrap`: state, ECR, connection, CodeBuild, CodePipeline, boundary, budget

**Files:**
- Create:
  - `infra/bootstrap/{terraform.tf,variables.tf,state.tf,ecr.tf,boundary.tf,codebuild.tf,pipeline.tf,budget.tf,outputs.tf,README.md}`
  - `infra/bootstrap/tests/bootstrap.tftest.hcl`
- Modify:
  - `infra/ai/terraform.tf`: add an `s3` backend block with `use_lockfile = true` and key `ai.tfstate`. The local-state migration happens in Task 9.

**Interfaces:**
- Consumes:
  - **Variables:**
    - `github_repo`, default `ahochoy/phoebe-onboarding`.
    - `github_owner_id`, the owner's numeric GitHub user id. It is required and has no default.
    - `monthly_budget_usd`, default `20`.
- Produces:
  - **CodeBuild projects:**
    - `phoebe-pr`: events PULL_REQUEST_CREATED, UPDATED and REOPENED.
    - `phoebe-pr-cleanup`: events PULL_REQUEST_CLOSED and MERGED.
    - `phoebe-staging`: event PUSH to `^refs/heads/main$`.
  - **Pipeline:** `phoebe-release`, a CodePipeline V2.
    - A Source stage on CodeConnections with a git trigger for tags matching `v*`.
    - A `Plan` CodeBuild stage.
    - A `Approve` manual approval stage.
    - An `Apply` CodeBuild stage.
  - **Roles:**
    - `phoebe-ci-plan`: read-only plus state read.
    - `phoebe-ci-deploy-staging` and `phoebe-ci-deploy-production`, scoped per the Global Constraints.
  - **Policy:** `phoebe-boundary`.
  - **State bucket:** versioned, SSE, every public-access block on, TLS-only bucket policy.
  - **ECR repo:** `phoebe-api`, immutable tags, scan on push, lifecycle keeping the last 30 images.
  - **Budget:** one account budget at `monthly_budget_usd`, alerting at 80% actual to SNS topic `phoebe-budget` in us-east-2.

- [ ] **Step 1: Write the failing `terraform test`** (`mock_provider "aws"`):
  - **Webhooks** (Review Focus 5):
    - Every `aws_codebuild_webhook.filter_group` contains a filter `{type = "ACTOR_ACCOUNT_ID", pattern = "^${var.github_owner_id}$"}`.
    - The `phoebe-pr` webhook's groups include PULL_REQUEST events only.
    - The staging webhook has `PUSH` plus `HEAD_REF ^refs/heads/main$`.
  - **Pipeline:**
    - It has exactly the stages Source, Plan, Approve and Apply, in that order.
    - Approve is `category = "Approval"`.
    - The trigger includes tags `v*`.
  - **Project roles:**
    - `phoebe-pr` uses `phoebe-ci-plan`, which has no `*:Create*`, `*:Put*`, `*:Delete*` or `*:Update*` actions, except `s3:PutObject` and `s3:DeleteObject` on `arn:aws:s3:::phoebe-staging-site-*/previews/*` and CloudFront `CreateInvalidation` on the staging distribution.
    - The staging and production projects use their own deploy roles.
  - **Boundary:** the policy denies `iam:Create*`, `iam:Put*`, `iam:Attach*` and `iam:Delete*` unless the target matches `role/phoebe-*`. It also denies all actions where `aws:RequestedRegion` is not `us-east-2`, except the global services (CloudFront, IAM, STS, Budgets).
  - **Deploy roles:** they may create roles only with `iam:PermissionsBoundary` equal to the boundary ARN.
  - **Builds:**
    - All CodeBuild projects use `ARM_CONTAINER` with an `aws/codebuild/amazonlinux-aarch64-standard:*` image.
    - Privileged mode is on only where Docker builds run (`phoebe-staging`).
    - `concurrent_build_limit = 1` for the staging and release builds.

- [ ] **Step 2: Run to verify it fails.** **Step 3: Implement.**
  - **Connection.** The connection is created `PENDING` with `provider_type = "GitHub"`. `README.md` explains the owner's one-time console step: Developer Tools → Connections → Update pending connection.
  - **Buildspecs.** Each project points at its buildspec path in the repo (Task 8).

- [ ] **Step 4: Run to verify it passes.** `make tf-check` must be green.

- [ ] **Step 5: Commit.** `git commit -m "feat(infra): bootstrap state, ECR, CodeBuild, release pipeline, boundary"`

---

### Task 8: Buildspecs, deploy scripts and the GitHub Actions additions

**Files:**
- Create:
  - `ci/buildspec-pr.yml`, `ci/buildspec-pr-cleanup.yml`, `ci/buildspec-staging.yml`, `ci/buildspec-release-plan.yml`, `ci/buildspec-release-apply.yml`
  - `ci/deploy.sh`, `ci/smoke.sh`, `ci/tests/test_deploy_scripts.bats` (or a `pytest` driving the scripts with `PATH`-stubbed `aws`, `terraform` and `docker`)
  - `.github/workflows/preview-link.yml`
- Modify:
  - `.github/workflows/ci.yml`: add an `infra` job (`make tf-check`) and an `e2e` job.
  - `Makefile`: add `deploy-check`.

**Interfaces:**
- Consumes: Task 5/6 outputs and Task 7 project names.
- **`ci/deploy.sh <env> <image_digest>`:**
  1. `terraform init -backend-config=envs/<env>.s3.tfbackend`
  2. `terraform apply -auto-approve -var-file=envs/<env>.tfvars -var image_digest=…`, run in `infra/ai` (staging only), then in `infra/app`
  3. Invoke ops `migrate`
  4. Invoke ops `seed_if_empty`
  5. `npm ci && npm run build` (base `/`)
  6. `aws s3 sync dist/ s3://<site_bucket>/ --delete --exclude "previews/*" --exclude "seed-sources/*"`
  7. Sync `backend/seed/content/{benefits.html,project-manifest.txt}` to `seed-sources/`
  8. Create a CloudFront invalidation for `/*`
  9. Run `ci/smoke.sh <site_url>`
- **`ci/smoke.sh <site_url>`:** checks, in order:
  1. `/api/health` returns 200.
  2. `/` returns HTML containing the app's root element.
  3. A direct call to the function URL returns 403, since it isn't through CloudFront (Review Focus 3, live).
  4. `/pr-0/` doesn't 404 at the router level.
  It exits non-zero on any failure.
- **Staging buildspec:**
  1. `docker buildx build --platform linux/arm64 -f backend/Dockerfile .`
  2. Push `phoebe-api:<sha>`
  3. Read the pushed digest
  4. `ci/deploy.sh staging <digest>`
- **Release:**
  - Plan stage: resolves `phoebe-api:<tag commit sha>` to its digest (it fails if the image is missing, meaning the commit never reached staging), then runs `terraform plan` for production and saves the plan as an artifact.
  - Apply stage: applies **that saved plan**, then runs the production steps of `deploy.sh`.
- **PR buildspec:**
  - `terraform plan` for staging, read-only, with the summary printed to the logs.
  - `PHOEBE_BASE=/pr-$N/ npm run build`, then sync to `previews/pr-$N/` and invalidate `/pr-$N/*`.
- **Cleanup buildspec:** removes `previews/pr-$N/`.
- **`preview-link.yml`:** on `pull_request` (opened or synchronize), it posts or updates one PR comment: "Preview (deploys in a few minutes): `${{ vars.STAGING_SITE_URL }}/pr-<n>/`". It uses `GITHUB_TOKEN` with `pull-requests: write` only and makes no AWS calls. It skips forks.
- **`e2e` job in `ci.yml`:** runs on `ubuntu-24.04`. It starts `make stack-e2e` (Docker Compose is on the runner), installs the Playwright browsers with deps, and runs `make e2e`. On failure it uploads the Playwright report as an artifact.

- [ ] **Step 1: Write the failing tests.**
  - **Script tests** (stubbed binaries record their argv):
    - `deploy.sh staging sha256:abc` calls terraform with `-var image_digest=sha256:abc` and the staging backend config.
    - Ops is invoked with `migrate` before `seed_if_empty`.
    - The site sync excludes `previews/*` and `seed-sources/*`.
    - `smoke.sh` fails when health isn't 200 and when the direct function URL call isn't 403.
    - The release plan step fails with a clear message when the ECR image for the commit is missing.
  - **CI:** `actionlint` runs on the workflows (add it to `make lint` through a pinned binary or `npx`), and the new jobs are present.

- [ ] **Step 2: Run to verify they fail.** **Step 3: Implement.** **Step 4: Run to verify they pass.** `make deploy-check`, `make lint`, `make tf-check` and the full suites must be green. Push the branch and confirm the GitHub `infra` and `e2e` jobs pass. Pushing a feature branch is pre-authorised for this task; merging is not.

- [ ] **Step 5: Commit.** `git commit -m "feat(ci): CodeBuild buildspecs, deploy and smoke scripts, e2e and infra CI jobs"`

---

### Task 9: Owner-gated rollout (no code; every AWS write needs the owner's go-ahead)

**Files:** Modify `infra/bootstrap/README.md`, `infra/app/README.md` and the root `README.md` (deploy and runbook sections), and record the results.

- [ ] **Step 1: Read-only pre-flight.** Re-run the SCP simulation for every action the plans use, with `aws:RequestedRegion=us-east-2`. Confirm Aurora PostgreSQL's latest 16.x supports `min_capacity = 0` in us-east-2. Check whether idle AgentCore runtime sessions are billed (a Plan 2 carry-forward). Show the owner any denial or surprise before going on.
- [ ] **Step 2: Bootstrap.**
  1. Owner gate: show `terraform plan` for `infra/bootstrap` with its first-run local state, and get approval.
  2. Apply.
  3. `terraform init -migrate-state` to move the bootstrap state into its own bucket.
  4. The owner authorizes the `phoebe-github` connection in the console.
- [ ] **Step 3: Move `infra/ai` state to S3.** Owner gate: run `terraform init -migrate-state`, then `terraform plan`. The plan must show 0 changes.
- [ ] **Step 4: Per-environment secrets.** The owner creates the `phoebe-staging-password-hash` and `phoebe-production-password-hash` secrets, using `uv run python -m phoebe.auth <password>`. The password never enters this session.
- [ ] **Step 5: First staging deploy.**
  1. Owner gate: show the staging plan.
  2. Start the `phoebe-staging` CodeBuild build manually, at the branch head.
  3. Watch it. `smoke.sh` must pass.
  4. The owner checks the staging URL in a browser.
  5. Set the repo variable `STAGING_SITE_URL`.
- [ ] **Step 6: Preview check.** Open a throwaway PR, confirm the preview link renders and the `pr-cleanup` job deletes it on close.
- [ ] **Step 7: First release.** The owner publishes a `v0.1.0` release from the merged `main`, then approves the pipeline. `smoke.sh` must pass on production. The owner then sets up the `phoebe-onboarding.hochoy.dev` redirect outside AWS.
- [ ] **Step 8: Record and close.**
  - Record the URLs, timings and costs seen in `infra/app/README.md`.
  - Update `make pause` / `make kill` / `make open` to accept `ENV=staging|production`, using DynamoDB through the owner's local AWS session.
  - Write the reseed runbook: wipe sandboxes first, then call ops `seed_if_empty`, which only works on an empty seed.
