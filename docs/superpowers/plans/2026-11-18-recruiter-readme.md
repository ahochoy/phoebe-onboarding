# Recruiter README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A README that leads with real screenshots and a demo GIF, then the live link, then architecture, trade-offs, evals and cost. Developer material moves to `docs/development.md`.

**Architecture:**
- An owner-run Playwright capture (separate config, `frontend/capture/`) drives staging and writes PNGs and a WebM.
- A small ffmpeg script turns the WebM into `docs/images/demo.gif`.
- The README is rewritten in the order the spec fixes; the old developer sections move verbatim, with stale lines fixed.

**Tech Stack:** Playwright, ffmpeg, Markdown, Mermaid (GitHub-rendered).

**Spec:** `docs/superpowers/specs/2026-11-18-recruiter-readme-design.md`

Branch: `feat/recruiter-readme`.

## Global Constraints

- The password comes only from `PHOEBE_CAPTURE_PASSWORD`. Never write it to the repo, a log, a screenshot filename or the console. I (the agent) never run the capture: the owner does.
- `PHOEBE_CAPTURE_URL` defaults to `https://d3vws9k2ggm24m.cloudfront.net` (staging).
- Capture never runs in CI or `make e2e`: separate config, separate test dir, its own make target `screenshots`.
- Image outputs and sizes:
  - Images go to `docs/images/`: `landing.png`, `employee.png`, `chat-citations.png`, `mobile.png` and `demo.gif`.
  - Desktop stills are 1280x800 at deviceScaleFactor 2. The phone is the `iPhone 15` device.
  - `demo.gif` runs 15 seconds or less at about 12 fps, 800 px wide, and is under 5 MB.
- The question for the chat shots is `What holidays do we have in November and December?`.
- Each capture context resets its sandbox (`POST /api/reset` with `X-Phoebe-Csrf: 1`) when done.
- The live link is `https://phoebe-onboarding.hochoy.dev`, with the copy "password provided with this link".
- Measured cost, gross, 2026-11-01 to 2026-11-17, staging and production:
  - Aurora $0.96
  - AgentCore $0.47
  - Secrets Manager $0.07
  - Haiku tokens $0.04
  - other about $0.03
  - total $1.57
- Eval numbers, from the 2026-11-18 runs:
  - converse: 9/9 fact cases, p50 1.5 s, p90 1.9 s
  - harness: 9/9, p50 4.0 s, p90 6.5 s
- Docs are written in plain, short sentences. No marketing superlatives.

## Review Focus

1. **Password unset or empty.** `make screenshots` stops before launching a browser, with a message naming `PHOEBE_CAPTURE_PASSWORD`.
2. **Staging paused or closed.** The SpendBanner or offline copy shows, and the answer never settles. The capture fails with a clear timeout rather than committing an image of an error. `settledAnswer` already fails on an error line, so reuse it.
3. **Missing ffmpeg, or no WebM because the capture failed.** `to-gif.sh` exits non-zero with a message and leaves any existing `demo.gif` untouched.
4. **A GIF over 5 MB.** `to-gif.sh` fails and names the size, so an oversized GIF is never silently committed.
5. **Broken README links after the move.** Every relative link and image path in `README.md` and `docs/development.md` resolves to a file in the repo.

---

### Task 1: Capture script and `make screenshots`

**Files:**
- Create: `frontend/playwright.capture.config.ts`
- Create: `frontend/capture/readme.capture.ts`
- Modify: `frontend/tsconfig.e2e.json` (add `capture` and `playwright.capture.config.ts` to `include`)
- Modify: `Makefile` (target `screenshots`, add to `.PHONY`)
- Modify: `.gitignore` (add `frontend/capture-output`)

**Interfaces:**
- Consumes: from `frontend/e2e/fixtures.ts`: `test`, `expect`, `loggedIn`, `ask`, `citationButtons`, `showPanel`, `submitPassword`, `resetDemo`. `loggedIn` reads `PHOEBE_DEV_PASSWORD`; the make target sets it from `PHOEBE_CAPTURE_PASSWORD`.
- Produces: the PNGs in `docs/images/`, plus `frontend/capture-output/demo.webm` for Task 2.

- [ ] **Step 1: The config.** `testDir: "./capture"`, `testMatch: /\.capture\.ts$/`, `workers: 1`, `retries: 0`, timeout 120 s, no `webServer`, reporter `list`. `use.baseURL` is `process.env.PHOEBE_CAPTURE_URL ?? "https://d3vws9k2ggm24m.cloudfront.net"`. Two projects:
  - `desktop`: `Desktop Chrome`, viewport 1280x800, `deviceScaleFactor: 2`, `reducedMotion: "reduce"`.
  - `phone`: `iPhone 15` on chromium (`defaultBrowserType: "chromium"`), `reducedMotion: "reduce"`.
- [ ] **Step 2: The capture tests** in `readme.capture.ts`. Save with `page.screenshot({ path })` to `../docs/images/<name>.png`, resolved from `import.meta.url`.
  - `landing` (desktop): `goto("/")`, wait for the "Demo password" field, then screenshot.
  - `employee` (desktop): `loggedIn`, then screenshot.
  - `chat-citations` (desktop): `loggedIn`, then `ask(HOLIDAYS)`. Click the first `citationButtons(answer)` and wait for the document viewer's highlighted passage, then screenshot.
  - `mobile` (phone): `loggedIn`, `showPanel(page, "Chat")`, `ask(HOLIDAYS)`, then screenshot.
  - `demo video` (desktop): `browser.newContext({ recordVideo: { dir, size: { width: 1280, height: 800 } }, viewport: { width: 1280, height: 800 } })` with normal motion. Steps:
    1. Log in through the landing page: `submitPassword` and close the welcome splash.
    2. Call `resetDemo`, then `page.reload()`.
    3. Ask `HOLIDAYS`, open the first citation, and wait 1.5 s.
    4. Reset the sandbox again, close the context, and `video.saveAs("capture-output/demo.webm")`.
  - The fixture `test` resets the other contexts. The video context is created by hand, so it resets itself in a `finally`.
- [ ] **Step 3: The Makefile target.**
  ```make
  # Owner-run: README screenshots and demo video from staging (costs about a cent of Bedrock).
  screenshots:
  	@test -n "$$PHOEBE_CAPTURE_PASSWORD" || { echo "Set PHOEBE_CAPTURE_PASSWORD (the staging demo password)." >&2; exit 2; }
  	cd frontend && PHOEBE_DEV_PASSWORD="$$PHOEBE_CAPTURE_PASSWORD" npx playwright test -c playwright.capture.config.ts
  	frontend/capture/to-gif.sh frontend/capture-output/demo.webm docs/images/demo.gif
  ```
- [ ] **Step 4: Verify.**
  - `env -u PHOEBE_CAPTURE_PASSWORD make screenshots` exits 2 with that message and launches no browser.
  - `make fe-lint` is clean.
  - `cd frontend && npx playwright test -c playwright.capture.config.ts --list` lists the 5 tests.
  - `make e2e`'s config still does not list them: `npx playwright test --list | grep -c capture` prints 0.
- [ ] **Step 5: Commit.** `feat(docs): owner-run README capture against staging`.

### Task 2: WebM to GIF

**Files:**
- Create: `frontend/capture/to-gif.sh` (executable, `set -euo pipefail`)
- Test: `frontend/capture/to-gif.test.sh`

**Interfaces:** `to-gif.sh <input.webm> <output.gif>`. It exits 0 and writes the output, or exits non-zero and leaves the output untouched.

- [ ] **Step 1: The failing test** `to-gif.test.sh`. It uses a temp dir and generates a 3 s clip with `ffmpeg -f lavfi -i testsrc=size=1280x800:rate=30 -t 3 in.webm`. Then:
  1. Run `to-gif.sh in.webm out.gif`. Assert exit 0, `out.gif` exists, and `ffprobe` reports width 800.
  2. Run `to-gif.sh missing.webm out2.gif`. Assert non-zero and that `out2.gif` is absent.
  3. Run it with `MAX_BYTES=1` and an existing `keep.gif`. Assert non-zero, a message containing "MB", and `keep.gif` unchanged.
- [ ] **Step 2:** Run `bash frontend/capture/to-gif.test.sh`. Expected: FAIL (script missing).
- [ ] **Step 3: Implement `to-gif.sh`.**
  - Check that `ffmpeg` exists and the input exists.
  - Do a two-pass palette conversion into a temp file:
    - `fps=12,scale=800:-1:flags=lanczos,palettegen=stats_mode=diff`
    - `paletteuse=dither=bayer:bayer_scale=5`
    - `-t 15`
  - Check the size against `MAX_BYTES` (default 5000000), then `mv` the temp file over the output only on success.
- [ ] **Step 4:** Rerun the test. Expected: PASS. Run `shellcheck` on both scripts if it is installed.
- [ ] **Step 5: Commit.** `feat(docs): convert the capture video to a README GIF`.

### Task 3: Move developer docs to `docs/development.md`

**Files:**
- Create: `docs/development.md`
- Modify: `README.md` (remove the moved sections; Task 4 rewrites the rest)

- [ ] **Step 1: Move these sections verbatim**: Local quickstart, Frontend, End-to-end tests, Configuration, Chat refusal codes, Evals. Add a short "README screenshots" section for `make screenshots`, `PHOEBE_CAPTURE_PASSWORD` and `PHOEBE_CAPTURE_URL`.
- [ ] **Step 2: Fix stale lines while moving.**
  - Evals: "`haiku` is the production harness" becomes "`haiku` is the production config (Haiku 4.5 through direct Bedrock ConverseStream)". "`make eval` # the production Haiku harness only" becomes "# the production config only".
  - E2E: "Playwright runs locally for now; it joins CI in Plan 5" stays as is.
  - Remove the Configuration intro sentence that says these settings "were added for AI chat"; keep the table.
  - Grep the moved text for `harness` and keep only the rollback-path mentions.
- [ ] **Step 3: Verify links.** For every relative link and image in both files, check that the target exists: `grep -oE '\]\(([^)#]+)' README.md docs/development.md`, then test each path, resolved from its file's dir.
- [ ] **Step 4: Commit.** `docs: move developer docs to docs/development.md`.

### Task 4: Recruiter README

**Files:** Modify: `README.md`.

- [ ] **Step 1: Write the sections in the spec's order (1–11).**
  - Images:
    - `![Phoebe demo](docs/images/demo.gif)` near the top.
    - The four stills in a 2x2 Markdown table, each with alt text that describes it.
  - Architecture: one ` ```mermaid ` `flowchart LR` with the nodes and edges listed in spec item 5. Group them into subgraphs: Edge, API, Data, AI, Ops.
  - Trade-offs, about two to four sentences each:
    - pgvector, rather than Knowledge Bases or Pinecone;
    - direct Bedrock, rather than AgentCore (cite 1.5 s against 4.0 s p50, and the $0.47);
    - the Data API, rather than a VPC with a NAT gateway (about $32/month standing);
    - Aurora scaling to zero, versus the resume delay of about 15 s.
  - Evals: a table with the model path, pass count, p50 and p90, from Global Constraints. One line on how grading works (deterministic, no AI judge). Link to `docs/development.md#evals`.
  - Cost:
    - A measured table from Global Constraints, with the note "credits covered all of it; AgentCore is now $0".
    - A list-price estimate for idle and for light demo use. Use the Aurora, storage and Secrets Manager rates from the design spec §5.4. Take Haiku 4.5 token prices from the Bedrock pricing page on the day of writing, and cite page and date. If the page can't be read, give the token line as "bounded by the chat caps" with no number.
- [ ] **Step 2: Verify.**
  - Rerun the Task 3 link check.
  - `grep -n "larkspur-demo" README.md` finds nothing in the recruiter sections. The dev password stays only in `docs/development.md`, as the local default.
  - Push the branch and open the README on GitHub, to confirm the Mermaid renders.
- [ ] **Step 3: Commit.** `docs: recruiter README with images, architecture, evals and cost`.

### Task 5 (owner): capture and commit the images

- [ ] The owner runs `PHOEBE_CAPTURE_PASSWORD=… make screenshots` with staging open.
- [ ] The agent checks the outputs:
  - all five files exist;
  - the PNGs are 2560x1600 (desktop at 2x);
  - the GIF is under 5 MB and 800 px wide;
  - the agent views each PNG and confirms there is no error banner and no password text.
- [ ] Commit `docs/images/*` as `docs: README screenshots and demo GIF`, then open the PR.
