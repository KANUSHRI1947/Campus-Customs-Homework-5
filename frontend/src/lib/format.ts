const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

export const money = (n: number) => usd.format(n);

export function clockTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
}

export function prettyDate(isoDate: string | null | undefined): string {
  if (!isoDate) return "—";
  const d = new Date(`${isoDate}T12:00:00`);
  return Number.isNaN(d.getTime())
    ? isoDate
    : d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });
}

export const toolLabel = (tool: string) => tool.replace(/_/g, " ");

/** Short "key=value" list for tool arguments (long text is trimmed). */
export function argsText(args: unknown): string {
  if (!args || typeof args !== "object") return "";
  return Object.entries(args as Record<string, unknown>)
    .map(([k, v]) => {
      const s = typeof v === "string" ? `"${v.length > 60 ? v.slice(0, 57) + "…" : v}"` : JSON.stringify(v);
      return `${k}=${s}`;
    })
    .join(", ");
}

/** Strip light markdown so text can be shown as a one-line excerpt. */
export function plainExcerpt(text: string, max = 220): string {
  const flat = text
    .replace(/[#*_`>]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return flat.length > max ? flat.slice(0, max - 1) + "…" : flat;
}
