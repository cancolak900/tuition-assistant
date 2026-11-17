import { request } from "./client";

export type Role = "student" | "bank" | "admin";

export interface TokenResponse {
  accessToken: string;
  tokenType: string;
  expiresIn: number;
  role: Role;
  studentNo: string | null;
}

export interface Me {
  userId: number;
  username: string;
  role: Role;
  studentNo: string | null;
}

export function login(username: string, password: string): Promise<TokenResponse> {
  return request<TokenResponse>("/auth/login", { method: "POST", body: { username, password }, auth: false });
}

/** Goes through Kong's JWT check, so it also proves the token is accepted at the gateway. */
export function fetchMe(): Promise<Me> {
  return request<Me>("/auth/me");
}
