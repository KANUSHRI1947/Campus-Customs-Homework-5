import { useEffect, useRef, useState } from "react";
import type { Cash } from "../types";
import { money, prettyDate } from "../lib/format";

export function CashTill({ cash }: { cash: Cash | null }) {
  const prev = useRef<number | null>(null);
  const [delta, setDelta] = useState<number | null>(null);
  const [flash, setFlash] = useState(0);

  useEffect(() => {
    if (!cash) return;
    if (prev.current != null && cash.balance !== prev.current) {
      setDelta(cash.balance - prev.current);
      setFlash((f) => f + 1);
    }
    prev.current = cash.balance;
  }, [cash]);

  return (
    <section className="till" aria-live="polite">
      <div className="till-label">Checking balance</div>
      <div key={flash} className={`till-amount ${flash ? "till-flash" : ""}`}>
        {cash ? money(cash.balance) : "—"}
      </div>
      {delta != null && (
        <div className={`till-delta ${delta < 0 ? "down" : "up"}`}>
          {delta < 0 ? "▼" : "▲"} {money(Math.abs(delta))} last change
        </div>
      )}
      <div className="till-foot">
        <span>cash_accounts · {cash?.account ?? "checking"}</span>
        <span>as of {prettyDate(cash?.as_of)}</span>
      </div>
    </section>
  );
}
