// Everything here is DERIVED from real audit events (output/audit_trail.json via
// GET /api/events). Nothing is invented: if an event isn't there, it isn't shown.
import type { AuditEvent, PendingApproval } from "../types";
import { AGENTS, type AgentKey } from "./agents";
import { money } from "./format";

const str = (v: unknown) => (typeof v === "string" ? v : v == null ? "" : String(v));
const obj = (v: unknown) => (v && typeof v === "object" ? (v as Record<string, unknown>) : {});
const cash = (v: unknown) => (typeof v === "number" ? money(v) : str(v));

/** What a tool result "meant", in a few words, from the fields the MCP tools return. */
export function toolOutcome(e: AuditEvent): string {
  const r = obj(e.result);
  const tool = str(e.tool);
  if (tool === "request_discount_decision" && r.result === "approved")
    return `human APPROVED ${cash(r.final_unit_price)}/unit — no cash moved, catalogue unchanged`;
  if (tool === "request_discount_decision" && r.result === "rejected")
    return `human REJECTED ${cash(r.recommended_unit_price)}/unit — list ${cash(r.list_price)} stands`;
  if (typeof r.result === "string") {
    const extra = r.reason ? ` (${str(r.reason)})` : "";
    if (tool === "request_payment" && r.result === "paid")
      return `paid ${cash(r.amount)} — checking ${cash(r.checking_balance_before)} → ${cash(r.checking_balance_after)}`;
    if (tool === "request_vendor_restock" && r.result === "draft_saved")
      return `draft saved, arrives ${str(r.expected_arrival)} (not sent)`;
    if (tool === "draft_customer_message" && r.result === "draft_saved") return "draft saved (not sent)";
    return r.result + extra;
  }
  if (tool === "update_ticket_status") return `${str(r.previous_status)} → ${str(r.new_status)}`;
  if (tool === "list_open_tickets") return `${str(r.open_ticket_count)} open ticket(s)`;
  if (tool === "get_checking_balance") return `checking ${cash(r.balance)}`;
  if (tool === "get_stock_and_margin_for_bulk_order") {
    const s = obj(r.stock);
    return `${str(s.on_hand_qty)} on hand, short ${str(s.shortfall_qty)}`;
  }
  if (tool === "get_invoice_and_vendor_block_status") {
    const inv = obj(r.invoice);
    return `invoice ${str(inv.id)} (${cash(inv.amount)}) ${str(inv.status)}, vendor ${r.vendor_blocked_from_shipping ? "blocked" : "not blocked"}`;
  }
  if (tool === "get_lease_rent_due_and_cash_coverage") {
    const l = obj(r.lease);
    return `rent ${cash(l.monthly_rent)} due ${str(l.next_due)}, ${r.cash_covers_rent ? "cash covers it" : "cash short"}`;
  }
  return "done";
}

export type SeatState = "idle" | "working" | "done";

export interface AgentSummary {
  key: AgentKey;
  state: SeatState;
  assignments: string[];          // tasks the Boss sent (or the Boss's own task)
  tools: { tool: string; count: number; outcomes: string[] }[];
  lastWords: string | null;        // last answer to the Boss (or Boss final report)
  lastAction: string | null;       // most recent thing it did, for the live seat
  blocked: string[];               // tool calls refused for scope/permission
}

/** Build one summary per agent from a run's events. */
export function summarizeAgents(events: AuditEvent[], runFinished: boolean): AgentSummary[] {
  const by: Record<string, AgentSummary> = {};
  for (const a of AGENTS)
    by[a.key] = { key: a.key, state: "idle", assignments: [], tools: [], lastWords: null, lastAction: null, blocked: [] };

  for (const e of events) {
    const s = by[e.agent];
    if (e.event === "delegate") {
      const target = by[str(e.to)];
      if (target) {
        target.assignments.push(str(e.task));
        target.state = "working";
        target.lastAction = "Got a task from the Boss";
      }
      by.boss.lastAction = `Asked ${str(e.to).replace("_", " ")} for help`;
      by.boss.state = "working";
      continue;
    }
    if (!s) continue;
    if (e.event === "task") {
      s.assignments.push(str(e.task));
      s.state = "working";
    } else if (e.event === "tool_call") {
      s.state = "working";
      s.lastAction = `Calling ${str(e.tool)}`;
    } else if (e.event === "tool_result") {
      const tool = str(e.tool);
      let t = s.tools.find((x) => x.tool === tool);
      if (!t) s.tools.push((t = { tool, count: 0, outcomes: [] }));
      t.count += 1;
      t.outcomes.push(toolOutcome(e));
      s.lastAction = `${tool}: ${toolOutcome(e)}`;
    } else if (e.event === "tool_blocked" || e.event === "tool_error") {
      s.blocked.push(`${str(e.tool)}: ${str(e.reason ?? e.error)}`);
      s.lastAction = `${str(e.tool)} was ${e.event === "tool_blocked" ? "blocked" : "an error"}`;
    } else if (e.event === "answer_to_boss") {
      s.lastWords = str(e.answer);
      s.state = "done";
      s.lastAction = "Reported back to the Boss";
    } else if (e.event === "final_report") {
      s.lastWords = str(e.report);
      s.state = "done";
      s.lastAction = "Wrote the final report";
    }
  }
  if (runFinished) for (const s of Object.values(by)) if (s.state === "working") s.state = "done";
  return AGENTS.map((a) => by[a.key]);
}

export interface ApprovalDetails {
  amount: number | null; // payment amount, or recommended price per unit for a discount
  kind: string | null;   // "invoice" | "rent"
  refId: string | null;
  reason: string;        // what the payment is for
  balanceNow: number | null;
  balanceAfter: number | null;
}

const num = (s: string | undefined) => (s ? Number(s.replace(/,/g, "")) : null);

export interface DiscountDetails {
  unitPrice: number | null;
  listPrice: number | null;
  unitCost: number | null;
  qty: string | null;
  item: string | null;
  totalAtPrice: number | null;
  totalAtList: number | null;
}

/** Numbers for a DISCOUNT DECISION card, read from the prompt the MCP tool wrote. */
export function discountDetails(p: PendingApproval, events: AuditEvent[]): DiscountDetails {
  const call = [...events].reverse().find((e) => e.event === "tool_call" && e.tool === "request_discount_decision");
  const args = obj(call?.args);
  const m = p.message;
  const pick = (re: RegExp) => num(m.match(re)?.[1]);
  const item = m.match(/(\d+) x (\S+) size (\S+?)\./);
  return {
    unitPrice: typeof args.unit_price === "number" ? args.unit_price : pick(/recommends \$([\d,]+\.\d{2})/),
    listPrice: pick(/list \$([\d,]+\.\d{2})/),
    unitCost: pick(/cost \$([\d,]+\.\d{2})/),
    qty: item?.[1] ?? null,
    item: item ? `${item[2]} size ${item[3]}` : null,
    totalAtPrice: pick(/Order total \$([\d,]+\.\d{2})/),
    totalAtList: pick(/vs \$([\d,]+\.\d{2}) at list/),
  };
}

/** Amount and reason for a PAYMENT card: the request_payment tool call that is
 *  waiting (from the audit trail) plus the text the MCP server put in the prompt. */
export function approvalDetails(p: PendingApproval, events: AuditEvent[]): ApprovalDetails {
  // The most recent request_payment call in this run is the one waiting on the human.
  const call = [...events].reverse().find((e) => e.event === "tool_call" && e.tool === "request_payment");
  const args = obj(call?.args);
  const m = p.message;
  const forMatch = m.match(/ for (.+?)\. Checking now/);
  const now = m.match(/Checking now \$([\d,]+\.\d{2})/);
  const after = m.match(/after payment \$([\d,]+\.\d{2})/);
  const amountText = m.match(/pay \$([\d,]+\.\d{2})/);
  return {
    amount: typeof args.amount === "number" ? args.amount : num(amountText?.[1]),
    kind: args.kind != null ? str(args.kind) : null,
    refId: args.ref_id != null ? str(args.ref_id) : null,
    reason: forMatch?.[1] ?? m,
    balanceNow: num(now?.[1]),
    balanceAfter: num(after?.[1]),
  };
}

/** Status the Boss set on the ticket during this run (from update_ticket_status), if any. */
export function statusSetInRun(events: AuditEvent[]): string | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.event === "tool_result" && e.tool === "update_ticket_status") return str(obj(e.result).new_status) || null;
  }
  return null;
}
