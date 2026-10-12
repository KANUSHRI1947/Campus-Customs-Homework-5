import { useEffect, useRef, type UIEvent } from "react";
import type { AuditEvent } from "../types";
import { agentColor, agentName } from "../lib/agents";
import { argsText, clockTime, toolLabel } from "../lib/format";
import { toolOutcome } from "../lib/summary";
import { Markdown } from "../lib/markdown";

const s = (v: unknown) => (v == null ? "" : String(v));

function Row({ e }: { e: AuditEvent }) {
  const who = agentName(e.agent);
  const color = agentColor(e.agent);
  const time = <time>{clockTime(e.logged_at)}</time>;

  switch (e.event) {
    case "delegate":
      return (
        <li className="ev ev-handoff" style={{ ["--c" as string]: agentColor(s(e.to)) }}>
          {time}
          <div className="handoff">
            <b style={{ color: agentColor("boss") }}>Boss</b>
            <span className="handoff-arrow">hands off to</span>
            <b style={{ color: agentColor(s(e.to)) }}>{agentName(s(e.to))}</b>
          </div>
          <p className="ev-text">{s(e.task)}</p>
        </li>
      );
    case "tool_call":
      return (
        <li className="ev ev-tool" style={{ ["--c" as string]: color }}>
          {time}
          <div className="tool-line">
            <b style={{ color }}>{who}</b> called
            <code className="tool-chip">{s(e.tool)}</code>
          </div>
          {argsText(e.args) && <div className="tool-args">{argsText(e.args)}</div>}
        </li>
      );
    case "tool_result":
      return (
        <li className="ev ev-result" style={{ ["--c" as string]: color }}>
          {time}
          <div className="tool-line">
            <span className="result-arrow">↳</span> <span className="muted">{toolLabel(s(e.tool))}</span>
            <b className="result-text">{toolOutcome(e)}</b>
          </div>
          <details>
            <summary>Full result</summary>
            <pre>{JSON.stringify(e.result, null, 2)}</pre>
          </details>
        </li>
      );
    case "answer_to_boss":
    case "final_report":
      return (
        <li className={`ev ev-say ${e.event === "final_report" ? "ev-final" : ""}`} style={{ ["--c" as string]: color }}>
          {time}
          <div className="say-who" style={{ color }}>
            {e.event === "final_report" ? "Boss · final report" : `${who} → Boss`}
          </div>
          <div className="bubble">
            <Markdown text={s(e.answer ?? e.report)} />
          </div>
        </li>
      );
    case "approval_requested":
      return (
        <li className="ev ev-human">
          {time}
          <b>Waiting for your {e.kind === "discount" ? "DISCOUNT DECISION" : "PAYMENT approval"}</b>
          <p className="ev-text">{s(e.prompt)}</p>
        </li>
      );
    case "payment_approval":
    case "discount_decision":
      return (
        <li className={`ev ev-human ${e.decision === "approved" ? "ok" : "no"}`}>
          {time}
          <b>
            {s(e.approver_name) || "Human"} {s(e.decision)} the{" "}
            {e.event === "discount_decision" ? "DISCOUNT price" : "PAYMENT"}
          </b>
        </li>
      );
    case "tool_blocked":
    case "tool_error":
    case "run_error":
    case "run_stopped":
    case "approval_timed_out":
    case "delegation_refused":
      return (
        <li className="ev ev-warn">
          {time}
          <b>{who}</b> {e.summary}
        </li>
      );
    case "task":
      return (
        <li className="ev ev-system">
          {time} <b>Boss’s assignment:</b> {s(e.task)}
        </li>
      );
    default:
      return (
        <li className="ev ev-system">
          {time} {e.summary}
        </li>
      );
  }
}

export function LiveFeed({ events, running }: { events: AuditEvent[]; running: boolean }) {
  const box = useRef<HTMLOListElement>(null);
  const stick = useRef(true);

  useEffect(() => {
    const el = box.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [events.length]);

  return (
    <div className="feed-wrap">
      <div className="feed-head">
        <h3>Live desk feed</h3>
        <span className="muted">
          {running && <span className="dot dot-pulse" />} {events.length} events from audit_trail.json
        </span>
      </div>
      {events.length === 0 ? (
        <p className="empty">
          {running ? "Waiting for the first agent event…" : "Start a ticket to watch the team work here."}
        </p>
      ) : (
        <ol
          className="feed"
          ref={box}
          onScroll={(ev: UIEvent<HTMLOListElement>) => {
            const el = ev.currentTarget;
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
          }}
        >
          {events.map((e) => (
            <Row key={e.seq} e={e} />
          ))}
        </ol>
      )}
    </div>
  );
}
