import { Tabs } from "radix-ui";
import { Navigate, useNavigate, useParams } from "react-router";
import { DocumentsTab } from "../admin/DocumentsTab";
import { PeopleTab } from "../admin/PeopleTab";
import { MD_UP, useMediaQuery } from "../lib/useMediaQuery";

export const ADMIN_TABS = [
  { id: "people", label: "People & Progress" },
  { id: "documents", label: "Documents" },
  { id: "tasks", label: "Tasks" },
  { id: "groups", label: "Groups" },
] as const;

export type AdminTab = (typeof ADMIN_TABS)[number]["id"];

function isAdminTab(value: string | undefined): value is AdminTab {
  return ADMIN_TABS.some((t) => t.id === value);
}

const trigger =
  "inline-flex min-h-10 shrink-0 cursor-pointer items-center whitespace-nowrap rounded-md px-3 py-2 text-left text-sm font-medium text-ink/80 -outline-offset-2 data-[state=active]:bg-accent data-[state=active]:font-semibold data-[state=active]:text-white";

/** Placeholder until the tab's real content lands. */
function Soon({ title }: { title: string }) {
  return (
    <section aria-label={title} className="space-y-2">
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="text-sm text-ink/80">This section is coming soon.</p>
    </section>
  );
}

/**
 * The admin view. The active tab lives in the URL (`/admin/:tab`), so links and the back
 * button work. Tabs run vertically from md up and as a scrolling row below it; the same
 * tree renders in both, only its orientation and classes change.
 */
export function Admin() {
  const { tab } = useParams();
  const navigate = useNavigate();
  const wide = useMediaQuery(MD_UP);

  if (!isAdminTab(tab)) return <Navigate to="/admin/people" replace />;

  return (
    <Tabs.Root
      value={tab}
      onValueChange={(v) => void navigate(`/admin/${v}`)}
      orientation={wide ? "vertical" : "horizontal"}
      className="flex h-full min-h-0 flex-col gap-4 md:flex-row"
    >
      <Tabs.List
        aria-label="Admin sections"
        className="flex shrink-0 gap-1 overflow-x-auto border-b border-ink/15 pb-2 md:w-56 md:flex-col md:overflow-visible md:border-r md:border-b-0 md:pr-4 md:pb-0"
      >
        {ADMIN_TABS.map((t) => (
          <Tabs.Trigger key={t.id} value={t.id} className={trigger}>
            {t.label}
          </Tabs.Trigger>
        ))}
      </Tabs.List>
      <Tabs.Content value="people" className="min-h-0 min-w-0 flex-1 md:overflow-y-auto">
        <PeopleTab />
      </Tabs.Content>
      <Tabs.Content value="documents" className="min-h-0 min-w-0 flex-1 md:overflow-y-auto">
        <DocumentsTab />
      </Tabs.Content>
      {ADMIN_TABS.filter((t) => t.id !== "people" && t.id !== "documents").map((t) => (
        <Tabs.Content key={t.id} value={t.id} className="min-h-0 min-w-0 flex-1 md:overflow-y-auto">
          <Soon title={t.label} />
        </Tabs.Content>
      ))}
    </Tabs.Root>
  );
}
