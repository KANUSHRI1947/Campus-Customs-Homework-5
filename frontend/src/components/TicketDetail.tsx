import type { Ticket } from "../types";
import { StatusPill } from "./TicketRack";

interface Props {
  ticket: Ticket | null;
  activeRunTicket: number | null;
  starting: boolean;
  onStart: (id: number) => void;
}

function Field({ label, value }: { label: string; value: string | number | null }) {
  if (value == null || value === "") return null;
  return (
    <div className="field">
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}

export function TicketDetail({ ticket, activeRunTicket, starting, onStart }: Props) {
  if (!ticket)
    return (
      <section className="panel">
        <p className="muted">Pick a ticket from the rack to see it here.</p>
      </section>
    );

  const busyElsewhere = activeRunTicket != null;
  const resolved = ticket.status === "resolved";
  const disabled = busyElsewhere || resolved || starting;
  const why = starting
    ? "Starting…"
    : busyElsewhere
      ? activeRunTicket === ticket.id
        ? "The team is working on this ticket now."
        : `The team is busy with #${activeRunTicket}. One ticket at a time.`
      : resolved
        ? "Already resolved. Use Fresh start to run it again."
        : "Runs the agent team on this ticket only.";

  return (
    <section className="panel ticket-detail">
      <div className="panel-head">
        <h2>
          #{ticket.id} · {ticket.subject}
        </h2>
        <StatusPill status={ticket.status} />
      </div>
      <p className="request-quote">“{ticket.notes?.split(" | ")[0] ?? ticket.subject}”</p>
      <div className="fields">
        <Field label="Requester" value={ticket.requester} />
        <Field label="Type" value={ticket.type} />
        <Field label="SKU" value={ticket.sku} />
        <Field label="Size" value={ticket.size} />
        <Field label="Qty" value={ticket.qty} />
        <Field label="Invoice" value={ticket.invoice_id} />
        <Field label="Lease" value={ticket.lease_id} />
      </div>
      {ticket.notes && ticket.notes.includes(" | ") && (
        <div className="desk-notes">
          <span>Desk notes</span>
          {ticket.notes
            .split(" | ")
            .slice(1)
            .map((n, i) => (
              <p key={i}>{n}</p>
            ))}
        </div>
      )}
      <button className="btn btn-primary btn-wide" disabled={disabled} onClick={() => onStart(ticket.id)}>
        {starting ? "Starting the team…" : `Send #${ticket.id} to the agent team`}
      </button>
      <p className="hint">{why}</p>
    </section>
  );
}
