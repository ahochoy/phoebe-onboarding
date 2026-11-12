# infra/ai

Terraform root for Phoebe's AI pieces in `us-east-2`: one Bedrock Guardrail and
two AgentCore Harnesses (Haiku 4.5 and Nova Micro) sharing one execution role.
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

State is local and gitignored (`*.tfstate*`, `.terraform/`, `*.tfvars`).
Offline check, no AWS: `init -backend=false`, `fmt -check`, `validate`.

## Live check

After apply, with a throwaway database whose name ends in `_live`:

```sh
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

Not yet run.

| Date | Harness | Check | Result |
|---|---|---|---|
| not yet run | Haiku 4.5 | PTO question: cited, mentions 20 | not yet run |
| not yet run | Haiku 4.5 | Follow-up: cited or refused | not yet run |
| not yet run | Haiku 4.5 | Sales East quota: refused | not yet run |
| not yet run | Nova Micro | PTO question: cited, mentions 20 | not yet run |
