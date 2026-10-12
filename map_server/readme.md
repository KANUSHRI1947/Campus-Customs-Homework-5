# Campus Customs MCP Server

**What it's for:** This MCP server gives the Campus Customs agents one shared, safe way to look up shop data. Agents don't query the database directly; they call these tools, which return only what is stored in the database (plus simple arithmetic like days overdue or margin per unit).

**Database:** `data/campus_customs_new.db`. Lookup tools open it read-only; only `update_ticket_status` and `request_payment` write to it. The original `data/campus_customs.db` is never touched and serves as the reset copy.

**Code location:** The server code lives in `mcp_server/server.py`. This README is at `map_server/readme.md` because that is the path the assignment specifies.

## Tools

| Tool | Parameters | Reads | Helps unlock |
|---|---|---|---|
| `get_invoice_and_vendor_block_status` | `invoice_id` | `invoices`, `vendors`, `desk` | Ticket 101: shows invoice #501 is overdue and that Bulldog Print Co can't ship the size S tee until it's paid |
| `get_lease_rent_due_and_cash_coverage` | `lease_id` | `leases`, `cash_accounts`, `desk` | Ticket 102: shows the $2,400 rent due date and whether checking can cover it |
| `get_stock_and_margin_for_bulk_order` | `sku`, `size`, `qty` | `inventory`, `pricing` | Ticket 103: shows stock on hand, shortfall, and margin available for a bulk discount |

### Problem 5 tools (agent team)

| Tool | Parameters | Reads / writes | Used by |
|---|---|---|---|
| `list_open_tickets` | none | reads `tickets`, `desk` | Boss: starts the run with every open or waiting ticket |
| `update_ticket_status` | `ticket_id`, `status` (`resolved`/`waiting`), `note` | writes `tickets` (note appended) | Boss: closes or parks a ticket |
| `request_payment` | `kind` (`invoice`/`rent`), `ref_id`, `amount` | reads `invoices`, `vendors`, `leases`, `cash_accounts`; writes `payments`, `cash_accounts`, `invoices`/`leases` | Accounting: asks a human to approve, pays only if approved |
| `request_vendor_restock` | `vendor_id`, `sku`, `size`, `qty` | reads `vendors`, `invoices`, `inventory`, `desk`; saves a draft in `output/restock_requests/` | Inventory: draft restock, refused while the vendor is blocked |
| `draft_customer_message` | `ticket_id`, `message` | reads `tickets`; saves a draft in `output/customer_drafts/` | Customer Service: draft reply, never sent |
| `get_checking_balance` | none | reads `cash_accounts`, `desk` | Accounting: confirms cash covers a payment on any ticket (read-only) |
| `request_discount_decision` | `ticket_id`, `unit_price` | reads `tickets`, `pricing`, `desk`; appends the human's decision to `tickets.notes` | Boss: a human approves or rejects a recommended price ($22–$58); no cash, no catalogue change |

`request_payment` refuses before asking anyone if the amount doesn't match the database, the invoice is already paid, the rent isn't due yet, or checking can't cover it, so cash never goes negative. It then pauses and asks a human through MCP elicitation. If the client can't show that prompt, the payment is refused.

Bad inputs (an unknown invoice, lease, SKU, or size, or a quantity that isn't positive) return a clear error message instead of crashing the server.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python mcp_server/server.py
```

The package version is pinned to `mcp<2` because FastMCP was renamed in `mcp` 2.x and the assignment asks for FastMCP.
