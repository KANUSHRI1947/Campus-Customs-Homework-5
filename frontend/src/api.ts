// Thin client for the Problem 7 backend. Every call goes to a real FastAPI route
// in backend/main.py; nothing here invents or caches data.
import type {
  ApprovalsResponse, Cash, DecisionResponse, EventsResponse, Health, ResetResponse,
  RunsResponse, Run, StartRunResponse, Ticket, TicketsResponse,
} from "./types";

// The Problem 7 FastAPI backend. The browser calls it directly; the backend's CORS
// setting allows exactly this dashboard's origin (http://localhost:5173).
export const API_BASE = ((import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

interface ErrorBody {
  error?: { message?: string; details?: { loc?: (string | number)[]; msg?: string }[] };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    // Only POSTs send a JSON body, so only they need the Content-Type header.
    const headers: Record<string, string> = init?.body !== undefined ? { "Content-Type": "application/json" } : {};
    res = await fetch(API_BASE + path, { ...init, headers });
  } catch {
    throw new ApiError(
      `Can't reach the backend at ${API_BASE}. Start it from the backend/ folder with: uvicorn main:app --reload --port 8000`,
      0,
    );
  }
  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }
  if (!res.ok) {
    const err = (body as ErrorBody | null)?.error;
    let message = err?.message ?? `The backend returned ${res.status} ${res.statusText}.`;
    if (err?.details?.length) {
      message += " " + err.details.map((d) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`).join("; ");
    }
    throw new ApiError(message, res.status);
  }
  return body as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  health: () => request<Health>("/api/health"),
  tickets: () => request<TicketsResponse>("/api/tickets"),
  ticket: (id: number) => request<{ date_today: string | null; ticket: Ticket }>(`/api/tickets/${id}`),
  startRun: (id: number) => post<StartRunResponse>(`/api/tickets/${id}/run`, { reset_first: false }),
  runs: () => request<RunsResponse>("/api/runs"),
  run: (runId: string) => request<{ run: Run }>(`/api/runs/${encodeURIComponent(runId)}`),
  events: (runId: string, afterSeq?: number | null) => {
    const q = new URLSearchParams({ run_id: runId, limit: "500" });
    if (afterSeq != null) q.set("after_seq", String(afterSeq));
    return request<EventsResponse>(`/api/events?${q}`);
  },
  approvals: () => request<ApprovalsResponse>("/api/approvals"),
  decide: (approvalId: string, decision: "approve" | "reject", approverName: string) =>
    post<DecisionResponse>(`/api/approvals/${encodeURIComponent(approvalId)}`, {
      decision,
      approver_name: approverName,
    }),
  cash: () => request<Cash>("/api/cash"),
  reset: () => post<ResetResponse>("/api/reset", { confirm: "RESET" }),
};

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError || e instanceof Error) return e.message;
  return String(e);
}
