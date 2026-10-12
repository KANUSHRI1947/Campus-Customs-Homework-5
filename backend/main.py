"""Campus Customs backend API (FastAPI) for the React desk dashboard.

Reuses what's already built. Nothing here invents data or logs separately:
  - tickets and cash are read from data/campus_customs_new.db (read-only)
  - agent runs go through team.run_team() (same five agents, prompts, MCP tools)
  - events come from the existing append-only output/audit_trail.json (audit.read_events)
  - payments still go through the MCP tool request_payment, which pauses for a
    human; this API only passes on a human's click. Nothing is auto-approved.

Start it from the backend/ folder (with the project's .venv activated):
    cd backend
    source ../.venv/bin/activate
    uvicorn main:app --reload --port 8000
The API is then at http://localhost:8000 (interactive docs at http://localhost:8000/docs).
--reload restarts the server when a file in backend/ is saved, which also stops
any agent run in progress, so don't edit code during a run. The audit trail,
database, and drafts live outside backend/, so the agents' own writes never
trigger a reload.

Routes (all JSON):
    GET  /api/health
    GET  /api/tickets
    GET  /api/tickets/{ticket_id}
    POST /api/tickets/{ticket_id}/run
    GET  /api/runs
    GET  /api/runs/{run_id}
    GET  /api/events
    GET  /api/approvals
    POST /api/approvals/{approval_id}
    GET  /api/cash
    POST /api/reset
"""

import asyncio
import filecmp
import os
import sqlite3
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Path as PathParam, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastmcp.client.elicitation import ElicitResult
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
import team  # noqa: E402  (same agents, limits, and paths as the CLI)
from audit import log_event, read_events  # noqa: E402

WORKING_DB = team.WORKING_DB
ORIGINAL_DB = team.ORIGINAL_DB
# Give up waiting a little before the MCP connection itself would time out.
APPROVAL_TIMEOUT_SECONDS = max(team.APPROVAL_WAIT_SECONDS - 30, 30)
RESET_CONFIRM_WORD = "RESET"

app = FastAPI(title="Campus Customs Desk API", version="1.0")
FRONTEND_ORIGIN = "http://localhost:5173"  # the Vite dev server (frontend/, `npm run dev`)
app.add_middleware(  # CORS: only our dashboard may call these routes from a browser
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_methods=["GET", "POST"],      # the only methods our routes use
    allow_headers=["Content-Type"],     # JSON bodies on POST
)


# ---------------------------------------------------------------------------
# Structured errors: every error is {"error": {"status", "message", ...}}
# ---------------------------------------------------------------------------
def api_error(status: int, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"message": message, **extra})


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content={"error": {"status": exc.status_code, **detail}})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": {
        "status": 422, "message": "Invalid request.", "details": jsonable_encoder(exc.errors())}})


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": {
        "status": 500, "message": f"Unexpected server error: {type(exc).__name__}: {exc}"}})


# ---------------------------------------------------------------------------
# Database reads (read-only; the MCP tools remain the only writers)
# ---------------------------------------------------------------------------
TICKET_FIELDS = ("id", "type", "requester", "subject", "sku", "size", "qty", "lease_id",
                 "invoice_id", "status", "notes", "created_at")


def db_read(sql: str, params: tuple = ()) -> list[dict]:
    if not WORKING_DB.exists():
        raise api_error(500, f"Database not found: {WORKING_DB.name}. Use POST /api/reset to restore it.")
    conn = sqlite3.connect(f"file:{WORKING_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def date_today() -> str | None:
    rows = db_read("SELECT date_today FROM desk")
    return rows[0]["date_today"] if rows else None


def ticket_json(row: dict) -> dict:
    return {**row, "is_open": row["status"] != "resolved"}


def get_ticket_or_404(ticket_id: int) -> dict:
    rows = db_read(f"SELECT {', '.join(TICKET_FIELDS)} FROM tickets WHERE id = ?", (ticket_id,))
    if not rows:
        known = [r["id"] for r in db_read("SELECT id FROM tickets ORDER BY id")]
        raise api_error(404, f"No ticket with id {ticket_id}.", known_ticket_ids=known)
    return ticket_json(rows[0])


# ---------------------------------------------------------------------------
# Runs (one at a time) and human approvals (wait for a real click)
# ---------------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class RunRecord:
    run_id: str
    ticket_id: int
    status: str = "running"            # running | finished | stopped | failed
    started_at: str = field(default_factory=now_iso)
    finished_at: str | None = None
    final_report: str | None = None
    usage: dict | None = None
    delegations: int | None = None
    error: str | None = None
    task: asyncio.Task | None = None

    def to_json(self) -> dict:
        data = {k: v for k, v in self.__dict__.items() if k != "task"}
        data["pending_approvals"] = [a.to_json() for a in PENDING.values() if a.run_id == self.run_id]
        return data


@dataclass
class PendingApproval:
    approval_id: str
    run_id: str
    ticket_id: int | None
    message: str
    requested_at: str
    future: asyncio.Future
    kind: str = "payment"  # "payment" (request_payment) or "discount" (request_discount_decision)

    def to_json(self) -> dict:
        return {"approval_id": self.approval_id, "kind": self.kind, "run_id": self.run_id,
                "ticket_id": self.ticket_id, "message": self.message, "requested_at": self.requested_at}


RUNS: dict[str, RunRecord] = {}
PENDING: dict[str, PendingApproval] = {}


def active_run() -> RunRecord | None:
    return next((r for r in RUNS.values() if r.status == "running"), None)


def web_approval_factory(ticket_id: int | None):
    """Builds the MCP elicitation handler for a run: it parks the payment request (or
    discount decision) until a human answers through POST /api/approvals/{approval_id}."""
    def factory(run_id: str):
        async def handler(message, response_type, params, context):
            approval_id = uuid.uuid4().hex[:8]
            future = asyncio.get_running_loop().create_future()
            kind = team.approval_kind(message)
            PENDING[approval_id] = PendingApproval(approval_id, run_id, ticket_id, message, now_iso(), future, kind)
            log_event(run_id, "HUMAN", "approval_requested", approval_id=approval_id, kind=kind, prompt=message)
            try:
                approve, approver = await asyncio.wait_for(asyncio.shield(future), APPROVAL_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                # No click in time: treated as NOT approved (never auto-approved).
                log_event(run_id, "HUMAN", "approval_timed_out", approval_id=approval_id, kind=kind,
                          decision="no decision - treated as rejected")
                return ElicitResult(action="decline")
            finally:
                PENDING.pop(approval_id, None)
            return ElicitResult(action="accept", content={"approve": approve, "approver_name": approver})
        return handler
    return factory


async def _run_in_background(record: RunRecord, reset_first: bool) -> None:
    try:
        summary = await team.run_team(ticket_id=record.ticket_id, reset=reset_first, run_id=record.run_id,
                                      approval_factory=web_approval_factory(record.ticket_id))
        record.status = summary["status"]
        record.final_report = summary.get("final_report") or summary.get("reason")
        record.usage = summary.get("usage")
        record.delegations = summary.get("delegations")
    except Exception as exc:  # already written to the audit trail by run_team
        record.status = "failed"
        record.error = f"{type(exc).__name__}: {exc}"
    finally:
        record.finished_at = now_iso()


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
class RunRequest(BaseModel):
    reset_first: bool = Field(False, description="Reset the database to the original values before this run.")


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    approver_name: str = Field(..., min_length=1, max_length=100, description="Recorded in payments.approved_by")


class ResetRequest(BaseModel):
    confirm: str = Field(..., description=f'Must be exactly "{RESET_CONFIRM_WORD}".')


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
TicketId = PathParam(..., ge=1, description="Ticket id, e.g. 101")


@app.get("/api/health")
async def health():
    return {"ok": True, "database": WORKING_DB.name, "date_today": date_today(),
            "active_run_id": (r.run_id if (r := active_run()) else None)}


@app.get("/api/tickets")
async def list_tickets():
    """All tickets (open, waiting, and resolved) with is_open for each."""
    rows = db_read(f"SELECT {', '.join(TICKET_FIELDS)} FROM tickets ORDER BY id")
    return {"date_today": date_today(), "count": len(rows), "tickets": [ticket_json(r) for r in rows]}


@app.get("/api/tickets/{ticket_id}")
async def get_ticket(ticket_id: int = TicketId):
    return {"date_today": date_today(), "ticket": get_ticket_or_404(ticket_id)}


@app.post("/api/tickets/{ticket_id}/run", status_code=202)
async def run_ticket(ticket_id: int = TicketId, body: RunRequest | None = None):
    """Start the agent team on ONE ticket. Returns immediately; poll /api/runs/{run_id},
    /api/events?run_id=..., and /api/approvals while it runs."""
    body = body or RunRequest()
    ticket = get_ticket_or_404(ticket_id)
    if (running := active_run()) is not None:
        raise api_error(409, f"Run {running.run_id} (ticket {running.ticket_id}) is still running; "
                             "only one run at a time.", active_run_id=running.run_id)
    if ticket["status"] == "resolved" and not body.reset_first:
        raise api_error(409, f"Ticket {ticket_id} is already resolved. Reset the database first "
                             'or send {"reset_first": true}.')
    if not os.environ.get("PORTKEY_API_KEY"):
        raise api_error(503, "PORTKEY_API_KEY is missing from .env, so the agents can't run.")

    record = RunRecord(run_id=team.new_run_id(), ticket_id=ticket_id)
    RUNS[record.run_id] = record
    record.task = asyncio.create_task(_run_in_background(record, body.reset_first))
    return {"run_id": record.run_id, "ticket_id": ticket_id, "status": "running",
            "reset_first": body.reset_first,
            "poll": {"run": f"/api/runs/{record.run_id}", "events": f"/api/events?run_id={record.run_id}",
                     "approvals": "/api/approvals"}}


@app.get("/api/runs")
async def list_runs():
    """Runs started by this server since it was launched (newest first)."""
    runs = sorted(RUNS.values(), key=lambda r: r.started_at, reverse=True)
    return {"active_run_id": (r.run_id if (r := active_run()) else None), "runs": [r.to_json() for r in runs]}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    record = RUNS.get(run_id)
    if record is None:
        raise api_error(404, f"No run {run_id} was started by this server. "
                             "Past runs are still in /api/events?run_id=...")
    return {"run": record.to_json()}


def summarize(e: dict) -> str:
    """One readable line per audit event for the dashboard (derived, not stored)."""
    who, ev = e.get("agent", "?"), e.get("event", "?")
    if ev == "delegate":
        return f"Boss → {e.get('to')}: {e.get('task')}"
    if ev == "answer_to_boss":
        return f"{who} → Boss: {e.get('answer')}"
    if ev == "tool_call":
        return f"{who} called {e.get('tool')}({e.get('args')})"
    if ev == "tool_result":
        res = e.get("result")
        outcome = res.get("result") if isinstance(res, dict) and "result" in res else "ok"
        return f"{who} got {e.get('tool')} result: {outcome}"
    if ev in ("tool_error", "tool_blocked"):
        return f"{who} {ev.replace('_', ' ')} on {e.get('tool')}: {e.get('error') or e.get('reason') or ''}".strip()
    if ev == "approval_requested":
        return f"Waiting for a human {str(e.get('kind') or 'payment').upper()} decision: {e.get('prompt')}"
    if ev == "payment_approval":
        return f"Human {e.get('decision')} the PAYMENT ({e.get('approver_name') or 'no name'})"
    if ev == "discount_decision":
        return f"Human {e.get('decision')} the DISCOUNT price ({e.get('approver_name') or 'no name'})"
    if ev == "approval_timed_out":
        return f"No human decision in time; {e.get('kind') or 'payment'} treated as rejected"
    if ev == "final_report":
        return f"Boss final report: {e.get('report')}"
    if ev == "tools_available":
        acct = (e.get("agents") or {}).get("accounting", [])
        missing = e.get("missing_from_server") or {}
        return (f"MCP server exposed {len(e.get('mcp_server_tools') or [])} tools; Accounting has "
                f"{', '.join(acct)}" + (f"; MISSING: {missing}" if missing else ""))
    if ev == "run_start":
        return f"Run started (ticket {e.get('ticket_id') or 'all'})"
    return ev.replace("_", " ")


@app.get("/api/events")
async def get_events(
    limit: int = Query(50, ge=1, le=500, description="Most recent N matching events"),
    run_id: str | None = Query(None),
    agent: str | None = Query(None, description="boss, inventory, accounting, facilities, customer_service, HUMAN, SYSTEM"),
    event: str | None = Query(None, description="e.g. tool_call, delegate, answer_to_boss, payment_approval"),
    after_seq: int | None = Query(None, ge=0, description="Only events after this seq (for polling)"),
):
    """Recent agent events, read from the existing append-only output/audit_trail.json."""
    try:
        events = read_events(limit=limit, run_id=run_id, agent=agent, event=event, after_seq=after_seq)
    except ValueError as exc:
        raise api_error(500, str(exc))
    return {"count": len(events), "last_seq": events[-1]["seq"] if events else after_seq,
            "events": [{**e, "summary": summarize(e)} for e in events]}


@app.get("/api/approvals")
async def list_approvals():
    """Payments and discount decisions waiting for a human click (each has a `kind`)."""
    return {"pending": [a.to_json() for a in PENDING.values()]}


@app.post("/api/approvals/{approval_id}")
async def decide_approval(approval_id: str, body: ApprovalDecision):
    """A human approves or rejects a waiting PAYMENT or DISCOUNT DECISION (see `kind`).
    This is the ONLY way either gets approved. request_payment re-checks the facts
    before recording a payment; request_discount_decision only records the decision
    in the ticket notes (no cash, no catalogue change)."""
    pending = PENDING.get(approval_id)
    if pending is None or pending.future.done():
        raise api_error(404, f"Nothing is waiting for approval with id {approval_id}.",
                        pending_ids=[a for a in PENDING])
    name = body.approver_name.strip()
    if not name:
        raise api_error(422, "approver_name can't be blank.")
    approved = body.decision == "approve"
    log_event(pending.run_id, "HUMAN", team.DECISION_EVENT[pending.kind], approval_id=approval_id,
              kind=pending.kind, prompt=pending.message,
              decision="approved" if approved else "rejected", approver_name=name)
    pending.future.set_result((approved, name))
    note = ("The run continues; request_payment re-checks the facts and returns paid, rejected, or refused."
            if pending.kind == "payment" else
            "The run continues; request_discount_decision records your decision in the ticket notes. "
            "No cash moves and the catalogue price does not change.")
    return {"approval_id": approval_id, "kind": pending.kind, "run_id": pending.run_id,
            "decision": "approved" if approved else "rejected", "approver_name": name,
            "note": note + " See /api/events for the result."}


@app.get("/api/cash")
async def get_cash():
    rows = db_read("SELECT name, balance, date FROM cash_accounts WHERE name = 'checking'")
    if not rows:
        raise api_error(404, "No 'checking' account in cash_accounts.")
    row = rows[0]
    return {"account": row["name"], "balance": row["balance"], "as_of": row["date"], "date_today": date_today()}


@app.post("/api/reset")
async def reset_database(body: ResetRequest):
    """Copy data/campus_customs.db over data/campus_customs_new.db. Requires
    {"confirm": "RESET"} and is refused while a run is going or a payment is waiting."""
    if body.confirm != RESET_CONFIRM_WORD:
        raise api_error(400, f'To reset, send {{"confirm": "{RESET_CONFIRM_WORD}"}} exactly.')
    if (running := active_run()) is not None or PENDING:
        raise api_error(409, "Can't reset while a run is going or a payment/discount decision is waiting for approval.",
                        active_run_id=running.run_id if running else None, pending_ids=list(PENDING))
    if not ORIGINAL_DB.exists():
        raise api_error(500, f"Original database {ORIGINAL_DB.name} is missing; nothing to reset from.")
    reset_id = "reset-" + team.new_run_id()
    team.reset_database(reset_id)  # same reset (and audit event) the CLI uses
    tickets = db_read("SELECT id, status FROM tickets ORDER BY id")
    return {"reset": True, "reset_id": reset_id, "source": ORIGINAL_DB.name, "target": WORKING_DB.name,
            "matches_original": filecmp.cmp(ORIGINAL_DB, WORKING_DB, shallow=False),
            "checking_balance": db_read("SELECT balance FROM cash_accounts WHERE name = 'checking'")[0]["balance"],
            "tickets": tickets}


if __name__ == "__main__":  # alternative to the uvicorn command above (same host and port)
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
