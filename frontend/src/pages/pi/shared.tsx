import { useEffect, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useLoad } from "../../context";
import type { PiBatch, PiMeta } from "./types";
import { STATUS_TEXT, STATUS_TONE } from "./types";

export function PiStatus({ s }: { s: string | null | undefined }) {
  if (!s) return <span className="muted">—</span>;
  return <span className={`badge ${STATUS_TONE[s] ?? ""}`}>{STATUS_TEXT[s] ?? s}</span>;
}

export function Confidence({ c }: { c: string | null | undefined }) {
  if (!c) return <span className="muted">—</span>;
  const tone = c === "High" ? "good" : c === "Medium" ? "info" : "warn";
  return <span className={`badge ${tone}`} title="Rule-based evidence score; not a probability">{c}</span>;
}

export function Severity({ s }: { s: string }) {
  return <span className={`badge ${s === "high" ? "bad" : s === "medium" ? "warn" : ""}`}>{s}</span>;
}

/** Batch selector bound to the ?batch= query parameter so every screen deep-links to the same batch. */
export function useBatchParam(): [number | null, (id: number | null) => void] {
  const [params, setParams] = useSearchParams();
  const v = params.get("batch");
  const id = v ? Number(v) : null;
  const set = (x: number | null) => {
    const p = new URLSearchParams(params);
    if (x) p.set("batch", String(x));
    else p.delete("batch");
    setParams(p, { replace: true });
  };
  return [id, set];
}

export function BatchPicker({ value, onChange, autoSelect = true }: { value: number | null; onChange: (id: number | null) => void; autoSelect?: boolean }) {
  const batches = useLoad(() => api.get<PiBatch[]>("/api/pi/batches"), []);
  const list = batches.data ?? [];
  useEffect(() => {
    if (autoSelect && value === null && list.length) onChange(list[0].id);
  }, [autoSelect, value, list, onChange]);
  return (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)} aria-label="Valuation batch" style={{ minWidth: 280 }}>
      <option value="">Select a valuation batch…</option>
      {list.map((b) => (
        <option key={b.id} value={b.id}>#{b.id} · {b.name} ({b.lines} lines)</option>
      ))}
    </select>
  );
}

export function usePiMeta() {
  return useLoad(() => api.get<PiMeta>("/api/pi/meta"), []);
}

export function Steps({ at }: { at: number }) {
  const s = ["Upload & identify", "Research market", "Calculate prices", "Review & approve", "Quote & export"];
  return (
    <div className="steps" aria-label="Valuation workflow">
      {s.map((t, i) => (
        <div key={t} className={`step ${i === at ? "on" : i < at ? "done" : ""}`}>
          <span className="n">{i < at ? "✓" : i + 1}</span>
          <span>{t}</span>
        </div>
      ))}
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="field">
      {label}
      {hint && <span className="hint">{hint}</span>}
      {children}
    </label>
  );
}

export function ExtLink({ href, children }: { href: string | null; children?: ReactNode }) {
  if (!href) return <span className="muted">—</span>;
  let host = href;
  try {
    host = new URL(href).hostname.replace(/^www\./, "");
  } catch {
    /* show raw */
  }
  return (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow" title={href}>
      {children ?? host} ↗
    </a>
  );
}

export function Pager({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="row" style={{ padding: "10px 14px", gap: 8 }}>
      <span className="small muted">
        {total === 0 ? "No rows" : `${(page - 1) * pageSize + 1}–${Math.min(total, page * pageSize)} of ${total.toLocaleString("en-IN")}`}
      </span>
      <div className="spacer" />
      <button className="btn sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>‹ Prev</button>
      <span className="small">Page {page} / {pages}</span>
      <button className="btn sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next ›</button>
    </div>
  );
}
