import type { Ticket } from "../types";

const TYPE_LABEL: Record<string, string> = {
  customer_order: "Customer order",
  rent_notice: "Rent notice",
  price_override: "Price request",
};

export function StatusPill({ status }: { status: string }) {
  return <span className={`pill pill-${status}`}>{status}</span>;
}

interface Props {
  tickets: Ticket[];
  selectedId: number | null;
  activeTicket: number | null;
  onSelect: (id: number) => void;
}

export function TicketRack({ tickets, selectedId, activeTicket, onSelect }: Props) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Ticket rack</h2>
        <span className="muted">{tickets.length} tickets</span>
      </div>
      {tickets.length === 0 && <p className="muted">No tickets loaded yet.</p>}
      <div className="rack">
        {tickets.map((t) => (
          <button
            key={t.id}
            className={`stub ${selectedId === t.id ? "stub-selected" : ""} stub-${t.status}`}
            onClick={() => onSelect(t.id)}
            aria-pressed={selectedId === t.id}
          >
            <div className="stub-number">
              <span>No.</span>
              <b>{t.id}</b>
            </div>
            <div className="stub-body">
              <div className="stub-top">
                <span className="stub-type">{TYPE_LABEL[t.type] ?? t.type}</span>
                <StatusPill status={t.status} />
              </div>
              <div className="stub-subject">{t.subject}</div>
              <div className="stub-requester">{t.requester}</div>
              {activeTicket === t.id && (
                <div className="stub-live">
                  <span className="dot dot-pulse" /> agents working
                </div>
              )}
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}
