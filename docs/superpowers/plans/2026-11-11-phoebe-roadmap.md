# Phoebe Build Roadmap

**Spec:** `docs/superpowers/specs/2026-11-09-phoebe-design.md`

The spec covers five subsystems. Each one gets its own plan. Every plan ends with working, tested software, and later plans plug into the interfaces earlier ones produce.

| # | Plan | Delivers | Depends on |
|---|------|----------|------------|
| 1 | **Backend core** (`2026-11-11-phoebe-01-backend-core.md`) | Local FastAPI + Postgres/pgvector in docker compose. Password login and sessions, sandbox overlay, groups, tasks, progress, documents CRUD, ingestion (MD/CSV/PDF/URL/Google Doc), chunking, hybrid search with the visibility filter, seed company, and 0-leak tests. Uses a deterministic local embedder. No AWS. | none |
| 2 | AI chat & spend safety | Titan embedder, AgentCore Harness answers (Haiku 4.5, plus a manual Nova Micro switch), multi-turn memory with query rewrite, citation verifier, refusal, SSE streaming, Guardrail, per-session and global caps, login throttle, the kill switch, and the `/api/status` endpoint for the red pill. | 1 |
| 3 | Frontend | React/Vite/TS app: landing, employee three-column and mobile tabs, admin vertical tabs, document viewer with passage highlight, assistant-ui chat, delight moments, status pill. Playwright cross-browser and axe tests. | 1, 2 |
| 4 | Cloud | Terraform (us-east-2, budget in us-east-1): ECR, API and worker Lambdas, function URL, CloudFront + S3, Aurora Serverless v2 with the Data API (adds a `DataApiDatabase` adapter), DynamoDB, SQS + DLQ, S3 uploads, Secrets Manager, EventBridge session cleanup, budget → kill-switch Lambda, and the custom domain toggle (verify the ACM-in-us-east-1 SCP first). | 1–3 |
| 5 | Evals & polish | Golden set, metrics script, faithfulness judge (shadow mode), GitHub Actions (no Bedrock on PRs; manual eval workflow through OIDC), README with diagram, trade-offs, cost table, and demo GIF. A dated reminder before 2027-03-30. | 1–4 |

Plans 2–5 are written when their predecessor ships, so they build on real interfaces instead of guesses.

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
  - CI: `PHOEBE_REQUIRE_DB=1` fails when the DB env var is missing.
  - Log `skipped` (not `indexed`) when a doc is deleted mid-index.

**Plan 5 (Evals & polish)**
- HTML `td`/`th` cells run together, which hurts table retrieval. Fix it in the parser before the evals.
