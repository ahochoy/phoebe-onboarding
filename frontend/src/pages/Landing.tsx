import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";
import { ApiError, apiSend } from "../api/client";
import { PhoebeArt } from "../components/PhoebeArt";
import { SpendBanner } from "../components/SpendBanner";
import { WELCOME_KEY } from "../components/WelcomeSplash";
import { messageFor } from "../lib/messages";
import { hadSession, markHadSession, useMe } from "../session/useMe";
import { useStatus } from "../state/status";

// Answers that mean the whole demo is offline: shut by the owner, or its database
// stopped (the spend limit).
const OFFLINE_CODES: ReadonlySet<string> = new Set(["demo_closed", "database_stopped"]);

export function Landing() {
  const me = useMe();
  const { status } = useStatus();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  // First-time visitors bounced by the gate never had a session to end.
  const expired =
    (location.state as { expired?: boolean } | null)?.expired === true && hadSession();

  const fieldRef = useRef<HTMLInputElement>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [stopped, setStopped] = useState(false);

  // An existing session skips the form: logging in again would wipe the sandbox.
  if (me.isSuccess) return <Navigate to="/employee" replace />;

  const closed =
    stopped ||
    status?.state === "closed" ||
    (me.error instanceof ApiError && OFFLINE_CODES.has(me.error.code));

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy || !password) return;
    setBusy(true);
    setError(null);
    try {
      await apiSend("POST", "/api/login", { password });
      markHadSession();
      try {
        window.sessionStorage.setItem(WELCOME_KEY, "pending");
      } catch {
        // Without storage the splash is simply skipped.
      }
      // Discard the earlier 401 so the gate starts from a clean "pending".
      void queryClient.resetQueries({ queryKey: ["me"] });
      void navigate("/employee", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && OFFLINE_CODES.has(err.code)) {
        setStopped(true);
        setBusy(false);
        return;
      }
      setError(messageFor(err));
      setBusy(false);
      fieldRef.current?.focus();
    }
  }

  return (
    <>
      <SpendBanner />
      <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-4 p-4 text-center">
        <PhoebeArt pose="waving" size={192} />
        <h1 className="text-3xl font-semibold text-accent">Welcome to Larkspur Labs</h1>
        <p className="text-base">
          I&apos;m Phoebe, your AI onboarding guide. Ask a question and get answers drawn from your
          team&apos;s own documents.
        </p>

        {expired && !closed && (
          <p role="status" className="text-sm font-medium text-warn">
            {messageFor("session_expired")}
          </p>
        )}

        {closed ? (
          <p role="status" className="text-base font-medium">
            {messageFor("demo_closed")}
          </p>
        ) : me.isPending ? (
          <p role="status">Getting Phoebe ready…</p>
        ) : (
          <form onSubmit={(e) => void submit(e)} className="flex w-full flex-col gap-3 text-left">
            <label htmlFor="demo-password" className="text-sm font-medium">
              Demo password
            </label>
            <input
              id="demo-password"
              ref={fieldRef}
              type="password"
              autoComplete="off"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? "demo-password-error" : undefined}
              className="min-h-10 rounded-md border border-ink/40 bg-white px-3 py-2"
            />
            {error && (
              <p id="demo-password-error" role="alert" className="text-sm text-danger">
                {error}
              </p>
            )}
            <button
              type="submit"
              disabled={busy}
              className="inline-flex min-h-10 cursor-pointer items-center justify-center rounded-md bg-accent px-4 py-2 font-medium text-white disabled:opacity-60"
            >
              Enter
            </button>
          </form>
        )}
      </main>
    </>
  );
}
