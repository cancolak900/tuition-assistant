/**
 * Small fetch wrapper for the gateway. Every call goes to the same origin under /api/v1 (Kong in production,
 * the Vite proxy to Kong in development). Errors come back as ApiError with the service's error code.
 */

export const API_BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let currentToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

/** Set by the auth layer: the token sent with every request, and what to do when it is rejected. */
export function configureClient(token: string | null, unauthorized?: () => void): void {
  currentToken = token;
  if (unauthorized) onUnauthorized = unauthorized;
}

async function parseError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    // not JSON (e.g. an HTML error page from a proxy)
  }
  if (body && typeof body === "object") {
    const err = (body as { error?: { code?: string; message?: string; details?: unknown } }).error;
    if (err?.code) return new ApiError(res.status, err.code, err.message ?? err.code, err.details ?? null);
    const kongMessage = (body as { message?: string }).message; // Kong plugins answer {"message": "..."}
    if (kongMessage) return new ApiError(res.status, res.status === 429 ? "RATE_LIMITED" : `HTTP_${res.status}`, kongMessage);
  }
  return new ApiError(res.status, `HTTP_${res.status}`, res.statusText || "Request failed");
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  auth?: boolean; // default true
  signal?: AbortSignal;
}

export async function request<T>(path: string, { method = "GET", body, auth = true, signal }: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  if (auth && currentToken) headers.Authorization = `Bearer ${currentToken}`;

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { method, headers, body: payload, signal });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "NETWORK_ERROR", "The server cannot be reached. Check your connection and try again.");
  }
  if (!res.ok) {
    const error = await parseError(res);
    if (res.status === 401 && auth && currentToken) onUnauthorized?.();
    throw error;
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
