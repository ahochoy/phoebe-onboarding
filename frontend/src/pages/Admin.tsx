import { Tabs } from "radix-ui";
import { Navigate, useNavigate, useParams } from "react-router";
import { DocumentsTab } from "../admin/DocumentsTab";
import { GroupsTab } from "../admin/GroupsTab";
import { PeopleTab } from "../admin/PeopleTab";
import { TasksTab } from "../admin/TasksTab";
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
      <Tabs.Content value="tasks" className="min-h-0 min-w-0 flex-1 md:overflow-y-auto">
        <TasksTab />
      </Tabs.Content>
      <Tabs.Content value="groups" className="min-h-0 min-w-0 flex-1 md:overflow-y-auto">
        <GroupsTab />
      </Tabs.Content>
    </Tabs.Root>
  );
}
