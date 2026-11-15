# Phoebe Plan 3: Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the visitor-facing Phoebe web app on the Plan 1 and 2 API. It covers the landing page, the employee three-column view (mobile tabs), the admin vertical tabs, the document viewer with passage highlight, cited streaming chat, delight moments and the status pill. Everything is tested in Chromium, Firefox and WebKit, and with axe.

**Architecture:**
- `frontend/` is a static React app built with Vite. It talks to the existing FastAPI backend over `/api` only.
- In dev and in end-to-end tests, Vite proxies `/api` to the local stack, so the app and the API share one origin. The `SameSite=Strict` session cookie and the CSRF header then work unchanged. In Plan 4, CloudFront gives the same single origin.
- API types are generated from the backend's OpenAPI document. That document is exported to `frontend/openapi.json` and checked for drift in both test suites.
- Server state lives in TanStack Query. Chat state is a small reducer of our own, exposed to assistant-ui through `useExternalStoreRuntime`. We own the stream, so we can always replace the streamed text with `done.text`.

**Tech Stack:**
- Node: current Active LTS, recorded in `frontend/.nvmrc`. Package manager: npm, with a committed `package-lock.json`.
- App: React 19, TypeScript (strict), Vite.
- Styling and components: Tailwind CSS v4 (`@tailwindcss/vite`), Radix primitives (`radix-ui`), `lucide-react` icons, `@fontsource-variable/inter` (self-hosted).
- Data and routing: `@tanstack/react-query`, `react-router` (library mode).
- Chat: `@assistant-ui/react`.
- Delight: `canvas-confetti`.
- Tooling: `openapi-typescript`. Vitest with Testing Library and MSW. Playwright with `@axe-core/playwright`. ESLint (typescript-eslint, react-hooks, jsx-a11y). Prettier.
- Install the latest stable version of each package. Pin them through the lockfile and never use `latest` in `package.json`.

**Spec:** `docs/superpowers/specs/2026-11-09-phoebe-design.md`:
- §3: experience, all subsections.
- §4.1: visibility.
- §6: CSP-friendly frontend, no client choice of AI parameters.
- §7: streaming behaviour.
- §9: cross-browser and accessibility.

Also read the Plan 3 bullets under both "Carry-forward notes" sections, and the "Follow-up: Haiku 5.5" section, in `docs/superpowers/plans/2026-11-11-phoebe-roadmap.md`. The Haiku follow-up is **not** in this plan's scope.

## Global Constraints

**Commands**
- Run everything from the repo root.
- Backend: `make test`, `make lint`.
- Frontend: `make fe-install`, `make fe-test` (Vitest), `make fe-lint` (tsc, ESLint, Prettier check), `make fe-build`.
- End-to-end: `make e2e`. It needs `make stack` running, then it builds and serves the app and runs Playwright.
- All of these must be clean at every commit.

**Local setup**
- Vite dev server port: `5173`. Proxy `/api` to `http://localhost:${PHOEBE_PORT:-8080}`.
- The demo password comes from `PHOEBE_DEV_PASSWORD` (Makefile default `larkspur-demo`). Never hard-code it in `src/`. Playwright reads it from the environment.

**API conventions**
- Every non-GET request sends the header `X-Phoebe-Csrf: 1`. Requests use `credentials: "same-origin"`.
- There are two error vocabularies:
  - API `detail` is a snake_case code. Map it to copy in `frontend/src/lib/messages.ts` only.
  - The 415 `reason` and a document's `failure_reason` are human sentences. Show them verbatim.
- The client never sends a model id, token limit, temperature, tools, prompt, `k` or threshold. Chat sends only `{"question": string}`.
- Character offsets from the API are Python code points. Convert them with `cpToUtf16` before slicing or highlighting.

**Copy fixed by the spec (verbatim)**
- Status pill: **"Rate limit exceeded. Please wait for sessions to refresh."**
- Pill tooltip: **"You can still browse Phoebe and explore the UX. Chat and document upload are paused until limits reset."**
- Warm-up message: **"Getting Phoebe ready…"**
- Welcome message: **"Welcome to the {team_name} team, {first name}!"**. For Alex this is "Welcome to the Platform team, Alex!".
- Task progress: **"{done} of {total} done"**. Badge at 100%: **"All done!"**
- Closed-state landing (designer's wording): **"The Phoebe demo is temporarily offline. Please check back later."**
- Removed citation label: **"source removed"**.

**Quality bar**
- WCAG 2.2 AA:
  - Visible focus on every interactive element.
  - Targets at least 24×24 CSS px.
  - Colour contrast ≥ 4.5:1 for text.
  - Every dialog traps and returns focus (Radix does this).
- All motion is disabled under `prefers-reduced-motion: reduce`, confetti included.
- Breakpoint: `md` (768px). Below it, the employee view is mobile tabs and admin tabs become a horizontal scroller.
- No inline `<script>`, no `eval`, no third-party origins at runtime (fonts are self-hosted). Plan 4's CSP can then be `default-src 'self'`.
- Logs: the frontend never `console.log`s question or answer text.

**Git**
- One feature branch, `feat/frontend`.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never work around a blocked command or hook. Stop and report instead.

## Review Focus

These five inputs are the most likely to hurt a real visitor that no feature test would otherwise exercise. Each has a pinned test in the task named.

1. **SSE bytes split anywhere.** A frame, a `\n\n` separator or a multi-byte UTF-8 character can be cut across `read()` chunks. The parser must still produce the same events. *Pinned in Task 6* (`sse.test.ts`: byte-by-byte feed).
2. **Non-BMP text before a citation.** An emoji (🎉) or other astral character before the cited span shifts UTF-16 indices. The highlight must cover exactly the cited text. *Pinned in Task 5* (`offsets.test.ts` and `DocumentViewer.test.tsx`).
3. **Session expires mid-use.** Any call can return 401 `session_expired`, including the chat stream. The app returns to the landing page with "Your session ended. Enter the password to start again." It never shows a half-broken screen. *Pinned in Task 3* (`session.test.tsx`).
4. **Double actions.** Pressing Enter twice in chat, or rapid checkbox clicks, must produce one request in flight and a final state that matches the server. *Pinned in Task 4* (rapid toggles) and *Task 6* (send is disabled while running).
5. **Limits hit mid-session.**
   - `429 too_many_attempts` or `503 chat_paused` from chat or upload turns the pill on (refetch `/api/status`).
   - The chat composer and upload controls disable, with the tooltip copy beside them.
   - Tasks and the viewer keep working.
   - *Pinned in Task 6* (chat) and *Task 9* (upload).

---

### Task 1: Backend contract for the frontend

**Files:**
- Create: `backend/src/phoebe/chat/events.py`, `backend/src/phoebe/api/openapi_export.py`, `backend/tests/test_openapi_contract.py`, `frontend/openapi.json`
- Modify:
  - `backend/src/phoebe/api/routes_status.py`, `routes_documents.py`, `routes_portal.py`, `routes_auth.py`
  - `backend/src/phoebe/chat/service.py` (payload via models)
  - `backend/src/phoebe/tasks.py`, `backend/src/phoebe/documents.py` (patch semantics)
  - `backend/src/phoebe/__main__.py` (`openapi` command)
  - `backend/tests/test_tasks*.py`, `test_documents*.py` (new cases)

**Interfaces:**
- Produces:
  - `StatusOut(state: Literal["open","chat_paused","closed"], chat_available: bool, upload_available: bool, reasons: list[Literal["chat_paused","demo_closed","session_chat_limit","global_chat_limit","session_upload_limit","global_upload_limit"]])`. These are exactly the strings `routes_status.py` emits today, and the wire JSON must not change.
  - Response models with Literal fields:
    - `DocumentOut.status: DocStatus` and `.doc_type: DocType`.
    - `GroupNode.kind`, `DocumentOut.group_kind` and `TaskView.group_kind`: `Literal["company","department","team"]`.
    - `TurnOut.role: Literal["user","assistant"]`.
  - In `chat/events.py`:
    - `MetaEvent(turn_id: str)`
    - `DeltaEvent(text: str)`
    - `ClosestDoc(document_id: str, title: str)`
    - `DoneEvent(text: str, refused: bool, reason: Reason | None, citations: list[Citation], closest: list[ClosestDoc])`
    - `ErrorEvent(code: str)`
  - `python -m phoebe openapi` prints `app.openapi()` to stdout, with the four event schemas merged under `components.schemas`, keys sorted and indented by 2.

- [ ] **Step 1: Write the failing tests**
  - `test_openapi_contract.py::test_committed_schema_matches_app`: `json.loads(Path("frontend/openapi.json").read_text()) == export_openapi()`. Make the failure message say `run: uv run python -m phoebe openapi > frontend/openapi.json`.
  - `test_openapi_contract.py::test_event_schemas_present`: `{"MetaEvent","DeltaEvent","DoneEvent","ErrorEvent","StatusOut"} <= set(schema["components"]["schemas"])`.
  - `test_openapi_contract.py::test_doc_status_is_enum`: `schema["components"]["schemas"]["DocumentOut"]["properties"]["status"]` carries `enum == ["processing","indexed","failed"]`, directly or through a `$ref`.
  - `test_patch_null_clears_task_link`: create an owned task with a link, then `PATCH {"link": null}`. The response is 204 and `GET /api/tasks` shows `link is None`. Repeat for a **seed** task through the overlay.
  - `test_patch_omitted_field_unchanged`: `PATCH {"title": "New"}` leaves `link` as it was.
  - `test_patch_null_on_required_field_rejected`: `PATCH {"title": null}` returns 422 `invalid_request`. Do the same for `group_id`, and for documents `{"title": null}`.
  - `test_patch_null_clears_document_last_updated`: `PATCH {"last_updated": null}` returns 204, and the detail then shows `last_updated is None`.
  - `test_day_number_never_below_one`: with `deps.today` set before the persona's start date, `GET /api/me` returns `day_number == 1`.

- [ ] **Step 2: Run to verify they fail.** Run `make test`. Expect the new tests to FAIL: missing file, missing schemas, and today's `exclude_none` semantics.

- [ ] **Step 3: Implement.**
  - **Patch semantics.** `TaskPatch.changes()` and a new `DocumentPatch.changes()` return `{k: v for k in self.model_fields_set}`.
    - Explicit `null` is allowed only for the nullable columns: task `link`, document `last_updated`. A `null` description or purpose becomes `""`.
    - Explicit `null` on `title`, `group_id` or `position` raises a validation error, which the existing handler turns into 422 `invalid_request`.
  - **`day_number`.** Use `max(1, …)`.
  - **Events.** `_Outcome.payload()` builds `DoneEvent(...).model_dump(mode="json")`, so the wire JSON is unchanged.
  - **Commit the schema.** Run `uv run python -m phoebe openapi > frontend/openapi.json`.

- [ ] **Step 4: Run to verify they pass.** `make test` and `make lint` must both be green.

- [ ] **Step 5: Commit.** `git commit -m "feat(api): typed contract export, clear-field PATCH, day clamp"`

---

### Task 2: Frontend scaffold, API client, CI job

**Files:**
- Create:
  - `frontend/package.json`, `package-lock.json`, `.nvmrc`
  - `frontend/vite.config.ts`, `tsconfig*.json`, `eslint.config.js`, `.prettierrc`, `index.html`
  - `frontend/src/main.tsx`, `src/styles.css` (Tailwind import plus design tokens)
  - `frontend/src/api/schema.ts` (generated), `src/api/types.ts`, `src/api/client.ts`
  - `frontend/src/lib/messages.ts`
  - `frontend/src/test/setup.ts`, `src/test/server.ts` (MSW)
  - `frontend/src/api/client.test.ts`
- Modify: `Makefile`, `.github/workflows/ci.yml`, `.gitignore` (`frontend/node_modules`, `frontend/dist`, `frontend/test-results`, `frontend/playwright-report`)

**Interfaces:**
- Produces:
  - `types.ts` re-exports the schema types under short names: `Me`, `StatusOut`, `TaskView`, `GroupNode`, `DocumentOut`, `DocumentDetailOut`, `PersonProgress`, `TurnOut`, `TurnCitation`, `Citation`, `DoneEvent`, `ClosestDoc`, `NewTask`, `TaskPatch`, `DocumentPatch`, `NewGroup`, `LinkBody`, `DocStatus`, `DocType`, `GroupKind`.
  - In `client.ts`:
    - `class ApiError extends Error { status: number; code: string; reason?: string }`
    - `apiGet<T>(path: string): Promise<T>`
    - `apiSend<T = void>(method: "POST"|"PUT"|"PATCH"|"DELETE", path: string, body?: unknown): Promise<T>`. It returns `undefined` on 204.
    - `apiUpload<T>(path: string, form: FormData): Promise<T>`
    - `onSessionExpired(listener: () => void): () => void`, fired on any 401 whose code is `session_expired`.
  - `messageFor(err: unknown): string`. It covers every code in the backend list: `invalid_password`, `session_expired`, `csrf_required`, `not_found`, `group_in_use`, `sandbox_full`, `length_required`, `file_too_large`, `invalid_group`, `invalid_link`, `invalid_request`, `too_many_attempts`, `chat_paused`, `demo_closed`, `unsupported_type`, `internal_error`. Anything else gets a generic fallback. For `unsupported_type` it returns `err.reason` verbatim.
  - Makefile targets: `fe-install` (`npm ci`), `fe-gen` (`npx openapi-typescript openapi.json -o src/api/schema.ts`), `fe-dev`, `fe-test`, `fe-lint`, `fe-build`.
  - `fe-lint` also fails if `fe-gen` would change `schema.ts`: regenerate into a temp file and `diff`.

- [ ] **Step 1: Scaffold.**
  - Use `npm create vite@latest frontend -- --template react-ts`, then add the Tech Stack packages.
  - Turn on strict TypeScript, including `noUncheckedIndexedAccess`.
  - Set the Vite `server.proxy` and `preview.proxy` for `/api` to `http://localhost:${process.env.PHOEBE_PORT ?? 8080}`.
  - Load Inter through `@fontsource-variable/inter`.
  - Define the palette as Tailwind `@theme` tokens:
    - `--color-ink`, `--color-surface`, `--color-accent` (phoebe slate-brown, ≥4.5:1 on surface), `--color-ok`, `--color-warn`, `--color-danger`, `--color-focus`.
    - Use a single light theme.

- [ ] **Step 2: Write the failing tests** in `client.test.ts`, using MSW:
  - `sends csrf header on non-GET`: the server asserts `X-Phoebe-Csrf: 1` on POST, PATCH, PUT and DELETE, and its absence on GET.
  - `parses error detail into ApiError`: a 409 `{"detail":"group_in_use"}` rejects with `{status:409, code:"group_in_use"}`.
  - `keeps 415 reason`: `{"detail":"unsupported_type","reason":"Only PDF, Markdown and CSV files are supported."}` gives `err.reason` equal to that sentence, and `messageFor(err)` returns it verbatim.
  - `204 resolves undefined`.
  - `session_expired notifies listeners once per response`.
  - `non-JSON error body falls back to code "internal_error"`.

- [ ] **Step 3: Run to verify they fail.** Run `make fe-test`. Expect FAIL (no client yet).

- [ ] **Step 4: Implement `client.ts` and `messages.ts`.** Run `make fe-gen`. `main.tsx` renders a placeholder `App`.

- [ ] **Step 5: Add the CI job.** Add a `frontend` job to `ci.yml`, running in parallel with `ci`:
  - Steps: `actions/setup-node` with `node-version-file: frontend/.nvmrc` and npm cache, then `make fe-install`, `make fe-lint`, `make fe-test`, `make fe-build`.
  - Pin actions by commit SHA, as the existing job does.

- [ ] **Step 6: Run everything.** `make fe-lint fe-test fe-build` must be green.

- [ ] **Step 7: Commit.** `git commit -m "feat(frontend): scaffold, typed API client, CI job"`

---

### Task 3: App shell, session, landing, header, status pill

**Files:**
- Create:
  - `frontend/src/App.tsx`, `src/routes.tsx`
  - `src/session/useMe.ts`, `src/session/SessionGate.tsx`
  - `src/pages/Landing.tsx`
  - `src/components/Mascot.tsx`, `src/components/Header.tsx`, `src/components/StatusPill.tsx`, `src/components/ResetDialog.tsx`, `src/components/WelcomeSplash.tsx`
  - `src/state/status.ts`
  - Tests: `src/pages/Landing.test.tsx`, `src/session/session.test.tsx`, `src/components/StatusPill.test.tsx`, `src/components/Header.test.tsx`

**Interfaces:**
- Consumes: Task 2 `apiGet`, `apiSend`, `onSessionExpired`, `messageFor`, `Me`, `StatusOut`.
- Produces:
  - Routes:
    - `/` is the Landing page.
    - `/employee` and `/admin/:tab` sit inside `SessionGate`. The `tab` values are `people`, `documents`, `tasks` and `groups`, and `/admin` redirects to `/admin/people`.
  - `useMe(): UseQueryResult<Me>` with query key `["me"]`.
  - `useStatus(): { status: StatusOut | undefined; limited: boolean; chatAvailable: boolean; uploadAvailable: boolean; refresh(): void }`.
    - Query key `["status"]`.
    - It polls every 60 s, only while `document.visibilityState === "visible"`, and refetches on window focus.
    - `limited` is true when `state === "chat_paused"` or the `reasons` include any cap reason.
  - `invalidateAll(queryClient)`, used after reset.
  - `<Mascot size?: number; mood?: "idle"|"cheer" />`: an original inline SVG of an eastern phoebe (grey-brown back, pale belly, dark head). It is decorative, with `aria-hidden` and no animation under reduced motion.

- [ ] **Step 1: Write the failing tests** (MSW plus Testing Library):
  - **Landing.**
    - `shows password form, mascot and one-line description`.
    - `wrong password shows "That password didn't work."` for 401 `invalid_password`, and the field keeps focus.
    - `login success navigates to /employee`, then `shows "Getting Phoebe ready…" while /api/me is pending`. Delay `/api/me` by 1500 ms in MSW.
    - `closed state shows offline copy and no form` when `/api/status` returns `state:"closed"`.
  - **Session.**
    - `skips landing when /api/me succeeds`: visiting `/` with a valid session redirects to `/employee` and never shows the password form. This is the carry-forward rule: re-login wipes the sandbox.
    - `401 session_expired anywhere returns to landing with the session-ended message`. Make `/api/tasks` return 401 after the first render.
  - **Welcome.**
    - `welcome splash appears once after login`: after a login it shows "Welcome to the Platform team, Alex!".
    - After dismissing and reloading (a new render with the same `sessionStorage`), it does not appear again.
    - With a session restored from `/api/me` and no login in this tab, it does not appear.
  - **Header.**
    - `shows Alex Rivera, Platform, start date and "Day 5"` for `day_number: 5`.
    - The `Employee | Admin` toggle is a Radix `ToggleGroup`: arrow keys move between items, and the selected item changes the route.
  - **StatusPill.**
    - `hidden when open and no reasons`.
    - `shows exact copy when chat_paused`.
    - `tooltip opens on hover, focus and tap with exact copy`.
  - **Reset.**
    - `Reset my demo asks for confirmation, POSTs /api/reset, then refetches every query`.
    - `Cancel sends nothing`.

- [ ] **Step 2: Run to verify they fail.** Run `make fe-test`. Expect FAIL.

- [ ] **Step 3: Implement.**
  - **Welcome flag.** Login success sets `sessionStorage["phoebe.welcome"]="pending"`. The splash shows while it is `pending` and sets it to `done` on dismiss. Use a Radix `Dialog`.
  - **Header.** Mascot, "Phoebe", company name from the `/api/groups` root name, persona block (employee mode only), toggle, pill, the "Reset my demo" button (Radix `AlertDialog`), and a "Log out" button (POST `/api/logout`, then go to `/`).
  - **Reset.** After the POST, `invalidateAll` also dispatches the chat reducer's `{type:"reset"}` through a reset event the chat provider subscribes to, so the visible conversation clears too.
  - **Tooltip.** The pill is a `<button>` wrapped in a Radix `Tooltip`. Wrap it in a `Popover` as well, so a tap on touch devices opens it.

- [ ] **Step 4: Run to verify they pass.** `make fe-test` and `make fe-lint` must be green.

- [ ] **Step 5: Commit.** `git commit -m "feat(frontend): landing, session gate, header, status pill"`

---

### Task 4: Employee tasks sidebar with delight

**Files:**
- Create:
  - `frontend/src/employee/TasksPanel.tsx`, `src/employee/useTasks.ts`
  - `src/lib/tiers.ts`, `src/lib/celebrate.ts`
  - Tests: `src/employee/TasksPanel.test.tsx`, `src/lib/tiers.test.ts`

**Interfaces:**
- Consumes: `TaskView`, `GroupKind`, `apiGet`, `apiSend`.
- Produces:
  - `TIER_ORDER: GroupKind[] = ["company","department","team"]`
  - `groupByTier<T extends { group_kind: GroupKind }>(items: T[]): Record<GroupKind, T[]>`. The input order is kept inside each tier.
  - `useTasks(scope: "mine" | "all")`, with query key `["tasks", scope]`.
  - `useToggleTask(): (task: TaskView, done: boolean) => void`. It is an optimistic update, serialised per task id.
  - `celebrate(): void` calls `canvas-confetti` once. It is a no-op when `matchMedia("(prefers-reduced-motion: reduce)").matches`.

- [ ] **Step 1: Write the failing tests:**
  - `tiers.test.ts`: `groupByTier` buckets by kind and keeps order.
  - `progress bar reads "6 of 14 done"` for 14 tasks with 6 done. It has `role="progressbar"` with `aria-valuenow=6` and `aria-valuemax=14`.
  - Tier sections are Radix `Accordion` items titled "Company", "{department_name}" and "{team_name}", all open by default.
  - `checking a task PUTs /api/tasks/{id}/completion {"done":true} and updates the count immediately`.
  - `rapid toggles end in the server's state with at most one request in flight per task`: click the same checkbox 5 times quickly. The MSW handler records concurrency, which must be ≤1, and the final UI matches the last request body.
  - `failed toggle rolls back and shows messageFor(err)`.
  - `completing the last task of a tier calls celebrate once`, with `celebrate` mocked.
  - `at 100% shows the "All done!" badge`.
  - `task with link renders an external link with rel="noopener noreferrer"`.

- [ ] **Step 2: Run to verify they fail.** Run `make fe-test`. Expect FAIL.

- [ ] **Step 3: Implement.**
  - **Serialising toggles.** Keep the latest wanted state per id. If a request is already in flight, send the latest state when it settles, and only if it differs from the settled server state.
  - **Checkboxes.** Use Radix `Checkbox` with its label bound.

- [ ] **Step 4: Run to verify they pass.**

- [ ] **Step 5: Commit.** `git commit -m "feat(frontend): tiered task checklist with progress and celebration"`

---

### Task 5: Documents panel and document viewer

**Files:**
- Create:
  - `frontend/src/lib/offsets.ts`
  - `frontend/src/documents/DocumentsPanel.tsx`, `src/documents/DocIcon.tsx`
  - `frontend/src/documents/ViewerProvider.tsx` (context plus a `useViewer` hook), `src/documents/DocumentViewer.tsx`
  - Tests: `src/lib/offsets.test.ts`, `src/documents/DocumentViewer.test.tsx`, `src/documents/DocumentsPanel.test.tsx`

**Interfaces:**
- Consumes: `DocumentOut`, `DocumentDetailOut` (with `sections: {heading_path: string[]; start: number; end: number}[]`), `groupByTier`.
- Produces:
  - `cpToUtf16(text: string, cp: number): number`. It clamps `cp` to `[0, codePointLength]`.
  - `useViewer(): { open(docId: string, passage?: { start: number; end: number }): void; close(): void }`. Passage offsets are code points.
  - `<DocIcon type: DocType />`, with a lucide icon per type and an `sr-only` type label.

- [ ] **Step 1: Write the failing tests:**
  - **`offsets.test.ts`.**
    - ASCII is the identity.
    - `cpToUtf16("🎉ab", 1) === 2`.
    - `cpToUtf16("a🎉b🎉c", 4) === 6`.
    - Clamps a past-the-end value and a negative value.
  - **Panel.**
    - `groups documents by tier and shows type, title, purpose, last updated`.
    - `clicking a row opens the viewer`.
  - **Viewer.**
    - `renders sections with their heading paths as headings` (h2 for depth 1, h3 for depth 2+).
    - `highlights exactly the cited passage when the text before it has an emoji`: `full_text = "🎉 Intro\nPTO is 20 days."` with a passage over `"PTO is 20 days."` in code points. The `<mark>` text equals `"PTO is 20 days."`.
    - `scrolls the mark into view`: `Element.prototype.scrollIntoView` is called once.
    - `web and google_doc show a "View original" link to public_url`. It has `target="_blank"` and `rel="noopener noreferrer"`.
    - `processing or failed document shows its status and failure_reason verbatim instead of text`.
    - `404 shows "This document is no longer available."` This covers a document deleted in admin.
    - On desktop the viewer is a right-side Radix `Dialog` panel. Below `md` it is a full-height bottom sheet (the same Dialog with different classes). In both cases `Escape` closes it and focus returns to the trigger.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement.** Render `full_text` by section. Slice each section's text using `cpToUtf16`. Wrap the intersection of the passage with each section in a `<mark>`, so a passage that crosses sections is still fully highlighted.

- [ ] **Step 4: Run to verify they pass.**

- [ ] **Step 5: Commit.** `git commit -m "feat(frontend): documents panel and viewer with passage highlight"`

---

### Task 6: Cited streaming chat

**Files:**
- Create:
  - `frontend/src/api/sse.ts`
  - `frontend/src/chat/reducer.ts`, `src/chat/ChatRuntimeProvider.tsx`, `src/chat/ChatPanel.tsx`, `src/chat/CitedText.tsx`, `src/chat/SourceList.tsx`
  - Tests: `src/api/sse.test.ts`, `src/chat/reducer.test.ts`, `src/chat/ChatPanel.test.tsx`

**Interfaces:**
- Consumes: `DoneEvent`, `TurnOut`, `TurnCitation`, `useViewer().open`, `useStatus()`, `messageFor`.
- Produces:
  - `parseSse(body: ReadableStream<Uint8Array>): AsyncGenerator<{ event: string; data: unknown }>`. It decodes with one `TextDecoder` in `{stream:true}` mode, splits on `\n\n`, and throws `ApiError(0,"internal_error")` on a malformed frame.
  - `streamChat(question: string, signal: AbortSignal): AsyncGenerator<ChatStreamEvent>`.
    - `ChatStreamEvent` is `{type:"meta",turnId} | {type:"delta",text} | {type:"done",done:DoneEvent} | {type:"error",code}`.
    - A non-200 response rejects with `ApiError` before anything is yielded.
  - `ChatMessage`:
    - `{ id; role: "user"|"assistant"; text; status: "streaming"|"done"|"error"; refused: boolean; reason: DoneEvent["reason"]; citations: (Citation & { removed?: boolean })[]; closest: ClosestDoc[] }`
  - `chatReducer(state: ChatMessage[], action)`. The actions are:
    - `{type:"history", turns: TurnOut[]}`
    - `{type:"send", id, question}`. It appends the user message plus an empty streaming assistant message.
    - `{type:"delta", text}`
    - `{type:"done", done: DoneEvent}`. It **replaces** `text` with `done.text` and sets citations, closest and refused.
    - `{type:"error", code}`. The assistant message becomes `status:"error"` with `text = messageFor(code)`.
    - `{type:"reset"}`

- [ ] **Step 1: Write the failing tests:**
  - **`sse.test.ts`.**
    - `parses meta, deltas, done in order`.
    - `byte-by-byte feed gives the same events` (Review Focus 1). Encode a stream whose delta text includes "naïve 🎉" and enqueue it **one byte per chunk**.
    - `CRLF-free frames only; malformed frame throws`.
  - **`reducer.test.ts`.**
    - `done replaces streamed text even when refused`: deltas "PTO is [P3]" become `done.text` "PTO is 20 days [1]".
    - `history maps removed citations`.
    - `error on stream marks message error with mapped copy`.
  - **`ChatPanel.test.tsx`** (MSW streams SSE through `new ReadableStream`).
    - `shows mascot greeting and suggested questions`. The questions are exactly "How many PTO days do I get?", "What's on my first-week schedule?", "Who's who on the Platform team?" and "How does on-call work?". Clicking one sends it.
    - `streams text then settles to done.text with numbered citation buttons [1] [2]`.
    - `citation button opens the viewer at the passage`: `useViewer().open` is called with `(document_id, {start, end})`.
    - `source list under each answer lists unique cited documents`.
    - `refused answer shows refusal text and "Closest documents" links that open the viewer`.
    - `removed citation renders "source removed" and is not a button`.
    - `send is disabled while an answer is streaming`. Enter twice gives one POST (Review Focus 4).
    - `503 chat_paused before stream: composer disabled, tooltip copy shown, status refetched` (Review Focus 5).
    - `history loads from /api/chat/history on mount`.
    - `screen reader: one polite live region announces the settled answer text once per answer, not each delta`.
    - `unmount aborts the in-flight stream`: `AbortSignal.aborted` is true.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement.**
  - **Provider.** `ChatRuntimeProvider` uses `useExternalStoreRuntime({ messages, isRunning, convertMessage, onNew, onCancel })` from `@assistant-ui/react`. `convertMessage` maps a `ChatMessage` to `{ id, role, content: [{type:"text", text}] }`.
  - **Rendering.** `ChatPanel` renders with the assistant-ui `Thread`, `Composer` and message primitives. Assistant message bodies use `CitedText` and `SourceList` instead of the default text part.
  - **`CitedText`.**
    - Parse `[n]` markers in settled text into buttons labelled "Source {n}: {document_title}".
    - While streaming, show the raw text with labels shown as-is.
    - Render plain text only, with no HTML or Markdown injection. Blank lines are paragraph breaks, and lines starting with `#` become headings (`h3`).

- [ ] **Step 4: Run to verify they pass.**

- [ ] **Step 5: Commit.** `git commit -m "feat(frontend): streaming cited chat on assistant-ui"`

---

### Task 7: Employee layout (desktop columns, mobile tabs)

**Files:**
- Create: `frontend/src/pages/Employee.tsx`, `src/employee/PersonaCard.tsx`, `src/pages/Employee.test.tsx`

**Interfaces:**
- Consumes: Tasks 4–6 panels, `useMe`, `ViewerProvider`.

- [ ] **Step 1: Write the failing tests:**
  - `desktop (≥768px) shows Tasks | Chat | Documents as three labelled regions`, each a `<section aria-labelledby>`.
  - `mobile shows one panel with bottom tabs Tasks | Chat | Docs, Chat selected by default`. Use a Radix `Tabs` with `role="tablist"` at the bottom. Switching tabs keeps chat state, so the tab panels stay mounted.
  - `persona card shows start date, manager, buddy and "Day N"`.
  - Mock `matchMedia` for both widths.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement.**
  - **Columns.** Use CSS grid `md:grid-cols-[18rem_1fr_20rem]`.
  - **Mobile.** Tabs are fixed to the bottom, with safe-area padding (`env(safe-area-inset-bottom)`). Use `100dvh` heights for iOS Safari.

- [ ] **Step 4: Run to verify they pass.**

- [ ] **Step 5: Commit.** `git commit -m "feat(frontend): employee layout with mobile tabs"`

---

### Task 8: Admin shell and People & Progress

**Files:**
- Create: `frontend/src/pages/Admin.tsx`, `src/admin/PeopleTab.tsx`, `src/admin/PersonChecklist.tsx`, `src/pages/Admin.test.tsx`, `src/admin/PeopleTab.test.tsx`

**Interfaces:**
- Consumes: `PersonProgress`, `TaskView`, `groupByTier`.
- Produces: an `AdminTab` layout using Radix `Tabs` with `orientation="vertical"` at `md` and up. Below `md` the tab list is horizontal and scrolls on overflow. The tab value is synced with `/admin/:tab`.

- [ ] **Step 1: Write the failing tests:**
  - `vertical tabs People & Progress, Documents, Tasks, Groups; URL follows selection`.
  - `people table: name, department › team, start date, progress bar, "done of total"`. It is a real `<table>` with `<th scope="col">`.
  - `clicking a row (or Enter on its button) shows that person's checklist by tier, read-only`.
  - `Alex's row reflects completions made in employee mode`: after a completion PUT, invalidating `["people"]` changes the count.

- [ ] **Step 2: Run to verify they fail.** **Step 3: Implement.** **Step 4: Run to verify they pass.**

- [ ] **Step 5: Commit.** `git commit -m "feat(frontend): admin shell and people progress"`

---

### Task 9: Admin Documents

**Files:**
- Create: `frontend/src/admin/DocumentsTab.tsx`, `src/admin/AddDocumentDialog.tsx`, `src/admin/EditDocumentDialog.tsx`, `src/admin/GroupSelect.tsx`, `src/admin/DocumentsTab.test.tsx`

**Interfaces:**
- Consumes: `DocumentOut`, `DocumentPatch`, `LinkBody`, `apiUpload`, `useStatus().uploadAvailable`, `GroupNode`.
- Produces: `<GroupSelect value onChange />`, a Radix `Select` listing Company, the departments and the teams, with the team names indented under their department. It is reused by Task 10.

- [ ] **Step 1: Write the failing tests:**
  - **List.** `list shows title, type, group, purpose, last updated, status`. The status reads "Processing…", "Indexed ✓", or "Failed: {failure_reason}".
  - **Polling.** `while any doc is processing, the list refetches every 3 s and stops when none are` (fake timers).
  - **Upload.**
    - `upload sends multipart file,title,group_id,purpose,last_updated to /api/documents/upload`.
    - The file input accepts `.pdf,.md,.markdown,.csv`.
    - A client-side check rejects files over 5 MB with "Files must be 5 MB or smaller." and sends no request.
  - **Link.** `link form posts /api/documents/link`. `422 invalid_link` shows the mapped copy.
  - **Errors.** `415 shows the server's reason verbatim`. `409 sandbox_full` shows the mapped copy.
  - **Limits.** `upload disabled with tooltip copy when uploadAvailable is false` (Review Focus 5). `429 too_many_attempts from upload refetches status`.
  - **Edit.**
    - `edit dialog PATCHes only changed fields`.
    - `clearing last updated sends {"last_updated": null}`. This uses Task 1's semantics.
  - **Delete.** `delete asks for confirmation then DELETEs and invalidates ["documents"]` and the employee documents query.

- [ ] **Step 2: Run to verify they fail.** **Step 3: Implement.** **Step 4: Run to verify they pass.**

- [ ] **Step 5: Commit.** `git commit -m "feat(frontend): admin documents with upload, link, edit, delete"`

---

### Task 10: Admin Tasks and Groups

**Files:**
- Create: `frontend/src/admin/TasksTab.tsx`, `src/admin/TaskDialog.tsx`, `src/admin/GroupsTab.tsx`, `src/admin/TasksTab.test.tsx`, `src/admin/GroupsTab.test.tsx`

**Interfaces:**
- Consumes: `TaskView`, `NewTask`, `TaskPatch`, `GroupNode`, `NewGroup`, `GroupSelect`.

- [ ] **Step 1: Write the failing tests:**
  - **Tasks list.** `tasks listed by group (scope=all) with title, description, link`.
  - **Create and edit.**
    - `create posts NewTask`.
    - `edit PATCHes changed fields only`.
    - `removing a link sends {"link": null}`.
  - **Delete.** `delete confirms then DELETEs`.
  - **Reorder.**
    - Reorder uses "Move up" and "Move down" buttons (keyboard-accessible, no drag-and-drop). Each press PATCHes `position` on the two swapped tasks, in order.
    - The first task's "Move up" button is disabled.
  - **Groups tree.**
    - `groups tree shows company → departments → teams with document and task counts`. The counts come from `/api/documents?scope=all` and `/api/tasks?scope=all`. Selecting a group lists the titles of its documents and tasks (spec §3.4: "see which documents and tasks belong to each").
    - The tree uses `role="tree"` with `aria-level`, or nested lists with headings. Pick the nested lists if `tree` keyboard behaviour isn't implemented in full.
  - **Group actions.**
    - `add department under company; add team under a department` (POST `/api/groups`).
    - `rename` (PATCH).
    - `delete in-use group shows "Move or delete its documents, tasks and teams first."` for 409 `group_in_use`.
  - **Propagation.** `admin changes invalidate employee queries`: after creating a task in the Platform team, the `["tasks","mine"]` query is invalidated.

- [ ] **Step 2: Run to verify they fail.** **Step 3: Implement.** **Step 4: Run to verify they pass.**

- [ ] **Step 5: Commit.** `git commit -m "feat(frontend): admin tasks and groups"`

---

### Task 11: Cross-browser end-to-end and accessibility

**Files:**
- Create:
  - `frontend/playwright.config.ts`
  - `frontend/e2e/fixtures.ts`
  - `frontend/e2e/{auth,employee,chat,admin,limits,a11y,mobile}.spec.ts`
- Modify: `Makefile` (`e2e` target), `README.md` (a frontend section: dev, tests, e2e)

**Interfaces:**
- Consumes: the running stack from `make stack` (offline extractive answer model, hash embedder), the built app served by `vite preview` on `4173` with the `/api` proxy, and `PHOEBE_DEV_PASSWORD`.
- Produces:
  - `make e2e`: `cd frontend && npm run build && npx playwright test`. Playwright's `webServer` runs `vite preview --port 4173 --strictPort`.
  - The fixture `loggedIn(page)` logs in through the UI, and `resetDemo(page)` posts `/api/reset` with the CSRF header.
  - The fixture `setControl(state)` runs `make pause`, `make open` or `make kill` through Node `execFileSync("make", [...], {cwd: repoRoot})`. Tests that use it run serially (`test.describe.configure({mode:"serial"})`) and always restore `open` in `afterAll`.

- [ ] **Step 1: Write the specs.**
  - Projects: `chromium`, `firefox`, `webkit`, `mobile-safari` (`devices["iPhone 15"]`) and `mobile-chrome` (`devices["Pixel 8"]`).
  - Every test starts with `resetDemo` so runs are independent.
  - **`auth`.**
    - `wrong password then right password`.
    - `reload stays logged in` (no password prompt).
    - `logout returns to landing`.
  - **`employee`.** `check a task, see "x of y done" update, switch to Admin → People & Progress shows Alex's count +1`.
  - **`chat`.**
    - `ask "How many PTO days do I get?"`: the answer settles with at least one citation button.
    - Clicking it opens the viewer with a visible `<mark>`.
    - `ask "What's the Sales East quota?"` gives a refusal with closest documents.
    - **The anti-goal check:** `admin deletes "Employee Handbook" → asking the PTO question again cites no Employee Handbook passage`.
  - **`admin`.**
    - `upload a small Markdown file (fixture e2e/files/welcome.md) → status reaches "Indexed ✓" within 30 s → employee Documents panel lists it`.
    - `create a task in Platform → employee Tasks shows it`.
  - **`limits`** (serial).
    - `make pause` makes the pill appear with the exact copy, disables the chat composer, and leaves the task checkbox working.
    - `make kill` makes the landing page show the offline copy.
    - `make open` restores normal behaviour.
  - **`a11y`.**
    - Run `new AxeBuilder({page}).withTags(["wcag2a","wcag2aa","wcag21aa","wcag22aa"]).analyze()` on landing, employee, the viewer open, and each admin tab. Expect `violations` to equal `[]`.
    - `keyboard only: Tab from landing through login, check a task with Space, send a suggested question with Enter, open a citation, Escape returns focus to the citation button`.
  - **`mobile`** (mobile projects only). `bottom tabs switch panels; tapping a citation opens the bottom sheet; the sheet is fully inside the viewport`.

- [ ] **Step 2: Run.** With `make stack` up, run `make e2e`. Expect all projects to PASS. Then run `make fe-test fe-lint` and `make test lint`.

- [ ] **Step 3: Write the README section.** Cover `make stack` + `make fe-dev`, then `make e2e`. Note that Playwright runs locally and joins CI in Plan 5, per the roadmap.

- [ ] **Step 4: Commit.** `git commit -m "test(frontend): Playwright cross-browser and axe suite"`
