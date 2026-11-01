"use client";

/**
 * API client — all calls target the LocalDeploy API directly with credentials
 * (session cookie). CSRF double-submit token is attached to mutating requests.
 */
export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

let csrfToken: string | null = null;

function readCsrfCookie(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|;\s*)ld_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

export async function ensureCsrf(): Promise<string> {
  csrfToken = readCsrfCookie();
  if (csrfToken) return csrfToken;
  const res = await fetch(`${API_URL}/api/auth/csrf`, {
    credentials: "include",
  });
  const data = await res.json();
  csrfToken = data.csrf_token ?? readCsrfCookie();
  return csrfToken ?? "";
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

type Options = {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  formData?: FormData;
};

export async function api<T = unknown>(
  path: string,
  options: Options = {},
): Promise<T> {
  const { method = "GET", body, formData } = options;
  const headers: Record<string, string> = {};
  if (method !== "GET") {
    headers["X-CSRF-Token"] = await ensureCsrf();
  }
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers,
    credentials: "include",
    body: formData ?? (body !== undefined ? JSON.stringify(body) : undefined),
  });

  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/api/auth/login") && !path.startsWith("/api/auth/me")) {
    window.location.href = "/login";
    throw new ApiError(401, "Session expired");
  }
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : data.detail ?? data;
      if (Array.isArray(detail)) {
        detail = detail.map((d) => (d as { msg?: string }).msg).join("; ");
      }
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Build a WebSocket URL for the given API path (session cookie authenticates). */
export function wsUrl(path: string): string {
  const base = API_URL.replace(/^http/, "ws");
  return `${base}${path}`;
}
