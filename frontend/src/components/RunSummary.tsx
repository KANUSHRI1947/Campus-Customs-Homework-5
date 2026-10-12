import type { AuditEvent, Run } from "../types";
import { AGENT_BY_KEY } from "../lib/agents";
import { plainExcerpt } from "../lib/format";
import { statusSetInRun, type AgentSummary } from "../lib/summary";
import { Markdown } from "../lib/markdown";
import { StatusPill } from "./TicketRack";

interface Props {
  run: Run;
  seats: AgentSummary[];
  events: AuditEvent[];
}

const RUN_LABEL: Record<string, string> = {
  finished: "Finished",
  stopped: "Stopped by a safety limit",
  failed: "Failed",
  running: "Running",
};

/** After a run: one short card per agent, built from that run's audit events. */
export function RunSummary({ run, seats, events }: Props) {
  const status = statusSetInRun(events);
  const approvals = events.filter((e) => e.event === "payment_approval" || e.event === "discount_decision");
  const used = seats.filter((s) => s.assignments.length || s.tools.length || s.lastWords);
  const notCalled = seats.filter((s) => !used.includes(s)).map((s) => AGENT_BY_KEY[s.key].name);

  return (
    <section className="summary">
      <div className="summary-head">
        <div>
          <h3>What the team did on #{run.ticket_id}</h3>
          <p className="muted">
            Run {run.run_id} · {RUN_LABEL[run.status] ?? run.status}
            {run.usage && (
              <>
                {" "}
                · {run.usage.requests} model calls · {run.usage.tool_calls} tool calls ·{" "}
                {((run.usage.input_tokens ?? 0) + (run.usage.output_tokens ?? 0)).toLocaleString()} tokens
              </>
            )}
          </p>
        </div>
        <div className="summary-status">
          <span>Status set by Boss</span>
          {status ? <StatusPill status={status} /> : <em className="muted">not set</em>}
        </div>
      </div>

      {run.error && <div className="banner banner-error">Run error: {run.error}</div>}

      <div className="summary-grid">
        {used.map((s) => {
          const meta = AGENT_BY_KEY[s.key];
          return (
            <article key={s.key} className="sum-card" style={{ ["--agent" as string]: meta.color }}>
              <header>
                <span className="mini-avatar">{meta.initials}</span>
                <b>{meta.name}</b>
                {s.key !== "boss" && <span className="muted">{s.assignments.length} task(s) from Boss</span>}
              </header>
              {s.tools.length > 0 ? (
                <ul className="sum-tools">
                  {s.tools.map((t) => (
                    <li key={t.tool}>
                      <code>{t.tool}</code>
                      {t.count > 1 && <span className="muted"> ×{t.count}</span>}
                      <div className="sum-outcome">{t.outcomes[t.outcomes.length - 1]}</div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">No tools used.</p>
              )}
              {s.blocked.length > 0 && <p className="sum-blocked">Blocked: {s.blocked.join("; ")}</p>}
              {s.key !== "boss" && s.lastWords && <p className="sum-words">“{plainExcerpt(s.lastWords)}”</p>}
            </article>
          );
        })}
      </div>

      <p className="not-called">
        {notCalled.length ? <>Not called on this ticket: {notCalled.join(", ")}.</> : "Every agent was called."}{" "}
        {approvals.length > 0 &&
          `Human decisions: ${approvals
            .map((a) => `${a.event === "discount_decision" ? "discount" : "payment"} ${String(a.decision)} by ${String(a.approver_name)}`)
            .join(", ")}.`}
      </p>

      {run.final_report && (
        <details className="final-report">
          <summary>Boss’s final report</summary>
          <Markdown text={run.final_report} />
        </details>
      )}
    </section>
  );
}
