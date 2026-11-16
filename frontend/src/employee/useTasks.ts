import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef } from "react";
import { apiGet, apiSend } from "../api/client";
import type { TaskView } from "../api/types";
import { onDemoReset } from "../state/demoReset";

export type TaskScope = "mine" | "all";

export function useTasks(scope: TaskScope) {
  return useQuery({
    queryKey: ["tasks", scope],
    queryFn: () => apiGet<TaskView[]>(`/api/tasks?scope=${scope}`),
  });
}

function setDone(client: QueryClient, id: string, done: boolean) {
  client.setQueriesData<TaskView[]>({ queryKey: ["tasks"] }, (old) =>
    old?.map((t) => (t.id === id ? { ...t, done } : t)),
  );
}

/** Per-task bookkeeping: what the server has, what the user wants, and whether a PUT is out. */
interface Slot {
  server: boolean;
  wanted: boolean;
  inFlight: boolean;
}

/**
 * Returns `toggle(task, done)`. The cache updates at once; requests are
 * serialised per task id: while one is in flight only the latest wanted state
 * is remembered, and it is sent when the request settles, if it differs from
 * what the server now has. A failure rolls the task back to the server state.
 */
export function useToggleTask(onError?: (err: unknown) => void) {
  const client = useQueryClient();
  const slots = useRef(new Map<string, Slot>());
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onErrorRef.current = onError;
  });

  const put = useMutation({
    mutationFn: ({ id, done }: { id: string; done: boolean }) =>
      apiSend("PUT", `/api/tasks/${id}/completion`, { done }),
  });
  const { mutateAsync } = put;

  // A demo reset wipes the sandbox: forget every slot, so a PUT still in flight
  // neither sends the queued follow-up nor writes its answer over the fresh data.
  useEffect(
    () =>
      onDemoReset(() => {
        slots.current = new Map();
      }),
    [],
  );

  const pump = useCallback(
    async (id: string) => {
      const map = slots.current;
      const slot = map.get(id);
      if (!slot || slot.inFlight) return;
      const current = () => slots.current === map;
      while (current() && slot.wanted !== slot.server) {
        const sending = slot.wanted;
        slot.inFlight = true;
        try {
          await mutateAsync({ id, done: sending });
          slot.server = sending;
        } catch (err) {
          slot.wanted = slot.server;
          if (current()) {
            setDone(client, id, slot.server);
            onErrorRef.current?.(err);
          }
        } finally {
          slot.inFlight = false;
        }
      }
      if (!current()) return;
      map.delete(id);
      // A tasks refetch may have landed while the PUT was out and put the old value
      // back: write what the server now has, then refetch to agree with it.
      setDone(client, id, slot.server);
      void client.invalidateQueries({ queryKey: ["tasks"] });
      // The admin People table shows this person's progress too.
      void client.invalidateQueries({ queryKey: ["people"] });
    },
    [client, mutateAsync],
  );

  return useCallback(
    (task: TaskView, done: boolean) => {
      void client.cancelQueries({ queryKey: ["tasks"] });
      setDone(client, task.id, done);
      let slot = slots.current.get(task.id);
      if (!slot) {
        slot = { server: task.done, wanted: done, inFlight: false };
        slots.current.set(task.id, slot);
      }
      slot.wanted = done;
      void pump(task.id);
    },
    [client, pump],
  );
}
