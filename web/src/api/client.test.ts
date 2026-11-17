import { afterEach, describe, expect, it, vi } from "vitest";
import { installFakeApi } from "../test/fakeApi";
import { ApiError, configureClient, request } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
  configureClient(null);
});

describe("api client", () => {
  it("sends the token and JSON body under /api/v1", async () => {
    const calls = installFakeApi({ "POST /api/v1/x": () => ({ status: 200, body: { ok: true } }) });
    configureClient("tok");
    expect(await request("/x", { method: "POST", body: { a: 1 } })).toEqual({ ok: true });
    expect(calls[0].headers.Authorization).toBe("Bearer tok");
    expect(calls[0].body).toEqual({ a: 1 });
  });

  it("leaves the token out for public calls", async () => {
    const calls = installFakeApi({ "GET /api/v1/x": () => ({ status: 200, body: {} }) });
    configureClient("tok");
    await request("/x", { auth: false });
    expect(calls[0].headers.Authorization).toBeUndefined();
  });

  it("turns the API error body into an ApiError", async () => {
    installFakeApi({ "GET /api/v1/x": () => ({ status: 409, body: { error: { code: "DUPLICATE", message: "dup", details: { a: 1 } } } }) });
    await expect(request("/x")).rejects.toMatchObject({ status: 409, code: "DUPLICATE", message: "dup", details: { a: 1 } });
  });

  it("understands Kong's own error body", async () => {
    installFakeApi({ "GET /api/v1/x": () => ({ status: 429, body: { message: "API rate limit exceeded" } }) });
    await expect(request("/x")).rejects.toMatchObject({ status: 429, code: "RATE_LIMITED", message: "API rate limit exceeded" });
  });

  it("calls the unauthorized handler on a 401 for a signed-in request", async () => {
    installFakeApi({ "GET /api/v1/x": () => ({ status: 401, body: { message: "Unauthorized" } }) });
    const onUnauthorized = vi.fn();
    configureClient("expired", onUnauthorized);
    await expect(request("/x")).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("reports a network failure clearly", async () => {
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("Failed to fetch");
    });
    await expect(request("/x")).rejects.toMatchObject({ status: 0, code: "NETWORK_ERROR" });
  });
});
