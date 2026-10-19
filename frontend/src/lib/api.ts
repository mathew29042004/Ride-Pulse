/**
 * Thin fetch wrapper for the Ride Pulse REST API.
 *
 * - Sends the JWT access token and refreshes it once on a 401 (concurrent requests share a
 *   single refresh call).
 * - Turns the API's error envelope into an ApiError with a human message.
 */

const ACCESS_KEY = "rp.access";
const REFRESH_KEY = "rp.refresh";
export const API_BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  code: string;
  field: string | null;
  details: unknown;

  constructor(status: number, code: string, message: string, field: string | null, details: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.field = field;
    this.details = details;
  }
}

/**
 * Tokens live per browser tab (sessionStorage), so a rider and a driver can be signed in side by
 * side in two tabs. localStorage remembers the last login, so a new tab or a restarted browser
 * starts signed in as that user.
 */
function read(key: string): string | null {
  try {
    return sessionStorage.getItem(key) ?? localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string) {
  try {
    sessionStorage.setItem(key, value);
    localStorage.setItem(key, value);
  } catch {
    /* storage may be unavailable (private mode); the session just won't persist */
  }
}

export const tokens = {
  get access() {
    return read(ACCESS_KEY);
  },
  get refresh() {
    return read(REFRESH_KEY);
  },
  set(access: string, refresh?: string) {
    write(ACCESS_KEY, access);
    if (refresh) write(REFRESH_KEY, refresh);
  },
  /** Pin this tab to the identity it started with, even if another tab signs in as someone else. */
  pinToTab() {
    try {
      for (const key of [ACCESS_KEY, REFRESH_KEY]) {
        const value = localStorage.getItem(key);
        if (value && !sessionStorage.getItem(key)) sessionStorage.setItem(key, value);
      }
    } catch {
      /* ignore */
    }
  },
  clear() {
    try {
      for (const key of [ACCESS_KEY, REFRESH_KEY]) {
        if (localStorage.getItem(key) === sessionStorage.getItem(key)) localStorage.removeItem(key);
        sessionStorage.removeItem(key);
      }
    } catch {
      /* ignore */
    }
  },
};

let refreshing: Promise<boolean> | null = null;

async function refreshAccess(): Promise<boolean> {
  const refresh = tokens.refresh;
  if (!refresh) return false;
  refreshing ??= fetch(`${API_BASE}/auth/token/refresh/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh }),
  })
    .then(async (res) => {
      if (!res.ok) {
        tokens.clear();
        return false;
      }
      const data = await res.json();
      tokens.set(data.access, data.refresh);
      return true;
    })
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

function firstMessage(details: unknown): { message: string; field: string | null } | null {
  if (!details || typeof details !== "object") return null;
  for (const [field, value] of Object.entries(details as Record<string, unknown>)) {
    if (Array.isArray(value) && value.length) {
      const inner = typeof value[0] === "string" ? value[0] : firstMessage(value[0])?.message;
      if (inner) return { message: field === "non_field_errors" ? inner : `${field.replace(/_/g, " ")}: ${inner}`, field };
    } else if (typeof value === "object") {
      const nested = firstMessage(value);
      if (nested) return { message: nested.message, field };
    }
  }
  return null;
}

async function toError(res: Response): Promise<ApiError> {
  let body: { error?: { code?: string; message?: string; field?: string | null; details?: unknown }; detail?: string } = {};
  try {
    body = await res.json();
  } catch {
    /* non-JSON error page */
  }
  const error = body.error ?? {};
  const detailed = error.code === "validation_error" ? firstMessage(error.details) : null;
  return new ApiError(
    res.status,
    error.code ?? "error",
    detailed?.message ?? error.message ?? body.detail ?? `Request failed (${res.status})`,
    detailed?.field ?? error.field ?? null,
    error.details,
  );
}

type Options = Omit<RequestInit, "body"> & { body?: unknown; idempotencyKey?: string; raw?: boolean };

export async function request<T>(path: string, options: Options = {}, retry = true): Promise<T> {
  const { body, idempotencyKey, raw, headers, ...rest } = options;
  const isForm = body instanceof FormData;
  const res = await fetch(path.startsWith("/") ? path : `${API_BASE}/${path}`, {
    ...rest,
    headers: {
      Accept: "application/json",
      ...(body !== undefined && !isForm ? { "Content-Type": "application/json" } : {}),
      ...(tokens.access ? { Authorization: `Bearer ${tokens.access}` } : {}),
      ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
      ...headers,
    },
    body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
  });
  if (res.status === 401 && retry && tokens.refresh && (await refreshAccess())) {
    return request<T>(path, options, false);
  }
  if (!res.ok) throw await toError(res);
  if (raw) return res as unknown as T;
  if (res.status === 204 || res.status === 205) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown, opts: Options = {}) =>
    request<T>(path, { ...opts, method: "POST", body: body ?? {} }),
  patch: <T>(path: string, body: unknown) => request<T>(path, { method: "PATCH", body }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

/** Download an authenticated file (e.g. a PDF receipt) and open it in a new tab. */
export async function openFile(path: string) {
  const res = await request<Response>(path, { raw: true });
  const blob = await res.blob();
  window.open(URL.createObjectURL(blob), "_blank");
}

/** An authenticated file as an object URL (for showing a private image inline). */
export async function fileUrl(path: string): Promise<string> {
  const res = await request<Response>(path, { raw: true });
  return URL.createObjectURL(await res.blob());
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
