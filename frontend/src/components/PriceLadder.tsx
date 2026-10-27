import { inr } from "../format";
import type { Comparable, ValuationResult } from "../types";

const KIND_COLOR: Record<string, string> = {
  sale: "#0f8a5f",
  listing: "#2853c7",
  quote: "#b7791f",
  purchase: "#7c3aed",
};

type Side = "sell" | "buy";

/**
 * Comparables on one price axis with a single stated price basis per chart.
 * sell: completed sales and asking prices, tax-inclusive, with the sale range and listing price.
 * buy:  supplier quotes and completed purchases converted to the purchase basis, with target,
 *       maximum safe and supplier-ask markers.
 * Filled = included, hollow = excluded after matching; dot size follows weight.
 */
export default function PriceLadder({ r, side }: { r: ValuationResult; side: Side }) {
  const inp = r.economics.inputs as Record<string, unknown>;
  const standard = inp.tax_mode === "standard";
  const g = Number(inp.gst_rate_pct ?? 0) / 100;
  const toBuyBasis = (v: number) => (standard ? v / (1 + g) : v);
  const kinds = side === "sell" ? ["sale", "listing"] : ["quote", "purchase"];
  const price = (c: Comparable) => {
    const v = (c.adjusted_price ?? c.gross_price) as number;
    return side === "buy" ? toBuyBasis(v) : v;
  };
  const comps = r.comparables.filter((c) => kinds.includes(c.kind) && (c.adjusted_price ?? c.gross_price) != null);
  const sel = r.selling;
  const e = r.economics;
  const markers: { v: number; label: string; color: string }[] = [];
  if (side === "sell") {
    if (r.listing_recommendation) markers.push({ v: r.listing_recommendation.price_gross, label: "List at", color: "#2853c7" });
  } else {
    if (e.max_safe_buy != null) markers.push({ v: e.max_safe_buy, label: "Max safe buy", color: "#c2362f" });
    if (e.target_buy != null) markers.push({ v: e.target_buy, label: "Target buy", color: "#0f8a5f" });
    if (e.asking) markers.push({ v: e.asking.asking_buy_basis, label: "Supplier ask", color: "#291f56" });
  }
  const vals = [
    ...comps.map(price),
    ...markers.map((m) => m.v),
    ...(side === "sell" && sel ? [sel.p10_gross as number, sel.p90_gross as number] : []),
  ].filter((v) => typeof v === "number" && Number.isFinite(v));
  if (!vals.length) {
    return <div className="empty small">{side === "sell" ? "No selling-side evidence to plot." : "No procurement evidence or buy price to plot."}</div>;
  }
  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  const pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.1 || 1000;
  lo -= pad;
  hi += pad;
  const W = 1000;
  const x = (v: number) => 40 + ((v - lo) / (hi - lo)) * (W - 80);
  const LABEL: Record<string, string> = { sale: "Completed sales", listing: "Asking prices", quote: "Supplier quotes", purchase: "Completed purchases" };
  const lanes = kinds.map((k) => ({ key: k, label: LABEL[k], items: comps.filter((c) => c.kind === k) })).filter((l) => l.items.length);
  const laneH = 40;
  const top = side === "sell" && sel ? 44 : 22;
  const axisY = top + Math.max(1, lanes.length) * laneH;
  const H = axisY + (markers.length ? 66 : 24);
  const placed: { v: number; label: string; color: string; y: number }[] = [];
  [...markers].sort((a, b) => a.v - b.v).forEach((m) => {
    const prev = placed[placed.length - 1];
    const clash = prev && Math.abs(x(m.v) - x(prev.v)) < 118 && prev.y === axisY + 16;
    placed.push({ ...m, y: clash ? axisY + 40 : axisY + 16 });
  });
  const ticks = 6;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={side === "sell" ? "Selling-side price ladder" : "Buying-side price ladder"}>
      {side === "sell" && sel && (
        <>
          <rect x={x(sel.p25_gross as number)} y={top - 14} width={Math.max(2, x(sel.p75_gross as number) - x(sel.p25_gross as number))}
            height={lanes.length * laneH + 8} fill="#0f8a5f" opacity={0.09} rx={6} />
          <line x1={x(sel.p50_gross as number)} x2={x(sel.p50_gross as number)} y1={top - 14} y2={axisY - 6} stroke="#0f8a5f" strokeWidth={2} strokeDasharray="4 3" />
          <text x={x(sel.p50_gross as number)} y={top - 22} textAnchor="middle" fontSize={12} fill="#0f8a5f" fontWeight={700}>
            Expected sale {inr(sel.p50_gross as number)} · range {inr(sel.p25_gross as number)}–{inr(sel.p75_gross as number)}
          </text>
        </>
      )}
      {lanes.map((l, i) => {
        const y = top + i * laneH + 16;
        return (
          <g key={l.key}>
            <text x={40} y={y - 12} fontSize={11} fill="#64748b" fontWeight={600}>{l.label}</text>
            <line x1={40} x2={W - 40} y1={y} y2={y} stroke="#e2e8f0" />
            {l.items.map((c) => {
              const v = price(c);
              const rad = c.included && c.weights ? 4 + Math.min(6, c.weights.final * 6) : 4.5;
              return (
                <circle key={c.id} cx={x(v)} cy={y} r={rad} fill={c.included ? KIND_COLOR[c.kind] : "#fff"} fillOpacity={c.included ? 0.75 : 1}
                  stroke={KIND_COLOR[c.kind]} strokeWidth={1.5}>
                  <title>{`${c.kind_label}${c.channel ? ` (${c.channel})` : ""} ${inr(v)}${c.included ? ` · weight ${c.weights?.final}` : ` · excluded: ${c.exclusion}`}`}</title>
                </circle>
              );
            })}
          </g>
        );
      })}
      {Array.from({ length: ticks + 1 }, (_, i) => lo + ((hi - lo) * i) / ticks).map((t) => (
        <text key={t} x={x(t)} y={axisY + 4} textAnchor="middle" fontSize={10} fill="#94a3b8">{inr(Math.round(t / 100) * 100)}</text>
      ))}
      {placed.map((m) => (
        <g key={m.label}>
          <line x1={x(m.v)} x2={x(m.v)} y1={top - 8} y2={m.y} stroke={m.color} strokeWidth={2} />
          <rect x={x(m.v) - 62} y={m.y} width={124} height={20} rx={5} fill={m.color} />
          <text x={x(m.v)} y={m.y + 14} textAnchor="middle" fontSize={11} fill="#fff" fontWeight={600}>{m.label} {inr(m.v)}</text>
        </g>
      ))}
    </svg>
  );
}

export function LadderLegend() {
  return (
    <div className="legend">
      <span><i style={{ background: KIND_COLOR.sale }} />Completed sale</span>
      <span><i style={{ background: KIND_COLOR.listing }} />Asking price</span>
      <span><i style={{ background: KIND_COLOR.quote }} />Supplier quote</span>
      <span><i style={{ background: KIND_COLOR.purchase }} />Completed purchase</span>
      <span><i style={{ border: "1.5px solid #64748b", background: "#fff" }} />Hollow = excluded (hover for the reason)</span>
      <span>Dot size = weight</span>
    </div>
  );
}
