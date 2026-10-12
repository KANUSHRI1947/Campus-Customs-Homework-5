import { Component, type ReactNode } from "react";

export interface Notice {
  id: number;
  kind: "error" | "info" | "success";
  text: string;
}

export function Notices({ notices, onDismiss }: { notices: Notice[]; onDismiss: (id: number) => void }) {
  if (!notices.length) return null;
  return (
    <div className="notices" role="status">
      {notices.map((n) => (
        <div key={n.id} className={`notice notice-${n.kind}`}>
          <span>{n.text}</span>
          <button aria-label="Dismiss" onClick={() => onDismiss(n.id)}>
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

/** Last line of defence: a rendering bug shows a message instead of a blank page. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (this.state.error)
      return (
        <div className="crash">
          <h2>Something on the page broke</h2>
          <p>{this.state.error.message}</p>
          <button className="btn btn-primary" onClick={() => this.setState({ error: null })}>
            Try again
          </button>
        </div>
      );
    return this.props.children;
  }
}
