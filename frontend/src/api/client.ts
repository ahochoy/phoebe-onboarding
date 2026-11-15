// Typed fetch wrapper. Every non-GET request carries the CSRF header; the API's
// `detail` field is a snake_case code that only lib/messages.ts turns into copy.

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly reason?: string;

  constructor(status: number, code: string, reason?: string) {
    super(code);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    if (reason !== undefined) this.reason = reason;
  }
}

type Method = "POST" | "PUT" | "PATCH" | "DELETE";

const sessionListeners = new Set<() => void>();

/** Subscribe to 401 `session_expired` responses. Returns an unsubscribe function. */
export function onSessionExpired(listener: () => void): () => void {
  sessionListeners.add(listener);
  return () => {
    sessionListeners.delete(listener);
  };
}

async function toApiError(res: Response): Promise<ApiError> {
  let code = "internal_error";
  let reason: string | undefined;
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object") {
      const { detail, reason: r } = body as { detail?: unknown; reason?: unknown };
      if (typeof detail === "string" && detail) code = detail;
      else if (Array.isArray(detail)) code = "invalid_request";
      if (typeof r === "string") reason = r;
    }
  } catch {
    // Not JSON (proxy error page, empty body): keep the generic code.
  }
  return new ApiError(res.status, code, reason);
}

/**
 * Turns a non-OK response into an ApiError, notifying session listeners on a
 * 401 `session_expired`. For callers that need raw `fetch` (the chat stream).
 */
export async function responseError(res: Response): Promise<ApiError> {
  const err = await toApiError(res);
  if (res.status === 401 && err.code === "session_expired") {
    for (const listener of [...sessionListeners]) listener();
  }
  return err;
}

async function request<T>(
  method: "GET" | Method,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (method !== "GET") headers.set("X-Phoebe-Csrf", "1");
  const res = await fetch(path, { ...init, method, headers, credentials: "same-origin" });
  if (!res.ok) throw await responseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>("GET", path);
}

export function apiSend<T = void>(method: Method, path: string, body?: unknown): Promise<T> {
  if (body === undefined) return request<T>(method, path);
  return request<T>(method, path, {
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
  });
}

/** Multipart upload. The browser sets the Content-Type boundary itself. */
export function apiUpload<T>(path: string, form: FormData): Promise<T> {
  return request<T>("POST", path, { body: form });
}
