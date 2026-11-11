# Phoebe: Design

*Date: 2026-11-09. Status: draft, waiting for approval.*
*Derived from `~/Work/job-hunt/projects/groundwork-spec.md`, as revised in the brainstorming conversation. Where this document and that spec disagree, this document wins.*

## 1. Intent

Phoebe is an onboarding portal for new hires. It has two modes: an employee view and an admin view. The center of the employee view is a chat that answers questions from the company's own onboarding documents, using retrieval-augmented generation (RAG), and cites its sources.

It is a **portfolio demo** for recruiters and hiring teams. It is not a production product. It is shared privately through interviews, a resume, and the recruiting process, behind one shared password.

A visitor who spends five minutes in it should come away with two impressions:

1. **"This is RAG, and it works."** Answers are accurate and cited, and the citations follow the document set as it changes. Delete a document in admin and chat stops citing it. Add one and chat can cite it once it is indexed.
2. **"This is a complete, considered product."** Documents and tasks are organized in Company → Department → Team tiers. The employee checks off tasks, and the admin sees each person's progress. Small touches add delight: a mascot, a welcome message, celebrations. It works on mobile and desktop, in every major browser, with a keyboard and with a screen reader.

The technical depth (embeddings, chunking, hybrid search, evals, and the trade-offs between them) lives in the GitHub repo and README, not in the app.

The app runs entirely on AWS, because that is closest to what a client would use. The owner pays for the tokens, so spend protection is a hard requirement.

## 2. Goals, non-goals, anti-goals

**Goals**
- Cited, grounded chat over tiered documents, with a visible link between admin changes and chat behavior.
- A complete onboarding experience: tiered tasks, progress tracking, document library, metadata, delight moments.
- Responsive (phone and desktop), cross-browser (Windows/Chrome/Edge/Firefox, macOS/iOS Safari, Android Chrome), and accessible (WCAG 2.2 AA).
- Secure, with spend capped at every layer, and a kill switch the owner can pull at any time.
- A custom domain for a polished, shareable link, set up end to end in AWS as part of the infrastructure demo (see §5.3).
- Lowest possible standing cost. Target about $5–10 per month at demo usage, nearly $0 when idle.

**Non-goals**
- Rendering original files (such as PDF pages) in the viewer.
- Real accounts, per-person logins, SSO, or Cognito. One shared password. The data model should not make adding accounts later impossible, but nothing gets built for it now.
- An AI tuning UI. The prompt, model, refusal threshold, and citation count are fixed in config and code.
- The MCP server from the original spec. It may be added later.
- Hosting on Cloudflare or mixing cloud providers.
- Multi-region, high availability, or production-scale traffic.

**Anti-goals (failure even if it technically works)**
- Chat cites a document the visitor deleted, or one outside the employee's groups.
- One visitor's changes show up in another visitor's session.
- An uncapped path to Bedrock spend, or any way for a client to choose the model, the token limits, or the tools.
- It looks or behaves broken on a phone or in Safari, or can't be used with a keyboard.
- Cute copy that hides what's going on. Status and error messages say plainly what happened.

## 3. Experience

### 3.1 Entry and identity
- The landing page has a password field, the mascot, and a one-line description.
- The correct password creates a **visitor session**, held in an HttpOnly, Secure, SameSite=Strict cookie. Sessions expire after about 2 hours idle or 24 hours total.
- Every visitor plays the same pre-seeded new hire: **Alex Rivera, Engineering › Platform team**, with a start date, manager, and buddy. Other seeded hires exist so the admin progress view has content (for example Sam Chen, Engineering › Payments, almost done; Priya N., Sales › East, not started).
- On login, the frontend sends a warm-up request so the database wakes from pause (see §5.4). While it wakes, the UI shows "Getting Phoebe ready…".
- On first login in a session, the mascot shows a welcome: "Welcome to the Platform team, Alex!"

### 3.2 Header (both modes)
- Left: mascot and "Phoebe", company name, and in employee mode, Alex's name, team, and start date.
- Right: **Employee | Admin** toggle. A **status pill** appears next to it when limits apply (see §3.5). A small "Reset my demo" action is also here.
- The toggle switches views within the same session. It does not change identity.

### 3.3 Employee mode
**Desktop: three columns.**
- **Left sidebar: Tasks.** A progress bar ("6 of 14 done"), then collapsible groups: Company, Department, Team. Each task has a checkbox, title, and optional description or link. Checking a task persists to the visitor's sandbox.
- **Center: Chat.** Mascot greeting, suggested questions, streaming answers with numbered inline citations, and a source list under each answer. When the docs don't support an answer, Phoebe says it doesn't know and lists the closest documents.
- **Right sidebar: Documents.** Grouped by Company, Department, Team. Each row has a type icon (PDF, Markdown, CSV, web link, Google Doc), title, purpose, and last-updated date. Clicking opens the document viewer. Clicking a citation in chat opens the document scrolled to the cited passage, with the passage highlighted.
- **Document viewer (owner-decided):** a clean text view of the extracted content, rendered by heading sections, not the original file. No PDF rendering. Web pages and Google Docs show the text as captured at indexing time, with a "View original" link out to the live page.
- **Conversation memory (owner-decided):** chat is multi-turn within the visitor session. Follow-ups ("what about part-timers?") use earlier turns. History is stored in the visitor's sandbox and cleared by "Reset my demo" and at session expiry. A follow-up is rewritten into a standalone search query before retrieval. Only the last few turns are sent to the model, and the token caps count history. Old answers whose cited document has since been deleted keep their text, but the citation shows as "source removed".
- Small metadata touches: start date, manager, buddy, day count ("Day 5").

**Mobile:** full-screen chat with bottom tabs **Tasks | Chat | Docs**. Each tab keeps the tier grouping. Tapping a citation opens a bottom sheet with the passage.

**Delight:** welcome splash on first login; confetti when all tasks in a tier are done; an "All done!" badge at 100%. All motion respects `prefers-reduced-motion`.

### 3.4 Admin mode
The layout is vertical tabs on the left, with the content screen on the right. On mobile the tabs collapse into a menu or a horizontal scroller.

1. **People & Progress.** A table of seeded hires: name, department › team, start date, progress bar, count done. Clicking a row shows that person's checklist by tier. Alex's row reflects what the visitor checked in employee mode.
2. **Documents.** A list with title, type, group, purpose, last updated, and status (Processing… / Indexed ✓ / Failed with a reason). Admins can:
   - Add a document by uploading a file (PDF, Markdown, CSV) or pasting a link (public web page, or a Google Doc shared as "anyone with the link").
   - Fill in metadata: title, purpose, last updated, and group (Company, a Department, or a Team).
   - Edit metadata, move a document to another group, or delete it.
3. **Tasks.** Create, edit, delete, and reorder tasks. Each task has a title, an optional description and link, and a group.
4. **Groups.** The org tree: Company → Departments → Teams. Admins can add or rename departments and teams, and see which documents and tasks belong to each.

Admin changes show up in employee mode right away (tasks, docs list). Document changes reach chat as soon as indexing finishes (add) or immediately (delete).

### 3.5 Limits and status
- When a visitor's limit or a global limit is hit, or the kill switch is in `chat_paused`, a **red pill** next to the toggle reads: **"Rate limit exceeded. Please wait for sessions to refresh."**
- Its tooltip (reachable by hover, keyboard focus, and tap) reads: "You can still browse Phoebe and explore the UX. Chat and document upload are paused until limits reset."
- Everything else keeps working: tasks, the document viewer, admin browsing and non-AI edits.
- In the `closed` state, the landing page says the demo is temporarily offline.

## 4. Data model

### 4.1 Groups and visibility
- Groups form a tree: one Company root, then Departments, then Teams. Each document and task belongs to exactly one group.
- A person sees items in their team, that team's department, and the company. Alex sees Company + Engineering + Platform.
- **Chat retrieves only from documents in the employee's visible groups.** If an admin moves a document to the Sales department, Alex's chat stops citing it. This keeps the original spec's principle that permissions are enforced in the retrieval query, not in the prompt.

### 4.2 Sandbox overlay
- **Seed data** (company, groups, people, documents, chunks, tasks, seeded progress) is shared and read-only. Seed rows have `session_id = NULL`.
- **Visitor changes** are rows with `session_id = <visitor session>`: new documents and their chunks, new or edited tasks, new groups, task completions, metadata edits.
- **Edits and deletes of seed items** are stored as per-session overrides: a "hidden" marker for deletes, and an override row for metadata edits or group moves. The effective view is the seed data with the session's overrides applied.
- **The retrieval filter is a single SQL query:** chunks where (seed AND not hidden or moved out of the visible groups by this session) OR (owned by this session), AND the effective group is in the employee's visible groups. Vector and keyword ranking run inside this filter, never before it.
- "Reset my demo" deletes the session's overlay rows. Expired sessions are swept by a scheduled cleanup job (EventBridge → Lambda) that deletes their overlay rows, chunks, and S3 objects.

### 4.3 Documents
- Metadata: title, purpose, last updated, type, group, source (an S3 key or a URL), status, and failure reason.
- Extracted text: the full cleaned text of each document, organized by heading sections, is stored for the viewer. Each chunk records its character offsets in that text so a citation can scroll to the passage and highlight it.
- Chat history: turns (role, text, cited chunk IDs) keyed by session ID.
- Chunks: text, heading path ("Employee Handbook › Leave › PTO"), embedding, full-text vector, document ID, group (denormalized for filtering), and session ID.

## 5. Architecture

```
Browser (React SPA)
   │ HTTPS
   ▼
Route 53 (custom domain) → CloudFront (ACM cert, us-east-1) ── S3 (static SPA)
   │ /api/*
   ▼
Lambda function URL (response streaming) — FastAPI in container (Lambda Web Adapter)
   ├── auth/       password check → session cookie; session + rate counters in DynamoDB
   ├── portal/     groups, people, tasks, documents CRUD (sandbox-aware)
   ├── ingest/     upload → S3 → SQS job
   ├── chat/       retrieve → answer (streamed) → verify citations
   └── control/    kill-switch check on every request
   ▼
SQS + DLQ → worker Lambda: fetch/parse → chunk by heading → embed → upsert chunks
   ▼
Aurora Serverless v2 PostgreSQL + pgvector (min 0 ACU, auto-pause), via RDS Data API
DynamoDB: sessions, rate counters, kill-switch flag
S3: uploaded files (private, encrypted)
Bedrock: Titan Text Embeddings v2; Claude Haiku 4.5 via AgentCore Harness; Guardrail
```

### 5.1 Stack (owner-approved)
- **Frontend:** React + TypeScript + Vite. assistant-ui for chat. Tailwind and Radix primitives for everything else. Static build on S3 + CloudFront.
- **Backend:** Python 3.14, FastAPI, Pydantic, uv. A container image on Lambda using the Lambda Web Adapter, following the phineas `Dockerfile`. arm64, image pinned by digest.
- **Ingestion:** SQS + DLQ + worker Lambda, following the phineas `sqs.tf` / `Dockerfile.worker` pattern.
- **Data:** Aurora Serverless v2 PostgreSQL with pgvector, accessed through the RDS Data API (credentials in Secrets Manager). DynamoDB for sessions, counters, and the kill switch. S3 for uploads.
- **AI:** Titan Text Embeddings v2 for embeddings. Answers come from an AgentCore Harness (phineas `harness.tf` pattern) on Claude Haiku 4.5, with Nova Micro as a cost fallback. A Bedrock Guardrail filters answers.
- **Infra:** Terraform, us-east-2, split into small modules. The budget lives in us-east-1 through the phineas `billing` provider alias.
- **Local dev:** docker compose with Postgres + pgvector and the API. Everything except Bedrock runs offline. Local mode talks to Postgres directly; cloud mode uses the Data API. Both sit behind one repository interface.

### 5.2 Why no VPC
The owner chose cost and simplicity over network isolation. A Lambda inside a VPC needs a NAT gateway (about $32/month standing) or several VPC endpoints to reach Bedrock. The Data API lets Lambda reach Aurora over HTTPS with IAM, so Lambda stays outside a VPC. Aurora still lives in AWS-managed private networking and is not publicly accessible.

### 5.3 Custom domain (owner-decided)
- The owner will register a domain through **Route 53 Domains**. The domain name is not chosen yet, so Terraform takes it as a variable.
- Terraform manages the Route 53 hosted zone, the DNS records (A/AAAA alias to CloudFront), and an **ACM certificate in us-east-1** validated by DNS and attached to the CloudFront distribution. HTTPS only; HTTP redirects to HTTPS.
- The site lives at the apex domain or a subdomain such as `phoebe.<domain>`. The builder decides.
- **Until the domain exists,** everything works on the default `*.cloudfront.net` address. The domain pieces sit behind a Terraform toggle (`domain_name = null` means off), so they can be added later without reworking anything.
- **Must verify before building this part:** CloudFront requires its ACM certificate to be in us-east-1. The project rules allow CloudFront, WAF, and CloudWatch Logs in us-east-1, but they don't explicitly mention ACM. First check that an ACM certificate can be requested in us-east-1 under this project's SCPs. If it can't, ask the owner before choosing a workaround.
- Cost: a hosted zone is $0.50/month, plus the yearly registration fee (about $13–15 for a `.com`). Public ACM certificates are free.

### 5.4 Cost (checked 2026-11-09, us-east-2 list prices)
- Aurora Serverless v2: $0.12 per ACU-hour, $0.10 per GB-month of storage, $0.20 per million I/O requests. At 0 ACU when paused, idle costs only storage (well under $1). Light demo use costs about $4–7 per month. The trade-off is a resume delay of roughly 15 seconds after a pause, which the warm-up call on login hides.
- Compared with RDS db.t4g.micro: about $14 per month, and it can't scale to zero.
- Lambda, CloudFront, S3, DynamoDB, SQS, and EventBridge cost pennies at demo volume. Secrets Manager costs about $0.40 per secret per month.
- Bedrock tokens are the main variable, and the caps in §6 bound them.
- The project is on the Free plan, with $159.92 in credits that expire 2027-03-30. Plan for upgrading or tearing down before then.

## 6. Security and spend protection

**Access**
- One shared demo password, stored as a hash in Secrets Manager. Rotating it cuts off everyone holding the old one. Login attempts are rate-limited per IP.
- Session cookie as described in §3.1. CSRF protection on state-changing requests. Strict CORS (CloudFront origin only). CSP and other security headers set at CloudFront.

**Server-owned AI parameters** (the phineas `bedrock.py` pattern)
- The client never chooses the model, `max_tokens`, temperature, tools, or the system prompt.
- A tool allowlist blocks built-in harness tools.
- Size caps on the question, the retrieved context, and the output.

**Caps** (starting values; the exact numbers are the builder's call, set in config)
- Per session: about 30 chat messages per hour, 5 uploads per day, and at most about 20 sandbox documents.
- Global: a daily cap on chat messages and on uploads across all sessions.
- Uploads: 5 MB max; PDF, Markdown, and CSV only, checked by content as well as extension.
- Link fetches: https only. Block private, link-local, and metadata IP ranges, both after DNS resolution and on every redirect. Size limit, timeout, and a content-type allowlist.
- Lambda reserved concurrency set to a small number.

**Kill switch**
- A DynamoDB flag with three states: `open`, `chat_paused`, `closed`. The API checks it on every request.
- The owner flips it with a script (`make kill` / `make pause` / `make open`).
- An AWS Budgets alert at 80% publishes to SNS, and a small Lambda subscriber sets `chat_paused`.
- Backstop: set Lambda reserved concurrency to 0.

**Content and logs**
- Bedrock Guardrail on answers. Text inside retrieved documents is treated as data. The prompt fences it as untrusted, and the citation verifier rejects answers whose citations don't match retrieved chunks.
- Logs hold metadata only (request ID, session hash, timings, chunk IDs, scores). Never questions or document text.
- All seed data is synthetic. No real company documents.

## 7. RAG pipeline

- **Parsing:** PDF to text, Markdown as is, CSV to row-wise text with headers, web pages and Google Docs to main-content text. Public Google Docs are fetched through their export-as-text URL.
- **Chunking:** split on headings, then by size (about 300–500 tokens with a small overlap). The heading path is stored as metadata and included in the embedded text.
- **Hybrid search:** top 20 by pgvector cosine and top 20 by Postgres full-text search, all inside the visibility and sandbox filter, merged with reciprocal rank fusion. Keep the top 5.
- **Answering:** the question and the top passages (with IDs) go to the model. It must cite passage IDs and may answer only from the passages.
- **Verification:** every cited ID must be one of the retrieved, visible chunks. A failed check produces a refusal or a regenerated answer. The builder decides which, but an uncited claim never reaches the user.
- **Refusal:** if the best fused score falls below a threshold, or verification fails, Phoebe says it doesn't know and lists the closest visible documents. The threshold is tuned on the eval set.
- **Streaming (designer's call):** tokens stream to the client live, and citations are attached when the answer completes. The verifier and Guardrail run on the finished answer. If either fails, the client replaces the streamed text with the refusal message, and the event is logged. This is expected to be rare. It is the accepted trade-off for responsive chat. The anti-goal applies to the final, settled answer.

## 8. Seed content

A fictional company (working name "Acme"; the builder may pick something better), all synthetic:
- **Company:** Employee Handbook (PDF; PTO, benefits, conduct), Benefits Guide (web page), Holiday Calendar (CSV), IT & Security policy (Markdown).
- **Engineering department:** Engineering Practices (Markdown), On-call guide.
- **Platform team:** Team Breakdown (Markdown; who's who), Project Manifest (Google Doc link), first-week schedule.
- **Other departments and teams** (Payments, Sales › East) each get a doc or two, so the "outside your groups" behavior can be demonstrated and tested.
- **Tasks per tier:** for example, Company: sign offer documents, register in the benefits portal, read the handbook. Engineering: laptop setup, security training. Platform: introduce yourself in #platform on Slack, schedule a 1:1 with each teammate.
- At least one seed document contains a planted prompt-injection line, for adversarial evals.
- Hosted copies of the web and Google Doc seed sources must exist. The builder can host them as static pages under CloudFront.

## 9. Quality

- **Tests:** pytest for the domain, sandbox overlay, retrieval filter, ingestion, and verifier. A required **0-leak test**: across sessions and groups, retrieval never returns another session's chunks, hidden chunks, or chunks outside the visible groups.
- **Evals** (repo and CI, not in the app): the golden-set approach from the original spec (answerable, unanswerable, outside-groups, adversarial), recall@5, refusal accuracy, leak rate = 0, and a faithfulness judge that runs in shadow mode first.
- **Cross-browser:** Playwright on Chromium, Firefox, and WebKit, plus mobile viewports (iPhone, Pixel). Manual pass on real iOS Safari and Android Chrome before sharing.
- **Accessibility:** WCAG 2.2 AA. axe checks in Playwright. Keyboard-only and screen-reader passes (VoiceOver). Visible focus. Chat streaming announced politely through a live region.
- **README:** architecture diagram, sandbox and visibility model, eval results, pgvector vs. Bedrock Knowledge Bases vs. Pinecone, cost breakdown, kill switch, and a demo GIF.

## 10. Calls made by the designer (owner to check)

- Seed persona Alex Rivera, Platform team; other seeded hires for the progress view.
- Session lengths of 2 h idle / 24 h max.
- Starting values for the caps.
- assistant-ui for chat; Tailwind + Radix for the UI.
- Claude Haiku 4.5 as the answer model, with Nova Micro as the fallback.
- Mascot: an eastern phoebe (a real songbird), illustrated and friendly.
- Evals live in the repo and CI only; MCP is dropped.
- Link-fetch restrictions as listed in §6.

- Streaming behavior as described in §7: live tokens, with the answer replaced if the check fails.
- Nova Micro fallback is a **manual config switch**, not automatic. It uses a second harness definition. Evals run per model before switching.
- CI is GitHub Actions: tests, lint, and Playwright on every PR, with no Bedrock calls. Evals that call Bedrock run only by manual trigger, through a GitHub OIDC role scoped to the two models, plus a CI-specific token cap. Deploys use local `terraform apply`, as in phineas. The faithfulness judge doesn't block merges until it's calibrated.
- Free plan check: Aurora, Bedrock (including Guardrails), AgentCore, Lambda, CloudFront, DynamoDB, SQS, S3, EventBridge, Secrets Manager, and Budgets are all on the Free-tier supported list. The plan includes a dated reminder before 2027-03-30 to decide whether to upgrade or tear down.

## 11. Left to the builder

- Module boundaries in Python and Terraform, the API route shapes, and the database schema details.
- Exact cap numbers, the refusal threshold, chunk sizes, and the RRF constant.
- PDF and HTML parsing libraries.
- The visual design system (palette, type, spacing) within the stated quality bar, plus the mascot's art and source.
- What a failed citation check does: refuse or regenerate once.
- The name of the fictional company.

## 12. Workflow

The agent writes most of the code. The owner reviews. There is no coaching loop as in phineas.
