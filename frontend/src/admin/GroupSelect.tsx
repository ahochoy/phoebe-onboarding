import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown } from "lucide-react";
import { Select } from "radix-ui";
import { apiGet } from "../api/client";
import type { GroupNode } from "../api/types";

interface Option {
  id: string;
  name: string;
  indent: boolean;
}

/** Company first, then each department followed by its teams (indented). */
function flatten(nodes: GroupNode[]): Option[] {
  const out: Option[] = [];
  const walk = (node: GroupNode) => {
    out.push({ id: node.id, name: node.name, indent: node.kind === "team" });
    for (const child of node.children) walk(child);
  };
  for (const node of nodes) walk(node);
  return out;
}

export interface GroupSelectProps {
  value: string;
  onChange: (id: string) => void;
  id?: string;
  "aria-label"?: string;
  "aria-labelledby"?: string;
  "aria-describedby"?: string;
  "aria-invalid"?: boolean;
  disabled?: boolean;
}

export function GroupSelect({ value, onChange, disabled, ...aria }: GroupSelectProps) {
  const { data, error, isPending } = useQuery({
    queryKey: ["groups"],
    queryFn: () => apiGet<GroupNode[]>("/api/groups"),
  });
  const options = data ? flatten(data) : [];
  const placeholder = isPending
    ? "Loading groups…"
    : error
      ? "Groups unavailable"
      : "Choose a group";

  return (
    <Select.Root value={value} onValueChange={onChange} disabled={disabled || options.length === 0}>
      <Select.Trigger
        {...aria}
        className="flex min-h-10 w-full cursor-pointer items-center justify-between gap-2 rounded-md border border-ink/30 bg-white px-3 py-2 text-left text-sm disabled:cursor-not-allowed disabled:bg-ink/5 data-[placeholder]:text-ink/70"
      >
        <Select.Value placeholder={placeholder} />
        <Select.Icon>
          <ChevronDown aria-hidden="true" className="size-4" />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content
          position="popper"
          sideOffset={4}
          className="z-[60] max-h-72 min-w-(--radix-select-trigger-width) overflow-y-auto rounded-md border border-ink/20 bg-white p-1 shadow-lg"
        >
          <Select.Viewport>
            {options.map((o) => (
              <Select.Item
                key={o.id}
                value={o.id}
                className={`relative flex min-h-8 cursor-pointer items-center rounded px-2 py-1 pr-7 text-sm outline-none data-[highlighted]:bg-accent data-[highlighted]:text-white ${o.indent ? "pl-6" : ""}`}
              >
                <Select.ItemText>{o.name}</Select.ItemText>
                <Select.ItemIndicator className="absolute right-2">
                  <Check aria-hidden="true" className="size-4" />
                </Select.ItemIndicator>
              </Select.Item>
            ))}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  );
}
