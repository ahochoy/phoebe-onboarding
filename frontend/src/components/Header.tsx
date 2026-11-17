import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ToggleGroup } from "radix-ui";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { apiGet, apiSend } from "../api/client";
import logo from "../assets/brand/larkspur-logo.svg";
import type { GroupNode } from "../api/types";
import { formatStart } from "../lib/dates";
import { clearHadSession, forgetSession, useMe } from "../session/useMe";
import { ResetDialog } from "./ResetDialog";
import { StatusPill } from "./StatusPill";

const toggleItem =
  "inline-flex min-h-8 min-w-16 cursor-pointer items-center justify-center rounded-md px-3 py-1 text-sm font-medium data-[state=on]:bg-accent data-[state=on]:text-white";

export function Header() {
  const me = useMe();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [loggingOut, setLoggingOut] = useState(false);

  const groups = useQuery({
    queryKey: ["groups"],
    queryFn: () => apiGet<GroupNode[]>("/api/groups"),
  });
  const company = (groups.data?.find((g) => g.kind === "company") ?? groups.data?.[0])?.name;

  const mode = pathname.startsWith("/admin") ? "admin" : "employee";

  async function logout() {
    setLoggingOut(true);
    try {
      await apiSend("POST", "/api/logout");
    } catch {
      // Leave either way: the session is being abandoned.
    }
    clearHadSession();
    void navigate("/", { replace: true });
    forgetSession(queryClient);
  }

  return (
    <header className="border-b border-ink/15 bg-white">
      <div className="mx-auto flex max-w-screen-2xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2">
        <div className="flex items-center gap-2">
          <img src={logo} alt="Larkspur Labs" className="h-7 w-auto" />
          <span aria-hidden="true" className="h-6 w-px bg-ink/20" />
          <span className="text-lg font-semibold">Phoebe</span>
          {company && <span className="text-sm text-ink/80">{company}</span>}
        </div>

        {mode === "employee" && me.data && (
          <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
            <span className="font-medium">{me.data.name}</span>
            <span>{me.data.team_name}</span>
            <span aria-hidden="true">·</span>
            <span>{`Started ${formatStart(me.data.start_date)}`}</span>
            <span aria-hidden="true">·</span>
            <span>{`Day ${me.data.day_number}`}</span>
          </div>
        )}

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <StatusPill />
          <ToggleGroup.Root
            type="single"
            value={mode}
            aria-label="View"
            onValueChange={(next) => {
              if (next === "employee") void navigate("/employee");
              else if (next === "admin") void navigate("/admin/home");
            }}
            className="inline-flex gap-1 rounded-lg border border-ink/20 p-0.5"
          >
            <ToggleGroup.Item value="employee" className={toggleItem}>
              Employee
            </ToggleGroup.Item>
            <ToggleGroup.Item value="admin" className={toggleItem}>
              Admin
            </ToggleGroup.Item>
          </ToggleGroup.Root>
          <ResetDialog />
          <button
            type="button"
            disabled={loggingOut}
            onClick={() => void logout()}
            className="inline-flex min-h-8 cursor-pointer items-center rounded-md px-3 py-1 text-sm font-medium text-accent underline disabled:opacity-60"
          >
            Log out
          </button>
        </div>
      </div>
    </header>
  );
}
