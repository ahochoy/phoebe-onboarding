import { Tabs } from "radix-ui";
import { useState, type ReactNode } from "react";
import { ChatPanel } from "../chat/ChatPanel";
import { DocumentsPanel } from "../documents/DocumentsPanel";
import { ViewerProvider } from "../documents/ViewerProvider";
import { PersonaCard } from "../employee/PersonaCard";
import { TasksPanel } from "../employee/TasksPanel";
import { LG_UP, useMediaQuery } from "../lib/useMediaQuery";

type TabId = "tasks" | "chat" | "docs";

const TABS: { id: TabId; label: string }[] = [
  { id: "tasks", label: "Tasks" },
  { id: "chat", label: "Chat" },
  { id: "docs", label: "Docs" },
];

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

const tabTrigger =
  "flex min-h-12 flex-1 cursor-pointer items-center justify-center text-sm font-medium text-ink/80 data-[state=active]:border-t-2 data-[state=active]:border-accent data-[state=active]:font-semibold data-[state=active]:text-accent";

/**
 * The employee view: three columns from lg up, bottom tabs below. One stable tree
 * (each panel mounted once, never remounted) so chat state survives tab switches and
 * breakpoint changes; CSS decides which panels show.
 */
export function Employee() {
  const wide = useMediaQuery(LG_UP);
  const [tab, setTab] = useState<TabId>("chat");

  const panel = (id: TabId, children: ReactNode) => (
    <Tabs.Content
      value={id}
      forceMount
      // At lg+ the panels are plain columns, not tab panels: no role, label or tab stop.
      {...(wide ? { role: "presentation", "aria-labelledby": undefined, tabIndex: undefined } : {})}
      className="flex min-h-0 flex-1 flex-col max-lg:data-[state=inactive]:hidden lg:flex-none"
    >
      {children}
    </Tabs.Content>
  );

  return (
    <ViewerProvider>
      <Tabs.Root
        value={tab}
        onValueChange={(v) => setTab(v as TabId)}
        className="flex h-full min-h-0 flex-col lg:grid lg:grid-cols-[18rem_minmax(0,1fr)_20rem] lg:gap-4"
      >
        {panel(
          "tasks",
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
            <PersonaCard />
            <TasksPanel />
          </div>,
        )}
        {panel(
          "chat",
          <Region id="chat-heading" title="Chat">
            <div className="flex min-h-0 flex-1 flex-col">
              <ChatPanel />
            </div>
          </Region>,
        )}
        {panel(
          "docs",
          <Region id="docs-heading" title="Documents">
            <div className="min-h-0 flex-1 overflow-y-auto">
              <DocumentsPanel />
            </div>
          </Region>,
        )}
        {!wide && (
          <Tabs.List
            aria-label="Sections"
            className="-mx-4 -mb-4 flex shrink-0 border-t border-ink/15 bg-white pb-[env(safe-area-inset-bottom)]"
          >
            {TABS.map((t) => (
              <Tabs.Trigger key={t.id} value={t.id} className={tabTrigger}>
                {t.label}
              </Tabs.Trigger>
            ))}
          </Tabs.List>
        )}
      </Tabs.Root>
    </ViewerProvider>
  );
}
