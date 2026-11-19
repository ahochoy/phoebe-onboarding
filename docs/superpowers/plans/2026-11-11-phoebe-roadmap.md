# Phoebe Build Roadmap

**Spec:** `docs/superpowers/specs/2026-11-09-phoebe-design.md`

The spec covers five subsystems. Each one gets its own plan. Every plan ends with working, tested software, and later plans plug into the interfaces earlier ones produce.

| # | Plan | Delivers | Depends on |
|---|------|----------|------------|
| 1 | **Backend core** (`2026-11-11-phoebe-01-backend-core.md`) | Local FastAPI + Postgres/pgvector in docker compose. Password login and sessions, sandbox overlay, groups, tasks, progress, documents CRUD, ingestion (MD/CSV/PDF/URL/Google Doc), chunking, hybrid search with the visibility filter, seed company, and 0-leak tests. Uses a deterministic local embedder. No AWS. | none |
| 2 | AI chat & spend safety | Titan embedder, AgentCore Harness answers (Haiku 4.5, plus a manual Nova Micro switch), multi-turn memory with query rewrite, citation verifier, refusal, SSE streaming, Guardrail, per-session and global caps, login throttle, the kill switch, and the `/api/status` endpoint for the red pill. GitHub Actions CI (tests + lint, no Bedrock). | 1 |
| 3 | Frontend | React/Vite/TS app: landing, employee three-column and mobile tabs, admin vertical tabs, document viewer with passage highlight, assistant-ui chat, delight moments, status pill. Playwright cross-browser and axe tests. | 1, 2 |
| 4 | Cloud | Terraform (us-east-2, budget in us-east-1): ECR, API and worker Lambdas, function URL, CloudFront + S3, Aurora Serverless v2 with the Data API (adds a `DataApiDatabase` adapter), DynamoDB, SQS + DLQ, S3 uploads, Secrets Manager, EventBridge session cleanup, budget → kill-switch Lambda, and the custom domain toggle (verify the ACM-in-us-east-1 SCP first). | 1–3 |
| 5 | Evals & polish | Golden set, metrics script, faithfulness judge (shadow mode), manual eval workflow through OIDC; Playwright job added to CI, README with diagram, trade-offs, cost table, and demo GIF. A dated reminder before 2027-03-30. | 1–4 |

Plans 2–5 are written when their predecessor ships, so they build on real interfaces instead of guesses.

## Plan 5 working list (agreed 2026-11-17, in order)

Items are brainstormed and planned one at a time; each ships as its own PR.

1. **Spend-limit mode.** Done (#19, #20; `v0.1.2`). Degrade at 70% of the budget, close and email on a stopped database, `make db-start`.
2. **Evals.** Done (#21; follow-up #23). `make eval`; first run 2026-11-18: Haiku harness 9/9 facts; the verdict was to keep Haiku 4.5.
3. **README for recruiters.** Done (live link, architecture diagram, cost table, demo GIF). Docs cleanup 2026-11-18: infra READMEs rewritten against the code, planning ids (Task N, R-rulings) removed from comments.
4. **Answer-model switch: closed 2026-11-18, keep Haiku 4.5.** Haiku 5.5 and GLM-5.3 are not available to the account. On the fact cases, Kimi K3.1 matched Haiku (9/9), and gpt-oss-1205. **Direct Bedrock answers instead of the AgentCore harness.** Done (`v0.1.5`): production answers through ConverseStream at about a third of the harness latency. Remaining: remove the harnesses and the `harness` backend.
 for Phoebe's visibility model. The harnesses stay for one release as the rollback path, then a follow-up removes them.
6. **Smaller first page load:** the frontend bundle is 334 KB gzipped; split it with code-splitting.
7. **Safety and copy polish:**
   - a production guard on `reseed`;
   - an upload size hint;
   - numeric codes for general API errors in `messages.ts`;
   - use the `--color-highlight` token.
8. **Flakes and live checks:**
   - the Vitest Landing flake (fixed in #20, so watch it);
   - the IPv6 login throttle, checked by hand;
   - R26 (idle stays idle) after about 25 hours without traffic.
9. **Plan 4 deferred minors**, then delete the Plan 4 workspace.

Cost levers already applied (#22): Aurora at most 1 ACU, a 60 s harness idle timeout, and `make db-stop`.

## Carry-forward notes from Plan 1 final review

**Plan 2 (AI chat & spend safety)**
- Log `sandbox_id[:12]` everywhere, so middleware and domain log hashes correlate.
- Add per-IP login throttling.
- Add per-session upload and chat caps.

**Plan 3 (Frontend)**
- Skip the login screen when `/api/me` succeeds: re-login wipes the sandbox.
- `TaskPatch` and `DocumentPatch` need clear-field semantics (use `model_fields_set`).
- Clamp `day_number`.
- Two vocabularies: API `detail` is a snake_case code; `failure_reason` and the 415 `reason` are human sentences.
- Use `DocStatus` for typegen.
- Character offsets are Python code points. Convert them to UTF-16 indices for highlighting.

**Plan 4 (Cloud)**
- Data API:
  - Verify the result-size cap (thought to be 1 MiB). Cap or offload `full_text` for `get_document`.
  - Array params (`:gids::text[]`, `:groups::text[]`) need a literal or JSON workaround.
  - Add typeHints for uuid and date params.
  - `id::text = :id` defeats the PK index.
- Blob and filesystem:
  - Add an S3 blob backend. `create_configured_app` runs `mkdir` on `blob_dir` at import, which fails on Lambda's read-only filesystem, so add a `blob_backend` setting.
  - `S3BlobStore` must not raise `ValueError` for transient errors.
- Background jobs:
  - Sweeper (EventBridge → Lambda): purge sandboxes whose `last_seen` is older than 24 h (rows, chunks and blobs). Also mark `processing` docs older than N minutes as failed. The `sandboxes` table (migration 002) is the registry; its `id` equals the session-store key.
  - DLQ consumer: `mark_failed("Indexing timed out")`. The no-in-process-PDF-timeout ruling requires it.
- Deploy and ops:
  - Take a migration advisory lock (`pg_advisory_xact_lock`).
  - Re-seed runbook: wipe all sandboxes first, because `load_seed` breaks once visitors exist.
  - Log `skipped` (not `indexed`) when a doc is deleted mid-index.

**Plan 5 (Evals & polish)**
- HTML `td`/`th` cells run together, which hurts table retrieval. Fix it in the parser before the evals.

## Carry-forward notes from Plan 2 final review

**Plan 3 (Frontend)**
- On every `done` event, replace the streamed text with `done.text`. Streamed deltas carry raw `[P3]` labels; `done.text` and `citations[].n` are renumbered.
- Polling `GET /api/status` refreshes the session's `last_seen`, so an open tab keeps the session alive past the 2 h idle timeout. Pick a polling interval (or stop polling when the tab is hidden) with that in mind.

**Plan 4 (Cloud)**
- The sweeper must also purge `chat_turns` for expired sandboxes.
- Configure Python logging in the Lambda image. Today no `phoebe.*` INFO lines reach the container log.
- Trust `cloudfront-viewer-address` (`PHOEBE_CLIENT_IP_HEADER`) only when the origin is reachable through CloudFront alone (origin secret header or a restricted function URL). Otherwise the login throttle can be bypassed by forging the header.
- `infra/ai` resource names are stable; move them into the module layout with `moved {}` blocks, not a rebuild. Terraform reads `backend/prompts/answer.txt` from the repo, not from the image.
- Check whether idle AgentCore runtime sessions are billed. Each chat uses a fresh `runtimeSessionId` with a 1800 s idle timeout.
- When `PHOEBE_ANSWER_BACKEND=harness`, require `PHOEBE_GUARDRAIL_ID` and `PHOEBE_GUARDRAIL_VERSION` in the deployed config.

## Follow-up: switch the answer model to Claude Haiku 5.5

Do this before Plan 3 ships the chat UI.
- Account prerequisites (owner): submit the Anthropic use case form in the Bedrock console and confirm a payment method in AWS Settings. On 2026-11-15, `us.anthropic.claude-haiku-5-5` returned "not available for this account", and `GetUseCaseForModelAccess` reported that the form had not been filled out.
- `infra/ai`: set the Haiku Harness model to `us.anthropic.claude-haiku-5-5`, then update the IAM foundation-model and inference-profile ARNs to match.
- Remove `temperature = 0.1`: Haiku 5.5 rejects non-default sampling parameters.
- Thinking is on by default. Set effort `low` through the Harness `additionalParams`, and verify that it reaches the model.
- Raise `maxTokens` to leave room for thinking.
- Re-tune `answer_max_chars` and the caps, because the newer tokenizer counts about 30% more tokens.
- Rerun `make live-check` on Haiku 5.5. Then update the spec, Plan 2 and `infra/ai/README.md`, which currently name Haiku 4.5.

## Carry-forward notes from Plan 3 final review

**Plan 4 (Cloud)**
- Fix before the link is shared publicly. A first-time visitor who opens `/employee` directly sees "Your session ended…", because the backend sends `session_expired` when there is no cookie. Show that copy only when this tab previously had a session (a sessionStorage marker), or add a distinct backend code.
- The CSP can stay `default-src 'self'`. Confetti already runs without a `blob:` worker, and fonts are self-hosted.
- Serve the SPA with `/api/*` going to the function URL and every other path falling back to `index.html`. A 200 HTML answer on an `/api` path surfaces as a generic error in the client.
- E2E needs `make stack-e2e`, which raises the login, chat and upload caps through compose env. A deployed demo keeps the real caps.

**Plan 5 (Evals & polish)**
- Add Playwright to CI. Recheck the WebKit keyboard test's Alt+Tab workaround on Linux runners. Consider `--repeat-each` on `chat.spec.ts` to catch flakes.
- Add a live-model e2e (manual trigger) that proves the refusal path renders in a real browser. Offline models almost never refuse, so the offline suite checks only that no out-of-group document is cited.
- Do the manual passes from spec §9: real iOS Safari (including the on-screen keyboard over the chat composer, since `h-dvh` does not shrink for it), Android Chrome and VoiceOver.
- Chat history dedupe by id is ineffective: local ids are not server ids. Keep the meta `turn_id` as the local assistant id, so a slow history GET can't show a new turn twice.
