# infra/ai

A Terraform root in `us-east-2` for the AI resources that staging and
production share. Its state is `ai.tfstate` in the bootstrap state bucket, and
[`infra/app`](../app/README.md) reads its outputs. For the overall design, see
the [top-level README](../../README.md).

## What it creates

- **Bedrock Guardrail `phoebe-answers`** with one published version. It filters hate,
  insults, sexual content, violence and misconduct on input and output, and
  prompt attacks on input. Both environments use it for every chat answer.
- **Two AgentCore harnesses**, `PhoebeHaikuHarness` (Claude Haiku 4.5) and
  `PhoebeNovaHarness` (Amazon Nova Micro), sharing the execution role
  `PhoebeAgentCoreHarnessExecutionRole`. Both use the system prompt from
  `backend/prompts/answer.txt` and end idle runtime sessions after 60 seconds.

The API no longer uses the harnesses. It calls Haiku through Bedrock
ConverseStream (`answer_backend = converse` in `infra/app`), with the prompt
built into the API image, so a prompt change ships with a normal deploy. The
harnesses stay deployed for one release as a rollback
(`answer_backend = harness`) and will then be removed.

Model ids: `us.anthropic.claude-haiku-4-5-20251001-v1:0` and
`us.amazon.nova-micro-v1:0`. The `us.` inference profiles route to us-east-1,
us-east-2 and us-west-2, so the role allows the model in all three.

## Apply (owner only)

CI never applies this root. The owner reviews the plan and applies it locally:

```sh
terraform -chdir=infra/ai init -backend-config=bucket=phoebe-tfstate-<account_id>
terraform -chdir=infra/ai plan
terraform -chdir=infra/ai apply
```

Changing the guardrail's filters does not create a new guardrail version. After
an edit, run `terraform apply -replace=aws_bedrock_guardrail_version.answers`
so the `guardrail_version` output points at the new snapshot.

The execution role has no `logs:PutResourcePolicy`, so it cannot change
account-wide policies. If AgentCore log delivery ever needs a CloudWatch Logs
resource policy, add it in Terraform rather than granting it to the role.

## Checks

- `make tf-check` validates this root and runs `tests/ai.tftest.hcl` with a
  mocked AWS provider (no AWS calls).
- `make live-check` runs real chats against AWS and costs money. It is not part
  of `make test` or CI. It needs a separate database whose name ends in `_live`
  and the live `PHOEBE_*` settings:

```sh
docker compose exec -T db createdb -U postgres phoebe_live
export PHOEBE_LIVE_DATABASE_URL=postgresql://postgres:phoebe@localhost:5433/phoebe_live
export PHOEBE_EMBEDDER=titan
export PHOEBE_ANSWER_BACKEND=converse   # or harness, with PHOEBE_HARNESS_ARN
export PHOEBE_REWRITER_BACKEND=bedrock
export PHOEBE_GUARDRAIL_ID=$(terraform -chdir=infra/ai output -raw guardrail_id)
export PHOEBE_GUARDRAIL_VERSION=$(terraform -chdir=infra/ai output -raw guardrail_version)
make live-check
```

It prints pass or fail and citation titles only, never answer text, and exits
non-zero on any failure.
