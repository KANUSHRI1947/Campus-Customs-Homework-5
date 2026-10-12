import { AGENT_BY_KEY } from "../lib/agents";
import type { AgentSummary } from "../lib/summary";

const STATE_LABEL = { idle: "Not called yet", working: "Working", done: "Done" } as const;

export function AgentFloor({ seats, running }: { seats: AgentSummary[]; running: boolean }) {
  return (
    <div className="floor">
      {seats.map((s) => {
        const meta = AGENT_BY_KEY[s.key];
        const state = !running && s.state === "idle" && s.assignments.length === 0 ? "idle" : s.state;
        return (
          <div key={s.key} className={`seat seat-${state}`} style={{ ["--agent" as string]: meta.color }}>
            <div className="avatar">
              <span>{meta.initials}</span>
            </div>
            <div className="seat-name">{meta.name}</div>
            <div className="seat-role">{meta.role}</div>
            <div className="seat-state">{STATE_LABEL[state]}</div>
            {s.lastAction && <div className="seat-action" title={s.lastAction}>{s.lastAction}</div>}
          </div>
        );
      })}
    </div>
  );
}
