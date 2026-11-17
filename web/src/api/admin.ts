import { request } from "./client";

/** Admin API (through Kong at /api/v1/admin, JWT with role admin). Shapes mirror services/tuition-api/app/schemas.py. */

export interface AddTuitionRequest {
  studentNo: string;
  term: string;
  amount: string;
  currency: string;
}

export interface AddTuitionResponse {
  status: "CREATED" | "UPDATED";
  studentNo: string;
  term: string;
  amount: string;
  currency: string;
  previousAmount?: string;
}

export interface BatchRowError {
  row: number;
  studentNo: string | null;
  code: string;
  reason: string;
}

export interface BatchResponse {
  status: "COMPLETED" | "PARTIAL" | "FAILED";
  totalRows: number;
  successCount: number;
  failureCount: number;
  createdCount: number;
  updatedCount: number;
  errors: BatchRowError[];
}

export interface UnpaidItem {
  studentNo: string;
  fullName: string;
  tuitionTotal: string;
  paid: string;
  balance: string;
  currency: string;
}

export interface UnpaidPage {
  term: string;
  items: UnpaidItem[];
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
}

export const TERM_PATTERN = /^\d{4}-(FALL|SPRING)$/;
export const STUDENT_NO_PATTERN = /^[A-Za-z0-9]{1,16}$/;
export const MAX_CSV_BYTES = 1_000_000; // same limit as the API (1 MB)

export function addTuition(body: AddTuitionRequest): Promise<AddTuitionResponse> {
  return request<AddTuitionResponse>("/admin/tuition", { method: "POST", body });
}

export function uploadBatch(file: File): Promise<BatchResponse> {
  const form = new FormData();
  form.append("file", file);
  return request<BatchResponse>("/admin/tuition/batch", { method: "POST", body: form });
}

export function listUnpaid(term: string, page: number, pageSize = 10, signal?: AbortSignal): Promise<UnpaidPage> {
  const qs = new URLSearchParams({ term, page: String(page), pageSize: String(pageSize) });
  return request<UnpaidPage>(`/admin/tuition/unpaid?${qs}`, { signal });
}
