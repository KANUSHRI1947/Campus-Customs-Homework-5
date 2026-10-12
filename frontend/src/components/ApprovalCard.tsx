import { useState, type ChangeEvent } from "react";
import type { AuditEvent, PendingApproval } from "../types";
import { approvalDetails, discountDetails } from "../lib/summary";
import { money } from "../lib/format";

interface Props {
  approval: PendingApproval;
  events: AuditEvent[];
  approverName: string;
  onApproverName: (name: string) => void;
  onDecide: (approvalId: string, decision: "approve" | "reject") => Promise<void>;
}

/** Shown only when the backend reports something waiting for a human (GET /api/approvals).
 *  `kind` says which: a PAYMENT (cash leaves checking) or a DISCOUNT DECISION (a price for
 *  one ticket; no cash moves, catalogue unchanged). Nothing is approved unless "Approve" is clicked. */
export function ApprovalCard({ approval, events, approverName, onApproverName, onDecide }: Props) {
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const isDiscount = approval.kind === "discount";
  const d = approvalDetails(approval, events);
  const dd = discountDetails(approval, events);
  const nameOk = approverName.trim().length > 0;

  const decide = async (decision: "approve" | "reject") => {
    setBusy(decision);
    try {
      await onDecide(approval.approval_id, decision);
    } finally {
      setBusy(null);
    }
  };

  return (
    <section
      className={`approval ${isDiscount ? "approval-discount" : "approval-payment"}`}
      role="alertdialog"
      aria-labelledby="approval-title"
    >
      <div className="approval-stamp">Needs you</div>
      <div className={`approval-kind ${isDiscount ? "kind-discount" : "kind-payment"}`}>
        {isDiscount ? "Discount decision" : "Payment"}
      </div>
      <h3 id="approval-title">{isDiscount ? "Approve a DISCOUNT price?" : "Approve a PAYMENT?"}</h3>
      <p className="approval-sub">
        {isDiscount
          ? "The Boss recommends a price. Only you decide it. No cash moves and the catalogue price doesn't change"
          : "Accounting asked to pay. Cash leaves checking only if you approve"}
        {approval.ticket_id != null && <> · ticket #{approval.ticket_id}</>}.
      </p>
      {isDiscount ? (
        <>
          <div className="approval-amount">
            {dd.unitPrice != null ? money(dd.unitPrice) : "Price in message below"}
            <small> per unit</small>
          </div>
          {dd.item && (
            <div className="approval-for">
              <span>For</span> {dd.qty} × {dd.item}
            </div>
          )}
          <div className="approval-balance">
            <div>
              <span>List price</span>
              <b>{dd.listPrice != null ? money(dd.listPrice) : "—"}</b>
            </div>
            <div>
              <span>Unit cost</span>
              <b>{dd.unitCost != null ? money(dd.unitCost) : "—"}</b>
            </div>
            <div>
              <span>Order total</span>
              <b>
                {dd.totalAtPrice != null ? money(dd.totalAtPrice) : "—"}
                {dd.totalAtList != null && <small> vs {money(dd.totalAtList)}</small>}
              </b>
            </div>
          </div>
          <p className="approval-note">
            Reject keeps the list price. Either way your decision is recorded on the ticket and is final.
          </p>
        </>
      ) : (
        <>
      <div className="approval-amount">{d.amount != null ? money(d.amount) : "Amount in message below"}</div>
      <div className="approval-for">
        <span>For</span> {d.reason}
      </div>
      {(d.kind || d.refId) && (
        <div className="approval-ref">
          {d.kind} {d.refId && <>#{d.refId}</>}
        </div>
      )}
      {d.balanceNow != null && d.balanceAfter != null && (
        <div className="approval-balance">
          <div>
            <span>Checking now</span>
            <b>{money(d.balanceNow)}</b>
          </div>
          <div className="arrow">→</div>
          <div>
            <span>After payment</span>
            <b>{money(d.balanceAfter)}</b>
          </div>
        </div>
      )}
        </>
      )}
      <details className="approval-raw">
        <summary>Exact request from the MCP server</summary>
        <p>{approval.message}</p>
      </details>
      <label className="approver">
        Your name (saved as the approver)
        <input
          value={approverName}
          onChange={(e: ChangeEvent<HTMLInputElement>) => onApproverName(e.target.value)}
          placeholder="e.g. Kanushri"
          maxLength={100}
        />
      </label>
      <div className="approval-actions">
        <button className="btn btn-reject" disabled={!!busy || !nameOk} onClick={() => decide("reject")}>
          {busy === "reject" ? "Rejecting…" : isDiscount ? "Reject price" : "Reject payment"}
        </button>
        <button className="btn btn-approve" disabled={!!busy || !nameOk} onClick={() => decide("approve")}>
          {busy === "approve" ? "Approving…" : isDiscount ? "Approve price" : "Approve payment"}
        </button>
      </div>
      {!nameOk && <p className="hint">Enter your name to enable the buttons.</p>}
    </section>
  );
}
