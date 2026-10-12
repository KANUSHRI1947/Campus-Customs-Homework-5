"""Campus Customs MCP server.

Exposes tools over data/campus_customs_new.db so the shop's agents can look up
the facts they need to resolve tickets 101, 102, and 103, and take the few
actions they are allowed to take.

Problem 3 tools (read-only lookups):
  get_invoice_and_vendor_block_status, get_lease_rent_due_and_cash_coverage,
  get_stock_and_margin_for_bulk_order
Problem 5 tools (agent team):
  list_open_tickets, update_ticket_status, request_payment (human approval
  required), request_vendor_restock (draft only), draft_customer_message
  (draft only, never sent), get_checking_balance (read-only),
  request_discount_decision (human decides a price; never moves cash or edits pricing)

Every value returned comes straight from the database or is simple arithmetic
on stored values (days between dates, shortfall, margin). Nothing is invented.

Run with:  .venv/bin/python mcp_server/server.py
"""

import calendar
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "campus_customs_new.db"
RESTOCK_DRAFTS_DIR = PROJECT_ROOT / "output" / "restock_requests"
CUSTOMER_DRAFTS_DIR = PROJECT_ROOT / "output" / "customer_drafts"

mcp = FastMCP("campus-customs")


def _connect() -> sqlite3.Connection:
    """Open the working database read-only (these tools never change data)."""
    if not DB_PATH.exists():
        raise ToolError(f"Database not found at {DB_PATH}.")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _connect_rw() -> sqlite3.Connection:
    """Open the working database for writing. Only the Problem 5 action tools
    (update_ticket_status, request_payment) use this."""
    if not DB_PATH.exists():
        raise ToolError(f"Database not found at {DB_PATH}.")
    conn = sqlite3.connect(DB_PATH, isolation_level=None)  # we manage transactions
    conn.row_factory = sqlite3.Row
    return conn


def _today(conn: sqlite3.Connection) -> date:
    """The shop's current date is desk.date_today, not the computer clock."""
    row = conn.execute("SELECT date_today FROM desk").fetchone()
    if row is None:
        raise ToolError("The desk table has no date_today; cannot judge what is overdue.")
    return date.fromisoformat(row["date_today"])


@mcp.tool()
def get_invoice_and_vendor_block_status(invoice_id: int) -> dict:
    """Ticket 101: look up a vendor invoice, how overdue it is, and whether
    the vendor is blocked from shipping new product.

    A vendor may not ship new product while it has any open (unpaid) invoice.
    Pass the invoice_id stored on the ticket (ticket 101 uses invoice 501).
    """
    with _connect() as conn:
        today = _today(conn)
        invoice = conn.execute(
            "SELECT id, vendor_id, amount, due_date, status, description FROM invoices WHERE id = ?",
            (invoice_id,),
        ).fetchone()
        if invoice is None:
            raise ToolError(f"No invoice with id {invoice_id} exists.")

        vendor = conn.execute(
            "SELECT id, name, specialty, lead_days FROM vendors WHERE id = ?",
            (invoice["vendor_id"],),
        ).fetchone()
        if vendor is None:
            raise ToolError(f"Invoice {invoice_id} points to vendor {invoice['vendor_id']}, which does not exist.")

        open_invoices = conn.execute(
            "SELECT id, amount, due_date FROM invoices WHERE vendor_id = ? AND status = 'open' ORDER BY id",
            (vendor["id"],),
        ).fetchall()

    days_past_due = (today - date.fromisoformat(invoice["due_date"])).days
    return {
        "date_today": today.isoformat(),
        "invoice": {
            "id": invoice["id"],
            "amount": invoice["amount"],
            "due_date": invoice["due_date"],
            "status": invoice["status"],
            "description": invoice["description"],
            "is_overdue": invoice["status"] == "open" and days_past_due > 0,
            "days_overdue": max(days_past_due, 0) if invoice["status"] == "open" else 0,
        },
        "vendor": {
            "id": vendor["id"],
            "name": vendor["name"],
            "specialty": vendor["specialty"],
            "lead_days": vendor["lead_days"],
        },
        "vendor_blocked_from_shipping": len(open_invoices) > 0,
        "open_invoices_for_vendor": [dict(row) for row in open_invoices],
    }


@mcp.tool()
def get_lease_rent_due_and_cash_coverage(lease_id: int) -> dict:
    """Ticket 102: look up a lease's rent amount and due date, and whether the
    checking account can cover it.

    Pass the lease_id stored on the ticket (ticket 102 uses lease 1).
    This tool only reads; it does not pay anything.
    """
    with _connect() as conn:
        today = _today(conn)
        lease = conn.execute(
            "SELECT id, space_name, landlord, monthly_rent, next_due, notes FROM leases WHERE id = ?",
            (lease_id,),
        ).fetchone()
        if lease is None:
            raise ToolError(f"No lease with id {lease_id} exists.")

        account = conn.execute(
            "SELECT name, balance, date FROM cash_accounts WHERE name = 'checking'"
        ).fetchone()
        if account is None:
            raise ToolError("No 'checking' account exists in cash_accounts.")

    days_until_due = (date.fromisoformat(lease["next_due"]) - today).days
    rent = lease["monthly_rent"]
    balance = account["balance"]
    return {
        "date_today": today.isoformat(),
        "lease": {
            "id": lease["id"],
            "space_name": lease["space_name"],
            "landlord": lease["landlord"],
            "monthly_rent": rent,
            "next_due": lease["next_due"],
            "notes": lease["notes"],
            "days_until_due": max(days_until_due, 0),
            "is_overdue": days_until_due < 0,
            "days_overdue": max(-days_until_due, 0),
        },
        "cash_account": {
            "name": account["name"],
            "balance": balance,
            "as_of": account["date"],
        },
        "cash_covers_rent": balance >= rent,
        "balance_after_rent_if_paid": round(balance - rent, 2) if balance >= rent else None,
        "shortfall": round(rent - balance, 2) if balance < rent else 0,
    }


@mcp.tool()
def get_stock_and_margin_for_bulk_order(sku: str, size: str, qty: int) -> dict:
    """Ticket 103: check whether a bulk order can be filled from stock and how
    much margin there is to discount from.

    Pass the sku, size, and qty stored on the ticket
    (ticket 103 uses CC-HOOD-NAVY, M, 20).
    """
    sku = sku.strip()
    size = size.strip()
    if not sku or not size:
        raise ToolError("Both sku and size are required.")
    if qty <= 0:
        raise ToolError(f"qty must be a positive whole number; got {qty}.")

    with _connect() as conn:
        item = conn.execute(
            "SELECT sku, name, size, qty, location FROM inventory WHERE sku = ? AND size = ?",
            (sku, size),
        ).fetchone()
        if item is None:
            sizes = [r["size"] for r in conn.execute("SELECT size FROM inventory WHERE sku = ?", (sku,))]
            if sizes:
                raise ToolError(f"SKU {sku} has no size {size!r}. Sizes on file: {', '.join(sizes)}.")
            raise ToolError(f"No inventory item with SKU {sku!r} exists.")

        price = conn.execute(
            "SELECT unit_cost, list_price FROM pricing WHERE sku = ?", (sku,)
        ).fetchone()
        if price is None:
            raise ToolError(f"SKU {sku} has no row in the pricing table.")

    on_hand = item["qty"]
    unit_cost = price["unit_cost"]
    list_price = price["list_price"]
    margin = round(list_price - unit_cost, 2)
    return {
        "item": {
            "sku": item["sku"],
            "name": item["name"],
            "size": item["size"],
            "location": item["location"],
        },
        "stock": {
            "requested_qty": qty,
            "on_hand_qty": on_hand,
            "can_fill_from_stock": on_hand >= qty,
            "shortfall_qty": max(qty - on_hand, 0),
        },
        "pricing": {
            "unit_cost": unit_cost,
            "list_price": list_price,
            "margin_per_unit": margin,
            "margin_percent_of_list": round(margin / list_price * 100, 1) if list_price else None,
            "break_even_price_per_unit": unit_cost,
            "order_total_at_list_price": round(list_price * qty, 2),
            "order_total_at_cost": round(unit_cost * qty, 2),
        },
    }


# ---------------------------------------------------------------------------
# Problem 5 tools
# ---------------------------------------------------------------------------

OPEN_STATUSES = ("open", "waiting")
STATUS_CHOICES = ("resolved", "waiting")
CUSTOMER_TICKET_TYPES = ("customer_order", "price_override")


def _open_invoices_for_vendor(conn: sqlite3.Connection, vendor_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, amount, due_date FROM invoices WHERE vendor_id = ? AND status = 'open' ORDER BY id",
        (vendor_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _add_one_month(d: date) -> date:
    """Same day next month, clamped to the last day of that month."""
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


@mcp.tool()
def list_open_tickets() -> dict:
    """Boss: list every ticket that still needs work (status 'open' or
    'waiting'), with all of its linked fields.

    Call this first. Work only from the tickets it returns. Each ticket's
    sku/size/qty, lease_id, and invoice_id are the exact values to pass to
    the specialists' lookup tools.
    """
    with _connect() as conn:
        today = _today(conn)
        rows = conn.execute(
            "SELECT id, type, requester, subject, sku, size, qty, lease_id, invoice_id, "
            "status, notes, created_at FROM tickets WHERE status IN (?, ?) ORDER BY id",
            OPEN_STATUSES,
        ).fetchall()
    return {
        "date_today": today.isoformat(),
        "open_ticket_count": len(rows),
        "tickets": [dict(r) for r in rows],
    }


@mcp.tool()
def update_ticket_status(ticket_id: int, status: str, note: str) -> dict:
    """Boss only: set a ticket to 'resolved' or 'waiting' and record a short,
    factual note of what was done.

    Use 'resolved' only when the outcome is final. Use 'waiting' when the
    ticket depends on something that hasn't happened yet (a future restock
    arrival, a payment a human rejected). The note is appended to the
    ticket's existing notes; the original request text is never overwritten.
    """
    status = status.strip().lower()
    note = note.strip()
    if status not in STATUS_CHOICES:
        raise ToolError(f"status must be one of {', '.join(STATUS_CHOICES)}; got {status!r}.")
    if not note:
        raise ToolError("A short note explaining what was done is required.")

    conn = _connect_rw()
    try:
        conn.execute("BEGIN IMMEDIATE")
        today = _today(conn)
        ticket = conn.execute("SELECT id, status, notes FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if ticket is None:
            raise ToolError(f"No ticket with id {ticket_id} exists.")
        if ticket["status"] == "resolved":
            raise ToolError(f"Ticket {ticket_id} is already resolved; it cannot be changed.")
        entry = f"[{today.isoformat()} {status}] {note}"
        new_notes = f"{ticket['notes']} | {entry}" if ticket["notes"] else entry
        conn.execute("UPDATE tickets SET status = ?, notes = ? WHERE id = ?", (status, new_notes, ticket_id))
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    return {
        "ticket_id": ticket_id,
        "previous_status": ticket["status"],
        "new_status": status,
        "notes": new_notes,
    }


class PaymentApproval(BaseModel):
    """What the human fills in at the approval prompt."""

    approve: bool = Field(description="True to approve this payment, False to reject it.")
    approver_name: str = Field(description="Name of the person approving or rejecting.")


@mcp.tool()
async def request_payment(kind: str, ref_id: int, amount: float, ctx: Context) -> dict:
    """Accounting only: ask a HUMAN to approve paying a vendor invoice or the
    rent, and record the payment only if they approve.

    kind:   'invoice' (ref_id = invoices.id) or 'rent' (ref_id = leases.id)
    amount: must exactly match the database (invoice amount or monthly_rent).

    Before asking, the tool checks the facts and REFUSES (nothing changes) if
    the invoice/lease doesn't exist, the amount doesn't match, the invoice is
    already paid, the rent isn't due yet, or checking can't cover it (cash can
    never go negative). Then it pauses and asks the human. If approved, it adds
    a row to payments, lowers checking, and marks the invoice paid or moves the
    lease's next_due forward one month. If rejected, nothing changes.

    Returns result = 'paid', 'rejected', or 'refused' with the reason.
    """
    kind = kind.strip().lower()
    if kind not in ("invoice", "rent"):
        raise ToolError(f"kind must be 'invoice' or 'rent'; got {kind!r}.")
    amount = round(float(amount), 2)

    def refused(reason: str, **extra) -> dict:
        return {"result": "refused", "kind": kind, "ref_id": ref_id, "amount": amount,
                "reason": reason, "database_changed": False, **extra}

    def check(conn: sqlite3.Connection) -> tuple[dict | None, str]:
        """Return (refusal, description). refusal is None if the payment may proceed."""
        today = _today(conn)
        acct = conn.execute("SELECT balance FROM cash_accounts WHERE name = 'checking'").fetchone()
        if acct is None:
            return refused("No 'checking' account exists in cash_accounts."), ""
        balance = acct["balance"]
        if kind == "invoice":
            inv = conn.execute(
                "SELECT i.amount, i.status, i.due_date, i.description, v.name AS vendor "
                "FROM invoices i JOIN vendors v ON v.id = i.vendor_id WHERE i.id = ?", (ref_id,)
            ).fetchone()
            if inv is None:
                return refused(f"No invoice with id {ref_id} exists."), ""
            if inv["status"] != "open":
                return refused(f"Invoice {ref_id} is already {inv['status']}; it will not be paid twice."), ""
            if amount != round(inv["amount"], 2):
                return refused(f"Amount ${amount:,.2f} does not match invoice {ref_id}'s amount of ${inv['amount']:,.2f}."), ""
            desc = f"invoice #{ref_id} to {inv['vendor']} ({inv['description']}), due {inv['due_date']}"
        else:
            lease = conn.execute(
                "SELECT space_name, landlord, monthly_rent, next_due FROM leases WHERE id = ?", (ref_id,)
            ).fetchone()
            if lease is None:
                return refused(f"No lease with id {ref_id} exists."), ""
            if amount != round(lease["monthly_rent"], 2):
                return refused(f"Amount ${amount:,.2f} does not match lease {ref_id}'s monthly rent of ${lease['monthly_rent']:,.2f}."), ""
            next_due = date.fromisoformat(lease["next_due"])
            if (next_due - today).days > 31:
                return refused(f"Rent for lease {ref_id} is not due yet (next due {lease['next_due']}); "
                               "the current period appears to be paid already."), ""
            desc = f"rent for {lease['space_name']} to {lease['landlord']}, due {lease['next_due']}"
        if balance < amount:
            return refused(f"Insufficient cash: checking has ${balance:,.2f} but the payment is ${amount:,.2f} "
                           f"(short ${amount - balance:,.2f}). Cash can never go negative.",
                           checking_balance=balance), ""
        return None, desc + f". Checking now ${balance:,.2f}; after payment ${balance - amount:,.2f}"

    # 1) Check the facts before bothering the human.
    with _connect() as conn:
        refusal, description = check(conn)
    if refusal:
        return refusal

    # 2) Ask the human. No approval (or no way to ask) means no payment.
    try:
        answer = await ctx.elicit(
            message=f"PAYMENT APPROVAL NEEDED: pay ${amount:,.2f} for {description}. Approve?",
            schema=PaymentApproval,
        )
    except Exception as exc:  # client can't show an approval prompt
        return refused(f"Could not reach a human for approval ({exc}). Payments require human approval.")

    approver = answer.data.approver_name.strip() if answer.action == "accept" else ""
    if answer.action != "accept" or not answer.data.approve:
        return {"result": "rejected", "kind": kind, "ref_id": ref_id, "amount": amount,
                "reason": f"Human {'rejected' if answer.action == 'accept' else {'decline': 'declined', 'cancel': 'cancelled'}.get(answer.action, answer.action)} the payment"
                          + (f" ({approver})" if approver else "") + ".",
                "database_changed": False}
    if not approver:
        return refused("Approval was given without an approver name; payments must record who approved them.")

    # 3) Record it atomically, re-checking in case anything changed while waiting.
    conn = _connect_rw()
    try:
        conn.execute("BEGIN IMMEDIATE")
        refusal, _ = check(conn)
        if refusal:
            conn.execute("ROLLBACK")
            return refusal
        today = _today(conn)
        before = conn.execute("SELECT balance FROM cash_accounts WHERE name = 'checking'").fetchone()["balance"]
        after = round(before - amount, 2)
        conn.execute("UPDATE cash_accounts SET balance = ?, date = ? WHERE name = 'checking'",
                     (after, today.isoformat()))
        cur = conn.execute(
            "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) VALUES (?, ?, ?, 'checking', ?, ?)",
            (kind, ref_id, amount, today.isoformat(), approver),
        )
        payment_id = cur.lastrowid
        extra: dict = {}
        if kind == "invoice":
            conn.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (ref_id,))
            vendor_id = conn.execute("SELECT vendor_id FROM invoices WHERE id = ?", (ref_id,)).fetchone()["vendor_id"]
            still_open = _open_invoices_for_vendor(conn, vendor_id)
            extra = {"invoice_status": "paid", "vendor_id": vendor_id,
                     "vendor_blocked_from_shipping": len(still_open) > 0}
        else:
            old_due = conn.execute("SELECT next_due FROM leases WHERE id = ?", (ref_id,)).fetchone()["next_due"]
            new_due = _add_one_month(date.fromisoformat(old_due)).isoformat()
            conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (new_due, ref_id))
            extra = {"lease_previous_due": old_due, "lease_next_due": new_due}
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    return {"result": "paid", "payment_id": payment_id, "kind": kind, "ref_id": ref_id,
            "amount": amount, "approved_by": approver, "paid_at": today.isoformat(),
            "checking_balance_before": before, "checking_balance_after": after,
            "database_changed": True, **extra}


@mcp.tool()
def request_vendor_restock(vendor_id: int, sku: str, size: str, qty: int) -> dict:
    """Inventory only: save a DRAFT restock order to a vendor. Nothing is sent
    and no vendor is contacted; inventory counts do not change.

    REFUSES if the vendor has any open (unpaid) invoice, because a blocked
    vendor may not ship new product. Expected arrival is desk.date_today plus
    the vendor's lead_days. The draft is saved under output/restock_requests/.
    Use the vendor shown by get_invoice_and_vendor_block_status; the database
    has no sku-to-vendor table, so never guess a vendor.
    """
    sku, size = sku.strip(), size.strip()
    if qty <= 0:
        raise ToolError(f"qty must be a positive whole number; got {qty}.")
    with _connect() as conn:
        today = _today(conn)
        vendor = conn.execute("SELECT id, name, specialty, lead_days FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if vendor is None:
            raise ToolError(f"No vendor with id {vendor_id} exists.")
        item = conn.execute("SELECT name, qty FROM inventory WHERE sku = ? AND size = ?", (sku, size)).fetchone()
        if item is None:
            raise ToolError(f"No inventory item with SKU {sku!r} in size {size!r} exists.")
        open_invoices = _open_invoices_for_vendor(conn, vendor_id)

    if open_invoices:
        ids = ", ".join(f"#{i['id']} (${i['amount']:,.2f}, due {i['due_date']})" for i in open_invoices)
        return {"result": "refused", "vendor": dict(vendor), "sku": sku, "size": size, "qty": qty,
                "reason": f"{vendor['name']} is blocked from shipping because of open invoice(s) {ids}. "
                          "Pay the invoice first (Accounting, with human approval).",
                "open_invoices_for_vendor": open_invoices, "draft_saved": False}

    arrival = today + timedelta(days=vendor["lead_days"])
    draft = {
        "status": "DRAFT - not sent",
        "created_on": today.isoformat(),
        "vendor": dict(vendor),
        "sku": sku, "size": size, "item_name": item["name"], "qty": qty,
        "on_hand_qty_at_request": item["qty"],
        "expected_arrival": arrival.isoformat(),
    }
    RESTOCK_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESTOCK_DRAFTS_DIR / f"vendor{vendor_id}_{sku}_{size}.json"
    path.write_text(json.dumps(draft, indent=2))
    return {"result": "draft_saved", **draft, "draft_file": str(path.relative_to(PROJECT_ROOT)),
            "sent_to_vendor": False}


@mcp.tool()
def draft_customer_message(ticket_id: int, message: str) -> dict:
    """Customer Service only: save a DRAFT reply to the customer on a ticket.
    Nothing is emailed or sent; a human reviews the draft.

    The greeting uses the requester's name exactly as stored on the ticket, so
    write the message body only. Works for customer tickets (customer_order,
    price_override). Saved as output/customer_drafts/ticket_<id>.md; a new
    draft for the same ticket replaces the old one.
    """
    message = message.strip()
    if not message:
        raise ToolError("The message body is empty.")
    with _connect() as conn:
        ticket = conn.execute("SELECT id, type, requester, subject FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if ticket is None:
        raise ToolError(f"No ticket with id {ticket_id} exists.")
    if ticket["type"] not in CUSTOMER_TICKET_TYPES:
        raise ToolError(f"Ticket {ticket_id} is a {ticket['type']} ticket from {ticket['requester']}, not a "
                        "customer ticket; Customer Service does not draft a reply for it.")

    text = (f"<!-- DRAFT - NOT SENT. Ticket {ticket_id}: {ticket['subject']} -->\n\n"
            f"Hi {ticket['requester']},\n\n{message}\n")
    CUSTOMER_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    path = CUSTOMER_DRAFTS_DIR / f"ticket_{ticket_id}.md"
    path.write_text(text)
    return {"result": "draft_saved", "ticket_id": ticket_id, "requester": ticket["requester"],
            "draft_file": str(path.relative_to(PROJECT_ROOT)), "draft_text": text, "sent": False}


@mcp.tool()
def get_checking_balance() -> dict:
    """Accounting: the current checking balance (cash_accounts 'checking') and the
    shop date. Read-only.

    Use it to confirm the cash covers a payment before calling request_payment, for
    ANY ticket: an invoice ticket like 101 has no lease_id, so the rent lookup can't
    be used there. request_payment still re-checks the cash and still needs a human.
    """
    with _connect() as conn:
        today = _today(conn)
        acct = conn.execute("SELECT name, balance, date FROM cash_accounts WHERE name = 'checking'").fetchone()
    if acct is None:
        raise ToolError("No 'checking' account exists in cash_accounts.")
    return {"date_today": today.isoformat(), "account": acct["name"], "balance": acct["balance"],
            "as_of": acct["date"]}


class DiscountDecision(BaseModel):
    """What the human fills in at the discount-decision prompt (same shape as a payment
    approval so the same approval channel works, but it is NOT a payment)."""

    approve: bool = Field(description="True to approve this per-unit price, False to reject it (list price stands).")
    approver_name: str = Field(description="Name of the person deciding.")


DISCOUNT_PROMPT_PREFIX = "DISCOUNT DECISION NEEDED (not a payment; no cash moves)"


@mcp.tool()
async def request_discount_decision(ticket_id: int, unit_price: float, ctx: Context) -> dict:
    """Boss only: ask a HUMAN to approve or reject a specific per-unit price for a
    price_override ticket (e.g. ticket 103's bulk hoodie request).

    unit_price must be between the item's unit_cost and list_price (inclusive),
    from the pricing table. The tool REFUSES (nothing changes) for any other ticket
    type, an out-of-range price, a resolved ticket, or a ticket that already has a
    recorded decision. Otherwise it pauses for the human. The decision and the
    human's name are appended to the ticket's notes. It NEVER moves cash and NEVER
    changes the pricing table (the catalogue list price stays the same).

    Returns result = 'approved', 'rejected', 'no_decision', or 'refused'.
    """
    price = round(float(unit_price), 2)

    def refused(reason: str) -> dict:
        return {"result": "refused", "ticket_id": ticket_id, "unit_price": price, "reason": reason,
                "cash_changed": False, "catalogue_price_changed": False}

    with _connect() as conn:
        ticket = conn.execute("SELECT id, type, requester, sku, size, qty, status, notes FROM tickets WHERE id = ?",
                              (ticket_id,)).fetchone()
        if ticket is None:
            return refused(f"No ticket with id {ticket_id} exists.")
        if ticket["type"] != "price_override":
            return refused(f"Ticket {ticket_id} is a {ticket['type']} ticket; discount decisions are only for price_override tickets.")
        if ticket["status"] == "resolved":
            return refused(f"Ticket {ticket_id} is already resolved.")
        if "discount decision]" in (ticket["notes"] or ""):
            return refused(f"Ticket {ticket_id} already has a recorded human discount decision; it is final.")
        pricing = conn.execute("SELECT unit_cost, list_price FROM pricing WHERE sku = ?", (ticket["sku"],)).fetchone()
        if pricing is None:
            return refused(f"SKU {ticket['sku']} has no row in the pricing table.")
    cost, list_price, qty = pricing["unit_cost"], pricing["list_price"], ticket["qty"] or 0
    if not (round(cost, 2) <= price <= round(list_price, 2)):
        return refused(f"${price:,.2f} is outside the allowed range: unit cost ${cost:,.2f} to list price ${list_price:,.2f}.")

    message = (f"{DISCOUNT_PROMPT_PREFIX}: ticket {ticket_id} ({ticket['requester']}), {qty} x {ticket['sku']} "
               f"size {ticket['size']}. Boss recommends ${price:,.2f} per unit (list ${list_price:,.2f}, "
               f"cost ${cost:,.2f}, margin ${price - cost:,.2f} per unit). Order total ${price * qty:,.2f} "
               f"vs ${list_price * qty:,.2f} at list. The catalogue price will not change. Approve this price?")
    try:
        answer = await ctx.elicit(message=message, schema=DiscountDecision)
    except Exception as exc:
        return refused(f"Could not reach a human for the decision ({exc}). Discounts require a human decision.")

    base = {"ticket_id": ticket_id, "sku": ticket["sku"], "size": ticket["size"], "qty": qty,
            "recommended_unit_price": price, "unit_cost": cost, "list_price": list_price,
            "cash_changed": False, "catalogue_price_changed": False}
    if answer.action != "accept":
        return {**base, "result": "no_decision", "reason": f"Human {'declined' if answer.action == 'decline' else 'cancelled'} the prompt; nothing recorded."}
    approver = answer.data.approver_name.strip()
    if not approver:
        return {**base, "result": "no_decision", "reason": "No approver name was given; nothing recorded."}
    approved = bool(answer.data.approve)

    conn = _connect_rw()
    try:
        conn.execute("BEGIN IMMEDIATE")
        today = _today(conn)
        row = conn.execute("SELECT notes FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if "discount decision]" in (row["notes"] or ""):
            conn.execute("ROLLBACK")
            return refused(f"Ticket {ticket_id} already has a recorded human discount decision; it is final.")
        if approved:
            entry = (f"[{today.isoformat()} discount decision] APPROVED ${price:,.2f}/unit for {qty} x {ticket['sku']} "
                     f"size {ticket['size']} by {approver} (list ${list_price:,.2f}, cost ${cost:,.2f}); catalogue price unchanged.")
        else:
            entry = (f"[{today.isoformat()} discount decision] REJECTED ${price:,.2f}/unit by {approver}; "
                     f"list price ${list_price:,.2f} stands.")
        notes = f"{row['notes']} | {entry}" if row["notes"] else entry
        conn.execute("UPDATE tickets SET notes = ? WHERE id = ?", (notes, ticket_id))
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    return {**base, "result": "approved" if approved else "rejected", "decided_by": approver,
            "final_unit_price": price if approved else list_price, "decided_on": today.isoformat(),
            "recorded_in": "tickets.notes"}


if __name__ == "__main__":
    mcp.run()
