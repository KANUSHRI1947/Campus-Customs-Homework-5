import { prettyDate } from "../lib/format";

interface Props {
  dateToday: string | null;
  backendOk: boolean | null;
  activeTicket: number | null;
}

export function Header({ dateToday, backendOk, activeTicket }: Props) {
  return (
    <header className="awning">
      <div className="awning-inner">
        <div className="brand">
          <svg className="brand-mark" viewBox="0 0 64 64" aria-hidden="true">
            <rect width="64" height="64" rx="14" fill="#f4e9d4" />
            <path d="M14 40h36v6H14zM18 22h28l4 14H14z" fill="#00356b" />
            <circle cx="32" cy="29" r="3" fill="#c9a227" />
          </svg>
          <div>
            <h1>Campus Customs</h1>
            <p>Service Desk · Chapel Street</p>
          </div>
        </div>
        <div className="awning-meta">
          <span className="chip chip-paper" title="desk.date_today, the shop's 'today'">
            Shop date <b>{prettyDate(dateToday)}</b>
          </span>
          {activeTicket != null && (
            <span className="chip chip-live">
              <span className="dot dot-pulse" /> Team working on #{activeTicket}
            </span>
          )}
          <span className={`chip ${backendOk ? "chip-ok" : backendOk === false ? "chip-bad" : "chip-paper"}`}>
            <span className={`dot ${backendOk ? "dot-ok" : backendOk === false ? "dot-bad" : ""}`} />
            {backendOk == null ? "Connecting…" : backendOk ? "Backend connected" : "Backend offline"}
          </span>
        </div>
      </div>
      <div className="scallop" aria-hidden="true" />
    </header>
  );
}
