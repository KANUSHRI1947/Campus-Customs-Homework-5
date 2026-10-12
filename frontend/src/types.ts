// Shapes returned by the Problem 7 FastAPI backend (backend/main.py).

export type TicketStatus = "open" | "waiting" | "resolved" | string;

export interface Ticket {
  id: number;
  type: string;
  requester: string;
  subject: string;
  sku: string | null;
  size: string | null;
  qty: number | null;
  lease_id: number | null;
  invoice_id: number | null;
  status: TicketStatus;
  notes: string | null;
  created_at: string;
  is_open: boolean;
}

export interface TicketsResponse {
  date_today: string | null;
  count: number;
  tickets: Ticket[];
}

export interface Health {
  ok: boolean;
  database: string;
  date_today: string | null;
  active_run_id: string | null;
}

export type ApprovalKind = "payment" | "discount";

export interface PendingApproval {
  approval_id: string;
  kind: ApprovalKind; // PAYMENT (request_payment) or DISCOUNT DECISION (request_discount_decision)
  run_id: string;
  ticket_id: number | null;
  message: string;
  requested_at: string;
}

export type RunStatus = "running" | "finished" | "stopped" | "failed";

export interface Run {
  run_id: string;
  ticket_id: number;
  status: RunStatus;
  started_at: string;
  finished_at: string | null;
  final_report: string | null;
  usage: Record<string, number> | null;
  delegations: number | null;
  error: string | null;
  pending_approvals: PendingApproval[];
}

export interface RunsResponse {
  active_run_id: string | null;
  runs: Run[];
}

export interface StartRunResponse {
  run_id: string;
  ticket_id: number;
  status: "running";
  reset_first: boolean;
}

/** One line of output/audit_trail.json, plus the backend's derived `summary`. */
export interface AuditEvent {
  seq: number;
  logged_at: string;
  run_id: string;
  agent: string;
  event: string;
  summary: string;
  [key: string]: unknown;
}

export interface EventsResponse {
  count: number;
  last_seq: number | null;
  events: AuditEvent[];
}

export interface ApprovalsResponse {
  pending: PendingApproval[];
}

export interface DecisionResponse {
  approval_id: string;
  kind: ApprovalKind;
  run_id: string;
  decision: "approved" | "rejected";
  approver_name: string;
  note: string;
}

export interface Cash {
  account: string;
  balance: number;
  as_of: string;
  date_today: string | null;
}

export interface ResetResponse {
  reset: boolean;
  reset_id: string;
  matches_original: boolean;
  checking_balance: number;
  tickets: { id: number; status: string }[];
}
