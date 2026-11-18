import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../App";
import { AuthProvider } from "../auth/AuthContext";
import { saveSession } from "../auth/session";
import { fakeJwt, installFakeApi, type Call } from "../test/fakeApi";

const item = (n: number) => ({ studentNo: `S${1000 + n}`, fullName: `Student ${n}`, tuitionTotal: "2500.00", paid: "0.00", balance: "2500.00", currency: "USD" });

function unpaidRoute(total = 24) {
  return (c: Call) => {
    const q = new URLSearchParams(c.path.split("?")[1]);
    const page = Number(q.get("page"));
    const size = Number(q.get("pageSize"));
    const items = Array.from({ length: total }, (_, i) => item(i + 4)).slice((page - 1) * size, page * size);
    return { status: 200, body: { term: q.get("term"), items, page, pageSize: size, totalItems: total, totalPages: Math.ceil(total / size) } };
  };
}

function renderAdmin() {
  saveSession({
    token: fakeJwt({ sub: "9", role: "admin", exp: Math.floor(Date.now() / 1000) + 3600 }),
    user: { userId: 9, username: "admin", role: "admin", studentNo: null },
    expiresAt: Date.now() + 3_600_000,
  });
  return render(
    <MemoryRouter initialEntries={["/admin"]}>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </MemoryRouter>,
  );
}

const unpaidCalls = (calls: Call[]) => calls.filter((c) => c.path.startsWith("/api/v1/admin/tuition/unpaid"));
const table = () => within(screen.getByRole("region", { name: "Unpaid tuition" }));

beforeEach(() => sessionStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("admin screen", () => {
  it("lists unpaid tuition with paging", async () => {
    const calls = installFakeApi({ "GET /api/v1/admin/tuition/unpaid": unpaidRoute(24) });
    renderAdmin();
    expect(await table().findByText("S1004")).toBeTruthy();
    expect(table().getByText("Showing 1–10 of 24")).toBeTruthy();
    expect(table().getByText("Page 1 of 3")).toBeTruthy();
    expect(table().getAllByText("$2,500.00").length).toBeGreaterThan(0);
    expect((table().getByRole("button", { name: "Previous" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(table().getByRole("button", { name: "Next" }));
    expect(await table().findByText("S1014")).toBeTruthy();
    expect(table().getByText("Showing 11–20 of 24")).toBeTruthy();
    expect(unpaidCalls(calls).at(-1)?.path).toBe("/api/v1/admin/tuition/unpaid?term=2026-FALL&page=2&pageSize=10");
    expect(unpaidCalls(calls).at(-1)?.headers.Authorization).toMatch(/^Bearer /);
  });

  it("shows a compact list instead of the wide table on a phone", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query === "(max-width: 639px)",
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    installFakeApi({ "GET /api/v1/admin/tuition/unpaid": unpaidRoute(24) });
    renderAdmin();
    const list = await table().findByRole("list", { name: "Unpaid tuition" });
    expect(table().queryByRole("table")).toBeNull();
    const first = within(list).getAllByRole("listitem")[0];
    expect(first.textContent).toContain("S1004");
    expect(first.textContent).toContain("Paid $0.00 of $2,500.00");
    expect(table().getByRole("button", { name: "Prev" })).toBeTruthy();
  });

  it("changes the term and goes back to page 1", async () => {
    const calls = installFakeApi({ "GET /api/v1/admin/tuition/unpaid": unpaidRoute(24) });
    renderAdmin();
    await table().findByText("S1004");
    const term = table().getByLabelText("Term");
    fireEvent.change(term, { target: { value: "2027-spring" } });
    fireEvent.keyDown(term, { key: "Enter" });
    await waitFor(() => expect(unpaidCalls(calls).at(-1)?.path).toContain("term=2027-SPRING&page=1"));
  });

  it("does not query with an invalid term", async () => {
    const calls = installFakeApi({ "GET /api/v1/admin/tuition/unpaid": unpaidRoute(0) });
    renderAdmin();
    await table().findByText("No unpaid tuition for 2026-FALL.");
    const term = table().getByLabelText("Term");
    fireEvent.change(term, { target: { value: "fall" } });
    fireEvent.keyDown(term, { key: "Enter" });
    expect(term.getAttribute("aria-invalid")).toBe("true");
    expect(unpaidCalls(calls)).toHaveLength(1);
  });

  it("saves a tuition record, reports CREATED/UPDATED and reloads the list", async () => {
    let created = false;
    const calls = installFakeApi({
      "GET /api/v1/admin/tuition/unpaid": unpaidRoute(3),
      "POST /api/v1/admin/tuition": (c) => {
        const body = c.body as { studentNo: string; amount: string };
        const res = created
          ? { status: 200, body: { status: "UPDATED", studentNo: body.studentNo, term: "2026-FALL", amount: body.amount, currency: "USD", previousAmount: "7500.00" } }
          : { status: 201, body: { status: "CREATED", studentNo: body.studentNo, term: "2026-FALL", amount: body.amount, currency: "USD" } };
        created = true;
        return res;
      },
    });
    renderAdmin();
    const form = within(screen.getByRole("region", { name: "Add or update tuition" }));
    await table().findByText("S1004");
    const fill = (amount: string) => {
      fireEvent.change(form.getByLabelText("Student No"), { target: { value: "s1031" } });
      fireEvent.change(form.getByLabelText("Amount"), { target: { value: amount } });
      fireEvent.click(form.getByRole("button", { name: "Save tuition" }));
    };
    fill("7,500");
    expect(await form.findByText("Created: S1031 · 2026-FALL · $7,500.00")).toBeTruthy();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ studentNo: "S1031", term: "2026-FALL", amount: "7500.00", currency: "USD" });
    await waitFor(() => expect(unpaidCalls(calls).length).toBe(2)); // reloaded after saving
    fill("8000");
    expect(await form.findByText("Updated: S1031 · 2026-FALL · $7,500.00 → $8,000.00")).toBeTruthy();
  });

  it("validates the form before calling the API", async () => {
    const calls = installFakeApi({ "GET /api/v1/admin/tuition/unpaid": unpaidRoute(0) });
    renderAdmin();
    const form = within(screen.getByRole("region", { name: "Add or update tuition" }));
    fireEvent.change(form.getByLabelText("Term"), { target: { value: "fall" } });
    fireEvent.change(form.getByLabelText("Amount"), { target: { value: "-5" } });
    fireEvent.click(form.getByRole("button", { name: "Save tuition" }));
    expect(form.getByText("Letters and digits only, e.g. S1004")).toBeTruthy();
    expect(form.getByText("Use YYYY-FALL or YYYY-SPRING")).toBeTruthy();
    expect(form.getByText("A positive amount with at most 2 decimals")).toBeTruthy();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("shows the API's business errors", async () => {
    installFakeApi({
      "GET /api/v1/admin/tuition/unpaid": unpaidRoute(0),
      "POST /api/v1/admin/tuition": () => ({ status: 404, body: { error: { code: "STUDENT_NOT_FOUND", message: "Student S9999 not found." } } }),
    });
    renderAdmin();
    const form = within(screen.getByRole("region", { name: "Add or update tuition" }));
    fireEvent.change(form.getByLabelText("Student No"), { target: { value: "S9999" } });
    fireEvent.change(form.getByLabelText("Amount"), { target: { value: "100" } });
    fireEvent.click(form.getByRole("button", { name: "Save tuition" }));
    expect(await form.findByText("Student S9999 not found.")).toBeTruthy();
  });

  it("uploads a CSV and shows the summary with failed rows", async () => {
    const calls = installFakeApi({
      "GET /api/v1/admin/tuition/unpaid": unpaidRoute(0),
      "POST /api/v1/admin/tuition/batch": () => ({
        status: 200,
        body: {
          status: "PARTIAL", totalRows: 13, successCount: 6, failureCount: 7, createdCount: 5, updatedCount: 1,
          errors: [{ row: 7, studentNo: "S1006", code: "INVALID_AMOUNT", reason: "amount must be greater than 0" }, { row: 15, studentNo: "S9999", code: "STUDENT_NOT_FOUND", reason: "unknown student S9999" }],
        },
      }),
    });
    renderAdmin();
    const panel = within(screen.getByRole("region", { name: "Batch upload (CSV)" }));
    const file = new File(["studentNo,term,amount,currency\n"], "sample_batch.csv", { type: "text/csv" });
    fireEvent.change(screen.getByTestId("csv-input"), { target: { files: [file] } });
    expect(await panel.findByText("6 succeeded")).toBeTruthy();
    expect(panel.getByText("13 processed")).toBeTruthy();
    expect(panel.getByText("7 failed")).toBeTruthy();
    expect(panel.getByText("5 created · 1 updated")).toBeTruthy();
    expect(panel.getByText("Row 7 · amount must be greater than 0")).toBeTruthy();
    const upload = calls.find((c) => c.path === "/api/v1/admin/tuition/batch");
    expect((upload?.body as FormData).get("file")).toBeInstanceOf(File);
  });

  it("rejects a non-CSV file without uploading it", async () => {
    const calls = installFakeApi({ "GET /api/v1/admin/tuition/unpaid": unpaidRoute(0) });
    renderAdmin();
    const panel = within(screen.getByRole("region", { name: "Batch upload (CSV)" }));
    fireEvent.change(screen.getByTestId("csv-input"), { target: { files: [new File(["x"], "photo.png")] } });
    expect(await panel.findByText(/Choose a \.csv file/)).toBeTruthy();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("shows a file-level error from the API", async () => {
    installFakeApi({
      "GET /api/v1/admin/tuition/unpaid": unpaidRoute(0),
      "POST /api/v1/admin/tuition/batch": () => ({ status: 400, body: { error: { code: "INVALID_CSV_HEADER", message: "The first line must be: studentNo,term,amount,currency" } } }),
    });
    renderAdmin();
    const panel = within(screen.getByRole("region", { name: "Batch upload (CSV)" }));
    fireEvent.change(screen.getByTestId("csv-input"), { target: { files: [new File(["a,b\n"], "bad.csv")] } });
    expect(await panel.findByText("bad.csv: The first line must be: studentNo,term,amount,currency")).toBeTruthy();
  });
});
