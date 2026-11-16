# infra/bootstrap

The delivery machinery for Phoebe, all in `us-east-2` (IAM, CloudFront
invalidations and Budgets are global). The owner applies this root locally,
once, with their own session. Nothing in CI can change it: no CI role can read
or write `bootstrap.tfstate`, and the CI boundary forbids CI roles from
touching the `phoebe-ci-*` roles. Nothing here has been applied yet (Task 9).

## What it creates

| File | Resources |
|---|---|
| `state.tf` | S3 `phoebe-tfstate-<account_id>` (versioned, SSE-S3, every public-access block, BucketOwnerEnforced, TLS-only policy, noncurrent versions expire after 90 days, `prevent_destroy`). It holds `bootstrap.tfstate`, `ai.tfstate`, `app/staging.tfstate` and `app/production.tfstate`. S3 `phoebe-pipeline-artifacts-<account_id>` (same hardening, objects expire after 14 days) holds the release pipeline's source zip and saved production plan. |
| `ecr.tf` | ECR `phoebe-api`: immutable tags, scan on push. Lifecycle (ruling R13) has two rules. Rule 1 never expires `release-*` images. Rule 2 expires everything else beyond the newest 60 (30 commits × `<sha>` api + `<sha>-jobs`). The repo policy lets `lambda.amazonaws.com` pull for `function:phoebe-*`. |
| `codebuild.tf` | CodeConnections `phoebe-github` (GitHub, created `PENDING`). Five CodeBuild projects, all `ARM_CONTAINER` on `aws/codebuild/amazonlinux-aarch64-standard:3.0`. Each logs to a pre-created `/aws/codebuild/<project>` group (30 days). Webhooks are created once `github_connection_ready = true`. |
| `buildspecs/` | Inline buildspecs for `phoebe-pr` and `phoebe-pr-cleanup`, rendered with `templatefile` (ruling R15). |
| `pipeline.tf` | CodePipeline V2 `phoebe-release`, in `QUEUED` execution mode. Stages: Source (CodeConnections, triggered by pushed tags `v*`), then Plan (`phoebe-release-plan`, read-only), then Approve (manual), then Apply (`phoebe-release-apply`, on the saved plan). |
| `roles.tf` | Six `phoebe-ci-*` roles, each with `phoebe-boundary-ci` and one inline policy. Managed `phoebe-ci-reads-<env>` holds the Terraform refresh reads; it is attached to the roles that run infra/app for that env. Trust is scoped by `aws:SourceAccount` and, for CodeBuild roles, by the role's own project ARN. |
| `boundary.tf` | `phoebe-boundary-staging`, `phoebe-boundary-production` and `phoebe-boundary-ci` (below). |
| `budget.tf` | SNS `phoebe-budget-staging` and `phoebe-budget-production` in us-east-2 (ruling R16). Each topic policy lets `budgets.amazonaws.com` publish, scoped by `aws:SourceAccount` and `arn:aws:budgets::<account_id>:*`. A monthly account cost budget `phoebe-monthly` at `monthly_budget_usd` alerts both topics at 80% ACTUAL. Each env's budget Lambda subscribes only to its own topic. `aws_budgets_budget` has no `region` argument: the provider reaches the global Budgets API from the us-east-2 provider, so there is no us-east-1 provider. |

### CodeBuild projects and roles

| Project | Role | Trigger (every group also requires `ACTOR_ACCOUNT_ID ^<github_owner_id>$`) | Buildspec |
|---|---|---|---|
| `phoebe-pr` | `phoebe-ci-plan` | `PULL_REQUEST_CREATED, UPDATED, REOPENED` into `main`; fork PRs also need a maintainer's approval comment | inline `buildspecs/pr.yml` |
| `phoebe-pr-cleanup` | `phoebe-ci-pr-cleanup` | `PULL_REQUEST_CLOSED, MERGED` into `main` | inline `buildspecs/pr-cleanup.yml` |
| `phoebe-staging` | `phoebe-ci-deploy-staging` | `PUSH`, `HEAD_REF ^refs/heads/main$`; privileged (the only Docker build); one build at a time | `ci/buildspec-staging.yml` |
| `phoebe-release-plan` | `phoebe-ci-plan-production` (read-only) | pipeline Plan stage, before approval; one at a time | `ci/buildspec-release-plan.yml` |
| `phoebe-release-apply` | `phoebe-ci-deploy-production` | pipeline Apply stage, after approval; one at a time | `ci/buildspec-release-apply.yml` |

The actor filter is Review Focus 5: a PR from a fork has the fork author as its
actor, so it matches no filter group and no build runs. `tests/bootstrap.tftest.hcl`
asserts this for every group.

**Why the PR specs are inline (R15).** On a close or merge, the actor is whoever
closed it. The owner closing a stranger's PR would otherwise run that PR's
checked-out buildspec. Both PR projects therefore take their steps from
Terraform:

- **`pr-cleanup.yml`** runs no repo code. It takes `N` from
  `CODEBUILD_WEBHOOK_TRIGGER` (`pr/<n>`) and refuses unless `N` is all digits.
  It then deletes `s3://phoebe-staging-site-<account_id>/previews/pr-$N/` and
  invalidates `/pr-$N/*`. It still clones, because a webhook needs a GitHub
  source (`NO_SOURCE` projects cannot have one). Its role cannot read state or
  secrets.
- **`pr.yml`** builds the PR's frontend (`PHOEBE_BASE=/pr-$N/`), syncs it to
  `previews/pr-$N/`, invalidates, and then runs a read-only
  `terraform plan -lock=false` for staging. The plan uses the digests staging
  runs now, read from the Lambda config. The PR's own code still runs here
  (`npm ci`, the build, Terraform), so the actor filter remains the gate.
- **Fork gate in `pr.yml`.** Owner actions on a fork PR, such as a reopen or a
  maintainer-edit push, pass the actor filter. The first install command
  therefore checks the PR's head repo before any repo code runs. It reads the
  PR from GitHub's public REST API (`repos/<github_repo>/pulls/$N`, 20 s
  timeout) and aborts unless `.head.repo.full_name` equals `github_repo`. It
  parses with jq, or python3 if jq is missing. It fails closed: an API error,
  rate limit or deleted fork leaves the value empty, and the build stops. The
  checkout happens before the phases, but nothing from it executes before
  this check.
- **The invalidation** in both specs needs `staging_distribution_id`. It is
  empty (invalidation skipped) until the first staging deploy; then the owner
  sets it and re-applies.

### Contract for Task 8

- **`ci/buildspec-pr.yml` and `ci/buildspec-pr-cleanup.yml` are no longer
  used.** Do not create them; the inline specs above replace them.
- **Release-plan (`phoebe-ci-plan-production`) is read-only**, so its
  `terraform plan` must use `-lock=false`. It may write only its output artifact
  (`plan`) to the artifacts bucket. It resolves `phoebe-api:<sha>` and
  `<sha>-jobs` with `ecr:DescribeImages` / `ecr:BatchGetImage`.
- **Release actions get `RELEASE_COMMIT`** (`#{SourceVariables.CommitId}`).
  Apply receives `source` (primary) and `plan` (secondary,
  `CODEBUILD_SRC_DIR_plan`).
- **Apply (`phoebe-ci-deploy-production`) adds release tags** to the promoted
  digests: `release-<git tag>` and `release-<git tag>-jobs`, via
  `ecr:BatchGetImage` for the manifest and `ecr:PutImage` with the new tag.
  IMMUTABLE only forbids moving an existing tag. Lifecycle rule 1 then keeps
  those images forever.
- **Release tags may already exist.** `phoebe-ci-deploy-staging` also holds
  `ecr:PutImage` (it pushes), so it could pre-create a `release-*` tag. The
  release step must therefore check an existing `release-<git tag>` tag. It may
  continue only if that tag already points at the digest being promoted, and
  must fail otherwise. Never skip the check.
- **infra/ai is owner-applied locally (R12).** No CI role can write it or call
  Bedrock or AgentCore. CI only reads `ai.tfstate` through
  `terraform_remote_state`. `deploy.sh` must not apply `infra/ai`.

### Boundaries

**`phoebe-boundary-<env>`** goes on every infra/app role in that env (infra/app's
`boundary_policy_arn`; another env's boundary fails validation). It allows:

- `s3`, `dynamodb`, `sqs`, `rds-data`, `lambda:InvokeFunction`, log writes and
  secret reads, only on `phoebe-<env>-*` ARNs (buckets
  `phoebe-<env>-*-<account_id>`, cluster `phoebe-<env>`);
- the Aurora master secret `rds!cluster-*` (its name is a uuid), but **only**
  when `secretsmanager:ResourceTag/aws:rds:primaryDBClusterArn` is this env's
  cluster. This fails closed: an untagged secret, or one tagged for another
  cluster, is refused. I could not find the tag key in the AWS docs (the
  Aurora Secrets Manager page lists none). Task 9 must confirm it with
  `aws secretsmanager describe-secret` on the first staging cluster's secret.
  If the key differs, the app's first DB call fails loudly (AccessDenied),
  which the smoke test catches. Deploy roles cannot forge it: `aws:`-prefixed
  tag keys are reserved for AWS;
- shared Bedrock and AgentCore invokes (models, the guardrail, harnesses are
  env-agnostic).

It allows nothing else: no CodeBuild, ECR, IAM, STS or CloudFront. It also
carries the Region deny, the organizations/account deny and an IAM-write deny
outside `role/phoebe-<env>-*`. A role a staging deploy creates can therefore
never reach production, whatever inline policy it is given.

**`phoebe-boundary-ci`** goes on the CI roles. It:

- allows only the services CI uses;
- denies every action outside `us-east-2` except CloudFront, IAM, STS and
  Budgets;
- denies `organizations:*` and `account:*`;
- denies every IAM write unless the target is `role/phoebe-staging-*`,
  `role/phoebe-production-*` or the RDS service-linked role (needed by the
  first cluster);
- denies IAM writes on `role/phoebe-ci-*`;
- denies creating or editing a role that does not carry an env boundary;
- denies removing a boundary and `sts:AssumeRole`.

Each deploy role's own policy narrows this further: it may create roles only
with **its own** env's boundary.

The Region deny exempts one Bedrock case: a `us.` inference profile called in
us-east-2 is routed to the model in another US Region. Only that routed
evaluation carries `bedrock:InferenceProfileArn`, and the call itself must
still be made in us-east-2.

### Env-scoped reads (R14)

CloudFront distribution config holds the `X-Phoebe-Origin` value, and Lambda
config holds the env vars. `phoebe-ci-reads-<env>` therefore grants:

- `cloudfront:GetDistribution*`, `GetInvalidation` and `ListTagsForResource`
  only with `aws:ResourceTag/env = <env>`. infra/app's provider `default_tags`
  set `env` on the distribution.
- No CloudFront `List*` at all. `ListDistributions` would return every origin's
  custom headers.
- `lambda:Get*` / `List*` only on `function:phoebe-<env>-*`.
- `dynamodb`, `sqs`, `scheduler`, S3 bucket config and CloudFront Functions,
  each scoped to the env.

The account-wide reads that remain are metadata only (RDS describe, log-group
describe, secret describe, IAM role reads, SNS attributes, ECR describe, event
source mappings).

### Wildcards that could not be avoided

- Metadata reads on `*` (listed above).
- CloudFront `distribution/*`, always with an env tag condition (creation uses
  `IfExists` because the tag does not exist yet).
- CloudFront OAC and response-headers policies (`origin-access-control/*`,
  `response-headers-policy/*`): id-only ARNs, no tag condition keys.
- Event source mappings (`event-source-mapping:*`), scoped by
  `lambda:FunctionArn` to the env's functions.
- RDS defaults (`cluster-pg:default.*`, `pg:default.*`, `og:default:*`,
  `subgrp:default`), which CreateDBCluster authorizes on.
- The RDS-managed master secret (`secret:rds!cluster-*`).
- `kms:DescribeKey` and `kms:CreateGrant` on `*`, only via RDS or Secrets
  Manager (AWS managed keys).
- `ecr:GetAuthorizationToken` on `*` (staging only).
- `s3:PutBucket*` and `s3:GetBucket*` on `phoebe-<env>-*-<account_id>`.

### Accepted risks

- **`iam:UpdateAssumeRolePolicy` on `role/phoebe-<env>-*`.** A deploy role could
  rewrite an app role's trust. This is accepted because:
  - CodeBuild runs only the owner's commits (actor filter; release tags are
    owner-only);
  - the env boundary caps any such role to its own env's data-plane resources,
    with no IAM, STS, CloudFront or CodeBuild.
- **CloudFront OAC and response-headers policies across envs.** A deploy role
  can modify the other env's OAC or response-headers policy. These have
  id-only ARNs and no tag keys, so they cannot be scoped. CI runs only the
  owner's commits.
- **`phoebe-release-apply` uses `ci/buildspec-release-apply.yml` from the tagged
  source.** Tags are owner-only, and the approval gate reviews the saved plan
  first.
- **Untagged distributions are writable by both deploy roles.** Distribution
  writes use `StringEqualsIfExists` on `aws:ResourceTag/env`, so that creation
  works before the tag exists. A distribution with no `env` tag therefore
  matches both roles. infra/app's `default_tags` always set it, so only a
  hand-made, untagged distribution in this account would be exposed.
- **Budget topics (R16).** Each deploy role may `sns:Subscribe` only its own
  env's budget Lambda (`sns:Endpoint` `function:phoebe-<env>-budget`, protocol
  `lambda`) to its own topic. It may `sns:Unsubscribe` only subscriptions on
  that topic, and reads only that topic. No CI role has
  `sns:SetSubscriptionAttributes`, so no filter policy can mute the kill
  switch.
- **Pathed roles.** `*` in an ARN crosses `/`, so deploy roles explicitly deny
  `iam:CreateRole` on `role/*/*`. That blocks a role under a path such as
  `/phoebe-<env>-x/`.

## Inputs

| Variable | Notes |
|---|---|
| `github_owner_id` | Required, no default. The owner's numeric GitHub user id (public; `terraform.tfvars` holds it). |
| `github_repo` | Default `ahochoy/phoebe-onboarding`. |
| `github_connection_ready` | Default `false`. Set `true` once the connection is authorized; CodeBuild can only create webhooks through an `AVAILABLE` connection. |
| `staging_distribution_id` | Default `""`. The staging CloudFront id, used by the inline PR specs to invalidate `/pr-<n>/*`. Set it after the first staging deploy. |
| `monthly_budget_usd` | Default `20`. |

## Outputs

`state_bucket`, `boundary_policy_arns` (`staging`, `production`, `ci`),
`budget_topic_arns` (`staging`, `production`), `ecr_repository_url`,
`connection_arn`, `connection_status`, `codebuild_projects`, `pipeline_name`,
`ci_role_arns`. `state_bucket`, the matching env boundary and the matching env
topic feed `infra/app/envs/<env>.tfvars`.

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

3. **Authorize the GitHub connection.** In the AWS console, go to Developer
   Tools → Settings → Connections → `phoebe-github` and choose **Update pending
   connection**. Install or choose the AWS Connector for GitHub app, limited to
   this repository, and finish. The status becomes `Available`.

4. **Create the webhooks.** Set `github_connection_ready = true` in
   `terraform.tfvars`. Plan (the only additions should be three
   `aws_codebuild_webhook` resources), then apply. Commit the tfvars change.

5. **Move `infra/ai` state.** `infra/ai/terraform.tf` now declares the `s3`
   backend with key `ai.tfstate`. infra/ai stays owner-applied from here on.

   ```sh
   cd infra/ai
   terraform init -migrate-state -backend-config=bucket=phoebe-tfstate-<account_id>
   terraform plan   # must show no changes
   ```

6. **Fill in infra/app inputs.** Put the outputs above into
   `infra/app/envs/<env>.tfvars` and `<env>.s3.tfbackend`.
   `boundary_policy_arn` is `phoebe-boundary-<env>`.

7. **After the first staging deploy,** set `staging_distribution_id` in
   `terraform.tfvars` and re-apply, so previews invalidate.

Budget alerts reach the per-env budget Lambdas only. To also get an email, the
owner subscribes an address to `phoebe-budget-production` in the console; it is not
recorded here.

## Offline checks

`make tf-check` runs `init -backend=false`, `validate` and `test` here as well.
`tests/bootstrap.tftest.hcl` uses `mock_provider "aws"`, so it makes no AWS
calls.
