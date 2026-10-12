# Campus Customs Agent Harness

Working database: `data/campus_customs_new.db` (copy of the original `data/campus_customs.db`, which stays untouched for resets).

## Database tables

### `desk`
- **Fields:** `date_today`, `notes`
- **Why it matters:** `date_today` is the shop's "today," so agents use it to decide what is overdue or due soon.

### `cash_accounts`
- **Fields:** `name`, `balance`, `date`
- **Why it matters:** This is the money available for payments; agents must check it before paying and it can never go negative.

### `inventory`
- **Fields:** `sku`, `name`, `size`, `qty`, `location`
- **Why it matters:** Shows whether an item and size is in stock, so agents can tell if a customer order (#101, #103) can be filled.

### `pricing`
- **Fields:** `sku`, `unit_cost`, `list_price`
- **Why it matters:** Gives cost and selling price, so agents can judge how much discount (e.g., #103's bulk request) the margin allows.

### `vendors`
- **Fields:** `id`, `name`, `specialty`, `lead_days`
- **Why it matters:** Tells agents who supplies what and how many days a restock takes to arrive.

### `leases`
- **Fields:** `id`, `space_name`, `landlord`, `monthly_rent`, `next_due`, `notes`
- **Why it matters:** Holds the shop's rent amount and due date, which agents need to handle the rent notice (#102).

### `invoices`
- **Fields:** `id`, `vendor_id`, `amount`, `due_date`, `status`, `description`
- **Why it matters:** Shows what the shop owes vendors; an open invoice blocks that vendor from shipping new product (invoice #501 blocks Bulldog Print Co).

### `payments`
- **Fields:** `id`, `kind`, `ref_id`, `amount`, `account`, `paid_at`, `approved_by`
- **Why it matters:** The record of every payment made, including who approved it, so agents leave an audit trail for each human-approved payment.

### `tickets`
- **Fields:** `id`, `type`, `requester`, `subject`, `sku`, `size`, `qty`, `lease_id`, `invoice_id`, `status`, `notes`, `created_at`
- **Why it matters:** The work queue: each open ticket is a request the agents must resolve, and its fields point to the related inventory, lease, or invoice.

## MCP tools (Problem 3)

Server: `mcp_server/server.py` (FastMCP), reading `data/campus_customs_new.db` read-only. All three tools only look things up; none of them changes the database or moves money.

### `get_invoice_and_vendor_block_status(invoice_id)`
- **Reads:** `invoices`, `vendors`, `desk`
- **Unlocks:** Ticket #101 (Tauhid Zaman needs a white tee, size S; 0 in stock)
- **Why it's the right tool:** The size S tee can only be restocked by reprint from Bulldog Print Co, which is blocked from shipping while its $840 invoice #501 sits open and 3 days overdue (counted from `desk.date_today`), so this tool tells the agent the order is blocked, what must be paid to unblock it, and that the tee arrives 5 days (`vendors.lead_days`) after that.

### `get_lease_rent_due_and_cash_coverage(lease_id)`
- **Reads:** `leases`, `cash_accounts`, `desk`
- **Unlocks:** Ticket #102 (Elm City Properties: rent due notice)
- **Why it's the right tool:** The landlord's notice says rent is due in 2 days, and this tool confirms the exact $2,400 rent for the Chapel Street shop due 2026-09-02 and shows that the $3,400 in checking covers it (leaving $1,000), which is what a person needs to see before approving the payment.

### `get_stock_and_margin_for_bulk_order(sku, size, qty)`
- **Reads:** `inventory`, `pricing`
- **Unlocks:** Ticket #103 (Yale AI Club wants 20 navy hoodies, size M, at a bulk discount)
- **Why it's the right tool:** The club's request for 20 size M hoodies at a discount can only be answered by knowing that just 8 are on hand (12 short) and that each hoodie costs $22 against a $58 list price, giving $36 of margin per hoodie to discount from without selling below cost.

## MCP tools (Problem 5)

The server also has action tools now. Lookups stay read-only; only the two tools below that change data write to the database, and nothing is ever sent to a real person.

### `list_open_tickets()`
- **Reads:** `tickets`, `desk`
- **Unlocks:** All three tickets (#101, #102, #103)
- **Why it's the right tool:** The Boss must start from the real queue, and this returns tickets 101, 102 and 103 with the exact `sku`/`size`/`qty`, `lease_id` 1 and `invoice_id` 501 to hand to the specialists.

### `update_ticket_status(ticket_id, status, note)`
- **Writes:** `tickets` (status, note appended to existing notes)
- **Unlocks:** All three tickets
- **Why it's the right tool:** #101 has to be marked `waiting` until the reprinted tee arrives 5 days after invoice #501 is paid, while #102 can be `resolved` once rent is paid, and this tool records that difference with a dated note.

### `request_payment(kind, ref_id, amount)`
- **Reads/writes:** `invoices`, `vendors`, `leases`, `cash_accounts`, `payments`
- **Unlocks:** Ticket #101 (pay invoice #501, $840) and #102 (pay lease #1 rent, $2,400)
- **Why it's the right tool:** Both payments total $3,240 against $3,400 in checking, so this tool checks each amount against the database, stops for a human to approve, refuses if cash would go negative, and on approval records the payment, which marks #501 paid (unblocking Bulldog Print Co) or moves the rent due date to 2026-10-02.

### `request_vendor_restock(vendor_id, sku, size, qty)`
- **Reads:** `vendors`, `invoices`, `inventory`, `desk` (saves a draft file)
- **Unlocks:** Ticket #101 (white tee, size S, 0 in stock)
- **Why it's the right tool:** It refuses the size S tee reprint while Bulldog Print Co's invoice #501 is open, and once it's paid it saves a draft order with arrival on 2026-09-05 (`desk.date_today` + 5 `lead_days`), without contacting the vendor.

### `draft_customer_message(ticket_id, message)`
- **Reads:** `tickets` (saves a draft file)
- **Unlocks:** Tickets #101 and #103 (customer tickets)
- **Why it's the right tool:** Tauhid Zaman and the Yale AI Club need a reply about the tee delay and the 8-of-20 hoodie stock, and this saves a draft addressed with the name stored on the ticket, never emailing a real customer.


### `get_checking_balance()`
- **Reads:** `cash_accounts`, `desk`
- **Unlocks:** Ticket #101 (and any payment)
- **Why it's the right tool:** Ticket 101 links invoice #501 but no lease, so when 101 runs on its own Accounting had no way to see the $3,400 checking balance and never requested the $840 payment. This read-only tool gives Accounting the balance for any ticket, so it can confirm the cash covers the payment before `request_payment` asks a human.

### `request_discount_decision(ticket_id, unit_price)`
- **Reads:** `tickets`, `pricing`, `desk`. **Writes:** `tickets.notes` (only after a human decides)
- **Unlocks:** Ticket #103 (Yale AI Club, 20 navy hoodies, size M, bulk discount)
- **Why it's the right tool:** The database has no discount policy, so ticket 103 can only be finished by a human: the Boss recommends one per-unit price between the real $22 cost and $58 list price, and the human approves it or rejects it (keeping $58). The decision and the decider's name are recorded on the ticket. No cash moves and the catalogue price never changes, so it can't be mistaken for a payment.
## Agent team and their MCP tools (Problem 5)

Code: `backend/team.py` (PydanticAI, GPT-6-Luna via Portkey, using the Responses API `/v1/responses` because GPT-6-Luna can't combine reasoning with tool calls on `/v1/chat/completions`). Prompts: `backend/prompts/<agent>.md`. Each agent can see and call **only** the tools listed for it; the Boss reaches the specialists through its `ask_*` delegation tools.

| Agent | MCP tool | Tables the tool uses |
|---|---|---|
| **Boss** | `list_open_tickets` | `tickets`, `desk` (read) |
| | `update_ticket_status` | `tickets` (write), `desk` (read) |
| | `request_discount_decision` | `tickets`, `pricing`, `desk` (read); `tickets.notes` (write, only after a human decides) |
| | `ask_inventory`, `ask_accounting`, `ask_facilities`, `ask_customer_service` | none (delegation to specialists, not MCP) |
| **Inventory** | `get_stock_and_margin_for_bulk_order` | `inventory`, `pricing` (read) |
| | `get_invoice_and_vendor_block_status` | `invoices`, `vendors`, `desk` (read) |
| | `request_vendor_restock` | `vendors`, `invoices`, `inventory`, `desk` (read); draft file in `output/restock_requests/` |
| **Accounting** | `get_invoice_and_vendor_block_status` | `invoices`, `vendors`, `desk` (read) |
| | `get_lease_rent_due_and_cash_coverage` | `leases`, `cash_accounts`, `desk` (read) |
| | `get_checking_balance` | `cash_accounts`, `desk` (read) |
| | `request_payment` | `invoices`, `vendors`, `leases`, `desk` (read); `payments`, `cash_accounts`, `invoices`/`leases` (write, only after human approval) |
| **Facilities** | `get_lease_rent_due_and_cash_coverage` | `leases`, `cash_accounts`, `desk` (read) |
| **Customer Service** | `get_stock_and_margin_for_bulk_order` | `inventory`, `pricing` (read) |
| | `draft_customer_message` | `tickets` (read); draft file in `output/customer_drafts/` |

**Audit trail:** every run start, the tools the MCP server exposed (`tools_available`), delegation, tool call, tool result or error, human decision (`payment_approval` or `discount_decision`), specialist answer, final report, and run end is appended to `output/audit_trail.json` as it happens, tagged with a `run_id`. Each run adds to the file; earlier runs are never replaced.

## Safety

- **Token and loop limits (whole run, all five agents combined):** 300,000 total tokens, 60 model requests, 60 tool calls, 4,000 output tokens per reply (reasoning included), GPT-6-Luna reasoning effort set to `low`, 15 Boss-to-specialist delegations, 2 retries per agent. Hitting a limit stops the run and logs `run_stopped` in the audit trail.
- **Payments:** a human must approve every payment (dashboard card or terminal prompt); the tool refuses wrong amounts, double payments, and anything that would make cash negative.
- **Discounts:** only a human decides a discount, through `request_discount_decision` ($22–$58 for the hoodie). It's labeled DISCOUNT DECISION, never moves cash, never edits `pricing`, and one decision per ticket is final.
- **Resolved means:** the desk finished every action in its control using real data and recorded every human decision (101: invoice paid with approval, restock draft with real arrival date, reply drafted; 102: rent confirmed and paid with approval; 103: real stock/price facts, human price decision, reply drafted). It never means stock arrived or time passed.
- **Least privilege:** each agent only sees its own tools; only `update_ticket_status` and `request_payment` write to the database.
- **No real contact:** restock orders and customer replies are drafts saved to files; nothing is emailed or sent.
- **Clean start:** the database is reset from `campus_customs.db` before every full run (`--no-reset` skips this).

## Backend routes (Problem 7)

Start from the `backend/` folder: `uvicorn main:app --reload --port 8000`, then use `http://localhost:8000`. All responses are JSON, and errors look like `{"error": {"status", "message"}}`.

- `GET /api/health`: Server check: database file, shop date, and the run in progress (if any).
- `GET /api/tickets`: All 3 tickets with their status and `is_open` (open/waiting = true, resolved = false).
- `GET /api/tickets/{ticket_id}`: One ticket by id (404 if it doesn't exist).
- `POST /api/tickets/{ticket_id}/run`: Start the agent team on that ONE ticket (returns a `run_id`; optional `{"reset_first": true}`).
- `GET /api/runs`: Runs started since the server launched, newest first, with status and final report.
- `GET /api/runs/{run_id}`: One run's status (running/finished/stopped/failed), final report, usage, and pending approvals.
- `GET /api/events`: Recent agent events from `output/audit_trail.json` (who delegated, what each agent said, which tools it used); filters `limit`, `run_id`, `agent`, `event`, `after_seq`.
- `GET /api/approvals`: Payments waiting for a human click.
- `POST /api/approvals/{approval_id}`: A human approves or rejects a waiting payment (`{"decision": "approve"|"reject", "approver_name": "..."}`); nothing is auto-approved.
- `GET /api/cash`: Current checking balance from `cash_accounts`.
- `POST /api/reset`: Reset `campus_customs_new.db` to the original values; requires `{"confirm": "RESET"}` and is refused during a run.

## Agent dashboard (Problem 8)

React + Vite + TypeScript in `frontend/`. Design choices are explained in `output/design.md`.

**Start it (two terminals):**
1. Backend: `cd backend`, then `uvicorn main:app --reload --port 8000` (with `.venv` activated).
2. Frontend: `cd frontend`, then `npm install` (first time only), then `npm run dev`. Open **http://localhost:5173**.

The browser calls the backend directly at `http://localhost:8000` (`frontend/src/api.ts`), using only the Problem 7 routes. FastAPI's CORS allows exactly one origin, `http://localhost:5173` (GET/POST, `Content-Type` header), and Vite is pinned to that port (`strictPort`), so it fails loudly instead of moving to a port CORS would block.

- **Ticket rack:** all 3 tickets and their status (open, waiting, or resolved), from `GET /api/tickets`.
- **Send to the agent team:** runs ONE ticket with `POST /api/tickets/{ticket_id}/run`. Disabled while another run is going or if the ticket is resolved.
- **The team:** five agent seats and a live feed of hand-offs, tool calls, results, and what each agent said, from `GET /api/runs/{run_id}` and `GET /api/events?run_id=…`, polled every 1.5 s while running.
- **Run summary:** after a run, one card per agent (tasks, tools used, outcomes) built from that run's audit events, plus the Boss's final report.
- **Approval card:** appears only when `GET /api/approvals` shows something waiting, and says whether it is a **PAYMENT** (navy label) or a **DISCOUNT DECISION** (purple label, with price per unit, list price, cost, and order totals). Shows the amount, reason, and balance before and after, with Approve and Reject buttons that call `POST /api/approvals/{approval_id}`. Nothing is approved without a click.
- **Till:** the checking balance from `GET /api/cash`, refreshed while running so a paid invoice shows the drop.
- **Fresh start:** `POST /api/reset`. Two steps (open the panel, then type RESET), and disabled during a run or while a payment is waiting.
- **Errors:** backend error messages are shown as readable notices, and an error boundary keeps the page from going blank.

## Final run (Problem 9)

Source of truth: `output/audit_trail.json` events #343–#426 and `data/campus_customs_new.db` after the run. Earlier test runs (#1–#342) stay in the audit trail unchanged.

| Step | Run id | Audit events | Result |
|---|---|---|---|
| Reset | `reset-20261012-102641-00d174` | #343 | Database restored; checking **$3,400.00** |
| Ticket 101 | `20261012-102659-928d21` | #344–#380 | Invoice 501 **$840** paid (approved by Kanushri) → $2,560; restock draft, arrival 2026-09-05; reply drafted; **resolved** |
| Ticket 102 | `20261012-102802-d47dd0` | #381–#403 | Rent **$2,400** paid (approved by Kanushri) → **$160**; lease next due 2026-10-02; **resolved** |
| Ticket 103 | `20261012-103013-77fb78` | #404–#426 | 8 of 20 in stock; discount **$50.00/hoodie approved** by Kanushri (no cash moved, list price still $58); reply drafted; **resolved** |

Cash: $3,400.00 − $840.00 − $2,400.00 = **$160.00** ending balance.

Deliverables:
- `output/desk_tickets.html`: Actual for 101–103, the Cash tab, and the Reflection tab.
- `output/resolved_tickets.json`: the machine-readable record built from the audit trail and the database.
- `output/resolved_board.html`: the visual board.

