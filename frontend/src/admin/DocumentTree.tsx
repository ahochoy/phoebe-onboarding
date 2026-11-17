import { ChevronDown } from "lucide-react";
import { Collapsible } from "radix-ui";
import { useState, type ReactNode } from "react";
import type { DocumentOut, GroupNode } from "../api/types";
import { buildDocTree, groupIds, loadCollapsed, saveCollapsed, type DocTreeNode } from "./docTree";

const HEADINGS = ["h3", "h4", "h5", "h6"] as const;
const OTHER_ID = "__other__";

function Section({
  node,
  depth,
  collapsed,
  toggle,
  renderDoc,
}: {
  node: DocTreeNode;
  depth: number;
  collapsed: Set<string>;
  toggle: (id: string) => void;
  renderDoc: (d: DocumentOut) => ReactNode;
}) {
  const Heading = HEADINGS[Math.min(depth, HEADINGS.length - 1)]!;
  const open = !collapsed.has(node.group.id);
  return (
    <Collapsible.Root
      open={open}
      onOpenChange={() => toggle(node.group.id)}
      className={depth > 0 ? "ml-4 border-l border-ink/15 pl-2" : ""}
    >
      <Heading className="text-sm font-semibold">
        <Collapsible.Trigger className="flex min-h-10 w-full cursor-pointer items-center gap-2 rounded-md px-2 text-left hover:bg-highlight-soft">
          <ChevronDown
            aria-hidden="true"
            className={`size-4 shrink-0 text-accent transition-transform ${open ? "" : "-rotate-90"}`}
          />
          <span>
            {node.group.name}{" "}
            <span className="font-normal text-ink/70">
              ({node.count}{" "}
              <span className="sr-only">{node.count === 1 ? "document" : "documents"}</span>)
            </span>
          </span>
        </Collapsible.Trigger>
      </Heading>
      <Collapsible.Content>
        {node.docs.length > 0 ? (
          <ul className="divide-y divide-ink/10">
            {node.docs.map((d) => (
              <li key={d.id}>{renderDoc(d)}</li>
            ))}
          </ul>
        ) : null}
        {node.children.map((c) => (
          <Section
            key={c.group.id}
            node={c}
            depth={depth + 1}
            collapsed={collapsed}
            toggle={toggle}
            renderDoc={renderDoc}
          />
        ))}
      </Collapsible.Content>
    </Collapsible.Root>
  );
}

export function DocumentTree({
  groups,
  docs,
  renderDoc,
}: {
  groups: GroupNode[];
  docs: DocumentOut[];
  renderDoc: (d: DocumentOut) => ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(loadCollapsed);
  const toggle = (id: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      saveCollapsed(next);
      return next;
    });

  const known = groupIds(groups);
  const orphans = docs.filter((d) => !known.has(d.group_id));
  const roots = buildDocTree(groups, docs);
  if (orphans.length > 0) {
    roots.push({
      group: {
        id: OTHER_ID,
        kind: "team",
        name: "Other",
        owned: false,
        parent_id: null,
        children: [],
      },
      docs: [...orphans].sort((a, b) => a.title.localeCompare(b.title)),
      children: [],
      count: orphans.length,
    });
  }

  return (
    <div className="space-y-1 rounded-md border border-ink/20 bg-white p-2">
      {roots.map((r) => (
        <Section
          key={r.group.id}
          node={r}
          depth={0}
          collapsed={collapsed}
          toggle={toggle}
          renderDoc={renderDoc}
        />
      ))}
    </div>
  );
}
