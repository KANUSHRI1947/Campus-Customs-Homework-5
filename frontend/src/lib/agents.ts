// Display info for the five agents in backend/team.py (plus the human and system).
export type AgentKey = "boss" | "inventory" | "accounting" | "facilities" | "customer_service";

export interface AgentMeta {
  key: AgentKey;
  name: string;
  role: string;
  initials: string;
  color: string; // accent colour for the seat, bubbles, and chips
}

export const AGENTS: AgentMeta[] = [
  { key: "boss", name: "Boss", role: "Reads the ticket, delegates, sets status", initials: "BO", color: "#00356b" },
  { key: "inventory", name: "Inventory", role: "Stock, margin, vendor blocks, restock drafts", initials: "IN", color: "#2f7d5b" },
  { key: "accounting", name: "Accounting", role: "Invoices, cash, payment requests", initials: "AC", color: "#b0711c" },
  { key: "facilities", name: "Facilities", role: "Lease, rent, due dates", initials: "FA", color: "#6a4c9c" },
  { key: "customer_service", name: "Customer Service", role: "Drafts replies (never sent)", initials: "CS", color: "#c0463f" },
];

export const AGENT_BY_KEY: Record<string, AgentMeta> = Object.fromEntries(AGENTS.map((a) => [a.key, a]));

export function agentName(key: string): string {
  if (key === "HUMAN") return "You";
  if (key === "SYSTEM") return "System";
  return AGENT_BY_KEY[key]?.name ?? key;
}

export function agentColor(key: string): string {
  if (key === "HUMAN") return "#1f6f8b";
  if (key === "SYSTEM") return "#6b7280";
  return AGENT_BY_KEY[key]?.color ?? "#6b7280";
}
