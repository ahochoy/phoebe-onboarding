# infra/app

Per-environment Terraform root for Phoebe (`staging`, `production`), all in
`us-east-2`. One state per env (`app/<env>.tfstate` in the bootstrap state
bucket). CodeBuild applies it (Task 8); nothing here has been applied yet.

## What it creates

All names start with `phoebe-<env>`.

| File | Resources |
|---|---|
| `data.tf` | Aurora PostgreSQL Serverless v2 cluster `phoebe-<env>` (0–2 ACU, auto-pause 300 s, Data API on, encrypted, managed master-user secret, no public access; deletion protection and a final snapshot in production only). DynamoDB `phoebe-<env>-sessions` and `phoebe-<env>-state` (on demand, `pk` hash key, TTL on `expires_at`). `infra/ai` remote state. |
| `storage.tf` | S3 `phoebe-<env>-uploads-<account_id>` (all public-access blocks, SSE-S3, objects expire after 2 days) and `phoebe-<env>-site-<account_id>` (all public-access blocks, SSE-S3; Task 6 adds the CloudFront OAC bucket policy). |
| `queue.tf` | SQS `phoebe-<env>-jobs` (visibility 720 s) with DLQ `phoebe-<env>-jobs-dlq` (maxReceiveCount 3, 14-day retention). Event source mappings for the worker and the DLQ handler, both `ReportBatchItemFailures`. |
| `lambdas.tf` | Six arm64 image Lambdas, all from ECR repo `phoebe-api` pinned by digest. `api` runs the `api` image (image CMD: uvicorn behind the Lambda Web Adapter; response-streaming function URL with auth NONE; reserved concurrency 5). `worker` (120 s, reserved 2), `dlq`, `sweeper`, `ops` and `budget` run the `jobs` image (ENTRYPOINT `python -m awslambdaric`, command `phoebe.lambdas.<name>.handler`). Log groups with retention. The origin secret `phoebe-<env>-origin-secret`. |
| `iam.tf` | One role per Lambda plus the scheduler role, each with the bootstrap permissions boundary and only the actions its code uses. |
| `schedule.tf` | EventBridge Scheduler `phoebe-<env>-sweeper`, `rate(1 hour)`. |
| `budget.tf` | Subscribes this env's budget Lambda to the bootstrap `phoebe-budget` topic. |

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
| `boundary_policy_arn` | `arn:aws:iam::<account_id>:policy/phoebe-boundary` (bootstrap). |
| `ai_state_bucket` | `phoebe-tfstate-<account_id>`; the `infra/ai` state is read from key `ai.tfstate`. |
| `budget_topic_arn` | `arn:aws:sns:us-east-2:<account_id>:phoebe-budget` (bootstrap). |
| `password_hash_secret_arn` | This env's `phoebe-<env>-password-hash` secret, created by the owner (Task 9). Must be the full ARN, including the 6-character random suffix; another env's secret is rejected. |
| `answer_harness` | `haiku` (default) or `nova`. Use `nova` until the account's Anthropic use-case form is approved (see `infra/ai/README.md`). |
| `log_level` | Default `INFO`. |

## Outputs

`api_function_url`, `site_bucket`, `ops_function_name`, `cluster_arn`,
`db_secret_arn`, `origin_secret_arn`, `api_role_arn`.

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

## Offline checks

`make tf-check` runs `terraform fmt -check -recursive infra`, then for each
root `init -backend=false`, `validate` and `test`. `tests/app.tftest.hcl` uses
`mock_provider "aws"` with overridden ARNs, so it makes no AWS calls.
