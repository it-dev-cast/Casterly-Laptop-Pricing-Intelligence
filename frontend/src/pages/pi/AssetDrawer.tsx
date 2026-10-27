import { Fragment, useState } from "react";
import { api } from "../../api";
import { Drawer, ErrorBox, Loading } from "../../components/ui";
import { useApp, useLoad } from "../../context";
import { date, dateTime, inr } from "../../format";
import { Confidence, ExtLink, PiStatus, Severity } from "./shared";
import type { Breakdown, PiAsset, PiEstimate, PiException } from "./types";
import { n } from "./types";

interface Detail {
  asset: PiAsset;
  product: { id: number; label: string; category: string; spec: Record<string, unknown>; product_key: string } | null;
  estimate: (PiEstimate & { breakdown: Breakdown }) | null;
  exceptions: PiException[];
  overrides: { id: number; calculated_price: string | null; previous_price: string | null; new_price: string | null; reason: string; at: string }[];
  history: PiEstimate[];
}

const SPEC_SKIP = new Set(["source_text", "source_spec", "risk_flags", "label", "model_text", "grade_source"]);

export default function AssetDrawer({ assetId, onClose, onChanged }: { assetId: number; onClose: () => void; onChanged: () => void }) {
  const { can, toast } = useApp();
  const d = useLoad(() => api.get<Detail>(`/api/pi/assets/${assetId}`), [assetId]);
  const [price, setPrice] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const act = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
      toast(msg);
      d.reload();
      onChanged();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const a = d.data?.asset;
  const e = d.data?.estimate;
  const br = e?.breakdown;
  return (
    <Drawer title={a ? a.label ?? a.original_spec ?? `Row ${a.row_number}` : "Asset"} onClose={onClose}
      footer={a && <>
        {can("pi_approve") && <button className="btn primary" disabled={busy || a.final_price === null || a.status === "approved"}
          onClick={() => act(() => api.post("/api/pi/assets/approve", { asset_ids: [a.id] }), "Price approved.")}>Approve price</button>}
        <button className="btn" onClick={onClose}>Close</button>
      </>}>
      {d.loading && !d.data ? <Loading /> : d.error ? <ErrorBox error={d.error} /> : a && (
        <div className="stack">
          <ErrorBox error={err} />
          <div className="grid g3">
            <div className="card kpi"><div className="label">Market benchmark</div><div className="value sm">{inr(n(e?.benchmark ?? null))}</div></div>
            <div className="card kpi accent"><div className="label">Market Unit Price</div><div className="value sm">{inr(n(a.final_price))}</div>
              <div className="foot">{a.override_price !== null ? `override (calculated ${inr(n(a.calculated_price))})` : "calculated"}</div></div>
            <div className="card kpi"><div className="label">Lot value</div><div className="value sm">{inr(n(a.total_value))}</div><div className="foot">{a.quantity ?? "?"} units</div></div>
          </div>
          <div className="row" style={{ gap: 8 }}>
            <PiStatus s={a.status} /> <Confidence c={e?.confidence} />
            {e?.confidence_score != null && <span className="small muted">score {e.confidence_score}/100</span>}
            <div className="spacer" />
            <span className="small muted">Sheet {a.sheet} · row {a.row_number}{a.serial ? ` · ${a.serial}` : ""}</span>
          </div>
          {br && <div className={`banner ${br.status === "priced" ? "good" : br.status === "provisional" ? "warn" : "bad"}`}>{br.message}</div>}

          <section>
            <h3 className="small" style={{ marginBottom: 6 }}>Normalised specification</h3>
            <dl className="kv small">
              <dt>Original</dt><dd className="mono">{a.original_spec}</dd>
              <dt>Category</dt><dd>{d.data?.product?.category ?? a.category}</dd>
              <dt>Grade</dt><dd>{a.grade ?? "unknown"}{(a.normalized.grade_source as string) === "batch default" ? " (batch default)" : ""}</dd>
              {Object.entries(d.data?.product?.spec ?? a.normalized).filter(([k, v]) => !SPEC_SKIP.has(k) && v !== null && v !== "").map(([k, v]) => (
                <Fragment key={k}><dt>{k.replace(/_/g, " ")}</dt><dd>{String(v)}</dd></Fragment>
              ))}
              <dt>Identification</dt><dd>{a.identify_confidence} confidence</dd>
              <dt>Pricing date</dt><dd>{a.pricing_date ? dateTime(a.pricing_date) : "Not priced"}</dd>
              <dt>Research method</dt><dd>{a.research_methods?.join(", ") || "No sufficient evidence"}</dd>
            </dl>
          </section>

          {br && br.steps.length > 0 && (
            <section>
              <h3 className="small" style={{ marginBottom: 6 }}>Calculation</h3>
              <table className="t">
                <tbody>
                  {br.steps.map((s) => (
                    <tr key={s.step}>
                      <td>{s.label}</td>
                      <td className="num">{s.value ? inr(Number(s.value), true) : s.pct ? (Number(s.pct) ? `−${Number(s.pct)}%` : "0%") : ""}</td>
                      <td className="small muted">{s.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="tiny muted" style={{ marginTop: 4 }}>Rules: {br.rules_name} · as of {dateTime(br.as_of)}</div>
            </section>
          )}

          {br && (
            <section>
              <h3 className="small" style={{ marginBottom: 6 }}>Market observations ({br.observations.filter((o) => o.included).length} used of {br.observations.length})</h3>
              {br.observations.length === 0 ? <div className="small muted">No verified evidence for this product.</div> : (
                <div className="tablewrap">
                  <table className="t">
                    <thead><tr><th>Type</th><th className="num">Observed</th><th className="num">Ex-GST</th><th className="num">× factor</th><th className="num">Buy-side</th><th>Source</th><th>Use</th></tr></thead>
                    <tbody>
                      {br.observations.map((o) => (
                        <tr key={o.id} className={o.included ? "" : "excluded"}>
                          <td className="small">{o.price_type_label}<div className="tiny muted">{o.match_quality} · {date(o.observed_at)}{o.stale ? " · stale" : ""}</div></td>
                          <td className="num">{inr(n(o.observed))}<div className="tiny muted">{o.tax_basis}</div></td>
                          <td className="num">{inr(n(o.ex_gst))}</td>
                          <td className="num">{o.factor ?? "—"}</td>
                          <td className="num">{inr(n(o.converted))}</td>
                          <td className="small">{o.url ? <ExtLink href={o.url} /> : o.source}
                            <div className="tiny muted">{o.research_mode ?? "verified record"}</div>
                            <div className="tiny muted">Source date: {o.source_timestamp ? date(o.source_timestamp) : "unknown / recorded observation only"}</div>
                          </td>
                          <td className="small">{o.included ? <span className="badge good">used · w {o.weight}</span> : <span className="muted">{o.exclusion}</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}

          {br && br.confidence_parts.length > 0 && (
            <section>
              <h3 className="small" style={{ marginBottom: 6 }}>Confidence explanation</h3>
              <dl className="kv small">{br.confidence_parts.map((p) => <Fragment key={p.label}><dt>{p.label}</dt><dd>{p.points >= 0 ? "+" : ""}{p.points}</dd></Fragment>)}</dl>
            </section>
          )}

          {br && br.assumptions.length > 0 && (
            <section>
              <h3 className="small" style={{ marginBottom: 6 }}>Assumptions</h3>
              <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{br.assumptions.map((x) => <li key={x}>{x}</li>)}</ul>
            </section>
          )}

          {(d.data?.exceptions.length ?? 0) > 0 && (
            <section>
              <h3 className="small" style={{ marginBottom: 6 }}>Verification issues</h3>
              {d.data!.exceptions.map((x) => (
                <div key={x.id} className="card" style={{ padding: 10, marginBottom: 6 }}>
                  <div className="row" style={{ gap: 6 }}><Severity s={x.severity} /><b className="small">{x.code.replace(/_/g, " ")}</b>{x.resolved && <span className="badge good">resolved</span>}</div>
                  <div className="small">{x.message}</div>
                  <div className="tiny muted">Impact: {x.impact}</div>
                  <div className="tiny">Action: {x.action}</div>
                </div>
              ))}
            </section>
          )}

          {(d.data?.history.length ?? 0) > 1 && (
            <section>
              <h3 className="small" style={{ marginBottom: 6 }}>Price history for this product</h3>
              <table className="t"><thead><tr><th>As of</th><th>Batch</th><th className="num">Benchmark</th><th className="num">Recommended</th><th>Status</th></tr></thead>
                <tbody>{d.data!.history.map((h) => <tr key={h.id}><td className="small">{dateTime(h.as_of)}</td><td>#{h.batch_id}</td><td className="num">{inr(n(h.benchmark))}</td><td className="num">{inr(n(h.recommended_unit))}</td><td className="small">{h.status}{h.is_current ? " · current" : ""}</td></tr>)}</tbody>
              </table>
            </section>
          )}

          {can("pi_import") && a.status !== "approved" && <Reidentify asset={a} onDone={() => { d.reload(); onChanged(); }} />}

          {can("pi_override") && (
            <section className="card" style={{ padding: 12 }}>
              <h3 className="small" style={{ marginBottom: 8 }}>Override price</h3>
              <div className="formgrid">
                <label className="field">New unit price (₹, ex-GST)<input inputMode="decimal" value={price} onChange={(ev) => setPrice(ev.target.value)} placeholder="blank = clear override" /></label>
                <label className="field" style={{ gridColumn: "span 2" }}>Reason (required)<input value={reason} onChange={(ev) => setReason(ev.target.value)} placeholder="e.g. vendor's written quote of 20 Oct" /></label>
              </div>
              <div className="row" style={{ marginTop: 8 }}>
                <div className="spacer" />
                <button className="btn" disabled={busy || reason.trim().length < 5}
                  onClick={() => act(() => api.post("/api/pi/assets/override", { asset_ids: [a.id], price: price.trim() || null, reason }), price.trim() ? "Override saved." : "Override cleared.")}>
                  {price.trim() ? "Save override" : "Clear override"}
                </button>
              </div>
              {d.data!.overrides.length > 0 && (
                <table className="t" style={{ marginTop: 8 }}>
                  <thead><tr><th>When</th><th className="num">Calculated</th><th className="num">Previous</th><th className="num">New</th><th>Reason</th></tr></thead>
                  <tbody>{d.data!.overrides.map((o) => <tr key={o.id}><td className="small">{dateTime(o.at)}</td><td className="num">{inr(n(o.calculated_price))}</td><td className="num">{inr(n(o.previous_price))}</td><td className="num">{inr(n(o.new_price))}</td><td className="small">{o.reason}</td></tr>)}</tbody>
                </table>
              )}
            </section>
          )}
        </div>
      )}
    </Drawer>
  );
}

function Reidentify({ asset, onDone }: { asset: PiAsset; onDone: () => void }) {
  const { can, toast } = useApp();
  const [open, setOpen] = useState(asset.product_id === null);
  const [f, setF] = useState<Record<string, string>>({ make: "", model: "", cpu: "", ram: "", storage: "", grade: "" });
  const [same, setSame] = useState(true);
  const [method, setMethod] = useState<"manual" | "ai_suggested">("manual");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const suggest = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.post<{ suggestions: Record<string, { value: string; confidence: string }> }>(`/api/pi/assets/${asset.id}/ai-suggest`);
      const next = { ...f };
      Object.entries(r.suggestions).forEach(([k, v]) => { if (k in next) next[k] = String(v.value); });
      setF(next);
      setMethod("ai_suggested");
      toast("AI suggestions loaded. Check every value before applying.");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const apply = async () => {
    setBusy(true);
    setErr(null);
    try {
      const fields = Object.fromEntries(Object.entries(f).filter(([, v]) => v.trim()));
      const r = await api.post<{ updated: number[] }>(`/api/pi/assets/${asset.id}/reidentify`, { fields, method, apply_to_same_spec: same });
      toast(`${r.updated.length} row(s) re-identified. Recalculate prices to price them.`);
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  if (!open) return <button className="btn sm ghost" onClick={() => setOpen(true)}>Correct identification…</button>;
  return (
    <section className="card" style={{ padding: 12 }}>
      <h3 className="small" style={{ marginBottom: 6 }}>Correct identification</h3>
      <div className="tiny muted" style={{ marginBottom: 8 }}>Corrections are layered over the original cells (which are kept). Leave a field blank to keep the source value.</div>
      <ErrorBox error={err} />
      <div className="formgrid">
        {(["make", "model", "cpu", "ram", "storage", "grade"] as const).map((k) => (
          <label key={k} className="field">{k === "cpu" ? "CPU / spec" : k[0].toUpperCase() + k.slice(1)}<input value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>
        ))}
      </div>
      <label className="small row" style={{ gap: 6, marginTop: 8 }}><input type="checkbox" checked={same} onChange={(e) => setSame(e.target.checked)} />Apply to every row with the same original specification</label>
      <div className="row" style={{ marginTop: 8, gap: 8 }}>
        {can("use_ai") && <button className="btn sm" disabled={busy} onClick={suggest}>Suggest with AI</button>}
        {method === "ai_suggested" && <span className="badge warn">AI-suggested values</span>}
        <div className="spacer" />
        <button className="btn sm primary" disabled={busy || !Object.values(f).some((v) => v.trim())} onClick={apply}>Re-identify</button>
      </div>
    </section>
  );
}
