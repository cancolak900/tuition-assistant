import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../App";
import { AuthProvider } from "../auth/AuthContext";
import { loadSession } from "../auth/session";
import { fakeJwt, installFakeApi } from "../test/fakeApi";

const exp = () => Math.floor(Date.now() / 1000) + 3600;

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </MemoryRouter>,
  );
}

function signIn(username: string, password: string) {
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: username } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

function loginRoutes(role: "student" | "admin" | "bank", studentNo: string | null) {
  const token = fakeJwt({ sub: "1", role, studentNo, exp: exp() });
  return installFakeApi({
    "POST /api/v1/auth/login": (c) =>
      (c.body as { password: string }).password === "right"
        ? { status: 200, body: { accessToken: token, tokenType: "bearer", expiresIn: 3600, role, studentNo } }
        : { status: 401, body: { error: { code: "INVALID_CREDENTIALS", message: "Invalid username or password." } } },
    "GET /api/v1/auth/me": (c) =>
      c.headers.Authorization === `Bearer ${token}`
        ? { status: 200, body: { userId: 1, username: studentNo?.toLowerCase() ?? role, role, studentNo } }
        : { status: 401, body: { message: "Unauthorized" } },
  });
}

beforeEach(() => sessionStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("login screen", () => {
  it("signs a student in, checks the token with /auth/me and opens the chat", async () => {
    const calls = loginRoutes("student", "S1001");
    renderAt("/login");
    signIn("s1001", "right");
    expect(await screen.findByRole("heading", { name: "Assistant" })).toBeTruthy();
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual(["POST /api/v1/auth/login", "GET /api/v1/auth/me"]);
    expect(loadSession()?.user.studentNo).toBe("S1001"); // kept in sessionStorage for reloads
  });

  it("sends an admin to the admin screen", async () => {
    loginRoutes("admin", null);
    renderAt("/login");
    signIn("admin", "right");
    expect(await screen.findByRole("heading", { name: "Tuition administration" })).toBeTruthy();
  });

  it("shows the Figma error state for wrong credentials", async () => {
    loginRoutes("student", "S1001");
    renderAt("/login");
    signIn("s1001", "wrong");
    expect(await screen.findByText("Invalid username or password")).toBeTruthy();
    expect(screen.getByLabelText("Password").getAttribute("aria-invalid")).toBe("true");
    expect(loadSession()).toBeNull();
  });

  it("explains the gateway's sign-in rate limit", async () => {
    installFakeApi({ "POST /api/v1/auth/login": () => ({ status: 429, body: { message: "API rate limit exceeded" } }) });
    renderAt("/login");
    signIn("s1001", "x");
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Too many sign-in attempts. Wait a minute and try again.");
  });

  it("asks for both fields before calling the API", async () => {
    const calls = installFakeApi({});
    renderAt("/login");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter your username and password")).toBeTruthy();
    expect(calls).toHaveLength(0);
  });

  it("fills the username from the demo accounts box", () => {
    installFakeApi({});
    renderAt("/login");
    fireEvent.click(screen.getByRole("button", { name: "s1002" }));
    expect((screen.getByLabelText("Username") as HTMLInputElement).value).toBe("s1002");
  });

  it("protects screens and returns to them after signing in", async () => {
    loginRoutes("admin", null);
    renderAt("/admin");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
    signIn("admin", "right");
    expect(await screen.findByRole("heading", { name: "Tuition administration" })).toBeTruthy();
  });

  it("keeps a student out of the admin screen", async () => {
    loginRoutes("student", "S1001");
    renderAt("/login");
    signIn("s1001", "right");
    await screen.findByRole("heading", { name: "Assistant" });
    cleanup();
    renderAt("/admin");
    expect(await screen.findByRole("heading", { name: "Assistant" })).toBeTruthy();
  });

  it("signs out from the account menu and forgets the token", async () => {
    loginRoutes("student", "S1001");
    renderAt("/login");
    signIn("s1001", "right");
    fireEvent.click(await screen.findByRole("button", { name: "Account menu" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy());
    expect(loadSession()).toBeNull();
  });

  it("drops an expired stored session", () => {
    sessionStorage.setItem("tuition-assistant.session", JSON.stringify({ token: "t", user: { role: "student" }, expiresAt: Date.now() - 1 }));
    expect(loadSession()).toBeNull();
  });
});
