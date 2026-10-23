// Calls the Flask API through this site's own /api path (see next.config.ts),
// so the login cookie is first-party and is sent automatically. JavaScript
// never sees the cookie: it is HttpOnly.

export type School = {
  id: string;
  name: string;
  code: string;
  county_code: number;
  county_name: string;
  is_active: boolean;
};

export type User = {
  id: string;
  email: string;
  full_name: string;
  is_platform_admin: boolean;
};

export type Me = {
  user: User;
  memberships: { role: string; school: School }[];
  active_school: School | null;
  permissions: string[];
};

export type ApiErrorBody = {
  code: string;
  message: string;
  request_id?: string;
  details?: { field: string; message: string }[];
};

export type ApiResult<T> =
  | { ok: true; status: number; data: T }
  | { ok: false; status: number; error: ApiErrorBody; retryAfter: number | null };

const NETWORK_ERROR: ApiErrorBody = {
  code: "network_error",
  message: "Could not reach the server. Check your connection and try again.",
};

const UNEXPECTED_ERROR: ApiErrorBody = {
  code: "unexpected",
  message: "Something went wrong. Please try again.",
};

export async function api<T>(
  path: string,
  options: { method?: "GET" | "POST" | "PATCH"; body?: unknown } = {},
): Promise<ApiResult<T>> {
  const hasBody = options.body !== undefined;
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method: options.method ?? "GET",
      headers: hasBody ? { "Content-Type": "application/json" } : undefined,
      body: hasBody ? JSON.stringify(options.body) : undefined,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    return { ok: false, status: 0, error: NETWORK_ERROR, retryAfter: null };
  }

  let body: unknown = null;
  if (response.status !== 204) {
    try {
      body = await response.json();
    } catch {
      body = null;
    }
  }
  if (response.ok) {
    return { ok: true, status: response.status, data: body as T };
  }
  const error = (body as { error?: ApiErrorBody } | null)?.error ?? UNEXPECTED_ERROR;
  const retryAfter = Number(response.headers.get("Retry-After"));
  return {
    ok: false,
    status: response.status,
    error,
    retryAfter: Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null,
  };
}

// For messages the person may need to quote to support.
export function withReference(error: ApiErrorBody): string {
  return error.request_id ? `${error.message} (Reference: ${error.request_id})` : error.message;
}
