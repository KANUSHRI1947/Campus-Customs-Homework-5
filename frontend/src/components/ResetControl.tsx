import { useState, type ChangeEvent } from "react";

interface Props {
  disabledReason: string | null;
  onReset: () => Promise<void>;
}

/** Deliberately two steps: open the panel, then type RESET. Calls POST /api/reset. */
export function ResetControl({ disabledReason, onReset }: Props) {
  const [open, setOpen] = useState(false);
  const [word, setWord] = useState("");
  const [busy, setBusy] = useState(false);

  const close = () => {
    setOpen(false);
    setWord("");
  };

  const confirm = async () => {
    setBusy(true);
    try {
      await onReset();
      close();
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel reset">
      <div className="panel-head">
        <h2>Fresh start</h2>
      </div>
      {!open ? (
        <>
          <p className="muted small">
            Puts <code>campus_customs_new.db</code> back to the original values: tickets reopen and checking returns to
            its starting balance. The audit trail keeps every past event.
          </p>
          <button className="btn btn-ghost-danger btn-wide" disabled={!!disabledReason} onClick={() => setOpen(true)}>
            Reset the database…
          </button>
          {disabledReason && <p className="hint">{disabledReason}</p>}
        </>
      ) : (
        <div className="reset-confirm">
          <p>
            <b>This undoes every payment and status change</b> made by the agents in the working database.
          </p>
          <label>
            Type <code>RESET</code> to confirm
            <input value={word} onChange={(e: ChangeEvent<HTMLInputElement>) => setWord(e.target.value)} autoFocus placeholder="RESET" />
          </label>
          <div className="row">
            <button className="btn btn-quiet" onClick={close} disabled={busy}>
              Cancel
            </button>
            <button className="btn btn-danger" disabled={word !== "RESET" || busy} onClick={confirm}>
              {busy ? "Resetting…" : "Reset now"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
