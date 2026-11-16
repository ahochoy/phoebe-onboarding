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
| `lambdas.tf` | Six arm64 image Lambdas, all from ECR repo `phoebe-api` pinned by digest. `api` runs the `api` image (image CMD: uvicorn behind the Lambda Web Adapter; response-streaming function URL with auth NONE; reserved concurrency 5). `worker` (120 s, reserved 2), `dlq`, `sweeper`, `ops` and `budget` run the `jobs` image (ENTRYPOINT `python -m awslambdaric`, command `phoebe.lambdas.<name>.handler`). Log groups with retention. The origin secret `phoebe-<env>-origin-secret`. |
| `iam.tf` | One role per Lambda plus the scheduler role, each with the bootstrap permissions boundary and only the actions its code uses. |
| `schedule.tf` | EventBridge Scheduler `phoebe-<env>-sweeper`, `rate(1 hour)`. |
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
| `phoebe-release-plan` (tag `v*`) | `ci/buildspec-release-plan.yml` | `ci/release-plan.sh` | Resolves `phoebe-api:<tag sha>` and `<tag sha>-jobs`; stops with "never reached staging" if either is missing. Finds the commit's single `v*` tag (GitHub public API). `terraform plan -lock=false` for production; saves `production.tfplan` and `release.env` (commit, tag, both digests) as the `plan` artifact. |
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
