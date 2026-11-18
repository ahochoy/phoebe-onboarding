# Direct Bedrock answers instead of the AgentCore harness

Plan 5, item 5. Status: approved in conversation 2026-11-18 (owner: "write the
design and plan for direct Bedrock").

## Intent

Chat answers come from Haiku 4.5 through an AgentCore harness. Phoebe uses
almost none of what the harness offers: `max_iterations = 1`, tools blocked by
a non-matching allowlist, memory disabled, a fresh runtime session per chat.
The harness adds latency and cost:

- In `make eval` (2026-11-18), Haiku 4.5 through a direct ConverseStream call
  (`haiku-direct`) passed the same 9/9 at p50 1.6 s / p90 2.1 s, against
  4.0 s / 6.5 s through the harness.
- AgentCore was $0.47 of November's $1.58 gross, mostly idle microVM memory.

The harness reaches documents only through tools (AgentCore Gateway: a
Bedrock Managed Knowledge Base target, or a Lambda tool). Both were rejected
in conversation: a knowledge base cannot express Phoebe's per-team visibility
plus per-visitor sandbox overlay, and a model-driven search tool widens the
leak surface (identity would have to be injected outside the model) while
adding round trips. Phoebe's retrieval stays app-controlled and deterministic.

## Goals

- The API answers with Haiku 4.5 through Bedrock ConverseStream, with the same
  system prompt, messages, temperature (0.1) and `max_tokens` (700) as the
  harness, on the same `us.` cross-region inference profile.
- Everything around the answer model is unchanged: rewriter, retrieval,
  refusal gate, citation verifier, guardrail input and output checks, SSE,
  refusal codes, logging (metadata only).
- One setting switches back to the harness for one release (rollback).
- Prompt changes ship with a normal deploy (no `infra/ai` apply for them).

## Non-goals

- Changing the model, the prompt, or the guardrail.
- Agentic retrieval, tools, or memory.
- Deleting `infra/ai`'s guardrail (still used). The harnesses are removed in a
  follow-up once the direct path has run a release.

## Anti-goals

- A prompt that silently differs between the harness and the direct path.
- Any loss of the "no tool use" guarantee: the direct request sends no tool
  config, and a `toolUse` block in the stream is still an error.

## Approaches

1. **Direct ConverseStream from the API (chosen).** Promote the eval's
   `ConverseAnswerModel` into `phoebe.chat.models`; `PHOEBE_ANSWER_BACKEND`
   gains `converse`; IAM grants the API role `bedrock:InvokeModelWithResponseStream`
   on the Haiku profile and its foundation models.
2. Keep the harness and lean into AgentCore (Gateway tools or a managed
   knowledge base). Rejected (see Intent).
3. Keep the harness as is. Rejected: slower and costlier for no feature used.

## Design

**App.** `ConverseAnswerModel` moves from `phoebe.evals.converse` to
`phoebe.chat.models` (the eval imports it from there). It reads the system
prompt from `ANSWER_PROMPT_PATH` at construction, sends no tools, treats a
`toolUse` content block as an error (like the harness model), and maps errors
to `ModelUnavailable` without provider text. `Settings.answer_backend` becomes
`"extractive" | "harness" | "converse"`, with `answer_model_id` (default
`us.anthropic.claude-haiku-4-5-20251001-v1:0`). `make_models` builds the
converse model with `answer_max_tokens` and temperature 0.1. Startup fails
fast if the backend is `converse` without guardrail settings, matching the
roadmap note for `harness`.

**Image.** The Dockerfile copies `backend/prompts` into the image (today it
does not; only the harness had the prompt).

**infra/app.** A variable `answer_backend` (`converse` default, `harness` for
rollback) replaces the hard-coded `PHOEBE_ANSWER_BACKEND = "harness"`.
`PHOEBE_ANSWER_MODEL_ID` is set for `converse`; `PHOEBE_HARNESS_ARN` only for
`harness`. The API role gets `bedrock:InvokeModel` and
`bedrock:InvokeModelWithResponseStream` on the Haiku inference profile in
us-east-2 and the Haiku foundation model in the profile's three Regions
(the same pattern the rewriter already uses for Nova Micro). The harness
statement stays while `answer_backend = "harness"` is possible.

**Rollout.** Merge, staging deploys with `converse`. Verify on staging: the
holiday question, a refusal, and `make eval MODEL=haiku-direct` against the
`_live` database. Release to production. After a release with no rollback,
a follow-up removes the harnesses from `infra/ai` (owner apply), the
`harness` backend, and its IAM statement.

## Left to the builder

- Exact test cases (request shape, tool-use rejection, error mapping, the
  settings guard, the IAM tftest).
- Whether the eval's `haiku-direct` candidate keeps its own entry or simply
  uses the production model class (it should use the same class).
