"""Campus Customs agent team (PydanticAI + the campus-customs MCP server).

Five agents, each with its own prompt from backend/prompts/ and ONLY its own
MCP tools:

  Boss              list_open_tickets, update_ticket_status, request_discount_decision,
                    + ask_inventory / ask_accounting / ask_facilities /
                      ask_customer_service (delegation)
  Inventory         get_stock_and_margin_for_bulk_order,
                    get_invoice_and_vendor_block_status, request_vendor_restock
  Accounting        get_invoice_and_vendor_block_status,
                    get_lease_rent_due_and_cash_coverage, get_checking_balance,
                    request_payment
  Facilities        get_lease_rent_due_and_cash_coverage
  Customer Service  get_stock_and_margin_for_bulk_order, draft_customer_message

Every agent run, delegation, tool call, tool result, and human approval is
appended to output/audit_trail.json as it happens.

Run a full ticket-resolution run (resets the database first):
    .venv/bin/python backend/team.py
Skip the reset (e.g. to continue from the current database):
    .venv/bin/python backend/team.py --no-reset
Run just one ticket (no reset unless you add --reset):
    .venv/bin/python backend/team.py --ticket 102

The FastAPI backend (backend/main.py) calls run_team() directly and supplies a
web-based approval handler instead of the terminal prompt.
"""

import argparse
import asyncio
import os
import shutil
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

import anyio
from dotenv import load_dotenv
from fastmcp.client.elicitation import ElicitResult
from fastmcp.client.transports import StdioTransport
from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.toolsets import WrapperToolset
from pydantic_ai.usage import UsageLimits

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit import AUDIT_PATH, log_event  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "backend" / "prompts"
ORIGINAL_DB = PROJECT_ROOT / "data" / "campus_customs.db"
WORKING_DB = PROJECT_ROOT / "data" / "campus_customs_new.db"
load_dotenv(PROJECT_ROOT / ".env")  # PORTKEY_API_KEY (+ optional PORTKEY_BASE_URL, MODEL_API)

# ---------------------------------------------------------------------------
# Safety limits (keep a run from burning through tokens or looping forever)
# ---------------------------------------------------------------------------
MODEL_NAME = "gpt-6-luna"           # the only string that reaches GPT-6-Luna via Portkey
RUN_LIMITS = UsageLimits(           # shared by ALL five agents in one run
    request_limit=60,               # max model calls
    tool_calls_limit=60,            # max tool calls
    total_tokens_limit=300_000,     # hard token ceiling for the whole run
)
MAX_OUTPUT_TOKENS = 4_000           # max tokens per single model reply (reasoning + answer)
REASONING_EFFORT = "low"            # keep GPT-6-Luna's reasoning cheap; enough for tool use
MAX_DELEGATIONS = 15                # max Boss -> specialist hand-offs per run
AGENT_RETRIES = 2                   # max retries after a bad tool call / output
APPROVAL_WAIT_SECONDS = 900         # how long a payment approval can wait for a human

AGENT_TOOLS = {
    "boss": {"list_open_tickets", "update_ticket_status", "request_discount_decision"},
    "inventory": {"get_stock_and_margin_for_bulk_order", "get_invoice_and_vendor_block_status",
                  "request_vendor_restock"},
    "accounting": {"get_invoice_and_vendor_block_status", "get_lease_rent_due_and_cash_coverage",
                   "get_checking_balance", "request_payment"},
    "facilities": {"get_lease_rent_due_and_cash_coverage"},
    "customer_service": {"get_stock_and_margin_for_bulk_order", "draft_customer_message"},
}


@dataclass
class TeamDeps:
    run_id: str
    delegations: int = 0
    scope: dict | None = None  # set when a run is limited to ONE ticket (see load_ticket_scope)


# ---------------------------------------------------------------------------
# Model (GPT-6-Luna through Portkey)
# ---------------------------------------------------------------------------
# GPT-6-Luna reasons by default, and Portkey's /v1/chat/completions endpoint
# rejects reasoning + function tools for it ("Function tools with
# reasoning_effort are not supported ... use /v1/responses"). So the agents use
# the Responses API (/v1/responses) via OpenAIResponsesModel. Same model name.
# Fallback: set MODEL_API=chat in .env to use /v1/chat/completions with
# reasoning turned off (reasoning_effort='none'), which that endpoint allows.
def model_api() -> str:
    return os.environ.get("MODEL_API", "responses").strip().lower()


def build_model() -> OpenAIResponsesModel | OpenAIChatModel:
    key = os.environ.get("PORTKEY_API_KEY")
    if not key:  # raise (not sys.exit) so a web server reports it instead of shutting down
        raise RuntimeError("PORTKEY_API_KEY is missing from .env")
    client = AsyncOpenAI(
        api_key=key,
        base_url=os.environ.get("PORTKEY_BASE_URL", "https://api.portkey.ai/v1"),
        default_headers={"x-portkey-api-key": key},
    )
    provider = OpenAIProvider(openai_client=client)
    if model_api() == "chat":
        return OpenAIChatModel(MODEL_NAME, provider=provider)
    return OpenAIResponsesModel(MODEL_NAME, provider=provider)


def build_model_settings() -> dict:
    """Per-reply limits shared by all five agents."""
    effort = "none" if model_api() == "chat" else REASONING_EFFORT
    return {"max_tokens": MAX_OUTPUT_TOKENS, "openai_reasoning_effort": effort}


# ---------------------------------------------------------------------------
# Per-agent tool access + audit logging of every MCP tool call
# ---------------------------------------------------------------------------
@dataclass
class AuditedToolset(WrapperToolset[TeamDeps]):
    """Shows an agent only its own MCP tools and logs every call it makes."""

    agent_name: str = ""
    allowed: frozenset[str] = frozenset()

    async def get_tools(self, ctx: RunContext[TeamDeps]):
        tools = await self.wrapped.get_tools(ctx)
        return {name: t for name, t in tools.items() if name in self.allowed}

    async def call_tool(self, name: str, tool_args: dict[str, Any], ctx: RunContext[TeamDeps], tool) -> Any:
        run_id = ctx.deps.run_id
        if name not in self.allowed:  # belt and braces: should never happen
            log_event(run_id, self.agent_name, "tool_blocked", tool=name, args=tool_args)
            raise PermissionError(f"{self.agent_name} is not allowed to use {name}.")
        reason = out_of_scope(name, tool_args, ctx.deps.scope)
        if reason:  # one-ticket run: don't act on a different ticket
            log_event(run_id, self.agent_name, "tool_blocked", tool=name, args=tool_args, reason=reason)
            return {"result": "refused", "reason": reason, "database_changed": False}
        log_event(run_id, self.agent_name, "tool_call", tool=name, args=tool_args)
        try:
            result = await self.wrapped.call_tool(name, tool_args, ctx, tool)
        except Exception as exc:
            log_event(run_id, self.agent_name, "tool_error", tool=name, error=str(exc))
            raise
        log_event(run_id, self.agent_name, "tool_result", tool=name, result=result)
        return result


# ---------------------------------------------------------------------------
# One-ticket scope (used when a run is limited to a single ticket)
# ---------------------------------------------------------------------------
def load_ticket_scope(ticket_id: int) -> dict:
    """Read the ticket's own linked values from the working database (read-only)."""
    conn = sqlite3.connect(f"file:{WORKING_DB}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT id, sku, size, invoice_id, lease_id FROM tickets WHERE id = ?",
                           (ticket_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError(f"No ticket with id {ticket_id} exists.")
    return dict(zip(("ticket_id", "sku", "size", "invoice_id", "lease_id"), row))


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def out_of_scope(name: str, args: dict[str, Any], scope: dict | None) -> str | None:
    """Return a refusal reason if a tool call would act on a different ticket than
    the one this run is limited to. Lookups are always allowed."""
    if not scope:
        return None
    t = scope["ticket_id"]
    if name in ("update_ticket_status", "draft_customer_message", "request_discount_decision") \
            and _as_int(args.get("ticket_id")) != t:
        return f"This run is limited to ticket {t}; {name} for ticket {args.get('ticket_id')} is not allowed."
    if name == "request_payment":
        kind, ref = str(args.get("kind", "")).strip().lower(), _as_int(args.get("ref_id"))
        if not ((kind == "invoice" and scope["invoice_id"] is not None and ref == scope["invoice_id"])
                or (kind == "rent" and scope["lease_id"] is not None and ref == scope["lease_id"])):
            return (f"This run is limited to ticket {t}, which links invoice {scope['invoice_id']} and "
                    f"lease {scope['lease_id']}; a {kind} payment for {args.get('ref_id')} is not allowed.")
    if name == "request_vendor_restock" and (
            str(args.get("sku", "")).strip(), str(args.get("size", "")).strip()) != (scope["sku"], scope["size"]):
        return (f"This run is limited to ticket {t} ({scope['sku']} size {scope['size']}); "
                f"a restock for {args.get('sku')} size {args.get('size')} is not allowed.")
    return None


# ---------------------------------------------------------------------------
# Human approval for payments (answers the MCP server's approval prompt)
# ---------------------------------------------------------------------------
# An approval handler factory takes a run_id and returns the MCP elicitation
# handler for that run. The CLI uses the terminal; backend/main.py uses a web
# click. Either way, only a human's answer can approve a payment.
ApprovalFactory = Callable[[str], Callable[..., Awaitable[Any]]]


def approval_kind(message: str) -> str:
    """'discount' for request_discount_decision prompts, otherwise 'payment'.
    The MCP server starts every discount prompt with this exact prefix."""
    return "discount" if str(message).startswith("DISCOUNT DECISION NEEDED") else "payment"


# Audit event names for each kind of human decision (kept separate on purpose).
DECISION_EVENT = {"payment": "payment_approval", "discount": "discount_decision"}


def terminal_approval(run_id: str):
    async def human_approval(message, response_type, params, context):
        kind = approval_kind(message)
        print("\n" + "=" * 70 + f"\n[{kind.upper()}] {message}\n" + "=" * 70)
        answer = (await anyio.to_thread.run_sync(
            input, f"Type 'yes' to approve this {kind.upper()}, anything else to reject: ")).strip().lower()
        name = (await anyio.to_thread.run_sync(input, "Your name (recorded as the decider): ")).strip()
        approved = answer in ("y", "yes")
        log_event(run_id, "HUMAN", DECISION_EVENT[kind], kind=kind, prompt=message,
                  decision="approved" if approved else "rejected", approver_name=name)
        return ElicitResult(action="accept", content={"approve": approved, "approver_name": name})
    return human_approval


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
def build_team(model: OpenAIResponsesModel | OpenAIChatModel, mcp: MCPToolset) -> Agent[TeamDeps, str]:
    settings = build_model_settings()

    def make(name: str) -> Agent[TeamDeps, str]:
        return Agent(
            model,
            name=name,
            deps_type=TeamDeps,
            instructions=(PROMPTS_DIR / f"{name}.md").read_text(),
            toolsets=[AuditedToolset(wrapped=mcp, agent_name=name, allowed=frozenset(AGENT_TOOLS[name]))],
            model_settings=settings,
            retries=AGENT_RETRIES,
        )

    boss = make("boss")
    specialists = {n: make(n) for n in ("inventory", "accounting", "facilities", "customer_service")}

    async def delegate(ctx: RunContext[TeamDeps], who: str, task: str) -> str:
        deps = ctx.deps
        if deps.delegations >= MAX_DELEGATIONS:
            log_event(deps.run_id, "boss", "delegation_refused", to=who, task=task,
                      reason=f"MAX_DELEGATIONS ({MAX_DELEGATIONS}) reached")
            return (f"Delegation limit of {MAX_DELEGATIONS} reached for this run. "
                    "Finish with what you have and report anything unresolved to the human.")
        deps.delegations += 1
        log_event(deps.run_id, "boss", "delegate", to=who, task=task, delegation_number=deps.delegations)
        # usage=ctx.usage makes the specialist's tokens count toward the same run limits.
        result = await specialists[who].run(task, deps=deps, usage=ctx.usage, usage_limits=RUN_LIMITS)
        log_event(deps.run_id, who, "answer_to_boss", answer=result.output)
        return result.output

    @boss.tool
    async def ask_inventory(ctx: RunContext[TeamDeps], task: str) -> str:
        """Send a task to Inventory (stock, shortfall, cost/margin, vendor block, draft restock).
        Include the ticket id and exact sku, size, qty, and invoice_id."""
        return await delegate(ctx, "inventory", task)

    @boss.tool
    async def ask_accounting(ctx: RunContext[TeamDeps], task: str) -> str:
        """Send a task to Accounting (invoices, checking balance, payment requests that need
        human approval). Include the ticket id and exact invoice_id or lease_id and amount."""
        return await delegate(ctx, "accounting", task)

    @boss.tool
    async def ask_facilities(ctx: RunContext[TeamDeps], task: str) -> str:
        """Send a task to Facilities (lease, rent amount, due date, urgency). Include the
        ticket id and lease_id."""
        return await delegate(ctx, "facilities", task)

    @boss.tool
    async def ask_customer_service(ctx: RunContext[TeamDeps], task: str) -> str:
        """Send a task to Customer Service to draft (never send) a customer reply. Include the
        ticket id and every confirmed fact the reply may use."""
        return await delegate(ctx, "customer_service", task)

    return boss


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
BOSS_TASK = (
    "Resolve every open Campus Customs ticket. Start with list_open_tickets, delegate to the "
    "right specialists, plan payments across all tickets before any are requested, set each "
    "ticket's status, and finish with the final report described in your instructions."
)


def boss_task_for(ticket_id: int | None, scope: dict | None = None) -> str:
    if ticket_id is None:
        return BOSS_TASK
    scope = scope or {}
    if scope.get("invoice_id") is not None:
        obligation = f"invoice {scope['invoice_id']}"
    elif scope.get("lease_id") is not None:
        obligation = f"the rent on lease {scope['lease_id']}"
    else:
        obligation = None
    if obligation:
        cash_rule = (
            f"Cash planning for this run covers only ticket {ticket_id}'s own linked obligation: "
            f"{obligation}. Other tickets' cash needs are outside this run; you may mention them "
            f"in your report, but they must not stop this ticket. If {obligation} is open or due "
            "and Accounting confirms the checking balance covers it, ask Accounting to request "
            "the payment with request_payment. A human then approves or rejects it at the "
            "approval prompt; that decision is final. "
        )
    else:
        cash_rule = (f"Ticket {ticket_id} links no invoice or lease, so no payment is expected "
                     "in this run. ")
    return (
        f"This run covers ONLY ticket {ticket_id}. Start with list_open_tickets and work only on "
        f"ticket {ticket_id}: delegate to the specialists that ticket needs, set its status, and "
        f"finish with the final report for ticket {ticket_id} described in your instructions. "
        + cash_rule
        + "Take no actions (payments, restocks, drafts, or status changes) for any other ticket."
    )


def new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def reset_database(run_id: str) -> None:
    """Copy the original database over the working copy (fresh start)."""
    shutil.copyfile(ORIGINAL_DB, WORKING_DB)
    log_event(run_id, "SYSTEM", "database_reset", source=ORIGINAL_DB.name, target=WORKING_DB.name)


async def run_team(*, ticket_id: int | None = None, approval_factory: ApprovalFactory = terminal_approval,
                   reset: bool = False, run_id: str | None = None) -> dict:
    """Run the agent team on every open ticket (ticket_id=None) or on ONE ticket.

    Returns a summary dict. Everything that happens is appended to the audit trail.
    """
    run_id = run_id or new_run_id()
    scope = load_ticket_scope(ticket_id) if ticket_id is not None else None
    model = build_model()  # fails early (before any reset) if the API key is missing

    if reset:
        reset_database(run_id)

    mcp = MCPToolset(
        StdioTransport(command=sys.executable, args=[str(PROJECT_ROOT / "mcp_server" / "server.py")],
                       cwd=str(PROJECT_ROOT)),
        elicitation_handler=approval_factory(run_id),
        read_timeout=APPROVAL_WAIT_SECONDS,
    )
    boss = build_team(model, mcp)
    deps = TeamDeps(run_id=run_id, scope=scope)
    task = boss_task_for(ticket_id, scope)
    log_event(run_id, "SYSTEM", "run_start", model=MODEL_NAME, api=model_api(), ticket_id=ticket_id,
              reasoning_effort=build_model_settings()["openai_reasoning_effort"], limits={
        "request_limit": RUN_LIMITS.request_limit, "tool_calls_limit": RUN_LIMITS.tool_calls_limit,
        "total_tokens_limit": RUN_LIMITS.total_tokens_limit, "max_output_tokens": MAX_OUTPUT_TOKENS,
        "max_delegations": MAX_DELEGATIONS})
    log_event(run_id, "boss", "task", task=task)

    try:
        async with mcp:  # one MCP server process shared by all five agents
            exposed = sorted(t.name for t in await mcp.list_tools())
            log_event(run_id, "SYSTEM", "tools_available", mcp_server_tools=exposed,
                      agents={name: sorted(tools & set(exposed)) for name, tools in AGENT_TOOLS.items()},
                      boss_delegation_tools=["ask_accounting", "ask_customer_service",
                                             "ask_facilities", "ask_inventory"],
                      missing_from_server={name: sorted(tools - set(exposed))
                                           for name, tools in AGENT_TOOLS.items() if tools - set(exposed)})
            result = await boss.run(task, deps=deps, usage_limits=RUN_LIMITS)
    except UsageLimitExceeded as exc:
        log_event(run_id, "SYSTEM", "run_stopped", reason=f"usage limit hit: {exc}")
        return {"run_id": run_id, "ticket_id": ticket_id, "status": "stopped",
                "reason": f"usage limit hit: {exc}", "delegations": deps.delegations}
    except Exception as exc:
        log_event(run_id, "SYSTEM", "run_error", error=f"{type(exc).__name__}: {exc}")
        raise

    usage = result.usage  # a property (not a method) in this PydanticAI version
    usage_dict = {"requests": usage.requests, "tool_calls": usage.tool_calls,
                  "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}
    log_event(run_id, "boss", "final_report", report=result.output)
    log_event(run_id, "SYSTEM", "run_end", delegations=deps.delegations, usage=usage_dict)
    return {"run_id": run_id, "ticket_id": ticket_id, "status": "finished", "final_report": result.output,
            "delegations": deps.delegations, "usage": usage_dict}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Campus Customs agent team.")
    parser.add_argument("--ticket", type=int, help="run only this ticket id (default: all open tickets)")
    parser.add_argument("--no-reset", action="store_true", help="full run: don't reset the database first")
    parser.add_argument("--reset", action="store_true", help="one-ticket run: reset the database first")
    args = parser.parse_args()
    reset = args.reset if args.ticket is not None else not args.no_reset

    try:
        summary = await run_team(ticket_id=args.ticket, reset=reset)
    except (RuntimeError, ValueError) as exc:
        sys.exit(str(exc))
    if summary["status"] == "stopped":
        print(f"\nRun stopped by a safety limit: {summary['reason']}")
        return
    print("\n" + summary["final_report"])
    print(f"\nAudit trail: {AUDIT_PATH.relative_to(PROJECT_ROOT)} (run_id {summary['run_id']})")


if __name__ == "__main__":
    asyncio.run(main())
