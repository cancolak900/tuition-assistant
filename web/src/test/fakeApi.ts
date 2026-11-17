import { vi } from "vitest";

/** Replaces fetch with a router of canned responses and records every call (path, method, headers, body). */
export interface Call {
  path: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

type Handler = (call: Call) => { status: number; body?: unknown } | Promise<{ status: number; body?: unknown }>;

export function fakeJwt(claims: Record<string, unknown>): string {
  const enc = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${enc({ alg: "HS256", typ: "JWT" })}.${enc(claims)}.signature`;
}

export function installFakeApi(routes: Record<string, Handler>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", async (input: string, init: RequestInit = {}) => {
    const headers = (init.headers ?? {}) as Record<string, string>;
    const body = init.body instanceof FormData ? init.body : init.body ? JSON.parse(init.body as string) : undefined;
    const call: Call = { path: input, method: init.method ?? "GET", headers, body };
    calls.push(call);
    const handler = routes[`${call.method} ${input}`] ?? routes[`${call.method} ${input.split("?")[0]}`];
    const res = handler ? await handler(call) : { status: 404, body: { error: { code: "NOT_FOUND", message: "no route" } } };
    return new Response(res.body === undefined ? null : JSON.stringify(res.body), { status: res.status, headers: { "Content-Type": "application/json" } });
  });
  return calls;
}
