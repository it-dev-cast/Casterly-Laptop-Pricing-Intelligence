import { useState } from "react";
import { api } from "../api";
import { Card, Empty, Kpi, Loading, PageHead } from "../components/ui";
import { useApp, useLoad } from "../context";
import { date, dateTime, inr, pct } from "../format";

interface Errs { n: number; mae: number; mape_pct: number; median_ape_pct: number }
interface Report {
  id: number; created_at: string; status: string; message?: string; synthetic_data: boolean; holdout_fraction: number;
  total_completed_sales: number; holdout_count?: number; holdout_start_date?: string; config_version?: number;
  engine_estimate_rate?: number; baseline_estimate_rate?: number; head_to_head?: Errs | null; baseline_head_to_head?: Errs | null;
  engine_all?: Errs | null; interval_coverage?: { p25_p75: number | null; p10_p90: number | null };
  cases?: { sale_id: string; date?: string; actual?: number; engine_estimate?: number | null; engine_basis?: string | null; engine_p25?: number | null; engine_p75?: number | null; engine_rating?: string | null; baseline_estimate?: number | null; baseline_n?: number; skipped?: string }[];
  method: string; caveat?: string;
}

export default function Validation() {
  const { view, can, toast } = useApp();
  const synth = view === "demo";
  const runs = useLoad(() => api.get<Report[]>("/api/validation/backtest"), []);
  const [frac, setFrac] = useState(0.3);
  const [busy, setBusy] = useState(false);
  const latest = (runs.data ?? []).find((r) => r.synthetic_data === synth);

  const run = async () => {
    setBusy(true);
    try {
      await api.post("/api/validation/backtest", { holdout_fraction: frac, synthetic: synth });
      runs.reload();
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack fade-in">
      <PageHead title="Validation" sub="Measured accuracy, not claimed accuracy. The newest completed sales are held out; each is priced using only evidence that existed the day before it happened, and compared with a simple median baseline."
        actions={can("run_backtest") && <>
          <label className="row small">Hold out latest <select value={frac} onChange={(e) => setFrac(Number(e.target.value))}>{[0.2, 0.3, 0.4, 0.5].map((x) => <option key={x} value={x}>{x * 100}%</option>)}</select></label>
          <button className="btn primary" onClick={run} disabled={busy}>{busy ? <span className="spin" /> : `Run on ${synth ? "synthetic demo" : "real"} data`}</button>
        </>} />
      <div className="banner info small">Price forecasting is deliberately not implemented. It needs a longer real sales history and its own validation first.</div>
      {runs.loading && !runs.data ? <Loading /> : !latest ? <Empty>No validation run on {synth ? "synthetic" : "real"} data yet.</Empty> :
        latest.status !== "ok" ? <div className="banner warn">{latest.message}</div> : (
          <>
            <div className="small muted">Run #{latest.id} · {dateTime(latest.created_at)} · {latest.holdout_count} held-out sales from {date(latest.holdout_start_date)} · settings v{latest.config_version}{latest.synthetic_data && " · SYNTHETIC DATA"}</div>
            <div className="grid g4">
              <Kpi label="Engine MAPE (head-to-head)" value={latest.head_to_head ? `${latest.head_to_head.mape_pct}%` : "—"} foot={latest.head_to_head ? `MAE ${inr(latest.head_to_head.mae)} · n=${latest.head_to_head.n}` : ""} tone="accent" />
              <Kpi label="Median baseline MAPE" value={latest.baseline_head_to_head ? `${latest.baseline_head_to_head.mape_pct}%` : "—"} foot={latest.baseline_head_to_head ? `MAE ${inr(latest.baseline_head_to_head.mae)} · same cases` : ""} />
              <Kpi label="P25–P75 coverage" value={pct(latest.interval_coverage?.p25_p75)} foot="nominal 50%" />
              <Kpi label="P10–P90 coverage" value={pct(latest.interval_coverage?.p10_p90)} foot="nominal 80%" />
            </div>
            <div className="grid g2">
              <Kpi small label="Engine produced an estimate" value={pct(latest.engine_estimate_rate)} foot="the rest were 'insufficient evidence', by design" />
              <Kpi small label="Baseline produced an estimate" value={pct(latest.baseline_estimate_rate)} foot="needs at least one earlier identical sale" />
            </div>
            <Card title="Held-out cases" tight>
              <div className="tablewrap" style={{ maxHeight: 520 }}>
                <table className="t">
                  <thead><tr><th>Date</th><th className="num">Actual</th><th className="num">Engine</th><th className="num">Engine P25–P75</th><th>Rating</th><th className="num">Baseline</th><th className="num">Engine error</th></tr></thead>
                  <tbody>
                    {(latest.cases ?? []).map((c) => (
                      <tr key={c.sale_id}>
                        <td className="small">{date(c.date)} <span className="tiny muted">{c.sale_id}</span></td>
                        <td className="num">{inr(c.actual)}</td>
                        <td className="num">{c.engine_estimate == null ? <span className="muted small">insufficient</span> : inr(c.engine_estimate)}</td>
                        <td className="num small">{c.engine_p25 != null ? `${inr(c.engine_p25)} – ${inr(c.engine_p75)}` : "—"}</td>
                        <td>{c.engine_rating ?? "—"}</td>
                        <td className="num">{inr(c.baseline_estimate)} <span className="tiny muted">{c.baseline_n ? `n=${c.baseline_n}` : ""}</span></td>
                        <td className="num">{c.engine_estimate != null && c.actual ? pct((c.engine_estimate - c.actual) / c.actual) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
            <details className="small"><summary>Method</summary><p style={{ whiteSpace: "pre-wrap" }}>{latest.method}</p><p>{latest.caveat}</p></details>
          </>
        )}
    </div>
  );
}
