# Larkspur Labs Branding and Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Brand Phoebe as Larkspur Labs' internal onboarding tool, with illustrated Phoebe poses, a petal loader, a wider layout, an admin home, a collapsible documents tree, a sticky day strip, and manager and buddy avatars.

**Architecture:**
- **Frontend:** React + Vite + Tailwind v4. Images are imported through Vite, so they get hashed, long-cached URLs. Favicons and the manifest stay in `public/`.
- **Backend:**
  - one expand-only migration that adds the persona roles;
  - seed manifest and document edits;
  - a hand-run `reseed` ops task.
- **Admin statistics** are computed in the browser from existing queries. No new endpoints.

**Tech Stack:** React 19, TypeScript, Tailwind v4, Radix (Tabs/Accordion/Collapsible), TanStack Query, Vitest + MSW, Playwright + axe; FastAPI, Postgres, pytest; cwebp / ImageMagick for asset conversion.

**Spec:** `docs/superpowers/specs/2026-11-16-larkspur-branding-layout-design.md`

## Global Constraints

- One PR on branch `feat/larkspur-branding`. Commits are grouped in this order:
  1. assets (Task 1);
  2. branding (Tasks 2–3);
  3. seed and people (Tasks 4–6);
  4. layout and admin (Tasks 7–9).
- Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Asset sources:**
  - brand kit: `/Users/hochoy/Downloads/6d11aee5521a4771ae4cbd0d9090dec9/`;
  - Melinda's photo: `/Users/hochoy/Downloads/image_1bc43cfb.jpg`;
  - Jordan's photo: `/Users/hochoy/Downloads/image_107ac173.jpg`.

  Originals are never committed.
- **Brand colours:** navy `#0B2772`, petals `#6376F1` / `#665AE1` / `#8B9BF6`, overlap `#2F3DA6`.
- **Light theme only.** Text pairs meet WCAG AA, 4.5:1.
- **Every Phoebe illustration is decorative:** `alt=""` and `aria-hidden="true"`.
- **Motion respects `prefers-reduced-motion`.**
- **Copy is exact:**
  - page title "Phoebe · Larkspur Labs";
  - landing headline "Welcome to Larkspur Labs. I'm Phoebe, your onboarding guide.";
  - manifest name "Phoebe · Larkspur Labs", short name "Phoebe".
- **People:**
  - Alex's manager is **Melinda Grant** (she/her), "Engineering Manager, Platform".
  - Alex's buddy is **Jordan Moore** (he/him), "Senior Engineer".
- **Migrations are expand-only.** Deploys never call `reseed`.
- **CSP stays as is:** `img-src 'self' data:`, `default-src 'self'`. Every asset is served from the same origin.
- **Ruling (deviates from the spec):** PR previews omit `og:image` instead of using staging's origin.
  - Why: preview builds are configured in `infra/bootstrap/buildspecs/pr.yml`, which only the owner can apply, and previews are never shared publicly.
  - Cost if wrong: preview links show no image when pasted somewhere.
- **Checks before every commit:**
  - `make test`;
  - `make lint`;
  - in `frontend/`: `npx vitest run`, `npm run -s lint`, `npm run -s format:check`, `npx tsc --noEmit -p .`;
  - `make fe-gen` after any API change.

## Review Focus

1. **A persona whose manager or buddy has no photo** (Elena Petrova, Marcus Webb, etc.) gets an initials circle, never a broken image. Pinned in Task 6.
2. **A group with no documents of its own whose child has documents** is still shown, and a branch with no documents anywhere is hidden. Pinned in Task 9.
3. **A collapsed-state entry for a group that was deleted,** or a corrupt `sessionStorage` value, is ignored, not crashed on. Pinned in Task 9.
4. **Admin home with zero tasks** (`total = 0` for everyone) shows 0%, not `NaN%`. Pinned in Task 8.
5. **`reseed` on a database whose visitor rows have no `sandboxes` registry row** (orphans) still clears them, so `load_seed` doesn't hit a foreign-key error. Pinned in Task 5.

---

## File map

| Area | Files |
|---|---|
| Asset build | Create `frontend/scripts/brand-assets.sh` (reproducible conversion) |
| Brand images | Create `frontend/src/assets/brand/` (`phoebe-<pose>-{256,512}.webp`, `phoebe-avatar-{32,64}.webp`, `larkspur-logo.svg`, `larkspur-mark.svg`, `larkspur-loader.svg`) |
| Photos | Create `frontend/src/assets/people/{melinda-grant,jordan-moore}.webp` |
| Public | Replace `frontend/public/favicon.svg`; add the kit favicons, `site.webmanifest`, `og/link-preview.jpg` |
| Tokens | Modify `frontend/src/styles.css`; create `frontend/src/lib/contrast.test.ts` |
| Head/meta | Modify `frontend/index.html`, `frontend/vite.config.ts`, `ci/deploy.sh` |
| Illustrations | Create `frontend/src/components/PhoebeArt.tsx`, `frontend/src/components/PetalLoader.tsx`; delete `frontend/src/components/Mascot.tsx` |
| Placements | Modify `Header.tsx`, `Landing.tsx`, `WelcomeSplash.tsx`, `SessionGate.tsx`, `ChatPanel.tsx`, `QueryError.tsx`, `TasksPanel.tsx`, `DocumentsPanel.tsx`, `admin/DocumentsTab.tsx` |
| Backend roles | Create `backend/migrations/004_people_roles.sql`; modify `backend/src/phoebe/persona.py`, `backend/src/phoebe/seed.py`, `backend/seed/manifest.yaml`, seed docs, `backend/tests/test_data_api.py` (`EXPECTED_STATEMENTS`) |
| Reseed | Modify `backend/src/phoebe/lambdas/ops.py`; create `backend/src/phoebe/reseed.py` |
| Persona UI | Create `frontend/src/employee/PersonAvatar.tsx`, `frontend/src/employee/photos.ts`; modify `PersonaCard.tsx`, `pages/Employee.tsx` |
| Layout | Modify `session/SessionGate.tsx`, `pages/Employee.tsx` |
| Admin home | Create `frontend/src/admin/summary.ts`, `frontend/src/admin/HomeTab.tsx`; modify `pages/Admin.tsx`, `routes.tsx`, `admin/PeopleTab.tsx` (export `usePeople`), `admin/GroupsTab.tsx` (export `useGroups`) |
| Docs tree | Create `frontend/src/admin/docTree.ts`, `frontend/src/admin/DocumentTree.tsx`; modify `admin/DocumentsTab.tsx` |

---

### Task 1: Brand assets

**Files:**
- Create: `frontend/scripts/brand-assets.sh`, plus every output listed in the file map under brand images, photos and public.

**Interfaces:**
- **Produces these file names, which later tasks import:**
  - `src/assets/brand/phoebe-{waving,thinking,pointing,celebrating,onboarding-checklist,oops-error}-{256,512}.webp`;
  - `src/assets/brand/phoebe-avatar-{32,64}.webp`;
  - `src/assets/brand/larkspur-logo.svg`, `larkspur-mark.svg`, `larkspur-loader.svg`;
  - `src/assets/people/melinda-grant.webp`, `jordan-moore.webp`;
  - `public/og/link-preview.jpg`.

- [ ] **Step 1: Write `brand-assets.sh SRC_KIT MELINDA_JPG JORDAN_JPG`.**
  - **Sources:** poses come from `SRC_KIT/phoebe/transparent/`. Use `cwebp -q 82 -alpha_q 90 -resize N N` for poses at 256 and 512.
  - **Avatar:** crop the head and shoulders of the waving pose with `magick` (the top ~55% of the frame, centred on the head), then make 32 and 64 px WebP.
  - **Photos:** centre-crop to a square on the face, 192 px, `cwebp -q 80`.
  - **Copied as-is:**
    - `logo/larkspur-labs-logo.svg` → `larkspur-logo.svg`;
    - `logo/larkspur-labs-mark.svg` → `larkspur-mark.svg`;
    - `loader/larkspur-loader.svg`;
    - every file in `favicon/` → `public/`, replacing `favicon.svg`.
  - **Manifest:** rewrite `public/site.webmanifest` so `name` is "Phoebe · Larkspur Labs" and `short_name` is "Phoebe". Keep the icons. Leave `theme_color` / `background_color` at `#ffffff`.
  - **Link preview:** convert `social/larkspur-link-preview-1200x630.png` to `public/og/link-preview.jpg` at `-quality 85`.
- [ ] **Step 2: Run it.**
  - `bash frontend/scripts/brand-assets.sh "/Users/hochoy/Downloads/6d11aee5521a4771ae4cbd0d9090dec9" /Users/hochoy/Downloads/image_1bc43cfb.jpg /Users/hochoy/Downloads/image_107ac173.jpg`
  - Then look at each output image (the avatar crop and both photos especially) to check that the faces are framed.
- [ ] **Step 3: Verify the sizes.**
  - Run `find frontend/src/assets frontend/public -name '*.webp' -size +60k`. Expected: no output.
  - `public/og/link-preview.jpg` is under 200 KB.
- [ ] **Step 4: Commit.** `feat(brand): add Larkspur Labs brand assets`.

### Task 2: Palette, head tags and header

**Files:**
- Modify: `frontend/src/styles.css`, `frontend/index.html`, `frontend/vite.config.ts`, `ci/deploy.sh`, `frontend/src/components/Header.tsx`.
- Test: create `frontend/src/lib/contrast.test.ts`, modify `frontend/src/components/Header.test.tsx`.

**Interfaces:**
- **Produces CSS tokens** `--color-accent: #0B2772`, `--color-highlight: #665AE1`, and `--color-highlight-soft: #EEF0FE` (petal tint for hover and active backgrounds).

- [ ] **Step 1: Write the failing tests.**
  - `contrast.test.ts` reads `src/styles.css` with `fs`, parses `--color-ink`, `--color-surface`, `--color-accent` and `--color-highlight`, and asserts:
    - `ratio(accent, surface) >= 4.5`;
    - `ratio(accent, "#ffffff") >= 4.5`, since buttons put white text on the accent;
    - `ratio(highlight, "#ffffff") >= 4.5`.
  - Use the WCAG relative-luminance formula.
  - `Header.test.tsx`: `getByRole("img", { name: "Larkspur Labs" })` is present, and the text "Phoebe" is present.
- [ ] **Step 2: Run them.** Run `npx vitest run src/lib/contrast.test.ts src/components/Header.test.tsx`. Expected: FAIL. The accent is still brown and there's no logo.
- [ ] **Step 3: Implement.**
  - **Tokens:** set the values above. Recheck the warn and danger colours on `--color-highlight-soft`, if they're used there.
  - **Header:** replace `<Mascot>` with `<img src={logo} alt="Larkspur Labs" className="h-7 w-auto">`, followed by a divider and "Phoebe".
  - **`index.html`:**
    - `<title>Phoebe · Larkspur Labs</title>`;
    - favicon, apple-touch and manifest links from the kit's `head-snippet.html`, with paths prefixed `%BASE_URL%`;
    - `<meta name="theme-color" content="#ffffff">`;
    - `og:title` "Phoebe · Larkspur Labs" and `og:description` "Larkspur Labs' onboarding guide."
  - **`vite.config.ts`:** add a `transformIndexHtml` plugin. When `process.env.VITE_SITE_ORIGIN` is set, it injects `<meta property="og:image" content="${origin}${base}og/link-preview.jpg">`; otherwise nothing.
  - **`ci/deploy.sh`:** change the build line to `VITE_SITE_ORIGIN="$SITE_URL" PHOEBE_BASE=/ npm run build`.
- [ ] **Step 4: Run them.** Run the Step 2 tests, then `npm run build` and `grep -c 'Phoebe · Larkspur Labs' dist/index.html`. Expected: PASS and 1.
- [ ] **Step 5: Run the axe Playwright suite** (`npx playwright test --project=chromium e2e/a11y.spec.ts`). Expected: no contrast violations.
- [ ] **Step 6: Commit.** `feat(brand): Larkspur palette, favicon, title and header logo`.

### Task 3: Phoebe illustrations and petal loader

**Files:**
- Create: `frontend/src/components/PhoebeArt.tsx`, `frontend/src/components/PetalLoader.tsx`, `frontend/src/components/PhoebeArt.test.tsx`.
- Modify: `Landing.tsx`, `WelcomeSplash.tsx`, `SessionGate.tsx`, `chat/ChatPanel.tsx`, `QueryError.tsx`, `employee/TasksPanel.tsx`, `documents/DocumentsPanel.tsx`, `admin/DocumentsTab.tsx`, and their existing tests where they query the old SVG.
- Delete: `frontend/src/components/Mascot.tsx`.

**Interfaces:**
- **Produces:**
  - `type Pose = "waving" | "thinking" | "pointing" | "celebrating" | "onboarding-checklist" | "oops-error"`;
  - `PhoebeArt({ pose, size }: { pose: Pose; size: number }): JSX.Element`. It renders `<img alt="" aria-hidden srcSet="…256 1x, …512 2x">`, choosing the 256/512 pair. Sizes up to 128 use 256 as 1× and 512 as 2×.
  - `PhoebeAvatar({ size }: { size: number })`: the 32/64 head crop.
  - `PetalLoader({ size, label }: { size: number; label: string })`. It renders the loader SVG as `<img alt="">` next to a `role="status"` text `label`.

- [ ] **Step 1: Write the failing tests.**
  - `PhoebeArt.test.tsx`: each pose renders an `img` whose `src` contains `phoebe-<pose>-256` and `srcset` contains `512.webp 2x`. It is `aria-hidden`.
  - `PetalLoader`: `getByRole("status")` has the label text.
- [ ] **Step 2: Run them.** Expected: FAIL, because the modules are missing.
- [ ] **Step 3: Implement the components, then place them per the spec table:**
  - Landing hero: waving, 192, plus the headline copy.
  - Welcome splash: onboarding-checklist, 160. It replaces `Mascot mood="cheer"` and keeps the existing bounce under `motion-safe`.
  - Chat greeting: waving, 96.
  - Answer avatar: `PhoebeAvatar` 28.
  - "Phoebe is thinking…" row: thinking, 32, beside the text. The 8 s waking state uses `PetalLoader` 24 with `WAKING_COPY`.
  - `SessionGate` pending screen: `PetalLoader` 64 with "Getting Phoebe ready…".
  - `QueryError` and the chat error bubble: oops-error, 48, beside the message.
  - Empty lists ("No tasks yet." in TasksPanel; the empty states in DocumentsPanel and admin DocumentsTab): pointing, 96.
  - TasksPanel "All done!": celebrating, 64, beside the pill.
  - Delete `Mascot.tsx`.
- [ ] **Step 4: Update any existing tests** that assumed the old SVG, then run all of `npx vitest run`. Expected: everything passes.
- [ ] **Step 5: Check that `grep -rn "Mascot" frontend/src` is empty.**
- [ ] **Step 6: Commit.** `feat(brand): illustrated Phoebe poses and petal loader`.

### Task 4: Persona roles and renamed people (backend)

**Files:**
- Create: `backend/migrations/004_people_roles.sql`.
- Modify:
  - `backend/src/phoebe/persona.py` (`Persona` gains `manager_role: str | None`, `buddy_role: str | None`; the select reads them);
  - `backend/src/phoebe/seed.py` (`_insert_people` writes them from the manifest's optional `manager_role` / `buddy_role`);
  - `backend/seed/manifest.yaml`;
  - `backend/seed/content/{platform-team.md,first-week.md,project-manifest.txt}`;
  - `backend/tests/test_data_api.py` (`EXPECTED_STATEMENTS` gains `"004_people_roles.sql": 1`);
  - `backend/tests/test_api_chat.py` (if it names the old people);
  - `frontend/openapi.json` and `frontend/src/api/schema.ts`, regenerated.
- Test: `backend/tests/test_seed.py`, `backend/tests/test_api_auth.py`.

**Interfaces:**
- **Produces:** `/api/me` gains `manager_role: string | null` and `buddy_role: string | null`.

- [ ] **Step 1: Write the failing tests.**
  - `test_seed_persona_roles`: after `load_seed`, `get_persona(db)` has:
    - `manager == "Melinda Grant"`, `manager_role == "Engineering Manager, Platform"`;
    - `buddy == "Jordan Moore"`, `buddy_role == "Senior Engineer"`.
  - `test_me_includes_roles`: a logged-in `GET /api/me` JSON has those four values.
  - `test_seed_docs_name_the_new_people`: none of the seed docs contains "Jordan Lee" or "Mei", and `platform-team.md` contains both "Melinda Grant" and "Jordan Moore".
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - The migration is a single `alter table people add column manager_role text, add column buddy_role text;`.
  - In the manifest, give Alex the new names and roles. Give each other persona plausible roles.
  - **Rewrite the three documents by meaning, not find-and-replace:**
    - the old manager "Jordan Lee" becomes "Melinda Grant", she/her;
    - the old buddy "Mei Tanaka" becomes "Jordan Moore", he/him;
    - every bare "Jordan" or "Mei", and every pronoun, is resolved by which person it meant;
    - keep the facts (one-on-ones, the four-year tenure, pairing).
- [ ] **Step 4: Run** `make test`, then `cd backend && uv run python -m phoebe openapi > ../frontend/openapi.json && cd .. && make fe-gen`. Expected: all tests pass, and `schema.ts` shows the two new fields.
- [ ] **Step 5: Commit.** `feat(people): manager and buddy roles; Melinda Grant and Jordan Moore`.

### Task 5: `reseed` ops task

**Files:**
- Create: `backend/src/phoebe/reseed.py`.
- Modify: `backend/src/phoebe/lambdas/ops.py` (the docstring and allowed tasks gain `"reseed"`).
- Test: `backend/tests/test_lambdas.py` (ops section), `backend/tests/test_seed.py`.

**Interfaces:**
- **Consumes:** `reset_session(db, sid) -> list[str]` and `forget_sandbox(db, sid)` from `phoebe.sandbox`, and `load_seed(db, embedder, seed_dir) -> SeedReport`.
- **Produces:**
  - `clear_visitors(db: Database, blobs: BlobStore) -> int`, which returns the number of visitor ids cleared;
  - the ops result `{"reseeded": True, "visitors_cleared": n, **asdict(report)}`.

- [ ] **Step 1: Write the failing tests.**
  - `test_reseed_clears_visitors_then_reloads`: with a seeded db, create a visitor sandbox that has an owned group, a document, a task completion and a chat turn. Then `handler({"task": "reseed"})` returns `reseeded True` and `visitors_cleared == 1`. Afterwards no row has that `session_id`, and seed counts match a fresh seed.
  - `test_reseed_clears_orphan_visitor_rows`: a visitor `overrides` row whose session has no `sandboxes` row is also removed.
  - `test_deploy_never_calls_reseed`: `"reseed"` does not appear in `ci/deploy.sh`.
- [ ] **Step 2: Run them.** Expected: FAIL with `unknown_task`.
- [ ] **Step 3: Implement `clear_visitors`.**
  - Collect visitor ids as the union of `sandboxes.id` and the distinct non-null, non-empty `session_id` values in `chat_turns`, `task_completions`, `overrides`, `tasks`, `documents` and `groups`. The seed uses `''` in `task_completions`, which must be excluded.
  - For each id: delete the keys from `reset_session` from blobs (logging the type only on failure), then call `forget_sandbox`.
  - The ops handler calls `startup_check_embedder`, then `clear_visitors`, then `load_seed`, and logs counts only.
- [ ] **Step 4: Run** `make test`. Expected: PASS.
- [ ] **Step 5: Document it.** In `infra/app/README.md`, add a one-paragraph "Re-seeding staging" note: the payload is `{"task":"reseed"}`, it deletes every visitor's sandbox data, and it is staging-only.
- [ ] **Step 6: Commit.** `feat(ops): hand-run reseed that clears visitor sandboxes`.

### Task 6: Sticky day strip and manager/buddy avatars

**Files:**
- Create: `frontend/src/employee/photos.ts`, `frontend/src/employee/PersonAvatar.tsx`, `frontend/src/employee/PersonaCard.test.tsx`.
- Modify: `frontend/src/employee/PersonaCard.tsx`, `frontend/src/pages/Employee.tsx`, `frontend/src/test/fixtures.ts` (`ME` gains the roles and the new names).

**Interfaces:**
- **Consumes:** `Me.manager_role` and `Me.buddy_role` (Task 4), and `src/assets/people/*.webp` (Task 1).
- **Produces:**
  - `PHOTOS: Readonly<Record<string, string>>`, keyed by exact name;
  - `initials(name: string): string`, which returns the first and last initials, uppercase;
  - `PersonAvatar({ name, role, label }: { name: string; role: string | null; label: "Manager" | "Buddy" })`;
  - `DayStrip`, exported from `PersonaCard.tsx`.

- [ ] **Step 1: Write the failing tests.**
  - `initials("Melinda Grant") === "MG"`, `initials("Cher") === "C"`, `initials("  ") === "?"`.
  - Rendering with `ME`:
    - `getByRole("img", { name: "Melinda Grant" })` has a `src` containing `melinda-grant`;
    - the text "Engineering Manager, Platform" is present;
    - "Jordan Moore" and "Senior Engineer" are present.
  - A manager named "Elena Petrova" (no photo) renders the initials text "EP" with `aria-label="Elena Petrova"` and no `img`.
  - A `null` manager renders "Not assigned".
  - `DayStrip` has the class `sticky` and contains "Day 5" (`ME.day_number`).
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `PersonaCard` becomes two parts:
    - `DayStrip`: `sticky top-0 z-10 bg-surface`, showing "Day N · Started {date}". This is the only sticky element.
    - Below it, a two-column grid of `PersonAvatar`: a 64 px circle (`rounded-full object-cover`), then a small label ("Manager" / "Buddy"), the name, and the role in muted text.
  - `Employee.tsx` keeps `DayStrip` as the first child of the tasks column's scroll container, so the sticky positioning works on desktop and on the mobile Tasks tab.
- [ ] **Step 4: Run** `npx vitest run`. Expected: PASS.
- [ ] **Step 5: Commit.** `feat(people): sticky day strip and manager/buddy avatars`.

### Task 7: Wider layout

**Files:**
- Modify: `frontend/src/session/SessionGate.tsx` (`max-w-6xl` → `max-w-screen-2xl`), `frontend/src/pages/Employee.tsx` (`lg:grid-cols-[18rem_minmax(0,1fr)_20rem]` → `lg:grid-cols-[20rem_minmax(0,1fr)_22rem]`).
- Test: `frontend/src/pages/Employee.test.tsx`.

- [ ] **Step 1: Write the failing test.** The employee grid element's class contains `lg:grid-cols-[20rem_minmax(0,1fr)_22rem]`, and the `main` element's class contains `max-w-screen-2xl`.
- [ ] **Step 2: Run it.** Expected: FAIL.
- [ ] **Step 3: Implement the two class changes.**
- [ ] **Step 4: Run** `npx vitest run`, then `npx playwright test --project=chromium e2e/employee.spec.ts e2e/mobile.spec.ts`. Expected: PASS.
- [ ] **Step 5: Commit.** `feat(layout): wider page and roomier sidebars`.

### Task 8: Admin Home tab

**Files:**
- Create: `frontend/src/admin/summary.ts`, `frontend/src/admin/summary.test.ts`, `frontend/src/admin/HomeTab.tsx`, `frontend/src/admin/HomeTab.test.tsx`.
- Modify:
  - `frontend/src/admin/PeopleTab.tsx` (export `usePeople`);
  - `frontend/src/admin/GroupsTab.tsx` (export `useGroups()` with key `["groups"]`, and use it there);
  - `frontend/src/pages/Admin.tsx` (`ADMIN_TABS` starts with `{ id: "home", label: "Home" }`; the unknown-tab redirect goes to `/admin/home`);
  - `frontend/src/routes.tsx` (`/admin` → `/admin/home`);
  - `frontend/src/session/session.test.tsx` (the redirect test).

**Interfaces:**
- **Consumes:** `usePeople()`, `useAdminDocuments()`, `useGroups()`.
- **Produces:**
  - `interface AdminSummary { people: number; stillOnboarding: number; avgCompletion: number; documents: number; indexed: number; processing: number; failed: number; groups: number; taskCompletion: number }`, where the percentages are rounded integers from 0 to 100;
  - `summarize(people: PersonProgress[], docs: DocumentOut[], groups: GroupNode[]): AdminSummary`, which counts groups across the whole tree, not just the roots.

- [ ] **Step 1: Write the failing tests.**
  - `summary.test.ts`:
    - For people `[{done: 2, total: 4}, {done: 4, total: 4}]`: `people 2`, `stillOnboarding 1`, `avgCompletion 75`, `taskCompletion 75`.
    - All totals zero gives `avgCompletion 0` and `taskCompletion 0` (Review Focus 4).
    - Docs with statuses `[indexed, indexed, processing, failed]` give `4 / 2 / 1 / 1`.
    - A nested tree of 1 company, 2 departments and 3 teams gives `groups 6`.
  - `HomeTab.test.tsx`: with MSW fixtures, the cards show "People onboarding", "Documents", "Groups" and "Task completion" with their numbers. Each card is a link to `/admin/people`, `/admin/documents`, `/admin/groups` and `/admin/people` respectively.
  - In the session test, `/admin` redirects to `/admin/home` and shows the heading "Home".
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `HomeTab` uses `summarize` over the three queries and shows `QueryError` per failed query.
  - Cards use the `--color-highlight-soft` background.
- [ ] **Step 4: Run** `npx vitest run`. Expected: PASS.
- [ ] **Step 5: Commit.** `feat(admin): home tab with summary cards`.

### Task 9: Collapsible document tree in admin

**Files:**
- Create: `frontend/src/admin/docTree.ts`, `frontend/src/admin/docTree.test.ts`, `frontend/src/admin/DocumentTree.tsx`.
- Modify: `frontend/src/admin/DocumentsTab.tsx` (the table body is replaced by the tree; add/edit/delete/status actions are unchanged), `frontend/src/admin/DocumentsTab.test.tsx`.

**Interfaces:**
- **Consumes:** `useGroups()` (Task 8) and `useAdminDocuments()`.
- **Produces:**
  - `interface DocTreeNode { group: GroupNode; docs: DocumentOut[]; children: DocTreeNode[]; count: number }`, where `count` is the number of documents in the subtree;
  - `buildDocTree(groups: GroupNode[], docs: DocumentOut[]): DocTreeNode[]`. It keeps the group order, puts each group's own docs (sorted by title) before its children, and prunes nodes with `count === 0`.
  - `loadCollapsed(): Set<string>` and `saveCollapsed(ids: Set<string>): void`, using the `sessionStorage` key `"phoebe.admin.docs.collapsed"` and a JSON array of group ids.

- [ ] **Step 1: Write the failing tests.**
  - `docTree.test.ts`:
    - Company → Engineering → Platform, where only Platform has docs: the result keeps all three levels, with counts 2/2/2 (Review Focus 2).
    - A sibling department with no docs anywhere is pruned.
    - A group's own docs come before its child nodes.
  - `loadCollapsed` returns an empty set when the stored value is `"not json"` or `{"a":1}`, and it never throws (Review Focus 3).
  - `DocumentsTab.test.tsx`:
    - Section headers are buttons with `aria-expanded="true"` by default, labelled with the group name and count.
    - Clicking "Platform" hides its documents and sets `aria-expanded="false"`.
    - The collapsed set survives an unmount and remount within the test (`sessionStorage`).
    - An id in storage for a group that no longer exists is ignored.
    - The edit and delete buttons still work on a document row.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement `DocumentTree`.**
  - Use Radix `Collapsible` per node and indent each level.
  - The root company section is labelled with its name ("Larkspur Labs").
  - Keep the existing per-document row content: title, type, status cell and actions.
- [ ] **Step 4: Run** all of the frontend checks and `make test`. Expected: PASS.
- [ ] **Step 5: Commit.** `feat(admin): documents grouped in a collapsible tree`.

---

## After the last task

1. Push `feat/larkspur-branding` and open one PR, with the owner's go-ahead.
2. After merge, the owner invokes ops `{"task":"reseed"}` on staging.
3. Recheck staging:
   - the header logo and favicon;
   - the persona card shows Melinda and Jordan;
   - chat about "who is my buddy" cites Jordan Moore;
   - the admin home and the documents tree.
