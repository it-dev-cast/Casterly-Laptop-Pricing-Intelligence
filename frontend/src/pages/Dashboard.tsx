import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Card, ErrorBox, Grade, Kpi, Loading, PageHead, StatusBadge, VerdictBadge } from "../components/ui";
import { useApp, useLoad } from "../context";
import { dateTime, inr, inrShort, num, pct } from "../format";
import type { ValuationSummary } from "../types";

interface Portfolio {
  lines: number;
  units: number;
  lines_valued: number;
  status_counts: Record<string, number>;
  recommended_buy_total: number | null;
  max_safe_buy_total: number | null;
  asking_total: number | null;
  expected_contribution_total: number | null;
  total_lot_value: number | null;
  above_ceiling: number;
  critical_flags: number;
}
interface EvStat { total: number; fresh: number | null; fresh_window_days: number | null }
interface Dash {
  config_version: number;
  config_gaps: string[];
  evidence: Record<string, { real: EvStat; synthetic: EvStat }>;
  portfolio: { real: Portfolio; synthetic: Portfolio };
  market_coverage: { live: boolean; statement: string };
  demo_data_present: boolean;
  recent_valuations: ValuationSummary[];
  latest_backtest: null | {
    id: number; created_at: string; status: string; synthetic: boolean; holdout_count: number;
    head_to_head: { n: number; mae: number; mape_pct: number } | null;
    baseline_head_to_head: { n: number; mae: number; mape_pct: number } | null;
    interval_coverage: { p25_p75: number | null; p10_p90: number | null } | null;
  };
  pending_imports: number;
  ai: { configured: boolean; model: string | null; note: string | null };
}

const EV_LABEL: Record<string, string> = {
  completed_sales: "Completed sales",
  listings: "Advertised listings",
  supplier_quotes: "Supplier quotations",
  completed_purchases: "Completed purchases",
};

export default function Dashboard() {
  const { view, can, toast } = useApp();
  const nav = useNavigate();
  const { data, error, loading, reload } = useLoad(() => api.get<Dash>("/api/dashboard"), []);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const key = view === "demo" ? "synthetic" : "real";
  const p = data.portfolio[key];
  const recent = data.recent_valuations.filter((r) => r.is_synthetic === (view === "demo"));
  const savings = p.asking_total != null && p.recommended_buy_total != null ? p.asking_total - p.recommended_buy_total : null;

  const loadDemo = async () => {
    try {
      await api.post("/api/admin/demo");
      toast("Synthetic demo dataset loaded. Switch to the demo view to explore it.");
      reload();
    } catch (e) {
      toast((e as Error).message, true);
    }
  };

  return (
    <div className="stack fade-in">
      <PageHead
        title="Buying decisions at a glance"
        sub="What the current inventory is worth, what to pay for it, and how much of that rests on solid evidence."
        actions={
          <>
            <Link className="btn" to="/import">Upload data</Link>
            <Link className="btn primary" to="/inventory">Value inventory</Link>
          </>
        }
      />

      {p.lines === 0 ? (
        <div className={`hero ${view === "demo" ? "demo" : ""}`}>
          <div>
            <div className="eyebrow">Getting started</div>
            <div className="headline">No {view === "demo" ? "demo" : ""} inventory to value yet.</div>
            <div className="lede">
              1. Upload the stock list you are being offered. 2. Upload or enter comparable evidence: completed sales
              first, then listings and quotations. 3. Set your selling fees, costs and yields. 4. Run valuations.
            </div>
          </div>
          <div className="facts">
            <div className="fact"><div className="k">Evidence on file</div><div className="v">{num(Object.values(data.evidence).reduce((a, e) => a + e[key].total, 0))} records</div></div>
            <div className="fact"><div className="k">Config version</div><div className="v">v{data.config_version}</div></div>
            {view === "real" && !data.demo_data_present && can("manage_demo") && (
              <div className="fact" style={{ gridColumn: "1 / -1" }}>
                <button className="btn gold" onClick={loadDemo}>Load the synthetic demo dataset</button>
                <div className="small" style={{ color: "#c9d4ea", marginTop: 6 }}>Kept separate from real evidence and removable at any time.</div>
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className={`hero ${view === "demo" ? "demo" : ""}`}>
          <div>
            <div className="eyebrow">{view === "demo" ? "Synthetic demo portfolio" : "Current inventory"} · {p.lines_valued} of {p.lines} lines valued</div>
            <div className="headline">
              Pay no more than <span className="g">{inrShort(p.recommended_buy_total)}</span>
            </div>
            <div className="lede">
              {p.asking_total != null && savings != null ? (
                savings > 0 ? (
                  <>Suppliers are asking {inrShort(p.asking_total)} for the valued lines: {inrShort(savings)} above the recommended price.</>
                ) : (
                  <>Suppliers are asking {inrShort(p.asking_total)}, within the recommended total.</>
                )
              ) : (
                <>Recommended purchase total across valued lines with a computable price.</>
              )}{" "}
              Lines that are not yet valued, or lack evidence, are excluded from the totals.
            </div>
          </div>
          <div className="facts">
            <div className="fact"><div className="k">Expected contribution</div><div className="v">{inrShort(p.expected_contribution_total)}</div></div>
            <div className="fact"><div className="k">Total lot value (ex-GST)</div><div className="v">{inrShort(p.total_lot_value)}</div></div>
            <div className="fact"><div className="k">Max safe purchase</div><div className="v">{inrShort(p.max_safe_buy_total)}</div></div>
            <div className="fact"><div className="k">Units</div><div className="v">{num(p.units)}</div></div>
          </div>
        </div>
      )}

      <div className="grid g4">
        <Kpi label="Valued" value={`${p.status_counts.ok ?? 0} lines`} tone="good" foot="Dependable estimate and buy price" />
        <Kpi label="Insufficient evidence" value={`${p.status_counts.insufficient_evidence ?? 0} lines`} foot="No dependable estimate: add comparables" />
        <Kpi label="Needs input" value={`${p.status_counts.needs_input ?? 0} lines`} foot="Missing yield, repair cost, margin or specs" />
        <Kpi label="Ask above safe ceiling" value={`${p.above_ceiling} lines`} tone={p.above_ceiling ? "bad" : undefined}
          foot={p.critical_flags ? `${p.critical_flags} with negative ceiling / infeasible margin` : "Do not buy these at the asking price"} />
      </div>

      <div className={`banner ${data.market_coverage.live ? "good" : "info"}`}>
        <div>
          <b>Market coverage.</b> {data.market_coverage.statement}{" "}
          <Link to="/connectors">Connector status</Link>
        </div>
      </div>

      <div className="grid g2">
        <Card title="Evidence on file" actions={<Link className="btn sm" to="/evidence">Open evidence</Link>}>
          <table className="t">
            <thead><tr><th>Type</th><th className="num">Records</th><th className="num">Within freshness window</th></tr></thead>
            <tbody>
              {Object.entries(data.evidence).map(([k, v]) => {
                const s = v[key];
                return (
                  <tr key={k}>
                    <td>{EV_LABEL[k]}{k === "listings" && <div className="tiny muted">Asking prices: never treated as sales</div>}</td>
                    <td className="num">{num(s.total)}</td>
                    <td className="num">
                      {num(s.fresh)} <span className="muted tiny">≤ {s.fresh_window_days} d</span>
                      {s.total > 0 && <div className="meter" style={{ marginTop: 4 }}><i style={{ width: `${((s.fresh ?? 0) / s.total) * 100}%` }} /></div>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
        <Card title={`Configuration v${data.config_version}`} actions={<Link className="btn sm" to="/settings">Cost & margin settings</Link>}>
          {data.config_gaps.length === 0 ? (
            <div className="banner good">All fees, costs, yields and default margin are configured.</div>
          ) : (
            <div className="stack-sm">
              <div className="muted small">These are not configured. Valuations show each one as an assumption or ask for the input; nothing is silently invented.</div>
              <ul style={{ margin: 0, paddingLeft: 18, columns: data.config_gaps.length > 6 ? 2 : 1 }} className="small">
                {data.config_gaps.map((g) => <li key={g}>{g}</li>)}
              </ul>
            </div>
          )}
        </Card>
      </div>

      <Card title="Recent valuations" tight actions={<Link className="btn sm" to="/inventory">All inventory</Link>}>
        {recent.length === 0 ? (
          <div className="empty">No valuations yet in this view.</div>
        ) : (
          <div className="tablewrap">
            <table className="t">
              <thead>
                <tr><th>Item</th><th>Status</th><th>Evidence</th><th className="num">Expected sale</th><th className="num">Recommended buy</th><th className="num">Max safe buy</th><th>Ask</th><th>Valued</th></tr>
              </thead>
              <tbody>
                {recent.map((r) => (
                  <tr key={r.id} className="clickable" onClick={() => nav(`/valuations/${r.id}`)}>
                    <td>{r.label}</td>
                    <td><StatusBadge status={r.status} /></td>
                    <td><Grade g={r.rating} /></td>
                    <td className="num">{inr(r.selling_p50)}</td>
                    <td className="num"><b>{inr(r.recommended_buy)}</b></td>
                    <td className="num">{inr(r.max_safe_buy)}</td>
                    <td><VerdictBadge v={r.asking_verdict} /></td>
                    <td className="muted small nowrap">{dateTime(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="grid g2">
        <Card title="Validation against held-out sales" actions={<Link className="btn sm" to="/validation">Open</Link>}>
          {data.latest_backtest?.status === "ok" ? (
            <div className="stack-sm">
              <div className="small muted">
                Latest run {dateTime(data.latest_backtest.created_at)} on {data.latest_backtest.synthetic ? "synthetic demo" : "real"} data,{" "}
                {data.latest_backtest.holdout_count} held-out sales.
              </div>
              <div className="grid g3">
                <Kpi small label="Engine MAPE" value={data.latest_backtest.head_to_head ? `${data.latest_backtest.head_to_head.mape_pct}%` : "—"} />
                <Kpi small label="Median baseline MAPE" value={data.latest_backtest.baseline_head_to_head ? `${data.latest_backtest.baseline_head_to_head.mape_pct}%` : "—"} />
                <Kpi small label="P25–P75 coverage" value={pct(data.latest_backtest.interval_coverage?.p25_p75)} foot="nominal 50%" />
              </div>
            </div>
          ) : (
            <div className="muted">
              {data.latest_backtest ? "Not enough completed-sales history for a meaningful hold-out test yet." : "No validation run yet."} Accuracy is
              not claimed until it is measured against chronologically held-out completed sales.
            </div>
          )}
        </Card>
        <Card title="AI assistance">
          {data.ai.configured ? (
            <div className="stack-sm">
              <div><span className="badge good">Configured</span> <span className="mono">{data.ai.model}</span></div>
              <div className="small muted">Used only to suggest extracted fields (always reviewed) and to explain finished valuations. It never sets a price.</div>
            </div>
          ) : (
            <div className="stack-sm">
              <div><span className="badge">Not configured</span></div>
              <div className="small muted">{data.ai.note} Every pricing feature works without it.</div>
            </div>
          )}
          {data.pending_imports > 0 && (
            <div className="banner warn" style={{ marginTop: 12 }}>
              {data.pending_imports} upload(s) awaiting review or commit. <Link to="/import">Resume</Link>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
