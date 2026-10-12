# Campus Customs Desk: Dashboard Design

The dashboard (`frontend/`) is designed to look like the shop's front counter on Chapel Street, not a generic admin panel. The idea: tickets sit on a rack, five staff members sit at their seats, the cash is in a till, and anything that spends money needs the owner's signature. Every number and message on screen comes from the Problem 7 backend (`http://localhost:8000`) or the audit trail. Nothing is a placeholder.

## Layout

Three columns, read left to right in the order you work a ticket:

| Column | What's there | Why |
|---|---|---|
| **Left: "Ticket rack"** | The 3 tickets as stubs, then the selected ticket's details and the **Send #101 to the agent team** button | You start by picking a ticket, so it comes first. The button sits right under the ticket it acts on. |
| **Center: "The team"** | Five agent seats, a gold "waiting for your approval" banner when needed, the run summary after a run, and the **Live desk feed** | This is where the work happens, so it gets the most width. |
| **Right: the till and approvals** | The checking balance, the approval card (or a short "No payments waiting" note), and **Fresh start** | These are about money and the database. The column stays in place as you scroll, so the balance and any approval request stay visible. |

Under 1180 px wide, the right column moves below the other two. Under 780 px, everything stacks into one column.

**Header:** a Yale-blue awning (gradient with a scalloped bottom edge, like a shop awning) with the shop's name, "Service Desk · Chapel Street", and three chips:
- **Shop date**, from `desk.date_today` (e.g., *Mon, Aug 31, 2026*). It's the date the agents use, not the computer's date.
- **Team working on #101**, a gold chip with a pulsing dot, shown only during a run.
- **Backend connected / Backend offline**, from `GET /api/health`.

**Look:** a warm paper background (`#f6f1e7`, with faint ruled lines like receipt paper). Headings and numbers use a serif font (Iowan Old Style or Palatino), body text a clean sans-serif, and tool names and arguments a monospace font, so tool calls look technical and agent messages read like conversation.

## The five agents

Each agent has its own color and initials, used everywhere it appears: its seat, its feed rows, and its summary card. You can tell who is talking at a glance.

| Agent | Initials | Color | Role line under the name |
|---|---|---|---|
| Boss | BO | Yale blue `#00356b` | Reads the ticket, delegates, sets status |
| Inventory | IN | green `#2f7d5b` | Stock, margin, vendor blocks, restock drafts |
| Accounting | AC | amber `#b0711c` | Invoices, cash, payment requests |
| Facilities | FA | purple `#6a4c9c` | Lease, rent, due dates |
| Customer Service | CS | red `#c0463f` | Drafts replies (never sent) |

**Seat states,** worked out from the run's events:
- **Not called yet:** faded seat. This makes it obvious when a ticket didn't need someone. For example, Facilities stays faded on ticket 103.
- **Working:** the seat's border takes the agent's color, a ring pulses around the avatar, and the status label fills with the agent's color.
- **Done:** white seat with a green "Done" label.

Under each seat is the agent's latest action, e.g. "request_payment: paid $840.00 — checking $3,400.00 → $2,560.00".

**How agents appear in the live feed:** every row has a thin colored stripe for the agent, and each kind of event has its own format:
- **Hand-off:** "**Boss** hands off to → **Inventory**", with the exact task text.
- **Tool call:** "**Accounting** called `request_payment`", with the inputs below in monospace.
- **Tool result:** "↳ request payment **paid $840.00 — …**", with a "Full result" link that opens the raw data.
- **What an agent says:** a speech bubble tinted in the agent's color, e.g. "Inventory → Boss". The Boss's final report gets a larger blue bubble.
- **Your decisions:** teal while waiting, green when approved, red when rejected.
- **Problems** (blocked tool, error, safety limit): pale red rows.

**After a run:** a summary card for each agent that took part, with a colored top border. It lists how many tasks the agent got from the Boss, each tool it used with its latest outcome, and a short quote from its last report. Below the cards, a line names the agents **not called on this ticket**, so you can compare it with our Problem 6 plan (for example, ticket 103 should only involve Inventory and Customer Service).

## Open, waiting and resolved tickets

Each ticket is a paper ticket stub: a tall number block ("No. **101**") on the left, a perforated edge, and the type, subject and requester on the right.

| Status | Number block | Label |
|---|---|---|
| **open** | Yale blue | blue "OPEN" |
| **waiting** | amber | amber "WAITING" |
| **resolved** | green | green "RESOLVED" |

The status always shows as both a color and a written label, so it doesn't rely on color alone. The selected stub turns white with a blue outline. The ticket being worked on shows a pulsing "agents working" line. A ticket only turns green when `GET /api/tickets` says `resolved`. The dashboard never decides that on its own.

The ticket detail shows the customer's request as a quote with a gold bar beside it ("Needs a tee in size S."), small boxes for SKU, size, qty, invoice and lease, and a dashed amber **Desk notes** box with the dated notes the Boss added through `update_ticket_status`. The send button explains when it's disabled ("The team is busy with #102. One ticket at a time." or "Already resolved. Use Fresh start to run it again.").

## The checking balance (the till)

The balance is the most prominent number on the page, shown as a till display: a navy panel with a gold "CHECKING BALANCE" label and a large serif amount (e.g., **$3,400.00**) whose digits line up so they don't jump when the number changes. Below it: `cash_accounts · checking` and "as of" a date.

It refreshes every 1.5 s during a run and every 10 s otherwise. When the balance changes, for example after you approve the $840 invoice, the number flashes gold and a badge appears: **▼ $840.00 last change**. You see the drop right after you click.

## The human approval card

The approval card appears only when the backend reports a payment waiting for a human (`GET /api/approvals`). It's built to be impossible to miss and hard to click by accident:

- **Look:** cream card with a gold border that slowly pulses, and a rotated red rubber stamp in the corner that says **NEEDS YOU**. A matching gold banner in the center says "Accounting is waiting for your approval."
- **Amount:** in large serif text (e.g., **$840.00**), taken from Accounting's actual `request_payment` call.
- **Reason:** "**For** invoice #501 to Bulldog Print Co (Rush reprint CC-TEE-WHITE S), due 2026-08-28", plus a small tag like "invoice #501".
- **Balance before and after:** "Checking now **$3,400.00** → After payment **$2,560.00**", from the payment tool's own message.
- **"Exact request from the MCP server":** a link that shows the original text exactly as the tool wrote it.
- **Approver name:** required. **Reject** (white with a red outline) and **Approve** (solid green) stay disabled until you type a name, because the name is saved as `approved_by` on the payment.
- **Nothing happens without a click:** only a click sends `POST /api/approvals/{id}`. The payment tool then re-checks the amount and the cash before recording it. If no one decides in time, the backend treats it as rejected, never approved.

### Two kinds of approval, never confused
The same card handles two different human decisions, and the first thing on it says which one:

| | **PAYMENT** (navy label) | **DISCOUNT DECISION** (purple label and purple glow) |
|---|---|---|
| Who asks | Accounting, through `request_payment` | The Boss, through `request_discount_decision` |
| Big number | the amount, e.g. **$840.00** | the price per unit, e.g. **$48.00 per unit** |
| Details | what it's for, plus checking now → after payment | list price, unit cost, and order total vs. the total at list price |
| What Approve does | cash leaves checking and the till drops | records your price on the ticket; **no cash moves, the catalogue price doesn't change** |
| Buttons | Approve payment / Reject payment | Approve price / Reject price (rejecting keeps the list price) |

The center banner, the feed rows ("Kanushri approved the PAYMENT" vs. "…approved the DISCOUNT price"), and the post-run summary all use the same words, so a discount can never be mistaken for a payment.

## Fresh start (reset)

Fresh start sits at the bottom of the right column with a red dashed outline, so it looks like a careful action. It takes two steps: click **Reset the database…**, then type `RESET` before **Reset now** turns on. It explains that this undoes the agents' payments and status changes but keeps the audit trail. It's disabled during a run or while a payment is waiting.

## What makes it feel like a real Campus Customs desk

- **Shop details:** the awning header, ticket stubs with numbers like a deli counter, a till for the cash, and a rubber stamp on anything that needs the owner. They're familiar objects from a shop, so the screen is easy to read.
- **Yale colors:** Yale blue, cream and a brass-gold accent, matching a Yale merchandise shop.
- **Team seats:** the five agents are shown as staff at their seats, so you can see who is working, who finished and who wasn't needed, instead of reading through a log.
- **Readable activity:** hand-offs, tool calls and answers each have their own format, so the feed reads like conversation at the counter, while every tool call and result can still be checked.
- **Honest about drafts and money:** the footer says customer replies and restock orders are drafts only, the shop date is always visible, and the balance moves only when the backend says it did.
- **Small motion with a purpose:** the pulsing seat ring, new feed rows sliding in, and the till flash all mean something changed. Nothing moves just for decoration.
- **Readable errors:** if the backend is off or refuses something, a short message appears in the corner (e.g., "Ticket 103 is already resolved. Reset the database first…") and the page keeps working.
