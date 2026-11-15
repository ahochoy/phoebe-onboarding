import { Tabs } from "radix-ui";
import { useState, type ReactNode } from "react";
import { ChatPanel } from "../chat/ChatPanel";
import { DocumentsPanel } from "../documents/DocumentsPanel";
import { ViewerProvider } from "../documents/ViewerProvider";
import { PersonaCard } from "../employee/PersonaCard";
import { TasksPanel } from "../employee/TasksPanel";
import { MD_UP, useMediaQuery } from "../lib/useMediaQuery";

type TabId = "tasks" | "chat" | "docs";

const TABS: { id: TabId; label: string }[] = [
  { id: "tasks", label: "Tasks" },
  { id: "chat", label: "Chat" },
  { id: "docs", label: "Docs" },
];

function TasksColumn() {
  return (
    <div className="space-y-4">
      <PersonaCard />
      <TasksPanel />
    </div>
  );
}

function Region({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="flex min-h-0 flex-1 flex-col gap-2">
      <h2 id={id} className="text-lg font-semibold">
        {title}
      </h2>
      {children}
    </section>
  );
}

const chatRegion = (
  <Region id="chat-heading" title="Chat">
    <div className="flex min-h-0 flex-1 flex-col">
      <ChatPanel />
    </div>
  </Region>
);

const docsRegion = (
  <Region id="docs-heading" title="Documents">
    <div className="min-h-0 flex-1 overflow-y-auto">
      <DocumentsPanel />
    </div>
  </Region>
);

function DesktopLayout() {
  return (
    <div className="grid h-[calc(100dvh-6rem)] grid-cols-[18rem_1fr_20rem] gap-4">
      <div className="min-h-0 overflow-y-auto">
        <TasksColumn />
      </div>
      <div className="flex min-h-0 flex-col">{chatRegion}</div>
      <div className="flex min-h-0 flex-col">{docsRegion}</div>
    </div>
  );
}

const tabTrigger =
  "flex min-h-12 flex-1 cursor-pointer items-center justify-center text-sm font-medium text-ink/80 data-[state=active]:border-t-2 data-[state=active]:border-accent data-[state=active]:font-semibold data-[state=active]:text-accent";

function MobileLayout() {
  const [tab, setTab] = useState<TabId>("chat");
  // Every panel stays mounted (forceMount) so chat state survives tab switches.
  const panel = (id: TabId, children: ReactNode) => (
    <Tabs.Content
      value={id}
      forceMount
      hidden={tab !== id}
      className="min-h-0 flex-1 flex-col data-[state=active]:flex data-[state=inactive]:hidden"
    >
      {children}
    </Tabs.Content>
  );
  return (
    <Tabs.Root
      value={tab}
      onValueChange={(v) => setTab(v as TabId)}
      className="flex h-[calc(100dvh-7rem)] flex-col pb-[calc(3rem+env(safe-area-inset-bottom))]"
    >
      {panel(
        "tasks",
        <div className="min-h-0 flex-1 overflow-y-auto">
          <TasksColumn />
        </div>,
      )}
      {panel("chat", chatRegion)}
      {panel("docs", docsRegion)}
      <Tabs.List
        aria-label="Sections"
        className="fixed inset-x-0 bottom-0 z-10 flex border-t border-ink/15 bg-white pb-[env(safe-area-inset-bottom)]"
      >
        {TABS.map((t) => (
          <Tabs.Trigger key={t.id} value={t.id} className={tabTrigger}>
            {t.label}
          </Tabs.Trigger>
        ))}
      </Tabs.List>
    </Tabs.Root>
  );
}

/** The employee view: three columns from md up, bottom tabs below. */
export function Employee() {
  const wide = useMediaQuery(MD_UP);
  return <ViewerProvider>{wide ? <DesktopLayout /> : <MobileLayout />}</ViewerProvider>;
}
