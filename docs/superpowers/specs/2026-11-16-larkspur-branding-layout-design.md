# Larkspur Labs branding and layout: design

**Date:** 2026-11-16
**Status:** approaches A/A and builder-check answers (reseed A, sticky A) decided by the owner; doc awaiting owner approval
**Ships in:** one PR, before the v0.1.0 release

## Intent

Phoebe is the onboarding tool of a fictional company, Larkspur Labs. It is an internal tool, and Phoebe is the company's mascot: Larkspur Labs is not presented as Phoebe's maker. A visitor should feel like a new hire at Larkspur on their first days. Today the app shows a small hand-drawn bird and a slate-brown palette, with no company brand.

The owner has supplied a brand kit and wants:
1. the Larkspur brand and the illustrated Phoebe throughout the app;
2. a wider, roomier layout and a set of admin and employee improvements;
3. real-looking avatars for the persona's manager and buddy.

## Goals

- **Brand:**
  - Larkspur logo in the header, with "Phoebe" as the tool name.
  - The Larkspur favicon set and web manifest.
  - Page title "Phoebe · Larkspur Labs".
  - A link-preview image for shared links.
  - The Larkspur colour palette.
- **Phoebe illustrations** in fixed spots (table below), plus the petal loader animation.
- **Layout:**
  - The page content is wider.
  - Chat gets the most extra room, and both sidebars get a little more.
- **Admin:**
  - A new Home tab with summary cards.
  - The documents list is grouped by the group hierarchy, as a collapsible nested tree.
- **Employee:**
  - The day card ("Day N") stays pinned while tasks scroll beneath it.
  - Manager and buddy show as side-by-side circle avatars, each with name and role.
- **Seed data:** Alex's manager becomes **Melinda Grant** (she/her, Engineering Manager, Platform). Alex's buddy becomes **Jordan Moore** (he/him, Senior Engineer). Both use the owner-supplied photos.

## Non-goals

- A dark theme. The app stays light-only, as now. Dark-mode logo variants and the dark loader are not used.
- Phoebe as an independent product brand.
- New backend endpoints for admin statistics.
- Editing manager or buddy, or their photos, in the admin UI.
- Social banners (LinkedIn, X) and profile images from the kit. Only the 1200×630 link preview is used.

## Anti-goals (a failure even if it works)

- Pages noticeably slower or heavier. The source PNGs are about 1.4 MB each and must not ship as-is.
- Text or controls falling below WCAG AA contrast (4.5:1 for text) in the new palette.
- Chat answers citing people that no longer match the card. The seed documents must name Melinda and Jordan with the right pronouns.
- Motion that ignores `prefers-reduced-motion`.
- Breaking the existing test suites: Vitest, Playwright cross-browser, and axe.

## Constraints

- **Frontend:** React + Vite + TypeScript + Tailwind (v4 tokens in `frontend/src/styles.css`), with assistant-ui for chat. Tests are Vitest + MSW and Playwright with axe.
- **Hosting:**
  - Assets are served by CloudFront from S3.
  - Hashed files under `/assets/*` are cached long-term.
  - PR previews live under `/pr-<n>/`, so asset URLs must respect Vite's `base`.
- **Deploy order:** Lambda code updates before `migrate` runs, so schema changes must be expand-only (add nullable columns).
- **Seeding:** `ops seed_if_empty` never re-seeds a database that already has seed groups.
  - Production is empty at v0.1.0, so it gets the new seed.
  - Staging is already seeded, so it needs an explicit re-seed (see Seed data).
- Synthetic data only. The photos are of fictional people supplied by the owner.

## Asset sources

| Asset | Location |
|---|---|
| Brand kit (logo, favicons, loader, social, Phoebe poses) | `/Users/hochoy/Downloads/6d11aee5521a4771ae4cbd0d9090dec9/` |
| Manager photo (Melinda Grant) | `/Users/hochoy/Downloads/image_1bc43cfb.jpg` |
| Buddy photo (Jordan Moore) | `/Users/hochoy/Downloads/image_107ac173.jpg` |

**Brand colours (from the kit README):**
- navy wordmark `#0B2772`;
- petals `#6376F1`, `#665AE1` and `#8B9BF6`;
- overlaps `#2F3DA6`.

**Phoebe poses:** transparent 1024×1024 PNGs in `phoebe/transparent/`: waving, thinking, pointing, celebrating, onboarding-checklist and oops-error.

**Loader:** `loader/larkspur-loader.svg` is a 1.4 KB animated SVG with built-in reduced-motion and dark-mode handling.

## Approaches considered

1. **Where manager and buddy roles and photos live.**
   - **Chosen: A.** Roles go in the seed data and database, as two nullable `people` columns returned by `/api/me`. Photos are frontend assets chosen by name, with an initials circle when there is no photo.
   - **Rejected: B.** A frontend name → role and photo table. It needs no backend change, but role data would drift from the seed.
2. **Admin home statistics.**
   - **Chosen: A.** Computed in the browser from data the admin pages already fetch.
   - **Rejected: B.** A new `/api/admin/summary` endpoint. It isn't needed at demo scale (3 personas, about 30 documents).
3. **Images.**
   - Imported through Vite for hashed, long-cached URLs.
   - Favicons and the manifest stay in `public/`, because browsers request them by fixed name.
   - The animation uses the SVG loader. It needs no player library, unlike Lottie, and is lighter than WebM, APNG or GIF.

## Design

### Assets (commit 1)

**Phoebe poses:**
- Converted to WebP with alpha.
- Each is sized for its largest use, with a 2× version for sharp screens: the hero at 512 px (1× 256), and states and the splash at 256 px (1× 128).
- A head-and-shoulders crop of the waving pose for the chat avatar at 64 px (1× 32).
- Target: about 60 KB or less per file.

**Photos:**
- Square-cropped to the face.
- WebP at 192 px (shown at 64–96 px, round-masked in CSS).

**Other files:**
- Copied as-is: logo SVGs (colour lockup and mark), the loader SVG, the favicon set and `site.webmanifest`.
- The manifest's `name` is "Phoebe · Larkspur Labs" and its `short_name` is "Phoebe".
- `social/larkspur-link-preview-1200x630.png` is used for `og:image`, converted to optimised PNG or JPEG.

Originals are not committed.

### Branding (commit 2)

- **Palette:** in `styles.css`, the accent becomes navy `#0B2772`.
  - Add a highlight token from the petal colours, used for hover tints, focus accents and active tabs.
  - Recheck every text and background pair against AA.
  - The axe tests must stay green.
- **Header:** the Larkspur logo (colour lockup), then "Phoebe" as the tool name.
- **`index.html`:**
  - title "Phoebe · Larkspur Labs";
  - the favicon links from the kit's `head-snippet.html`, prefixed with Vite's base so they work under `/pr-<n>/`;
  - `theme-color`;
  - `og:title`, `og:description` and `og:image`.
- **`og:image` needs an absolute URL** *(builder call)*:
  - It is built from a build-time `VITE_SITE_ORIGIN` that the deploy sets per environment: the staging CloudFront domain, or production's.
  - PR previews use staging's origin, since previews are never shared publicly.
  - Without it (local dev), the tag is omitted.
- **Phoebe placement:**

| Spot | Asset |
|---|---|
| Landing hero | waving (copy: "Welcome to Larkspur Labs. I'm Phoebe, your onboarding guide.") |
| Welcome splash (first visit) | onboarding-checklist |
| Chat greeting | waving |
| Avatar beside each answer | waving head crop |
| "Phoebe is thinking…" | thinking, small, beside the text |
| Loading screen ("Getting Phoebe ready…") and the 8 s "Phoebe is waking up" chat state | petal loader |
| Errors (chat error, failed page loads) | oops-error, beside the message |
| Empty lists (no documents or tasks) | pointing |
| Task checklist completed (existing "cheer" moment) | celebrating |

- Every illustration is decorative (`alt=""`). Adjacent text carries the meaning.
- The old `Mascot.tsx` SVG is removed once nothing uses it.

### Seed and people (commit 3)

- **Migration `004_people_roles.sql`:** add nullable `manager_role text` and `buddy_role text` to `people`. This is expand-only.
- **Seed manifest:** add both roles for every persona.
  - Alex: manager Melinda Grant (Engineering Manager, Platform) and buddy Jordan Moore (Senior Engineer).
  - The other personas keep their names and get plausible roles.
- **`seed.py` and `persona.py`:** insert and read the new columns. `/api/me` returns `manager_role` and `buddy_role`, and the OpenAPI file and `schema.ts` are regenerated.
- **Seed documents:** rewrite `platform-team.md`, `first-week.md` and `project-manifest.txt`.
  - Jordan Lee (manager) becomes Melinda Grant, she/her.
  - Mei Tanaka (buddy) becomes Jordan Moore, he/him.
  - Watch the collision: the old manager's first name, Jordan, is the new buddy's first name, so every "Jordan" must be resolved by meaning, not by find-and-replace.
  - Update any test that names them (for example `tests/test_api_chat.py`).
- **Staging re-seed** *(owner decision)*:
  - `load_seed` cannot reload while visitor sandboxes exist, because they reference seed groups, tasks and people by foreign key (see its docstring).
  - Add an ops task `reseed` that first deletes every visitor sandbox and its rows, using the same path the session sweeper uses, then runs `load_seed`.
  - It is invoked by hand only. Deploys never call it, and `seed_if_empty` stays as is.
  - The owner runs it once on staging after merge. Staging visitor data is throwaway.
  - Production is never reseeded: it seeds fresh at v0.1.0.
- **Photos:** a frontend map `{ "Melinda Grant": melinda.webp, "Jordan Moore": jordan.webp }`. Any other name renders an initials circle in the same size and shape.

### Layout and admin (commit 4)

- **Width:**
  - The `SessionGate` content cap goes from `max-w-6xl` (1152 px) to `max-w-screen-2xl` (1536 px).
  - The employee grid goes from `18rem / 1fr / 20rem` to about `20rem / 1fr / 22rem`, so chat gains the most.
  - Mobile tabs are unchanged.
- **Employee sidebar:**
  - *(owner decision)* Only the "Day N · Started …" strip is `position: sticky; top: 0` inside the tasks column's scroll container, on desktop and on the mobile Tasks tab. It has an opaque background so tasks scroll beneath it.
  - Manager and buddy sit side by side just below that strip. Each shows a 64 px circle photo, the name, then the role in muted text. They scroll away with the tasks.
- **Admin Home:**
  - A new first tab, `home`. `/admin` redirects to `/admin/home` instead of `/admin/people`.
  - It shows these cards:
    - people onboarding;
    - documents, with the indexed count, plus processing and failed counts if any;
    - groups;
    - overall task completion, as a percentage.
  - "People onboarding" *(builder call)* shows the persona count as the headline, "N still onboarding" (`done < total` in `/api/people`) beneath it, and the average completion. The task-completion card uses `sum(done) / sum(total)` from the same response.
  - The data comes from the existing queries the other tabs use (shared React Query keys), so visiting tabs doesn't refetch.
  - Each card links to its tab.
- **Admin Documents:**
  - Rendered as a tree that follows the group hierarchy (`parent_id`). The seed has three levels: company, department, team.
  - *(builder call)* The company root is the top section ("Larkspur Labs") and holds company-wide documents. A group lists its own documents before its child groups.
  - Each group is a collapsible section showing its name and document count.
  - Groups with no documents are hidden, unless a descendant has documents.
  - Collapsed state is kept in `sessionStorage`, and all groups are expanded by default.
  - Existing actions (add, edit, delete, status) are unchanged.
  - The section headers are buttons with `aria-expanded`.
- **Empty and error states:** use the poses from commit 2.

## Left to the builder

- **Exact pixel sizes, spacing, and the hover or focus styles** within the palette above.
- **The exact WebP quality settings,** within the size target.
- **Roles for the non-Alex personas' managers and buddies.**
- **Copy tweaks for empty states,** in plain sentences consistent with `lib/messages.ts`.
- **Whether the document tree shows group kind labels,** such as "Department".
- **Test details:**
  - Each feature gets Vitest coverage for behaviour: the collapse toggle and its memory, the stats math, the sticky card class, the avatar fallback, and the `/admin` redirect.
  - Backend tests cover the migration, the seed columns, `/api/me` and `reseed`.
  - Playwright and axe stay green.
