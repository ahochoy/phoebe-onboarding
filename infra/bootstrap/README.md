# infra/bootstrap

The delivery machinery for Phoebe, all in `us-east-2` (IAM, CloudFront
invalidations and Budgets are global). The owner applies this root locally,
once, with their own session. Nothing in CI can change it: no CI role can read
or write `bootstrap.tfstate`, and the boundary forbids bounded roles from
touching the `phoebe-ci-*` roles. Nothing here has been applied yet (Task 9).

## What it creates

| File | Resources |
|---|---|
| `state.tf` | S3 `phoebe-tfstate-<account_id>` (versioned, SSE-S3, every public-access block, BucketOwnerEnforced, TLS-only policy, noncurrent versions expire after 90 days, `prevent_destroy`). Holds `bootstrap.tfstate`, `ai.tfstate`, `app/staging.tfstate`, `app/production.tfstate`. S3 `phoebe-pipeline-artifacts-<account_id>` (same hardening, objects expire after 14 days) for the release pipeline's source zip and saved production plan. |
| `ecr.tf` | ECR `phoebe-api`: immutable tags, scan on push, lifecycle keeps the last 60 images (30 commits × `<sha>` api + `<sha>-jobs`, ruling R9). Repo policy lets `lambda.amazonaws.com` pull for `function:phoebe-*`. |
| `codebuild.tf` | CodeConnections `phoebe-github` (GitHub, created `PENDING`). CodeBuild projects, all `ARM_CONTAINER` on `aws/codebuild/amazonlinux-aarch64-standard:3.0`, each logging to a pre-created `/aws/codebuild/<project>` group (30 days). Webhooks, once `github_connection_ready = true`. |
| `pipeline.tf` | CodePipeline V2 `phoebe-release`: Source (CodeConnections, trigger on pushed tags `v*`) → Plan (`phoebe-release-plan`) → Approve (manual) → Apply (`phoebe-release-apply`, on the saved plan). `QUEUED` execution mode. |
| `roles.tf` | `phoebe-ci-plan`, `phoebe-ci-deploy-staging`, `phoebe-ci-deploy-production`, `phoebe-ci-pipeline`, each with the boundary and one inline policy. Trust is scoped by `aws:SourceAccount` and, for CodeBuild, the project ARNs. |
| `boundary.tf` | Managed policy `phoebe-boundary` (below). |
| `budget.tf` | SNS `phoebe-budget` (us-east-2; topic policy lets `budgets.amazonaws.com` publish, scoped by `aws:SourceAccount` and `arn:aws:budgets::<account_id>:*`). Monthly account cost budget `phoebe-monthly` at `monthly_budget_usd`, alerting at 80% ACTUAL to the topic. `aws_budgets_budget` has no `region`; the provider reaches the global Budgets API from the us-east-2 provider, so there is no us-east-1 provider. |

### CodeBuild projects

| Project | Role | Trigger (every group also requires `ACTOR_ACCOUNT_ID ^<github_owner_id>$`) | Buildspec | Notes |
|---|---|---|---|---|
| `phoebe-pr` | `phoebe-ci-plan` | `PULL_REQUEST_CREATED, UPDATED, REOPENED` into `main` | `ci/buildspec-pr.yml` | Fork PRs also need a maintainer approval comment. |
| `phoebe-pr-cleanup` | `phoebe-ci-plan` | `PULL_REQUEST_CLOSED, MERGED` into `main` | `ci/buildspec-pr-cleanup.yml` | |
| `phoebe-staging` | `phoebe-ci-deploy-staging` | `PUSH`, `HEAD_REF ^refs/heads/main$` | `ci/buildspec-staging.yml` | Privileged (the only Docker build); one build at a time. |
| `phoebe-release-plan` | `phoebe-ci-deploy-production` | pipeline Plan stage | `ci/buildspec-release-plan.yml` | Not privileged (promotes by digest); one at a time. |
| `phoebe-release-apply` | `phoebe-ci-deploy-production` | pipeline Apply stage | `ci/buildspec-release-apply.yml` | Not privileged; one at a time. |

The actor filter is Review Focus 5: a PR from a fork has the fork author as its
actor, so it matches no filter group and no build (and so no CI role) ever sees
untrusted code. `tests/bootstrap.tftest.hcl` asserts it on every group.

### Contract for the buildspecs (Task 8)

- PR number: `CODEBUILD_WEBHOOK_TRIGGER` is `pr/<n>`.
- `phoebe-ci-plan` cannot write state, so the PR build's `terraform plan` must
  run with `-lock=false`. It may write only `previews/*` in
  `phoebe-staging-site-<account_id>` and invalidate the distribution tagged
  `env=staging`.
- Release actions get `RELEASE_COMMIT` (`#{SourceVariables.CommitId}`, the tag's
  commit). Plan must emit the saved plan as its output artifact (`plan`);
  Apply receives `source` (primary) and `plan` (secondary,
  `CODEBUILD_SRC_DIR_plan`).
- The staging build re-applies `infra/ai`, but `phoebe-ci-deploy-staging` can
  only read infra/ai's resources: its harness role
  (`PhoebeAgentCoreHarnessExecutionRole`) is not `phoebe-*` and has no
  boundary, so the boundary forbids changing it. A no-op apply passes; a real
  infra/ai change is applied by the owner locally.

### The boundary (`phoebe-boundary`)

On every CI role and every role `infra/app` creates. It:

- allows only the services Phoebe uses (Bedrock, AgentCore, CloudFront,
  CodeBuild, CodeConnections, DynamoDB, ECR, IAM, KMS, Lambda, Logs, RDS, RDS
  Data, S3, Scheduler, Secrets Manager, SNS, SQS, STS);
- denies every action outside `us-east-2` except CloudFront, IAM, STS and
  Budgets. The one carve-out is Bedrock routing a `us.` inference profile called
  in us-east-2 to the model in another US Region (the evaluation that carries
  `bedrock:InferenceProfileArn`); the call itself still has to be in us-east-2;
- denies `organizations:*` and `account:*`;
- denies every IAM write (`Create*`, `Put*`, `Attach*`, `Delete*`, `Update*`,
  `Tag*`, `PassRole`, ...) unless the target is `role/phoebe-*` (or the RDS
  service-linked role, which RDS needs for the first cluster);
- denies those writes on `role/phoebe-ci-*` outright (no self-escalation);
- denies creating, or changing the policies of, a role whose boundary is not
  `phoebe-boundary`, and denies removing a boundary;
- denies `sts:AssumeRole` (no role hopping);
- denies the state and artifact buckets to anything that is not a
  `phoebe-ci-*` role (plans carry secrets).

### Wildcards that could not be avoided

- Metadata reads (`rds:Describe*`, `lambda:List*`, `cloudfront:Get*`, ...) on
  `*`: most are not resource-scopable. No data-plane reads are in that set.
- CloudFront distributions (`distribution/*`): the id is unknown at bootstrap
  time. Writes and invalidations require `aws:ResourceTag/env` = the role's env
  (infra/app's `default_tags`); creation uses `IfExists` because the tag does
  not exist yet.
- CloudFront OAC and response-headers policies (`origin-access-control/*`,
  `response-headers-policy/*`): id-only ARNs with no tag condition keys.
- Event source mappings (`event-source-mapping:*`), scoped by
  `lambda:FunctionArn` to the env's functions.
- RDS defaults (`cluster-pg:default.*`, `pg:default.*`, `og:default:*`,
  `subgrp:default`): CreateDBCluster authorizes on them.
- The RDS-managed master secret (`secret:rds!cluster-*`): its name is a uuid.
- `kms:DescribeKey`/`kms:CreateGrant` on `*`, only `kms:ViaService` RDS or
  Secrets Manager (AWS managed keys).
- `ecr:GetAuthorizationToken` on `*` (staging only; the API has no resource).
- S3 bucket configuration as `s3:PutBucket*`/`s3:GetBucket*`, limited to
  `phoebe-<env>-*-<account_id>`.

## Inputs

| Variable | Notes |
|---|---|
| `github_owner_id` | Required, no default. The owner's numeric GitHub user id (public; `terraform.tfvars` holds it). |
| `github_repo` | Default `ahochoy/phoebe-onboarding`. |
| `github_connection_ready` | Default `false`. Set `true` once the connection is authorized; CodeBuild can only create webhooks through an `AVAILABLE` connection. |
| `monthly_budget_usd` | Default `20`. |

## Outputs

`state_bucket`, `boundary_policy_arn`, `budget_topic_arn`, `ecr_repository_url`,
`connection_arn`, `connection_status`, `codebuild_projects`, `pipeline_name`,
`ci_role_arns`. The first three feed `infra/app/envs/<env>.tfvars`.

## One-time owner steps (Task 9 runs these; every apply follows a shown plan)

1. **First apply with local state.** The state bucket does not exist yet, so
   override the backend with an uncommitted file (`*_override.tf` is
   gitignored):

   ```sh
   cd infra/bootstrap
   printf 'terraform {\n  backend "local" {}\n}\n' > local_override.tf
   terraform init
   terraform plan -out=bootstrap.plan   # owner reviews
   terraform apply bootstrap.plan
   ```

2. **Move the state into its own bucket.**

   ```sh
   rm local_override.tf bootstrap.plan
   terraform init -migrate-state \
     -backend-config=bucket=phoebe-tfstate-<account_id>
   terraform plan   # must show no changes
   rm terraform.tfstate terraform.tfstate.backup   # only after the plan is clean
   ```

3. **Authorize the GitHub connection.** In the AWS console: Developer Tools →
   Settings → Connections → `phoebe-github` → **Update pending connection**.
   Install or choose the AWS Connector for GitHub app, limited to this
   repository, and finish. The status becomes `Available`.

4. **Create the webhooks.** Set `github_connection_ready = true` in
   `terraform.tfvars`, then plan (three `aws_codebuild_webhook` additions only)
   and apply. Commit the tfvars change.

5. **Move `infra/ai` state** (`infra/ai/terraform.tf` now declares the `s3`
   backend, key `ai.tfstate`):

   ```sh
   cd infra/ai
   terraform init -migrate-state -backend-config=bucket=phoebe-tfstate-<account_id>
   terraform plan   # must show no changes
   ```

6. Fill `infra/app/envs/<env>.tfvars` and `<env>.s3.tfbackend` with the
   outputs above.

Budget alerts reach the per-env budget Lambdas only. To also get an email, the
owner subscribes an address to `phoebe-budget` in the console; it is not
recorded here.

## Offline checks

`make tf-check` runs `init -backend=false`, `validate` and `test` here as well.
`tests/bootstrap.tftest.hcl` uses `mock_provider "aws"`, so it makes no AWS
calls.
