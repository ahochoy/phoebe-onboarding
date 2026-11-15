import { ApiError } from "../api/client";

// The only place API error codes become user-facing copy. Plain sentences that
// say what happened; no jokes.
const RATE_LIMIT = "Rate limit exceeded. Please wait for sessions to refresh.";

const MESSAGES: Record<string, string> = {
  invalid_password: "That password didn't work.",
  session_expired: "Your session ended. Enter the password to start again.",
  csrf_required:
    "The request was blocked because it did not look like it came from this app. Reload the page and try again.",
  not_found: "That item no longer exists. It may have been moved or deleted.",
  group_in_use: "Move or delete its documents, tasks and teams first.",
  sandbox_full:
    "The demo has reached its storage limit, so nothing new can be added. Delete something first.",
  length_required: "The upload size could not be determined. Try the file again.",
  file_too_large: "That file is too large to upload.",
  invalid_group: "That group is not valid here. Pick a different one.",
  invalid_link: "That link is not valid. Check the address and try again.",
  invalid_request: "Some of the information entered is not valid. Check it and try again.",
  too_many_attempts: RATE_LIMIT,
  chat_paused: RATE_LIMIT,
  demo_closed: "The Phoebe demo is temporarily offline. Please check back later.",
  unsupported_type: "That file type is not supported.",
  internal_error: "Something went wrong on our side. Try again in a moment.",
};

const GENERIC = "Something went wrong. Try again in a moment.";

/** Copy for an ApiError, or for a bare error code string. */
export function messageFor(err: unknown): string {
  if (typeof err === "string") return MESSAGES[err] ?? GENERIC;
  if (err instanceof ApiError) {
    if (err.code === "unsupported_type" && err.reason) return err.reason;
    return MESSAGES[err.code] ?? GENERIC;
  }
  return GENERIC;
}
