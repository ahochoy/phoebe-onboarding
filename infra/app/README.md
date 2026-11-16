# infra/app

Per-environment Terraform root for Phoebe (`staging`, `production`), all in
`us-east-2`. One state per env (`app/<env>.tfstate` in the bootstrap state
bucket). CodeBuild applies it (Task 8); nothing here has been applied yet.

## What it creates

All names start with `phoebe-<env>`.

| File | Resources |
|---|---|
| `data.tf` | Aurora PostgreSQL Serverless v2 cluster `phoebe-<env>` (0–2 ACU, auto-pause 300 s, Data API on, encrypted, managed master-user secret, no public access; deletion protection and a final snapshot in production only). DynamoDB `phoebe-<env>-sessions` and `phoebe-<env>-state` (on demand, `pk` hash key, TTL on `expires_at`). `infra/ai` remote state. |
| `storage.tf` | S3 `phoebe-<env>-uploads-<account_id>` (all public-access blocks, SSE-S3, objects expire after 2 days) and `phoebe-<env>-site-<account_id>` (all public-access blocks, SSE-S3; bucket policy in `edge.tf`). |
| `queue.tf` | SQS `phoebe-<env>-jobs` (visibility 720 s) with DLQ `phoebe-<env>-jobs-dlq` (maxReceiveCount 3, 14-day retention). Event source mappings for the worker and the DLQ handler, both `ReportBatchItemFailures`. |
| `lambdas.tf` | Six arm64 image Lambdas, all from ECR repo `phoebe-api` pinned by digest. `api` runs the `api` image (image CMD: uvicorn behind the Lambda Web Adapter; response-streaming function URL with auth NONE; reserved concurrency `api_reserved_concurrency`, default 5). `worker` (120 s, reserved `worker_reserved_concurrency`, default 2), `dlq`, `sweeper`, `ops` and `budget` run the `jobs` image (ENTRYPOINT `python -m awslambdaric`, command `phoebe.lambdas.<name>.handler`). Log groups with retention. The origin secret `phoebe-<env>-origin-secret`. |
| `iam.tf` | One role per Lambda plus the scheduler role, each with the bootstrap permissions boundary and only the actions its code uses. The sweeper's state-table grant is `GetItem`/`PutItem` on the keys `activity#last` and `sweep#last_complete` only (`dynamodb:LeadingKeys`). |
| `schedule.tf` | EventBridge Scheduler `phoebe-<env>-sweeper`, `rate(1 hour)`. The sweeper skips all database work while the site is idle (ruling R20, below), so the hourly run does not wake a paused Aurora. |
| `edge.tf` | CloudFront distribution (default `*.cloudfront.net` certificate, `PriceClass_100`, no aliases/ACM/logging). Default behaviour: private site bucket via OAC, managed `CachingOptimized`, CloudFront Function `phoebe-<env>-spa-router` (viewer-request). `/api/*`: API function URL origin sending `X-Phoebe-Origin` (the origin secret), managed `CachingDisabled` and `AllViewerExceptHostHeader`, all methods, `compress = false` (SSE). Response headers policy (CSP, HSTS 1 year, nosniff, strict-origin-when-cross-origin) on both. Site bucket policy: `s3:GetObject` to `cloudfront.amazonaws.com` scoped to this distribution's ARN. |
| `budget.tf` | Subscribes this env's budget Lambda to its own bootstrap topic `phoebe-budget-<env>` (ruling R16: a staging deploy can't touch production's subscription). |

Timings match `backend/src/phoebe/lambdas/timings.py` (ruling R8): worker
timeout 120 s, visibility 720 s (6x), maxReceiveCount 3, hourly sweep. Change
them in both places together.

Secrets reach the Lambdas only as ARNs (`PHOEBE_DB_SECRET_ARN`,
`PHOEBE_ORIGIN_SECRET_ARN`, `PHOEBE_PASSWORD_HASH_SECRET_ARN`); the app reads
them once at startup. The origin secret's value is generated here
(`random_password.origin`) and is in state, because Task 6's CloudFront origin
header needs it.

Idle cost (spec §5.4, rulings R20/R21). Nothing at Lambda init touches the
database: the API checks the embedder lazily on its first DB-using request
(`503 database_unavailable` while Aurora resumes, `503 embedder_mismatch` if the
stored vectors came from another embedder), `/api/health` and `/api/status` are
DB-free, and the jobs Lambdas don't check at all (ops `seed_if_empty` does). The
API writes `activity#last` (epoch seconds, at most once a minute per container)
to the state table on login and on sandbox use; the sweeper writes
`sweep#last_complete` after a DB sweep and skips the sweep and stale-doc check
while `activity#last < sweep#last_complete`. If the state table can't be read,
it sweeps. The cost: a sandbox that expires during an idle stretch is removed
at the next sweep after new activity (its session has already ended).

## Inputs

| Variable | Notes |
|---|---|
| `env` | `staging` or `production`. |
| `api_image_digest` | `sha256:<64 hex>` of the `api` image (`backend/Dockerfile --target api`, tag `<sha>`). Passed per deploy; tags are rejected. |
| `jobs_image_digest` | `sha256:<64 hex>` of the `jobs` image (`--target jobs`, tag `<sha>-jobs`). Passed per deploy; tags are rejected. |
| `boundary_policy_arn` | `arn:aws:iam::<account_id>:policy/phoebe-boundary-<env>` (bootstrap; this env's boundary, which only allows `phoebe-<env>-*` resources). Another env's boundary is rejected. |
| `ai_state_bucket` | `phoebe-tfstate-<account_id>`; the `infra/ai` state is read from key `ai.tfstate`. |
| `budget_topic_arn` | `arn:aws:sns:us-east-2:<account_id>:phoebe-budget-<env>` (bootstrap; another env's topic is rejected). |
| `password_hash_secret_arn` | This env's `phoebe-<env>-password-hash` secret, created by the owner (Task 9). Must be the full ARN, including the 6-character random suffix; another env's secret is rejected. |
| `answer_harness` | `haiku` (default) or `nova`. Use `nova` until the account's Anthropic use-case form is approved (see `infra/ai/README.md`). |
| `api_reserved_concurrency` | Default `5`; `null` = unreserved. Ruling R23: reserved concurrency counts against the account's Lambda concurrency quota (a new account can be as low as 10, and AWS always keeps 10 unreserved). Task 9 checks the quota; the owner requests an increase or sets `null`. `0` is rejected. |
| `worker_reserved_concurrency` | Default `2`; `null` = unreserved (the SQS mapping's `maximum_concurrency = 2` still caps it). `0` is rejected. |
| `log_level` | Default `INFO`. |

## Outputs

`site_url`, `api_function_url`, `site_bucket`, `ops_function_name`, `distribution_id`,
`cluster_arn`, `db_secret_arn`, `origin_secret_arn`, `api_role_arn`. `ci/deploy.sh`
reads the first five after its apply. Staging's `distribution_id` is also the value
for infra/bootstrap's `staging_distribution_id` (bootstrap owner step 7).

## Per-env usage

`envs/<env>.s3.tfbackend` holds the backend key, Region and `use_lockfile`.
`envs/<env>.tfvars` holds the env's inputs. The account-specific lines (state
bucket, boundary, topic, password secret) are commented placeholders until
bootstrap exists; Task 9 fills them in. They are ARNs and names, not secrets.

```sh
cd infra/app
terraform init -backend-config=envs/staging.s3.tfbackend \
  -backend-config=bucket=phoebe-tfstate-<account_id>
terraform plan -var-file=envs/staging.tfvars \
  -var api_image_digest=sha256:... -var jobs_image_digest=sha256:...
```

Why two images (ruling R9): Lambda starts every extension in
`/opt/extensions`. In the `api` image that is the Lambda Web Adapter, which
waits for uvicorn on :8080 and then polls the Runtime API itself. In a
non-HTTP Lambda it would hang init and compete with `awslambdaric`, so the
`jobs` image leaves the adapter (and its `AWS_LWA_*` env) out.

Applies run only in CodeBuild (Task 8) or under the Task 9 owner gate.

## Deploys (ci/)

| CodeBuild project | Buildspec | Script | What it does |
|---|---|---|---|
| `phoebe-staging` (push to main) | `ci/buildspec-staging.yml` | `ci/staging.sh` | `docker buildx build --platform linux/arm64 --target api\|jobs -f backend/Dockerfile .`, pushed as `phoebe-api:<sha>` and `<sha>-jobs` (a retried build reuses already-pushed tags), digests read back from ECR, then `ci/deploy.sh staging <api> <jobs>`. |
| `phoebe-release-plan` (tag `v*`) | `ci/buildspec-release-plan.yml` | `ci/release-plan.sh` | Resolves `phoebe-api:<tag sha>` and `<tag sha>-jobs`; stops with "never reached staging" if either is missing. Reads the commit's `v*` tag with `git tag --points-at` in the `CODEBUILD_CLONE_REF` clone (R17; highest by `sort -V` if several, none stops the release). `terraform plan -lock=false` for production; saves `production.tfplan` and `release.env` (commit, tag, both digests) as the `plan` artifact. |
| `phoebe-release-apply` (after approval) | `ci/buildspec-release-apply.yml` | `ci/release-apply.sh` | Checks `release-<tag>` / `release-<tag>-jobs`: an existing tag must already point at the promoted digest, or the release stops before any change. Runs `ci/deploy.sh production` on **the saved plan** (no re-plan), then adds the missing release tags (BatchGetImage + PutImage). |

`ci/deploy.sh <env> <api_digest> <jobs_digest>`: `terraform init`/`apply` here
(staging with the two `-var`s; production applies `$PHOEBE_PLAN_FILE`), ops
`migrate` then `seed_if_empty` (stops on a function error or an `error`
result), `npm ci` + `npm run build` with base `/`, the site sync below, the two
seed sources to `seed-sources/`, an invalidation of `/*` (waited for), then
`ci/smoke.sh <site_url> <api_function_url>`. It never applies `infra/ai` (R12).

`ci/smoke.sh` checks, through CloudFront: `/api/health` is 200 `{"status":"ok"}`;
`/` is the SPA (root element); `/api/status` is 200 JSON; a direct call to the
function URL's `/api/status` is **403** (`/api/health` is exempt from the origin
guard, so it can't prove this); `/pr-0/` is not a 404/5xx. The
`CloudFront-Viewer-Address` check is reported as skipped: the API has no echo
endpoint (deliberately), so Task 9 checks it, and the throttle, by hand.

### Task 9 live checks

Run by hand against staging after the first owner-gated deploy (none of these
can be checked offline):

1. **Concurrency quota (R23).** Read the account's Lambda concurrent-executions
   quota. With 5 + 2 reserved, at least 17 is needed; otherwise request an
   increase or set `api_reserved_concurrency` / `worker_reserved_concurrency`
   to `null`.
2. **Deploy-role permissions (R24).** Simulate (or watch the first apply for)
   `lambda:CreateEventSourceMapping` and the RDS default-VPC `ec2:Describe*`
   calls as `phoebe-ci-deploy-staging`; simulate the rest of the apply.
3. **First migrate.** ops `migrate` succeeds on the Data API (the advisory lock
   now returns an int, not `void`).
4. **Large non-ASCII document.** Upload a ~100 KB Markdown file that is mostly
   multi-byte text (e.g. CJK or emoji), wait for `indexed`, open it, and check
   the full text renders intact (it is read in 15,000-character slices, each
   under the Data API's 64 KB row limit).
5. **Near-limit upload.** Upload a file just under 5 MB; it is accepted and
   indexes (or fails with a clear reason), and a file just over is `413
   file_too_large`.
6. **Client IP and throttle.** `CloudFront-Viewer-Address` reaches the API
   (IPv4 and, if available, IPv6) and the login throttle keys per viewer.
7. **Idle stays idle (R20).** With no visits for over an hour, the sweeper logs
   `sweep skipped idle` and the Aurora cluster stays paused (0 ACU); a login
   then makes the next hourly run sweep.
8. **Cold start while paused (R21).** With Aurora paused, the first page load
   shows the "waking up" copy (`503 database_unavailable`) rather than a 502,
   and `/api/health` stays 200 without resuming the cluster.

### Release behaviour to know (production)

- **Partial deploy recovery: re-run the pipeline from Plan.** If
  `phoebe-release-apply` fails after the apply started (a migration, the seed,
  the SPA sync or the smoke test), do not retry Apply: the saved plan is stale
  against the changed state, and Terraform refuses it. Start a new execution
  for the same commit so that Plan re-plans from the current state and the
  owner approves again. Push another `v*` tag on that commit, e.g.
  `v1.2.3.1`; release-plan takes the highest by `sort -V`. Don't use "Release
  change" in the console, because it runs Source at main's HEAD, which may be
  a different commit. Release tags are only added after a successful deploy,
  so a failed run leaves none behind.
- **Migrations must be expand/contract compatible.** `terraform apply` updates
  the Lambda code (new image digests) *before* ops `migrate` runs, so for a
  short window the new code runs against the old schema (and, if migrate
  fails, until the next release). Ship schema changes in two releases: first
  add (new columns/tables, nullable or defaulted) with code that works with
  both schemas, then remove the old shape once nothing reads it.
- **The SPA is rebuilt at the tag commit; images are promoted by digest.** The
  backend images in production are the exact bytes staging ran (resolved from
  `phoebe-api:<sha>` and `<sha>-jobs`). The frontend is not promoted: Apply runs
  `npm ci` + `npm run build` from the tag's checkout, so it is the same source
  as staging's build but a fresh build (`package-lock.json` pins dependencies).

`make deploy-check` runs these scripts offline against stubbed `aws`,
`terraform`, `docker`, `npm` and `curl` (`ci/tests/`).

### Site caching contract (R11)

| Path in the site bucket | `Cache-Control` | Why |
|---|---|---|
| `assets/*` (Vite output, content-hashed names) | `public, max-age=31536000, immutable` | A changed file gets a new name, so a cached copy is never stale. |
| `index.html`, `favicon.svg` and other root files | `no-cache` | Browsers and CloudFront revalidate on every request, so a deploy is visible at once and always points at assets that exist. |
| `seed-sources/*` | `no-cache` | Fetched by the seed loader; small. |
| `previews/pr-<n>/*` | written by the inline `phoebe-pr` buildspec (infra/bootstrap) | Never touched by `deploy.sh`'s sync. |

Order: `assets/` is uploaded first, then the root files, then a `--delete
--size-only` pass prunes stale files (excluding `previews/*` and
`seed-sources/*`; size-only so it never re-uploads a file without its header).
Then `/*` is invalidated. CloudFront's `CachingOptimized` policy honours these
headers (its max TTL is a year).

## Edge notes

- `functions/spa_router.js` (cloudfront-js-2.0, no dependencies): `/` and
  extensionless paths go to `/index.html`; files with an extension and
  `/seed-sources/...` pass through; `/pr-<n>/...` is served from
  `previews/pr-<n>/` in the site bucket (SPA fallback inside the prefix).
  It is attached to the S3 behaviour only. Preview builds must use Vite
  `base=/pr-<n>/`, because the built app references `/assets/...` absolutely.
- CSP check against `frontend/dist`: one external module script and one CSS
  file, self-hosted woff2 fonts via `url(/assets/...)`, no inline scripts, no
  `eval`, no external origins, so the CSP needed no widening. `style-src` keeps
  `'unsafe-inline'` for inline `style` attributes set by Radix/assistant-ui.
- The origin secret value is also in the distribution's origin config (and state).
- No custom error responses: they are distribution-wide and would rewrite
  `/api/*` 403s. Missing assets return S3's 403.
- `AllViewerExceptHostHeader` is documented to add the CloudFront viewer
  headers; Task 8's smoke test should confirm `CloudFront-Viewer-Address`
  reaches the API (it drives the client IP).

## Offline checks

`make tf-check` runs `terraform fmt -check -recursive infra`, then for each
root `init -backend=false`, `validate` and `test`, then `node --test` on the router
(`functions/*.test.js`). `tests/app.tftest.hcl` uses
`mock_provider "aws"` with overridden ARNs, so it makes no AWS calls.
