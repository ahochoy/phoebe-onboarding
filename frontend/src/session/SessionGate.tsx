import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Navigate, Outlet, useNavigate } from "react-router";
import { ApiError, onSessionExpired } from "../api/client";
import { ChatRuntimeProvider } from "../chat/ChatRuntimeProvider";
import { Header } from "../components/Header";
import { PetalLoader } from "../components/PetalLoader";
import { WelcomeSplash } from "../components/WelcomeSplash";
import { messageFor } from "../lib/messages";
import { nudgeWake } from "../lib/wake";
import { forgetSession, useMe } from "./useMe";

/** Renders its child routes only while there is a live session. */
export function SessionGate() {
  const me = useMe();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // Any request anywhere that comes back 401 session_expired sends us home.
  useEffect(
    () =>
      onSessionExpired(() => {
        forgetSession(queryClient);
        void navigate("/", { replace: true, state: { expired: true } });
      }),
    [navigate, queryClient],
  );

  // Signed in: start a paused database resuming before the first question.
  const signedIn = me.isSuccess;
  useEffect(() => {
    if (signedIn) nudgeWake();
  }, [signedIn]);

  if (me.isPending) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-3">
        <PetalLoader size={64} label="Getting Phoebe ready…" />
      </main>
    );
  }

  if (me.isError) {
    const err = me.error;
    if (err instanceof ApiError && err.status === 401) {
      return <Navigate to="/" replace state={{ expired: true }} />;
    }
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-3 p-4 text-center">
        <p role="alert">{messageFor(err)}</p>
        <button
          type="button"
          onClick={() => void me.refetch()}
          className="inline-flex min-h-8 cursor-pointer items-center rounded-md bg-accent px-4 py-1 text-sm font-medium text-white"
        >
          Try again
        </button>
      </main>
    );
  }

  return (
    <div className="flex h-dvh flex-col">
      <Header />
      <main className="mx-auto min-h-0 w-full max-w-screen-2xl flex-1 overflow-y-auto p-4">
        {/* Session-scoped, so the conversation and any answer in progress survive
            switching between the Employee and Admin views. */}
        <ChatRuntimeProvider>
          <Outlet />
        </ChatRuntimeProvider>
      </main>
      <WelcomeSplash me={me.data} />
    </div>
  );
}
