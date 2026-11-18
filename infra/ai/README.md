# infra/ai

Terraform root for Phoebe's AI pieces in `us-east-2`: one Bedrock Guardrail and
two AgentCore Harnesses (Haiku 4.5 and Nova Micro) sharing one execution role.

Since 2026-11-18 the API answers with Haiku through Bedrock directly
(`infra/app` variable `answer_backend = converse`). The guardrail is still in
use. The harnesses are kept for one release as the rollback path
(`answer_backend = harness`), then removed. With `converse` the system prompt
comes from `backend/prompts/answer.txt` in the API image, so a prompt change
reaches staging and production through a normal deploy. An apply here only
updates the rollback harnesses.
Plan 4 moves this root into its module layout with `moved {}` blocks, so keep
the resource names stable.

## Owner gate

Nothing here has been planned or applied. The owner reviews `terraform plan`
and approves any apply. Cost: the Guardrail is pay-per-use, and Harnesses and
the IAM role cost nothing while idle.

## Apply (owner only)

```sh
terraform -chdir=infra/ai init
terraform -chdir=infra/ai plan
terraform -chdir=infra/ai apply     # only after the owner says go
terraform -chdir=infra/ai output
```

The execution role deliberately has no `logs:PutResourcePolicy`: a runtime role
must not be able to change account-wide policies. If AgentCore log delivery
turns out to need a CloudWatch Logs resource policy, create it once in
Terraform (`aws_cloudwatch_log_resource_policy`), not by granting it to the role.

`aws_bedrock_guardrail_version` does not auto-bump when the Guardrail's filters
change. After editing filters, replace the version resource
(`terraform apply -replace=aws_bedrock_guardrail_version.answers`) so
`guardrail_version` points at the new snapshot.

State is local and gitignored (`*.tfstate*`, `.terraform/`, `*.tfvars`).
Offline check, no AWS: `init -backend=false`, `fmt -check`, `validate`.

## Live check

After apply, with a throwaway database whose name ends in `_live`:

```sh
docker compose exec -T db createdb -U postgres phoebe_live
export PHOEBE_LIVE_DATABASE_URL=postgresql://postgres:phoebe@localhost:5433/phoebe_live
export PHOEBE_EMBEDDER=titan
export PHOEBE_ANSWER_BACKEND=harness
export PHOEBE_HARNESS_ARN=$(terraform -chdir=infra/ai output -raw harness_haiku_arn)
export PHOEBE_REWRITER_BACKEND=bedrock
export PHOEBE_GUARDRAIL_ID=$(terraform -chdir=infra/ai output -raw guardrail_id)
export PHOEBE_GUARDRAIL_VERSION=$(terraform -chdir=infra/ai output -raw guardrail_version)
make live-check
```

It prints pass/fail and citation titles only, never answer text, and exits
non-zero on any failure. For the Nova run, set `PHOEBE_HARNESS_ARN` to
`harness_nova_arn`. `make live-check` is not part of `make test` or CI.

## Results

Applied 2026-11-11 (6 resources, us-east-2). Seeding with Titan v2 indexed
12 documents into 123 chunks. The `us.` inference profiles route to us-east-1,
us-east-2 and us-west-2, and the project's policies allow that routing.

| Date | Harness | Check | Result |
|---|---|---|---|
| 2026-11-11 | Nova Micro | PTO question: cited, mentions 20 | PASS (Benefits Guide, Employee Handbook) |
| 2026-11-11 | Nova Micro | Follow-up: cited or refused | PASS, cited (Benefits Guide, Employee Handbook) |
| 2026-11-11 | Nova Micro | Sales East quota: refused | PASS, no citations |
| 2026-11-11 | Haiku 4.5 | PTO question: cited, mentions 20 | BLOCKED: refused `model_unavailable` |
| 2026-11-11 | Haiku 4.5 | Follow-up and quota checks | PASS, refused (Haiku not reachable) |

Haiku is blocked on an account step, not on code. Through the Harness,
ConverseStream returns "Model use case details have not been submitted for
this account". The account owner submits the Anthropic use case form once
(Bedrock console, Model catalog, any Claude model), waits about 15 minutes,
then reruns `make live-check` with `harness_haiku_arn`. Until then, run with
`PHOEBE_HARNESS_ARN` set to `harness_nova_arn`.

Python reads `aws login` credentials through `botocore[crt]`, which is a dev
dependency for that reason.
