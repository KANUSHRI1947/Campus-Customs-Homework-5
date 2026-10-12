# Campus Customs MCP Server

**What it's for:** This MCP server gives the Campus Customs agents one shared, safe way to use shop data. Agents never query the database directly. They call these tools, which return only what is stored in the database plus simple arithmetic, such as days overdue, shortfall or margin per unit.

**Code:** `mcp_server/server.py` (FastMCP, server name `campus-customs`)

**Database:** `data/campus_customs_new.db`. The original `data/campus_customs.db` is never touched and serves as the reset copy.

**Shop date:** every "overdue" or "due in N days" calculation uses `desk.date_today`, never the computer's clock.

## Quick facts

- **Start the server:** `.venv/bin/python mcp_server/server.py`, run from the Homework 5 folder. The vibe coder starts it automatically from `.mcp.json`, and `backend/team.py` starts it for the agent team.
- **Database:** `data/campus_customs_new.db`. Reset it by copying `data/campus_customs.db` over it.
- **Payments need human approval:** a payment succeeds only after a human approves it in `request_payment`. Rejected or refused payments change nothing.
- **Discounts need a human decision:** `request_discount_decision` only records a price a human approved or rejected. No cash moves and the catalogue price stays the same.
- **Customer messages are never sent:** `draft_customer_message` only saves a draft file, and `request_vendor_restock` only saves a draft order. Nobody is emailed or contacted.

## All 10 tools

Every parameter, table and rule below comes directly from the tool definitions in `mcp_server/server.py`.

| # | Tool | Parameters | Reads | Writes | Used by | Helps unlock |
|---|---|---|---|---|---|---|
| 1 | `get_invoice_and_vendor_block_status` | `invoice_id: int` | `invoices`, `vendors`, `desk` | none | Inventory, Accounting | Ticket 101 |
| 2 | `get_lease_rent_due_and_cash_coverage` | `lease_id: int` | `leases`, `cash_accounts`, `desk` | none | Accounting, Facilities | Ticket 102 |
| 3 | `get_stock_and_margin_for_bulk_order` | `sku: str`, `size: str`, `qty: int` | `inventory`, `pricing` | none | Inventory, Customer Service | Ticket 103 |
| 4 | `list_open_tickets` | none | `tickets`, `desk` | none | Boss | Tickets 101, 102, 103 |
| 5 | `update_ticket_status` | `ticket_id: int`, `status: str`, `note: str` | `tickets`, `desk` | `tickets` | Boss | Tickets 101, 102, 103 |
| 6 | `request_payment` | `kind: str`, `ref_id: int`, `amount: float` | `invoices`, `vendors`, `leases`, `cash_accounts`, `desk` | `payments`, `cash_accounts`, `invoices` or `leases` (only after human approval) | Accounting | Tickets 101 and 102 |
| 7 | `request_vendor_restock` | `vendor_id: int`, `sku: str`, `size: str`, `qty: int` | `vendors`, `invoices`, `inventory`, `desk` | none (saves a draft file in `output/restock_requests/`) | Inventory | Ticket 101 |
| 8 | `draft_customer_message` | `ticket_id: int`, `message: str` | `tickets` | none (saves a draft file in `output/customer_drafts/`) | Customer Service | Tickets 101 and 103 |
| 9 | `get_checking_balance` | none | `cash_accounts`, `desk` | none | Accounting | Ticket 101 (and any payment) |
| 10 | `request_discount_decision` | `ticket_id: int`, `unit_price: float` | `tickets`, `pricing`, `desk` | `tickets.notes` only (after a human decides) | Boss | Ticket 103 |

## What each tool does

### Lookup tools (Problem 3, read-only)

1. **`get_invoice_and_vendor_block_status(invoice_id)`** returns the invoice's amount, due date, status, description, whether it is overdue and by how many days, the vendor's name, specialty and `lead_days`, and whether the vendor is blocked from shipping. A vendor is blocked while it has any open invoice. For ticket 101, it shows that invoice #501 ($840, Bulldog Print Co) blocks the size S tee reprint.
2. **`get_lease_rent_due_and_cash_coverage(lease_id)`** returns the lease's rent, `next_due`, days until due or overdue, the checking balance, whether checking covers the rent, and the balance after paying it or the shortfall. It never pays anything. For ticket 102, it covers lease 1: $2,400 due 2026-09-02, with $3,400 in checking.
3. **`get_stock_and_margin_for_bulk_order(sku, size, qty)`** returns the stock on hand, whether the order can be filled from stock and the shortfall, plus `unit_cost`, `list_price`, margin per unit and percent, the break-even price, and the order total at list price and at cost. For ticket 103, it covers CC-HOOD-NAVY, size M, qty 20.

### Agent-team tools (Problem 5)

4. **`list_open_tickets()`** returns `date_today` and every ticket with status `open` or `waiting`, with all of its fields (`sku`, `size`, `qty`, `lease_id`, `invoice_id`, and so on). The Boss calls this first.
5. **`update_ticket_status(ticket_id, status, note)`** sets a ticket to `resolved` or `waiting`. It appends a dated note to the ticket's existing notes, so the original request text is never overwritten. It refuses any other status, an empty note, an unknown ticket, or a ticket that is already resolved.
6. **`request_payment(kind, ref_id, amount)`** handles `kind`, which is `invoice` (`ref_id` = `invoices.id`) or `rent` (`ref_id` = `leases.id`). Before asking anyone, it refuses if:
   - the invoice or lease doesn't exist
   - the amount doesn't exactly match the database
   - the invoice is already paid
   - the rent isn't due yet (next due date more than 31 days away)
   - checking can't cover the payment (cash can never go negative)

   Otherwise it pauses and asks a human to approve or reject, using MCP elicitation. If approved, it adds a `payments` row with the approver's name, lowers checking, and either marks the invoice `paid` or moves the lease's `next_due` forward one month. It re-checks everything before writing. It returns `paid`, `rejected` or `refused`. If no human can be asked, it refuses.
7. **`request_vendor_restock(vendor_id, sku, size, qty)`** saves a **draft** restock order with the expected arrival date (`desk.date_today` + the vendor's `lead_days`). It refuses while the vendor has any open invoice. It never contacts the vendor and never changes inventory counts. The database has no sku-to-vendor table, so the vendor must come from `get_invoice_and_vendor_block_status`.
8. **`draft_customer_message(ticket_id, message)`** saves a **draft** reply, greeting the requester by the name stored on the ticket. It works only for customer tickets (`customer_order`, `price_override`) and is never sent. A new draft for the same ticket replaces the old one.
9. **`get_checking_balance()`** returns the checking balance from `cash_accounts` and `desk.date_today`. It's read-only, and it lets Accounting confirm cash covers a payment on any ticket. It was added because ticket 101 links an invoice but no lease, so the rent lookup couldn't provide the balance when 101 ran on its own. `request_payment` still re-checks cash and still needs a human.
10. **`request_discount_decision(ticket_id, unit_price)`** lets a **human** decide a per-unit price the Boss recommends for a `price_override` ticket (ticket 103). It refuses for other ticket types, a price outside `unit_cost`–`list_price` ($22–$58 for CC-HOOD-NAVY), a resolved ticket, or a ticket that already has a decision. Otherwise it pauses for a human through the same approval channel as payments, but the prompt starts with "DISCOUNT DECISION NEEDED (not a payment; no cash moves)" and the dashboard labels it a DISCOUNT DECISION. The decision and the human's name are appended to the ticket's notes. It **never moves cash and never changes the `pricing` table**. Returns `approved`, `rejected` (list price stands), `no_decision`, or `refused`.

## Errors

Bad inputs return a clear error message instead of crashing the server. This covers an unknown invoice, lease, ticket, vendor, SKU or size, a quantity that isn't positive, and an invalid `status` or `kind`.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python mcp_server/server.py
```

The connection config for the vibe coder is in `.mcp.json` at the project root. The `mcp` package is pinned below 2 (`mcp<2`) because FastMCP was renamed in `mcp` 2.x and the assignment asks for FastMCP.
