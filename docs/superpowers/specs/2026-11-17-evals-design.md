# Chat evals: a re-runnable question set and model comparison

Plan 5, items 2 and 4. Status: draft for owner approval.

## Intent

Phoebe's answers come from a real model, a citation verifier and a refusal
gate. The holiday-question bug (a list answer refused as `verification_failed`)
reached staging because nothing exercised the real model with realistic
questions before then. The owner wants:

1. A fixed set of questions with known-good outcomes, run against the real
   models, to catch regressions when the prompt, the verifier or the seed
   documents change.
2. Hard numbers to decide whether a model available in the account beats the
   current Haiku 4.5 (Haiku 4.5 and Sonnet 5.5 show agreement `NOT_AVAILABLE`).

It is a portfolio piece: the owner runs it by hand from this machine when they
want. No CI, no schedule.

## Goals

- `make eval` runs the question set and prints a per-model scorecard.
- Grading is deterministic: no AI judge.
- The same run compares the current harness with candidate models.
- Results are saved locally so a failure can be read, not just counted.
- A run's cost is visible before and after it runs.

## Non-goals

- CI or scheduled runs; a pass/fail gate on merges.
- An AI grader (approach 3, rejected for now: cost, bias, drift; it can be
  added later if deterministic checks miss real failures).
- Switching the production model. That is a separate, owner-approved change
  (a new harness in `infra/ai`, confirmed through staging) if the evals favour
  a candidate.
- Evaluating the rewriter or guardrail models on their own.

## Anti-goals

- Anything that touches the staging or production databases, harnesses' data,
  or the kill switch. Evals use the separate `_live` database like
  `make live-check`.
- Committing answer text that is not synthetic, or credentials. (All seed data
  is synthetic; results files are still git-ignored.)
- A run that silently costs more than expected.

## Constraints

- AWS: us-east-2 only. Candidates that are only offered through `us.`
  cross-region profiles (Kimi K3.1, GLM-5.3) route like Haiku 4.5 already does;
  gpt-oss-120b runs on-demand in us-east-2.
- Every run spends from the shared $30/month account limit, and at 70% the
  budget pauses Phoebe's chat. The run prints an estimate first and asks for
  confirmation unless `YES=1`.
- Runs with the owner's local AWS credentials (not a deploy role).
- The existing `make live-check` keeps working (or is folded in; builder's call).

## Approaches

1. **Grow `live-check` into `make eval` (chosen).** In-process app against the
   `_live` database with real Titan, rewriter and guardrail. `MODEL=` selects
   the answer model: the real Haiku harness, or a candidate through an
   eval-only adapter that calls Bedrock ConverseStream with the same system
   prompt (`backend/prompts/answer.txt`), the same messages from
   `build_messages`, `temperature 0.1` (the harness setting) and
   `PHOEBE_ANSWER_MAX_TOKENS`. Close to production, not identical; the winner
   gets one confirming run through a real staging harness before any switch.
2. A real harness per candidate. Exact path, but an `infra/ai` change and owner
   apply per candidate, before knowing it is worth it. Rejected.
3. Approach 1 plus an AI grader. Rejected for now (see non-goals).

## Design

**Question set** (`backend/evals/questions.yaml`, committed). About 30 cases,
each with an id, a category, the question (and optional prior turns for
follow-ups), and expectations:

- `answered: true|false`; when false, `code` (`1001`, `2307`, …).
- `must_cite`: document titles at least one citation must come from (any of).
- `must_not_cite`: titles that must never be cited or offered as closest.
- `must_contain`: case-insensitive substrings the answer must contain (facts,
  e.g. `20` for PTO days).
- `must_not_contain`: substrings that must be absent (e.g. a leaked system
  prompt phrase).

Categories, with rough counts:
- single fact (8): PTO days, benefits enrollment window, laptop setup steps…
- list answers (5): holidays in November and December, all onboarding tasks for
  a week, … (the bug class that reached staging)
- follow-ups (4): a second turn that depends on the first
- multi-document (3): an answer that needs two documents
- out of scope / another team's documents (4): must refuse `1001` and never
  cite Sales East, Sales Playbook or Payments Runbook
- prompt injection (3): must refuse (`2307` or `1001`) and not leak the prompt
- off-topic (3): weather, coding help unrelated to onboarding: refuse `1001`

Expectations are written against the seed documents in
`backend/seed/content/` (Employee Handbook, Benefits Guide, Holiday Calendar
2026-27, IT and Security Policy, Engineering Practices, …), checked by reading
them, not by running a model.

**Runner** (`backend/evals/run.py`, `make eval`). For each selected model and
case: post the question (and prior turns) to `/api/chat` on the in-process app,
parse the SSE, and record outcome, code, citations (titles), closest documents,
answer text, time to first token, total time, and token usage where the model
reports it. Each case runs once per model (temperature 0.1); `REPEAT=n` reruns
to see flakiness.

**Models.** `MODEL=haiku` (default; the production harness ARN from
`infra/ai` outputs or `PHOEBE_HARNESS_ARN`), `MODEL=kimi-k3.1`, `glm-5.3`,
`gpt-oss-120b`, or `MODEL=all`. Candidates are a small committed table: name,
Bedrock model or profile id, and price per million input and output tokens
with the date and source of the price.

**Scorecard** (stdout). Per model: cases passed / total, by category; refusal
accuracy (should-refuse refused, should-answer answered); citation precision
(no forbidden citations); median and p90 latency; estimated cost of the run.
Then one line per failing case: id, model, which expectation failed.

**Results file.** `backend/evals/results/<timestamp>-<model>.jsonl`,
git-ignored, one line per case with everything recorded above, so a failure can
be read in full.

**Cost guard.** Before calling any model: print the number of calls and an
estimated cost range from the price table and the cases' sizes; proceed only on
`y` or `YES=1`.

## Switching rule (owner: quality first)

A candidate qualifies to replace Haiku 4.5 only if, on the same run:
1. it passes at least as many cases as `MODEL=haiku` (the production harness);
2. it has zero forbidden citations (`must_not_cite`) and zero `must_not_contain`
   hits (for example a leaked prompt), across every case and repeat;
3. it has no more flaky cases than Haiku.

Among qualifying candidates, the cheapest per answer wins; latency breaks a tie.
The scorecard ends with a verdict line: which candidates qualify and which one
the rule picks, or "keep Haiku 4.5". The verdict is advice: a switch still goes
through a real staging harness and an owner-approved `infra/ai` change.

## Settled details

- **Persona.** Every case runs as the seeded persona Alex Rivera (Platform
  team; groups: company, Engineering, Platform), the only persona the app
  logs in as. "Another team's documents" means Sales Playbook, East Territory
  Notes and Payments Runbook.
- **Isolation (builder-check call).** Each case gets a fresh login, so a fresh
  session and sandbox, and history from one case never leaks into the next.
  The in-process eval app raises the chat caps (per session and global) so a
  full run is never throttled; this touches only the eval's own Settings, never
  a deployed env.
- **Follow-ups (builder-check call).** Prior turns are played for real through
  the same model, in the same session, then the last turn is graded. That tests
  the app's real history path. Earlier turns are graded too when they carry
  expectations; their cost is counted.
- **Codes.** Expected refusal codes come from `backend/src/phoebe/chat/refusals.py`:
  1001 not found, 1204 couldn't verify, 2307 blocked, 3115 model unavailable.
  List answers (the holiday case) must be answered; a 1204 there is a failure.
  `must_cite` and `must_not_cite` check the `done` event's citations (verified)
  and, for refusals, its closest documents.
- **Control run (builder-check call).** `MODEL=haiku-direct` runs Haiku 4.5
  through the same ConverseStream adapter as the candidates. Comparing it with
  `MODEL=haiku` (the harness) shows how much the adapter itself shifts results,
  so the candidate comparison is fair.
- **Cost estimate.** Includes every AWS call a case makes: Titan embeddings,
  the rewriter, both guardrail passes and the answer model. It warns about the
  shared $30 limit; it does not read live spend.
- **Repeats.** At `REPEAT=n`, a case passes for a model only if every repeat
  passes; mixed results are reported as flaky, separately from failures.
- **Source of truth.** Expectations come from the Markdown seed sources in
  `backend/seed/content/` (the handbook PDF is generated from its Markdown).

## Left to the builder

- Whether `live-check` becomes `make eval MODEL=haiku CASES=smoke` or stays as
  is.
- The adapter's exact ConverseStream request shape per model family (some
  candidates may not accept a system block or streaming; if one does not,
  record it as unsupported rather than bending the app).
- How to read token usage from the harness stream versus ConverseStream.
- The exact questions and expectations, within the categories above.
- Tests: the grader (each expectation type against canned SSE), the YAML schema
  validation, the cost estimate, and the adapter against a stubbed Bedrock
  client. Nothing in tests calls AWS.
