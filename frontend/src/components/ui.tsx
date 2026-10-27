import type { ReactNode } from "react";
import { STATUS_LABEL, VERDICT_LABEL } from "../format";

export function Card({ title, actions, children, tight, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; tight?: boolean; className?: string }) {
  return (
    <section className={`card ${className ?? ""}`}>
      {(title || actions) && (
        <div className="card-h">
          {typeof title === "string" ? <h2>{title}</h2> : title}
          <div className="spacer" />
          {actions}
        </div>
      )}
      <div className={`card-b ${tight ? "tight" : ""}`}>{children}</div>
    </section>
  );
}

export function Kpi({ label, value, foot, tone, small }: { label: string; value: ReactNode; foot?: ReactNode; tone?: "accent" | "good" | "bad"; small?: boolean }) {
  return (
    <div className={`card kpi ${tone ?? ""}`}>
      <div className="label">{label}</div>
      <div className={`value ${small ? "sm" : ""}`}>{value}</div>
      {foot && <div className="foot">{foot}</div>}
    </div>
  );
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <span className="badge">Not valued</span>;
  const tone = status === "ok" ? "good" : status === "needs_input" ? "warn" : "bad";
  return <span className={`badge ${tone}`}>{STATUS_LABEL[status] ?? status}</span>;
}

export function Grade({ g }: { g: string | null | undefined }) {
  if (!g) return <span className="muted">—</span>;
  return (
    <span className={`grade ${g}`} title="Evidence-quality rating (rule-based; not a probability)">
      {g}
    </span>
  );
}

export function VerdictBadge({ v }: { v: string | null | undefined }) {
  if (!v) return <span className="muted">—</span>;
  const tone = v === "within_target" || v === "within_ceiling" ? "good" : v === "above_target" ? "warn" : "bad";
  return <span className={`badge ${tone}`}>{VERDICT_LABEL[v] ?? v}</span>;
}

export function Synthetic({ on }: { on: boolean }) {
  return on ? <span className="badge demo" title="Generated demo data — not market evidence">SYNTHETIC</span> : null;
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="empty">
      <span className="spin" /> {label}…
    </div>
  );
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="banner bad">{error}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Drawer({ title, onClose, children, footer }: { title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  return (
    <>
      <div className="drawer-bg" onClick={onClose} />
      <aside className="drawer fade-in" role="dialog" aria-modal="true">
        <div className="dh">
          <h2>{title}</h2>
          <div className="spacer" />
          <button className="btn ghost" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <div className="db">{children}</div>
        {footer && <div className="df">{footer}</div>}
      </aside>
    </>
  );
}

export function PageHead({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="pagehead">
      <div>
        <h1>{title}</h1>
        {sub && <div className="sub">{sub}</div>}
      </div>
      <div className="spacer" />
      {actions && <div className="row wrap">{actions}</div>}
    </div>
  );
}
