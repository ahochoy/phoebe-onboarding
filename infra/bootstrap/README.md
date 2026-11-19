# infra/bootstrap

The delivery machinery for Phoebe: state buckets, the image repository, CI
roles and their permission boundaries, CodeBuild, the release pipeline, and
spend alerts. Everything lives in `us-east-2` (IAM, CloudFront invalidations
and Budgets are global).

The owner applies this root locally with their own session. CI cannot change
it: no CI role can read or write `bootstrap.tfstate`, and the CI boundary
denies IAM writes on the `phoebe-ci-*` roles.

## What it creates

| File | Resources |
|---|---|
| `state.tf` | S3 `phoebe-tfstate-<account_id>`: versioned, `prevent_destroy`, old versions expire after 90 days. Holds the bootstrap, ai and per-env app states. S3 `phoebe-pipeline-artifacts-<account_id>`: the release source and saved production plan, expired after 14 days. Both are SSE-S3, fully public-access-blocked, owner-enforced and TLS-only. |
| `ecr.tf` | ECR `phoebe-api`: immutable tags, scan on push. Each commit pushes `<sha>` and `<sha>-jobs`. The lifecycle keeps `release-*` images forever and expires everything else beyond the newest 60. Lambda may pull for `function:phoebe-*`. |
| `codebuild.tf` | The `phoebe-github` CodeConnections connection, five ARM CodeBuild projects (below), their log groups (30 days) and webhooks. |
| `buildspecs/` | Inline buildspecs for `phoebe-pr` and `phoebe-pr-cleanup`. |
| `pipeline.tf` | CodePipeline V2 `phoebe-release`, `QUEUED` mode. A pushed `v*` tag runs Source, then Plan (read-only), then a manual Approve, then Apply of the saved plan. |
| `roles.tf` | Six `phoebe-ci-*` roles, each with `phoebe-boundary-ci` and one inline policy, plus the managed `phoebe-ci-reads-<env>` refresh reads. Trust is scoped by `aws:SourceAccount` and, for CodeBuild roles, by the role's own project ARN. |
| `boundary.tf` | `phoebe-boundary-staging`, `phoebe-boundary-production` and `phoebe-boundary-ci`. |
| `budget.tf` | SNS `phoebe-budget-<env>` and two identical account-wide monthly cost budgets, `phoebe-monthly-<env>`. Each alerts its own topic at 70% of actual spend (a notification takes one SNS subscriber). The production budget also emails the owner when `alert_email` is set. |
| `alerts.tf` | SNS `phoebe-alerts` and an EventBridge rule per env on RDS-EVENT-0150 (cluster stopped). It invokes that env's budget Lambda, which closes the demo, and emails the owner how to restart (`make db-start ENV=<env>`). |

### CodeBuild projects

Every webhook filter group also requires `ACTOR_ACCOUNT_ID ^<github_owner_id>$`.

| Project | Role | Trigger | Buildspec |
|---|---|---|---|
| `phoebe-pr` | `phoebe-ci-plan` | PR created, updated or reopened into `main` | inline `pr.yml` |
| `phoebe-pr-cleanup` | `phoebe-ci-pr-cleanup` | PR closed or merged into `main` | inline `pr-cleanup.yml` |
| `phoebe-staging` | `phoebe-ci-deploy-staging` | push to `main`; privileged (the only Docker build) | `ci/buildspec-staging.yml` |
| `phoebe-release-plan` | `phoebe-ci-plan-production` (read-only) | pipeline Plan stage | `ci/buildspec-release-plan.yml` |
| `phoebe-release-apply` | `phoebe-ci-deploy-production` | pipeline Apply stage | `ci/buildspec-release-apply.yml` |

Staging and both release projects run one build at a time.

## Security model

**Only the owner's events build.** A fork PR's actor is the fork's author, so
it matches no filter group. Fork PRs would also need a maintainer's approval
comment. `tests/bootstrap.tftest.hcl` checks the actor filter on every group.

**PR buildspecs are inline.** On a close or merge, the actor is whoever closed
the PR, so the owner closing a stranger's PR must not run that PR's buildspec.
Both PR projects take their steps from Terraform:

- `pr-cleanup.yml` runs no repo code. It checks that the PR number is all
  digits, deletes `previews/pr-<n>/` from the staging site bucket and
  invalidates `/pr-<n>/*`. Its role has no state or secret access.
- `pr.yml` builds the PR's frontend into `previews/pr-<n>/`, invalidates, and
  runs a read-only `terraform plan -lock=false` for staging against the image
  digests staging runs now. The PR's code runs here, so the actor filter is
  the gate.

**Fork gate.** Some owner actions on a fork PR (a reopen, a maintainer-edit
push) pass the actor filter. So before any repo code runs, `pr.yml` asks
GitHub's API for the PR's head repo and aborts unless it is `github_repo`. It
fails closed on any error. It runs from an empty `mktemp -d` directory and
parses with jq only: `python3 -c` would import a planted `json.py` from the
fork's checkout.

**Release path.** Plan runs as a read-only role (`-lock=false`) that writes
only the saved plan. The source is a git clone through the connection
(`CODEBUILD_CLONE_REF`), so the tag is read with `git tag --points-at`. Apply
promotes the digests staging pushed and adds `release-<tag>` tags. Because the
staging role can push any tag, `ci/release-apply.sh` refuses if a release tag
already points at a different digest. `infra/ai` is owner-applied; CI only
reads `ai.tfstate`.

### Boundaries

**`phoebe-boundary-<env>`** goes on every infra/app role in that env. It
allows only:


- data-plane access (S3, DynamoDB, SQS, RDS Data API, Lambda invoke, logs,
  secret reads) on `phoebe-<env>-*` resources;
- the Aurora master secret, only when its `aws:rds:primaryDBClusterArn` tag is
  this env's cluster (`aws:` tags are reserved, so this cannot be forged);
- shared Bedrock invokes.

It also denies other Regions, Organizations and account actions, and IAM
writes outside `role/phoebe-<env>-*`. A role a staging deploy creates can
never reach production, whatever inline policy it is given.

**`phoebe-boundary-ci`** goes on the CI roles. It allows only the services CI
uses. It denies other Regions (except global CloudFront, IAM, STS and
Budgets), Organizations and account actions, IAM writes except on env roles
and the RDS service-linked role, any change to `phoebe-ci-*` roles, roles
without an env boundary, boundary removal, and `sts:AssumeRole`. Each deploy
role may create roles only with its own env's boundary.

Both Region denies let a `us.` Bedrock inference profile called in us-east-2
route to a model in another US Region.

**Env-scoped reads.** CloudFront distribution config holds the origin secret
header and Lambda config holds env vars. So `phoebe-ci-reads-<env>` grants
distribution reads only with tag `env = <env>`, no CloudFront `List*` at all,
and Lambda reads only on `function:phoebe-<env>-*`. The remaining wildcards
have no narrower form: metadata reads, CloudFront distributions (always
env-tag conditioned), OAC and response-headers policies, event source mappings
(limited by `lambda:FunctionArn`), five EC2 describes for RDS default-VPC
placement, RDS default groups and its managed secret, KMS only via RDS or
Secrets Manager, and `ecr:GetAuthorizationToken`.

### Accepted risks

All rest on CI running only the owner's commits and tags.

- A deploy role can rewrite trust on its env's roles; the boundary caps them.
- OAC and response-headers policies cannot be scoped by env.
- `phoebe-release-apply` runs the tagged source's buildspec, after approval.
- An untagged distribution matches both deploy roles (creation needs
  `IfExists`); infra/app always tags it.
- A deploy role may subscribe only its own budget Lambda to its own topic. No
  CI role can set a filter policy that mutes the kill switch.
- Deploy roles deny `iam:CreateRole` on `role/*/*`, because `*` crosses `/`.

## Inputs

| Variable | Notes |
|---|---|
| `github_owner_id` | Required. The owner's numeric GitHub user id (public, in `terraform.tfvars`). |
| `github_repo` | Default `ahochoy/phoebe-onboarding`. |
| `github_connection_ready` | Default `false`. Webhooks are created only when `true`, after the connection is authorized. |
| `staging_distribution_id` | Default `""` (PR invalidations skipped). The staging CloudFront id. |
| `monthly_budget_usd` | Default `30`. |
| `alert_email` | Default `null` (no email). Pass as `TF_VAR_alert_email`; never commit it. |

Outputs `state_bucket`, `boundary_policy_arns` and `budget_topic_arns` feed
`infra/app/envs/<env>.tfvars`; the rest name the ECR repo, connection,
projects, pipeline and CI roles.

## Applying

With the owner's session (`terraform.tfvars` holds the public inputs):

```sh
terraform init -backend-config=bucket=phoebe-tfstate-<account_id>
TF_VAR_alert_email=... terraform plan -out=bootstrap.plan
terraform apply bootstrap.plan
```

From scratch: apply first with local state (an uncommitted `local_override.tf`
with `terraform { backend "local" {} }`), delete the override, and move the
state with `terraform init -migrate-state -backend-config=bucket=...`. Then
authorize `phoebe-github` in the console, set `github_connection_ready = true`
and re-apply to create the webhooks. After the first staging deploy, set
`staging_distribution_id` and re-apply.

`make tf-check` runs `validate` and the offline tests here. The tests use
`mock_provider "aws"`, so they make no AWS calls.
