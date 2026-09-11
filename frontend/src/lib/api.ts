import type { ApiErrorBody } from "../types";

const baseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";
const apiPrefix = baseUrl ? "" : "/api";

export class ApiError extends Error {
  status: number;
  requestId?: string;
  code?: string;

  constructor(message: string, status: number, body?: ApiErrorBody) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.requestId = body?.request_id;
    this.code = body?.error?.code;
  }
}

function getToken(): string | null {
  return localStorage.getItem("institutional_access_token");
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${baseUrl}${apiPrefix}${path}`, { ...init, headers });
  const text = await response.text();
  const contentType = response.headers.get("content-type") ?? "";
  const body = text && contentType.includes("application/json") ? (JSON.parse(text) as unknown) : text || undefined;

  if (!response.ok) {
    const errorBody = typeof body === "object" && body !== null ? body as ApiErrorBody : undefined;
    if (response.status === 401) window.dispatchEvent(new Event("auth:expired"));
    const message = errorBody?.error?.message ?? errorBody?.detail ?? (typeof body === "string" ? body : "Request failed");
    throw new ApiError(message, response.status, errorBody);
  }
  return body as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) => request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
};

export function farmerPath(path: string, sessionToken: string): string {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}session_token=${encodeURIComponent(sessionToken)}`;
}
