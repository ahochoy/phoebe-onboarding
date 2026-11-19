# infra/app

The Terraform root for one Phoebe environment, `staging` or `production`, in
`us-east-2`. Each env has its own state (`app/<env>.tfstate` in the bootstrap
state bucket) and its own inputs in `envs/<env>.tfvars`. For the architecture
and the release flow, see the [top-level README](../../README.md).

## What it creates

Every name starts with `phoebe-<env>`.

| File | Resources |
|---|---|
| `data.tf` | Aurora PostgreSQL Serverless v2, reached only through the Data API: 0 to 1 ACU, auto-pause after 300 s, encrypted, managed master secret. Production adds deletion protection, a final snapshot and 7-day backups. DynamoDB tables `-sessions` and `-state` (on demand, TTL on `expires_at`). Reads the `infra/ai` outputs. |
| `storage.tf` | Private S3 buckets `-uploads-<account_id>` (objects expire after 2 days) and `-site-<account_id>` (the SPA and staging's PR previews). |
| `queue.tf` | SQS `-jobs` and its dead-letter queue `-jobs-dlq` (3 receives, 14-day retention). |
| `lambdas.tf` | Six arm64 container Lambdas from the ECR repo `phoebe-api`, pinned by digest (below). The API has a streaming function URL. Also the origin secret `-origin-secret`. |
| `iam.tf` | One role per Lambda plus the scheduler role. Each has the bootstrap permissions boundary and only the actions its code uses. |
| `schedule.tf` | EventBridge Scheduler `-sweeper`, hourly. |
| `edge.tf` | CloudFront: the private site bucket through OAC (with the `spa-router` CloudFront Function), and `/api/*` to the function URL with no caching. Security headers (CSP, HSTS) on both. |
| `budget.tf` | Subscribes the budget Lambda to this env's bootstrap topic `phoebe-budget-<env>`, and lets the `-db-stopped` rule invoke it. |

### Lambdas

| Function | Image | Job |
|---|---|---|
| `api` | `api` | FastAPI behind the Lambda Web Adapter. CloudFront adds an `X-Phoebe-Origin` header; a direct call to the function URL gets 403 (except `/api/health`). |
| `worker` | `jobs` | Indexes uploaded documents from SQS. 120 s timeout, at most 2 at once. |
| `dlq` | `jobs` | Marks a job that failed three times as failed. |
| `sweeper` | `jobs` | Deletes expired visitor sandboxes and marks stuck indexing jobs as failed. |
| `ops` | `jobs` | Operator tasks: `migrate`, `seed_if_empty`, `status`, `reseed`. |
| `budget` | `jobs` | Pauses or closes the demo on a budget alert or a stopped database. |

Two images come from one `backend/Dockerfile`. The `api` target contains the
Lambda Web Adapter extension. The `jobs` target leaves it out, because Lambda
starts every extension and the adapter would hang a non-HTTP function.

The queue timings (worker 120 s, visibility 720 s, 3 receives, hourly sweep)
match `backend/src/phoebe/lambdas/timings.py`. Change both together.

### Configuration

The Lambdas get `PHOEBE_*` settings for the Data API, S3, SQS, DynamoDB, the
Titan embedder, the Bedrock query rewriter and the guardrail. Secrets arrive
only as ARNs (`PHOEBE_DB_SECRET_ARN`, `PHOEBE_ORIGIN_SECRET_ARN`,
`PHOEBE_PASSWORD_HASH_SECRET_ARN`) and are read at startup.

`answer_backend` picks how chat answers:

- `converse` (the default): `PHOEBE_ANSWER_BACKEND=converse`. The API streams
  Claude Haiku 4.5 (`us.anthropic.claude-haiku-4-5-20251001-v1:0`) through
  Bedrock ConverseStream.
- `harness`: the AgentCore harness in [`infra/ai`](../ai/README.md), with
  `answer_harness` = `haiku` or `nova`. It is kept for one release as a
  rollback and will then be removed.

The IAM role grants only the chosen backend's permissions.

### Idle cost

Aurora pauses at 0 ACU when nothing uses it. No Lambda touches the database at
startup, and `/api/health` and `/api/status` never do. The sweeper runs hourly
while there has been recent activity. After about 25 idle hours it stops
touching the database, apart from one sweep a day.

## Deploys

Deploys run only in CodeBuild. `ci/deploy.sh <env>` applies this root, runs ops
`migrate` then `seed_if_empty`, builds and uploads the SPA, invalidates
CloudFront and runs `ci/smoke.sh`. It never applies `infra/ai`.

- **Staging**: CodeBuild `phoebe-staging`, on each push to main. It builds both
  images, pushes them as `phoebe-api:<sha>` and `<sha>-jobs`, and deploys by
  digest.
- **Production**: CodePipeline `phoebe-release`, on a `v*` tag. Plan
  (`phoebe-release-plan`) promotes the digests staging already ran, then waits
  for manual approval. Apply (`phoebe-release-apply`) applies that saved plan
  and tags the images `release-<tag>`.

A plan by hand (read-only):

```sh
cd infra/app
terraform init -backend-config=envs/staging.s3.tfbackend \
  -backend-config=bucket=phoebe-tfstate-<account_id>
terraform plan -var-file=envs/staging.tfvars \
  -var api_image_digest=sha256:... -var jobs_image_digest=sha256:...
```

### Release notes for production

- **Failed apply.** Don't retry Apply: the saved plan is stale. Push another
  `v*` tag on the same commit (for example `v1.2.3.1`; the plan stage takes
  the highest by `sort -V`). Don't use "Release change" in the console, which
  builds main's HEAD.
- **Migrations must be backward compatible.** The new code is live before
  `migrate` runs. Add columns or tables in one release and remove old ones in
  a later one.

## Operations

**Reseed after a seed-data change.** Deploys run only `seed_if_empty`, which
does nothing when a seed is already loaded. To load a changed seed, invoke the
env's ops Lambda by hand, once per environment:

```sh
aws lambda invoke --function-name phoebe-<env>-ops \
  --payload '{"task":"reseed"}' --cli-binary-format raw-in-base64-out out.json
```

`reseed` deletes every visitor sandbox (rows and uploaded files), then reloads
the seed. Run it when nobody is using the demo; re-running is safe.

**Stop and start the database.** The project's spend limit can stop Aurora.
A stopped cluster is not the same as a paused one, and deploys refuse to run
against it.

- `make db-stop ENV=<env>` closes the demo, then stops the cluster (useful for
  parking staging).
- `make db-start ENV=<env>` starts the cluster, waits for it, and reopens the
  demo with chat paused. Add `OPEN=1` to switch chat back on.

At 70% of the monthly budget, the budget Lambda pauses chat (browsing still
works). If the cluster stops, it closes the demo. Both are set up in
[`infra/bootstrap`](../bootstrap/README.md).

## Checks

- `make tf-check`: `terraform fmt`, `validate` and `test` for every root, plus
  `node --test` for the CloudFront router. `tests/app.tftest.hcl` uses a mocked
  AWS provider, so it makes no AWS calls.
- `make deploy-check`: runs the `ci/` scripts against stubbed `aws`,
  `terraform`, `docker`, `npm` and `curl`.
