const inr0 = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });
const n0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

/** Money in INR with Indian digit grouping. null/undefined render as an em dash (missing), never as 0. */
export function inr(v: number | null | undefined, precise = false): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return (precise ? inr2 : inr0).format(v);
}

/** Compact lakh/crore form for headline figures. */
export function inrShort(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  const a = Math.abs(v);
  const sign = v < 0 ? "−" : "";
  if (a >= 1e7) return `${sign}₹${(a / 1e7).toFixed(2)} Cr`;
  if (a >= 1e5) return `${sign}₹${(a / 1e5).toFixed(2)} L`;
  return inr(v);
}

export function num(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined) return "—";
  return digits ? v.toLocaleString("en-IN", { maximumFractionDigits: digits }) : n0.format(v);
}

/** Fraction (0.153) as a percentage. */
export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function date(v: string | null | undefined): string {
  if (!v) return "—";
  const d = new Date(v.length === 10 ? `${v}T00:00:00` : v);
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export function dateTime(v: string | null | undefined): string {
  if (!v) return "—";
  return new Date(v).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function show(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) return v.length ? v.join("; ") : "None";
  return String(v);
}

export const STATUS_LABEL: Record<string, string> = {
  ok: "Valued",
  insufficient_evidence: "Insufficient evidence",
  needs_input: "Needs input",
};

export const VERDICT_LABEL: Record<string, string> = {
  within_target: "Ask within target",
  above_target: "Negotiate",
  above_ceiling: "Above safe ceiling",
  within_ceiling: "Within ceiling",
};
