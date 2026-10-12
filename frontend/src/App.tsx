import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, errorMessage } from "./api";
import type { AuditEvent, Cash, PendingApproval, Run, Ticket } from "./types";
import { summarizeAgents } from "./lib/summary";
import { money } from "./lib/format";
import { Header } from "./components/Header";
import { TicketRack } from "./components/TicketRack";
import { TicketDetail } from "./components/TicketDetail";
import { AgentFloor } from "./components/AgentFloor";
import { LiveFeed } from "./components/LiveFeed";
import { RunSummary } from "./components/RunSummary";
import { CashTill } from "./components/CashTill";
import { ApprovalCard } from "./components/ApprovalCard";
import { ResetControl } from "./components/ResetControl";
import { Notices, type Notice } from "./components/Notices";

const RUN_POLL_MS = 1500;   // while a ticket is running
const IDLE_POLL_MS = 10000; // otherwise

export default function App() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [dateToday, setDateToday] = useState<string | null>(null);
  const [cash, setCash] = useState<Cash | null>(null);
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);
  const [starting, setStarting] = useState(false);
  const [approverName, setApproverName] = useState("");
  const [notices, setNotices] = useState<Notice[]>([]);

  const lastSeq = useRef<number | null>(null);
  const noticeId = useRef(0);

  // ---------- notices (readable errors instead of crashes) ----------
  const dismiss = useCallback((id: number) => setNotices((n) => n.filter((x) => x.id !== id)), []);
  const notify = useCallback(
    (kind: Notice["kind"], text: string) => {
      setNotices((list) => {
        if (list.some((n) => n.text === text)) return list; // don't stack the same message
        const id = ++noticeId.current;
        if (kind !== "error") setTimeout(() => dismiss(id), 6000);
        return [...list.slice(-3), { id, kind, text }];
      });
    },
    [dismiss],
  );

  // ---------- data loading (all from the real backend) ----------
  const refreshDesk = useCallback(
    async (quiet = false) => {
      const [t, c] = await Promise.allSettled([api.tickets(), api.cash()]);
      if (t.status === "fulfilled") {
        setTickets(t.value.tickets);
        setDateToday(t.value.date_today);
        setBackendOk(true);
      } else {
        setBackendOk(false);
        if (!quiet) notify("error", errorMessage(t.reason));
      }
      if (c.status === "fulfilled") setCash(c.value);
      else if (!quiet && t.status === "fulfilled") notify("error", errorMessage(c.reason));
    },
    [notify],
  );

  const loadRun = useCallback(async (runId: string) => {
    const [{ run: r }, ev] = await Promise.all([api.run(runId), api.events(runId)]);
    lastSeq.current = ev.last_seq;
    setEvents(ev.events);
    setRun(r);
    setApprovals(r.pending_approvals);
  }, []);

  const appendEvents = useCallback((incoming: AuditEvent[], last: number | null) => {
    if (!incoming.length) return;
    lastSeq.current = last;
    setEvents((prev) => {
      const seen = new Set(prev.map((e) => e.seq));
      return [...prev, ...incoming.filter((e) => !seen.has(e.seq))];
    });
  }, []);

  // First load: tickets, cash, and (if the page was reloaded mid-run) the active run.
  useEffect(() => {
    (async () => {
      await refreshDesk();
      try {
        const r = await api.runs();
        const active = r.runs.find((x) => x.run_id === r.active_run_id);
        if (active) {
          setSelectedId(active.ticket_id);
          await loadRun(active.run_id);
        }
      } catch {
        /* backend offline: already reported by refreshDesk */
      }
    })();
  }, [refreshDesk, loadRun]);

  // Select the first ticket once tickets arrive.
  useEffect(() => {
    if (selectedId == null && tickets.length) setSelectedId(tickets[0].id);
  }, [tickets, selectedId]);

  // ---------- polling while a ticket is running ----------
  const runId = run?.run_id ?? null;
  const isRunning = run?.status === "running";
  useEffect(() => {
    if (!runId || !isRunning) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tick = async () => {
      let stillRunning = true;
      try {
        const [r, ev, ap] = await Promise.all([api.run(runId), api.events(runId, lastSeq.current), api.approvals()]);
        if (stopped) return;
        appendEvents(ev.events, ev.last_seq);
        setApprovals(ap.pending.filter((a) => a.run_id === runId));
        setBackendOk(true);
        await refreshDesk(true); // tickets + cash, so status and balance update live
        if (r.run.status !== "running") {
          stillRunning = false;
          const tail = await api.events(runId, lastSeq.current); // catch the last few events
          appendEvents(tail.events, tail.last_seq);
          setApprovals([]);
          notify(
            r.run.status === "finished" ? "success" : "error",
            r.run.status === "finished"
              ? `The team finished ticket #${r.run.ticket_id}.`
              : `The run on #${r.run.ticket_id} ${r.run.status}${r.run.error ? `: ${r.run.error}` : "."}`,
          );
        }
        setRun(r.run);
      } catch (e) {
        setBackendOk(false);
        notify("error", errorMessage(e));
      }
      if (!stopped && stillRunning) timer = setTimeout(tick, RUN_POLL_MS);
    };
    tick();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [runId, isRunning, appendEvents, refreshDesk, notify]);

  // ---------- light polling when idle (keeps balance/tickets honest) ----------
  useEffect(() => {
    if (isRunning) return;
    const id = setInterval(async () => {
      try {
        const h = await api.health();
        setBackendOk(true);
        await refreshDesk(true);
        if (h.active_run_id && h.active_run_id !== runId) await loadRun(h.active_run_id);
      } catch {
        setBackendOk(false);
      }
    }, IDLE_POLL_MS);
    return () => clearInterval(id);
  }, [isRunning, runId, refreshDesk, loadRun]);

  // ---------- actions (each one is a single backend route) ----------
  const selectTicket = useCallback(
    async (id: number) => {
      setSelectedId(id);
      if (isRunning) return; // keep watching the live run
      try {
        const r = await api.runs();
        const latest = r.runs.find((x) => x.ticket_id === id); // newest first
        if (latest) await loadRun(latest.run_id);
        else {
          setRun(null);
          setEvents([]);
          lastSeq.current = null;
        }
      } catch (e) {
        notify("error", errorMessage(e));
      }
    },
    [isRunning, loadRun, notify],
  );

  const startRun = useCallback(
    async (id: number) => {
      setStarting(true);
      try {
        const started = await api.startRun(id); // POST /api/tickets/{id}/run
        lastSeq.current = null;
        setEvents([]);
        setApprovals([]);
        await loadRun(started.run_id);
        notify("info", `Ticket #${id} sent to the agent team.`);
      } catch (e) {
        notify("error", errorMessage(e));
      } finally {
        setStarting(false);
      }
    },
    [loadRun, notify],
  );

  const decide = useCallback(
    async (approvalId: string, decision: "approve" | "reject") => {
      try {
        const res = await api.decide(approvalId, decision, approverName.trim()); // only on a real click
        setApprovals((list) => list.filter((a) => a.approval_id !== approvalId));
        const msg =
          res.kind === "discount"
            ? decision === "approve"
              ? `Discount price approved by ${res.approver_name}. Recorded on the ticket; no cash moved.`
              : `Discount price rejected by ${res.approver_name}. The list price stands.`
            : decision === "approve"
              ? `Payment approved by ${res.approver_name}. The payment tool re-checks the facts and records it; the balance will update.`
              : `Payment rejected by ${res.approver_name}. Nothing was paid.`;
        notify(decision === "approve" ? "success" : "info", msg);
      } catch (e) {
        notify("error", errorMessage(e));
      }
    },
    [approverName, notify],
  );

  const reset = useCallback(async () => {
    try {
      const r = await api.reset(); // POST /api/reset {"confirm": "RESET"}
      setRun(null);
      setEvents([]);
      setApprovals([]);
      lastSeq.current = null;
      await refreshDesk();
      notify(
        "success",
        `Fresh start: database restored (${r.tickets.filter((t) => t.status !== "resolved").length} tickets open, checking ${money(
          r.checking_balance,
        )}).`,
      );
    } catch (e) {
      notify("error", errorMessage(e));
    }
  }, [refreshDesk, notify]);

  // ---------- derived view state ----------
  const seats = useMemo(() => summarizeAgents(events, !!run && run.status !== "running"), [events, run]);
  const activeTicket = isRunning ? run!.ticket_id : null;
  const selected = tickets.find((t) => t.id === selectedId) ?? null;
  const resetBlocked = isRunning
    ? "Can't reset while the team is working."
    : approvals.length
      ? "An approval (payment or discount decision) is waiting."
      : backendOk === false
        ? "The backend is offline."
        : null;

  return (
    <div className="app">
      <Header dateToday={dateToday} backendOk={backendOk} activeTicket={activeTicket} />
      <Notices notices={notices} onDismiss={dismiss} />

      <main className="desk">
        <aside className="col col-left">
          <TicketRack tickets={tickets} selectedId={selectedId} activeTicket={activeTicket} onSelect={selectTicket} />
          <TicketDetail ticket={selected} activeRunTicket={activeTicket} starting={starting} onStart={startRun} />
        </aside>

        <section className="col col-center">
          <div className="panel stage">
            <div className="panel-head">
              <h2>The team</h2>
              <span className="muted">
                {run
                  ? `${run.status === "running" ? "Working on" : "Last run on"} #${run.ticket_id}`
                  : "Idle · pick a ticket and send it to the team"}
              </span>
            </div>
            {approvals.length > 0 && (
              <div className="banner banner-waiting">
                {approvals.some((a) => a.kind === "discount")
                  ? "The Boss is waiting for your DISCOUNT DECISION. See the card on the right."
                  : "Accounting is waiting for your PAYMENT approval. See the card on the right."}
              </div>
            )}
            <AgentFloor seats={seats} running={isRunning} />
            {run && run.status !== "running" && <RunSummary run={run} seats={seats} events={events} />}
            <LiveFeed events={events} running={isRunning} />
          </div>
        </section>

        <aside className="col col-right">
          <CashTill cash={cash} />
          {approvals.length > 0 ? (
            approvals.map((a) => (
              <ApprovalCard
                key={a.approval_id}
                approval={a}
                events={events}
                approverName={approverName}
                onApproverName={setApproverName}
                onDecide={decide}
              />
            ))
          ) : (
            <section className="panel approvals-empty">
              <div className="panel-head">
                <h2>Approvals</h2>
              </div>
              <p className="muted small">
                Nothing waiting. If Accounting asks to pay (a <b>PAYMENT</b>) or the Boss recommends a price (a{" "}
                <b>DISCOUNT DECISION</b>), a card appears here. Nothing is approved unless you click <b>Approve</b>.
              </p>
            </section>
          )}
          <ResetControl disabledReason={resetBlocked} onReset={reset} />
        </aside>
      </main>

      <footer className="footer">
        Live data from the FastAPI backend (<code>localhost:8000</code>) · events from <code>audit_trail.json</code> ·
        customer replies and restock orders are drafts only.
      </footer>
    </div>
  );
}
