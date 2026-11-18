# Recruiter README Design

Plan 5, item 3. Owner decisions are marked *(owner)*; the rest are the designer's calls.

## Intent

A recruiter or hiring manager opens the public repo. They already hold the demo password *(owner)*, but the README should save them time: they should understand what Phoebe does and how it is built without logging in. So the page leads with images, then the live link, then the rest *(owner)*.

## Goals

- Images first: a short GIF of a real chat answer with citations, then still screenshots.
- The live link right after the images. The password is never written in the repo; the README says it comes with the link.
- Then, for readers who keep going: what it does, an architecture diagram, the main trade-offs, permission-aware retrieval, spend safety, eval results, and a monthly cost table.
- Developer material (quickstart, end-to-end tests, the config table, refusal codes, evals how-to) moves to `docs/development.md`, linked from the README.

## Non-goals

- No new app features. No marketing site.
- Capture does not run in CI or in `make e2e`.

## Approaches (owner picked 1)

1. **Playwright capture script against staging** *(owner)*. Real Haiku answers, rerun in one command after a UI change. Costs about a cent of Bedrock per run.
2. The same script against the local stack: free, but the offline extractive answers undersell the chat.
3. Manual captures: no code, nothing to rerun, inconsistent framing.

## Capture

- `frontend/playwright.capture.config.ts`, separate from the e2e config, with test dir `frontend/capture/`. No `webServer`.
- `baseURL` comes from `PHOEBE_CAPTURE_URL`, defaulting to staging (`https://d3vws9k2ggm24m.cloudfront.net`). The password comes only from `PHOEBE_CAPTURE_PASSWORD`; the script fails fast without it and never logs it.
- `make screenshots` runs the capture and then converts the video to a GIF with ffmpeg (two-pass palette, about 12 fps, 800 px wide). Output goes to `docs/images/`, and the files are committed.
- Stills (desktop 1280x800 at device scale 2; phone is an iPhone 15):
  1. `landing.png`: the landing page with the mascot.
  2. `employee.png`: the employee view (tasks, chat, docs).
  3. `chat-citations.png`: an answer to the holiday question with its citations, and the cited document open at the highlighted passage.
  4. `mobile.png`: the chat tab on the phone.
- `demo.gif`: log in, ask the holiday question, the answer streams with citations, open a citation. 15 seconds or less, and under 5 MB.
- Stills use reduced motion. The video keeps normal motion.
- Each context resets its sandbox when done, as the e2e fixtures do. That is three logins, well inside the login throttle.

## README order

1. Title, a one-line pitch, `demo.gif`.
2. The four stills in a 2x2 table.
3. **Live demo:** `https://phoebe-onboarding.hochoy.dev`, "password provided with this link". The tech line is FastAPI, pgvector, React, Bedrock (Claude Haiku 4.5) and Terraform.
4. **What it does:** personas and groups, a private sandbox for uploads and links, cited answers, refusals.
5. **Architecture:** a Mermaid diagram:
   - Browser → CloudFront (S3 SPA, `/api` → Lambda function URL);
   - API Lambda → Aurora Serverless v2 with pgvector, through the Data API (no VPC);
   - API Lambda → DynamoDB (sessions, caps, kill switch);
   - API Lambda → Bedrock: Haiku 4.5 ConverseStream, the Guardrail, Titan v2 embeddings, and the Nova Micro rewriter;
   - SQS → indexer Lambda;
   - Budget → SNS → budget Lambda (chat paused);
   - RDS stop event → closed;
   - CodePipeline (tag → plan → approve → apply).
6. **Trade-offs:**
   - pgvector rather than Bedrock Knowledge Bases or Pinecone (visibility filter in SQL, scale to zero);
   - direct Bedrock rather than the AgentCore harness (latency and cost, with the eval numbers);
   - the Data API rather than a VPC with a NAT gateway;
   - Aurora scaling to zero, versus resume delay.
7. **Permission-aware retrieval:** the sandbox overlay, the group visibility filter, and the required 0-leak test.
8. **Spend safety:**
   - per-session and global caps;
   - the kill switch;
   - degrade at 70% of the $30 budget;
   - close and email on a stopped database.
9. **Evals:** what is graded, and a small results table. Use the 2026-11-18 run: Haiku through ConverseStream, 9/9 fact cases, p50 1.5 s, p90 1.9 s. Also include the harness comparison: 9/9, p50 4.0 s.
10. **Cost:**
    - Measured, from Cost Explorer: gross spend 2026-11-01 to 11-17 for staging and production, by service. Total $1.57; Aurora $0.96, AgentCore $0.47 (now $0), Secrets Manager $0.07, Haiku tokens $0.04, other about $0.03.
    - An estimate at list prices for idle and light use. Note that the remaining AgentCore line goes away.
11. **Development:** a link to `docs/development.md` and to the design spec.

Stale lines are fixed while moving them. For example, "`haiku` is the production harness" becomes "`haiku` is the production config (direct Bedrock)".

## Left to the builder

- The exact copy and the wording of the trade-offs.
- Which citation to click in the GIF.
- Mermaid layout details.
