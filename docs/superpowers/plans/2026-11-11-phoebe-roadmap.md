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
