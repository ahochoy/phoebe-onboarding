# Direct Bedrock Answers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The API answers chat with Haiku 4.5 through Bedrock ConverseStream instead of the AgentCore harness, with a one-setting rollback.

**Architecture:** Promote the eval's `ConverseAnswerModel` into `phoebe.chat.models`, add a `converse` answer backend, ship the prompt in the image, and switch `infra/app` (env + IAM) to it behind an `answer_backend` variable. Everything around the answer model is unchanged.

**Tech Stack:** Python 3.14, boto3 `bedrock-runtime`, pytest; Docker; Terraform (tftest).

**Spec:** `docs/superpowers/specs/2026-11-18-direct-bedrock-design.md`

## Global Constraints

- Same answer request as the harness: system prompt = `backend/prompts/answer.txt`, messages as built today, `temperature` 0.1, `maxTokens` = `PHOEBE_ANSWER_MAX_TOKENS` (700), model id `us.anthropic.claude-haiku-4-5-20251001-v1:0`.
- No tools: the request carries no `toolConfig`; a `toolUse` block in the stream raises `ModelUnavailable` ("tool use not allowed"), like `HarnessAnswerModel`.
- Errors never carry provider or user text (`_unavailable(what, kind)` with the error code only).
- AWS us-east-2 only; the `us.` profile routes across us-east-1, us-east-2, us-west-2 (already accepted for Haiku).
- Settings: `answer_backend: Literal["extractive", "harness", "converse"]`; new `answer_model_id: str` with the default above.
- infra/app: variable `answer_backend` (`"converse"` default, `"harness"` allowed); the harness IAM statement and `PHOEBE_HARNESS_ARN` exist only when it is `harness`.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. The image has no prompt file: the API must fail at startup (import/`make_models`), not on the first chat (Task 2 `test_image_ships_the_prompt`, Task 1 `test_converse_reads_prompt_at_construction`).
2. A model that emits a `toolUse` block (prompt injection asking for tools): refused as `ModelUnavailable`, never streamed (Task 1 `test_converse_tool_use_raises`).
3. `answer_backend = "converse"` without guardrail settings in a deployed env: refuse to start, like the harness rule (Task 1 `test_converse_requires_guardrail_settings`).
4. Rollback: `answer_backend = "harness"` restores exactly today's env and IAM (Task 3 `answer_backend_harness_rollback`).
5. The eval's `haiku-direct` and production use the same class, so the eval measures what ships (Task 1 `test_eval_uses_the_production_converse_model`).

---

### Task 1: `converse` answer backend in the app

**Files:**
- Modify: `backend/src/phoebe/chat/models.py` (add `ConverseAnswerModel`, `ModelUnsupported`; `make_models` branch)
- Modify: `backend/src/phoebe/config.py` (`answer_backend` literal, `answer_model_id`)
- Modify: `backend/src/phoebe/evals/converse.py` (re-export from `phoebe.chat.models`, keep the module path working)
- Test: `backend/tests/test_chat_models.py`, `backend/tests/test_evals_converse.py` (unchanged tests must still pass)

**Interfaces:**
- Produces: `phoebe.chat.models.ConverseAnswerModel(model_id: str, region: str, *, max_tokens: int, temperature: float | None = 0.1, client: Any = None)` with `stream(messages) -> Iterator[str]` and `usage: dict[str, int]`; `ModelUnsupported(ModelUnavailable)`.

- [ ] **Step 1: Failing tests** in `test_chat_models.py`: `test_converse_request_is_server_owned` (exact kwargs: modelId, `system=[{"text": answer.txt}]`, messages, `inferenceConfig={"temperature": 0.1, "maxTokens": 700}`, and no `toolConfig` key); `test_converse_tool_use_raises` (a `contentBlockStart` with `toolUse`, or a delta with `toolUse`, raises `ModelUnavailable`); `test_converse_reads_prompt_at_construction` (a missing prompt path raises at construction, not on stream); `test_make_models_converse` (settings `answer_backend="converse"` plus guardrail → a `ConverseAnswerModel` with model id and 700); `test_converse_requires_guardrail_settings`; `test_eval_uses_the_production_converse_model` (`phoebe.evals.converse.ConverseAnswerModel is phoebe.chat.models.ConverseAnswerModel`).
- [ ] **Step 2: `make test`, expect FAIL.**
- [ ] **Step 3: Implement.** Move the class (and `ModelUnsupported`, `TEMPERATURE`, `_STREAM_ERRORS` for converse) into `chat/models.py`; add the `toolUse` checks; `make_models` raises `RuntimeError` for `converse` without guardrail id and version.
- [ ] **Step 4: `make test`, `make lint` green.**
- [ ] **Step 5: Commit** `feat(chat): converse answer backend (Haiku through Bedrock directly)`

### Task 2: The image ships the prompt

**Files:**
- Modify: `backend/Dockerfile` (`COPY --chmod=a+rX backend/prompts /app/backend/prompts`)
- Test: `ci/tests/test_deploy_scripts.py` (or a new `backend/tests/test_dockerfile.py`)

- [ ] **Step 1: Failing test** `test_image_ships_the_prompt`: parse `backend/Dockerfile`; the runtime stage copies `backend/prompts` to `/app/backend/prompts` (the path `ANSWER_PROMPT_PATH` resolves to under `PYTHONPATH=/app/backend/src`).
- [ ] **Step 2: Run, expect FAIL.** **Step 3: Implement.** **Step 4: Pass; `docker build --target api -f backend/Dockerfile .` succeeds locally and `docker run --rm --entrypoint python <img> -c "from phoebe.chat.prompt import ANSWER_PROMPT_PATH; print(ANSWER_PROMPT_PATH.read_text()[:20])"` prints the prompt's first words.**
- [ ] **Step 5: Commit** `build: ship backend/prompts in the image`

### Task 3: infra/app switches to `converse`

**Files:**
- Modify: `infra/app/variables.tf` (`answer_backend`), `infra/app/lambdas.tf` (env), `infra/app/iam.tf` (API statements), `infra/app/data.tf` only if `harness_arn` must become conditional
- Test: `infra/app/tests/app.tftest.hcl`

- [ ] **Step 1: Failing tftest runs:** `answer_backend_converse_default`: the API env has `PHOEBE_ANSWER_BACKEND = "converse"`, `PHOEBE_ANSWER_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"`, no `PHOEBE_HARNESS_ARN`; the API policy has a statement allowing `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` on exactly the Haiku profile ARN (us-east-2) and the Haiku foundation-model ARN in us-east-1, us-east-2, us-west-2; no `bedrock-agentcore:*` action. `answer_backend_harness_rollback`: with `answer_backend = "harness"`, today's env (`harness`, `PHOEBE_HARNESS_ARN`) and the `AnswerHarness` statement are back, and no Haiku invoke statement. `answer_backend_rejects_unknown`.
- [ ] **Step 2: `make tf-check`, expect FAIL.**
- [ ] **Step 3: Implement.** Keep `answer_harness` (haiku | nova) for the harness path. The deploy role already manages these role policies; no bootstrap change.
- [ ] **Step 4: `make tf-check` green.**
- [ ] **Step 5: Commit** `feat(app): answer through Bedrock directly (answer_backend = converse)`

### Task 4: Docs

**Files:**
- Modify: `README.md` (Configuration table: `PHOEBE_ANSWER_BACKEND` values, `PHOEBE_ANSWER_MODEL_ID`), `infra/app/README.md` (inputs table: `answer_backend`; note on rollback), `infra/ai/README.md` (the harnesses are now the rollback path; a prompt change reaches production through a normal deploy), `docs/superpowers/plans/2026-11-11-phoebe-roadmap.md` (item 5 status).

- [ ] **Step 1:** Update the four docs. **Step 2:** `make lint` (markdown is not linted; check links by reading). **Step 3: Commit** `docs: direct Bedrock answers`

### Task 5: Rollout (owner, not code)

- [ ] Merge; staging deploys with `converse`.
- [ ] On staging: ask "What holidays do we have in November and December?" (cited list), an other-team question (1001), check the API log shows `refused=-` and no `bedrock-agentcore` calls.
- [ ] `make eval MODEL=haiku-direct` (9 facts) against `_live` as a regression check.
- [ ] Release a `v*` tag; verify production the same way.
- [ ] After one release with no rollback: a follow-up removes the harnesses (infra/ai owner apply), the `harness` backend and its IAM.
