import { Fragment, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, download } from "../api";
import { Icon } from "../components/Icons";
import PriceLadder, { LadderLegend } from "../components/PriceLadder";
import { Card, ErrorBox, Grade, Kpi, Loading, PageHead, StatusBadge, Synthetic, VerdictBadge } from "../components/ui";
import { useApp, useLoad } from "../context";
import { date, dateTime, inr, num, pct, show } from "../format";
import type { Comparable, Economics, ValuationResult, ValuationSummary } from "../types";

interface Detail {
  summary: ValuationSummary;
  result: ValuationResult;
  item: { id: number; label: string; item_ref: string | null; lot_id: number | null; is_synthetic: boolean };
  config_version: { id: number; version: number; note: string | null; hash: string };
  ai_explanation: null | { text: string; model: string; unverified_figures: string[]; note: string; generated_at: string };
  evidence_snapshot_count: number;
}

const TIER: Record<string, [string, string]> = {
  exact: ["Exact", "good"], unverified: ["Unverified", "info"], adjusted: ["Adjusted", "warn"],
};

export default function ValuationDetail() {
  const { runId } = useParams();
  const nav = useNavigate();
  const { can, toast } = useApp();
  const d = useLoad(() => api.get<Detail>(`/api/valuations/${runId}`), [runId]);
  const history = useLoad(() => (d.data ? api.get<{ valuations: ValuationSummary[] }>(`/api/inventory/${d.data.item.id}`) : Promise.resolve(null)), [d.data?.item.id]);
  const [repro, setRepro] = useState<null | { reproduced: boolean; recomputed_output_hash: string }>(null);
  const [busy, setBusy] = useState("");
  const ai = useLoad(() => api.get<{ configured: boolean }>("/api/ai/status"), []);

  if (d.loading && !d.data) return <Loading />;
  if (d.error) return <ErrorBox error={d.error} />;
  const { result: r, summary: s, item } = d.data!;
  const e = r.economics;
  const sel = r.selling;
  const critical = e.flags.some((f) => f.severity === "critical");

  const revalue = async () => {
    setBusy("revalue");
    try {
      const [run] = await api.post<ValuationSummary[]>("/api/valuations", { inventory_item_ids: [item.id] });
      toast("New valuation snapshot created.");
      nav(`/valuations/${run.id}`);
    } catch (err) {
      toast((err as Error).message, true);
    } finally {
      setBusy("");
    }
  };
  const reproduce = async () => {
    setBusy("repro");
    try {
      setRepro(await api.post(`/api/valuations/${s.id}/reproduce`));
    } finally {
      setBusy("");
    }
  };
  const explain = async () => {
    setBusy("ai");
    try {
      await api.post(`/api/valuations/${s.id}/explain`);
      d.reload();
    } catch (err) {
      toast((err as Error).message, true);
    } finally {
      setBusy("");
    }
  };

  let heroClass = "";
  let eyebrow = `${r.channel} channel · ${sel ? (sel.basis === "completed_sales" ? "based on completed sales" : "based on asking prices × configured ratio") : "no dependable estimate"}`;
  let headline: ReactNode;
  let lede: ReactNode;
  if (r.status === "insufficient_evidence") {
    heroClass = "insufficient";
    headline = <>Insufficient evidence</>;
    lede = <>{r.messages.join(" ")} No selling range or buying price is shown rather than guessing.</>;
  } else if (e.recommended_buy != null) {
    if (critical) heroClass = "bad";
    headline = e.recommended_buy < 0 ? <>Do not buy: <span className="g">no positive price works</span></> :
      <>Buy at up to <span className="g">{inr(e.recommended_buy)}</span> per unit</>;
    lede = e.asking ? <>{e.asking.verdict_text} Supplier asks {inr(e.asking.asking_buy_basis)} on the purchase basis.</> :
      <>No supplier asking price recorded for this line.</>;
  } else {
    headline = <>Selling range established; buying price needs input</>;
    lede = <>{r.needs_input.join(" ")}</>;
    eyebrow += " · needs input";
  }

  return (
    <div className="stack fade-in">
      <PageHead
        title={item.label}
        sub={<span className="row wrap" style={{ gap: 8 }}>
          <StatusBadge status={s.status} /><Synthetic on={item.is_synthetic} />
          <span>Valuation #{s.id} · as of {dateTime(r.as_of)} · engine {r.engine_version} · settings v{d.data!.config_version.version}</span>
          {item.item_ref && <span className="mono">{item.item_ref}</span>}
        </span>}
        actions={<>
          <button className="btn" onClick={reproduce} disabled={!!busy}>{busy === "repro" ? <span className="spin" /> : "Verify reproducibility"}</button>
          <button className="btn" onClick={() => download(`/api/valuations/${s.id}/export`, `valuation-${s.id}.xlsx`)}><Icon.download /> Excel</button>
          {can("run_valuation") && <button className="btn primary" onClick={revalue} disabled={!!busy}>{busy === "revalue" ? <span className="spin" /> : "Re-value now"}</button>}
        </>}
      />
      {repro && (
        <div className={`banner ${repro.reproduced ? "good" : "bad"}`}>
          {repro.reproduced
            ? <>Reproduced exactly from the stored snapshot ({d.data!.evidence_snapshot_count} evidence records, settings v{d.data!.config_version.version}). Output hash <span className="mono">{s.output_hash.slice(0, 16)}…</span></>
            : <>Recomputation differs from the stored result (engine version changed?). Stored <span className="mono">{s.output_hash.slice(0, 12)}</span>, recomputed <span className="mono">{repro.recomputed_output_hash.slice(0, 12)}</span>.</>}
        </div>
      )}

      <div className={`hero ${heroClass} ${item.is_synthetic ? "demo" : ""}`}>
        <div>
          <div className="eyebrow">{eyebrow}</div>
          <div className="headline">{headline}</div>
          <div className="lede">{lede}</div>
          {r.confidence && (
            <div className="row" style={{ marginTop: 14 }}>
              <Grade g={r.confidence.grade} />
              <span className="small" style={{ color: "#c9d4ea" }}>
                Evidence quality {r.confidence.score}/{r.confidence.max_score}: {s.comparables_included} comparables used of {s.comparables_considered} considered. A rule-based rating, not a probability.
              </span>
            </div>
          )}
        </div>
        <div className="facts">
          <div className="fact"><div className="k">Target buy / unit</div><div className="v">{inr(e.target_buy)}</div></div>
          <div className="fact"><div className="k">Max safe buy / unit</div><div className="v">{inr(e.max_safe_buy)}</div></div>
          <div className="fact"><div className="k">Expected sale (median)</div><div className="v">{inr(sel?.p50_gross as number | undefined)}</div></div>
          <div className="fact"><div className="k">List at</div><div className="v">{inr(r.listing_recommendation?.price_gross)}</div></div>
          {e.asking && <div className="fact" style={{ gridColumn: "1 / -1" }}><VerdictBadge v={e.asking.verdict} />{" "}
            <span className="small" style={{ color: "#c9d4ea" }}>
              {e.asking.gap_to_target != null && <>Ask is {inr(Math.abs(e.asking.gap_to_target))} {e.asking.gap_to_target > 0 ? "above" : "below"} target. </>}
              Contribution at ask: {inr(e.asking.economics.contribution)} / unit ({pct(e.asking.economics.margin)} margin)
            </span>
          </div>}
        </div>
      </div>

      {e.flags.map((f) => <div key={f.code} className={`banner ${f.severity === "critical" ? "bad" : "warn"}`}><b>{f.severity === "critical" ? "Critical:" : "Warning:"}</b>&nbsp;{f.text}</div>)}
      {r.status === "needs_input" && r.needs_input.length > 0 && (
        <div className="banner warn"><div><b>Needs input.</b><ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{r.needs_input.map((m) => <li key={m}>{m}</li>)}</ul>
          <Link to="/settings">Cost & margin settings</Link> · <Link to="/inventory">Edit the item</Link></div></div>
      )}

      <div className="grid g4">
        <Kpi label="Selling range (P25–P75)" value={sel ? <>{inr(sel.p25_gross as number)} – {inr(sel.p75_gross as number)}</> : "—"} small
          foot={sel ? <>incl. GST · ex-GST {inr(sel.p25_ex_gst as number)} – {inr(sel.p75_ex_gst as number)}</> : "No dependable estimate"} />
        <Kpi label="Wholesale range" value={r.wholesale.supported ? <>{inr(r.wholesale.p25_gross)} – {inr(r.wholesale.p75_gross)}</> : "Not supported"} small
          foot={r.wholesale.supported ? `${r.wholesale.count} ${r.wholesale.basis === "completed_sales" ? "completed wholesale sales" : "wholesale ASKING prices"}` : r.wholesale.note} />
        <Kpi label="Contribution / unit at recommended" value={inr(e.at_recommended?.contribution)} small tone={e.at_recommended && e.at_recommended.contribution < 0 ? "bad" : "good"}
          foot={e.at_recommended ? <>Margin {pct(e.at_recommended.margin)} · markup {pct(e.at_recommended.markup)} (not the same)</> : "—"} />
        <Kpi label="Line totals" value={r.lot ? inr(r.lot.recommended_buy_total as number) : "—"} small tone="accent"
          foot={r.lot ? <>{num(r.lot.quantity as number)} units · {num(r.lot.expected_saleable_units as number, 1)} expected saleable · contribution {inr(r.lot.expected_contribution_total as number)} · value {inr(r.lot.total_lot_value as number)}</> : "Quantity or buy price missing"} />
      </div>

      <Card title="Price ladder" actions={<span className="small muted">Every priced comparable, with the decision points</span>}>
        <div className="stack">
          <div>
            <h3>Selling side <span className="muted small">· tax-inclusive prices buyers pay</span></h3>
            <PriceLadder r={r} side="sell" />
          </div>
          <div>
            <h3>Buying side <span className="muted small">· purchase basis: {String(e.inputs.buy_price_basis)}</span></h3>
            <PriceLadder r={r} side="buy" />
          </div>
          <LadderLegend />
        </div>
      </Card>

      <div className="grid g2">
        <EconomicsCard r={r} />
        <Card title="Evidence quality" actions={r.confidence && <Grade g={r.confidence.grade} />}>
          {!r.confidence ? <div className="muted">No rating: there is no dependable estimate to rate.</div> : (
            <div className="stack-sm">
              <table className="t">
                <thead><tr><th>Component</th><th>Value</th><th className="num">Points</th></tr></thead>
                <tbody>
                  {r.confidence.components.map((c) => (
                    <tr key={c.component}><td>{c.component}</td><td>{c.value}</td><td className="num">{c.points}{c.max_points ? ` / ${c.max_points}` : ""}</td></tr>
                  ))}
                  <tr className="subtotal"><td>Total</td><td>Grade {r.confidence.grade}</td><td className="num">{r.confidence.score} / {r.confidence.max_score}</td></tr>
                </tbody>
              </table>
              <div className="tiny muted">{r.confidence.note}</div>
            </div>
          )}
          <h3 style={{ margin: "16px 0 8px" }}>Evidence sets</h3>
          <div className="tablewrap">
            <table className="t">
              <thead><tr><th>Set</th><th className="num">Used</th><th className="num">Sources</th><th className="num">Exact</th><th className="num">Median</th><th className="num">IQR/med</th><th className="num">Age</th><th /></tr></thead>
              <tbody>
                {Object.values(r.estimates).map((x) => (
                  <tr key={x.set}>
                    <td className="small">{x.set.replace(":", " · ")}{x.broadened_with_adjustments && <div className="tiny" style={{ color: "var(--warn)" }}>broadened with adjustments</div>}</td>
                    <td className="num">{x.count}</td><td className="num">{x.independent_sources}</td><td className="num">{pct(x.exact_share, 0)}</td>
                    <td className="num">{inr(x.p50)}</td><td className="num">{pct(x.dispersion_iqr_over_median)}</td><td className="num">{x.weighted_median_age_days ?? "—"} d</td>
                    <td>{x.sufficient ? <span className="badge good">sufficient</span> : <span className="badge" title={x.requirement}>thin</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {Object.keys(r.procurement_market).length > 0 && (
            <>
              <h3 style={{ margin: "16px 0 8px" }}>As-is procurement market <span className="muted small">(purchase basis, never used for selling prices)</span></h3>
              <table className="t">
                <tbody>
                  {Object.entries(r.procurement_market).map(([k, p]) => (
                    <tr key={k}><td>{p.label}</td><td className="num">{p.count} records</td><td className="num">{inr(p.p25_buy_basis)} – {inr(p.p75_buy_basis)}</td><td className="num">median {inr(p.p50_buy_basis)}</td></tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </Card>
      </div>

      <ComparablesCard comps={r.comparables} />

      <div className="grid g2">
        <Card title="Assumptions & rules applied">
          <div className="stack-sm">
            {r.assumptions.map((a) => (
              <div key={a.code} className="row" style={{ alignItems: "flex-start" }}>
                <span className={`badge ${a.severity === "warning" ? "warn" : ""}`}>{a.severity}</span>
                <div className="small">{a.text}{a.count != null && <span className="muted"> ({a.count} record{a.count === 1 ? "" : "s"})</span>}</div>
              </div>
            ))}
            <details className="small"><summary>Definitions</summary>
              <dl className="kv" style={{ marginTop: 8 }}>{Object.entries(r.definitions).map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>)}</dl>
            </details>
          </div>
        </Card>
        <Card title="Explanation" actions={<button className="btn sm" onClick={explain} disabled={!ai.data?.configured || !can("use_ai") || !!busy}
          title={ai.data?.configured ? "" : "No Claude API key configured on the server"}>{busy === "ai" ? <span className="spin" /> : d.data!.ai_explanation ? "Regenerate" : "Explain with AI"}</button>}>
          {d.data!.ai_explanation ? (
            <div className="stack-sm">
              <div style={{ whiteSpace: "pre-wrap" }}>{d.data!.ai_explanation.text}</div>
              {d.data!.ai_explanation.unverified_figures.length > 0 && (
                <div className="banner warn small">Figures not found in the valuation: {d.data!.ai_explanation.unverified_figures.join(", ")}. Trust the numbers above, not the prose.</div>
              )}
              <div className="tiny muted">{d.data!.ai_explanation.note} Model {d.data!.ai_explanation.model}, {dateTime(d.data!.ai_explanation.generated_at)}.</div>
            </div>
          ) : (
            <div className="muted small">
              {ai.data?.configured ? "Generate a plain-language summary of this result. The AI receives only the computed figures and never changes them."
                : "AI explanations are off because no Claude API key is configured. Everything on this page is produced without AI."}
            </div>
          )}
          <h3 style={{ margin: "16px 0 8px" }}>History for this item</h3>
          <table className="t">
            <tbody>
              {(history.data?.valuations ?? []).map((h) => (
                <tr key={h.id} className={h.id === s.id ? "sel" : "clickable"} onClick={() => h.id !== s.id && nav(`/valuations/${h.id}`)}>
                  <td className="small">#{h.id} · {dateTime(h.created_at)}</td><td><StatusBadge status={h.status} /></td>
                  <td className="num">{inr(h.recommended_buy)}</td><td className="mono tiny">{h.output_hash.slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}

function EconomicsCard({ r }: { r: ValuationResult }) {
  const e = r.economics;
  const options: [string, string, Economics | undefined][] = [
    ["rec", "At recommended buy · median sale", e.at_recommended],
    ["ceil", "At max safe buy · P25 sale", e.at_ceiling_conservative],
    ["ask", "At supplier ask · median sale", e.asking?.economics],
  ];
  const avail = options.filter((o) => o[2]);
  const [k, setK] = useState(avail[0]?.[0] ?? "rec");
  const cur = avail.find((o) => o[0] === k) ?? avail[0];
  const inp = e.inputs as Record<string, unknown>;
  return (
    <Card title="Unit economics (per purchased unit)">
      {!cur ? <div className="muted">No buying price could be computed; see the status above.</div> : (
        <>
          <div className="tabs">{avail.map((o) => <button key={o[0]} className={k === o[0] ? "on" : ""} onClick={() => setK(o[0])}>{o[1]}</button>)}</div>
          <table className="t">
            <tbody>
              {cur[2]!.lines.map((l) => (
                <tr key={l.label} className={l.subtotal ? "subtotal" : ""}><td>{l.label}</td><td className="num">{inr(l.amount)}</td></tr>
              ))}
              <tr><td>Contribution margin <span className="tiny muted">contribution ÷ revenue</span></td><td className="num"><b>{pct(cur[2]!.margin)}</b></td></tr>
              <tr><td>Markup <span className="tiny muted">contribution ÷ total cost</span></td><td className="num">{pct(cur[2]!.markup)}</td></tr>
            </tbody>
          </table>
        </>
      )}
      <h3 style={{ margin: "16px 0 8px" }}>Inputs and where they came from</h3>
      <dl className="kv small">
        <dt>Tax</dt><dd>{show(inp.tax_mode)} · GST {show(inp.gst_rate_pct)}% · buy prices {show(inp.buy_price_basis)}</dd>
        <dt>Target margin</dt><dd>{inp.target_margin_pct == null ? "not set" : `${inp.target_margin_pct}%`} <span className="muted">({show(inp.target_margin_source)})</span></dd>
        <dt>Ceiling margin</dt><dd>{show(inp.minimum_margin_for_ceiling_pct)}% at the P25 sale price</dd>
        <dt>Fault category</dt><dd>{show(inp.fault_category)} <span className="muted">({show(inp.fault_category_source)})</span></dd>
        <dt>Saleable yield</dt><dd>{inp.expected_yield_pct == null ? "not set" : `${inp.expected_yield_pct}%`} <span className="muted">({show(inp.yield_source)})</span></dd>
        <dt>Repair / refurb</dt><dd>{inr(inp.repair_cost_per_unit as number | null)} <span className="muted">({show(inp.repair_source)})</span></dd>
        <dt>Salvage</dt><dd>{inr(inp.salvage_per_unsold_unit as number | null)} <span className="muted">({show(inp.salvage_source)})</span></dd>
        {e.inputs.cost_lines.map((c) => (
          <Fragment key={c.name}><dt>{c.name}</dt><dd>{c.configured ? (c.type.startsWith("%") ? `${c.value}% ${c.type.slice(1)}` : `${inr(c.value)} ${c.type.replace("INR ", "")}`) : <span style={{ color: "var(--warn)" }}>not configured: treated as 0</span>}</dd></Fragment>
        ))}
      </dl>
    </Card>
  );
}

function ComparablesCard({ comps }: { comps: Comparable[] }) {
  const [tab, setTab] = useState<"in" | "out">("in");
  const included = comps.filter((c) => c.included);
  const excluded = comps.filter((c) => !c.included);
  const reasons = useMemo(() => {
    const m = new Map<string, number>();
    excluded.forEach((c) => {
      const k = (c.exclusion ?? "").split(":")[0];
      m.set(k, (m.get(k) ?? 0) + 1);
    });
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [excluded]);
  const list = tab === "in" ? included : excluded;
  return (
    <Card tight title={
      <div className="tabs" style={{ margin: 0, border: 0 }}>
        <button className={tab === "in" ? "on" : ""} onClick={() => setTab("in")}>Included comparables ({included.length})</button>
        <button className={tab === "out" ? "on" : ""} onClick={() => setTab("out")}>Excluded ({excluded.length})</button>
      </div>
    }>
      {tab === "out" && reasons.length > 0 && (
        <div className="row wrap" style={{ padding: "10px 14px", borderBottom: "1px solid var(--line)" }}>
          {reasons.map(([k, n]) => <span key={k} className="badge">{k} · {n}</span>)}
        </div>
      )}
      <div className="tablewrap" style={{ maxHeight: 560 }}>
        <table className="t">
          <thead>
            <tr><th>Evidence</th><th>Source</th><th className="num">Price as recorded</th><th className="num">Normalised (incl. GST)</th>
              {tab === "in" ? <><th className="num">Adjusted</th><th>Match</th><th className="num">Weight</th></> : <th>Reason excluded</th>}
              <th className="num">Age</th></tr>
          </thead>
          <tbody>
            {list.map((c) => (
              <tr key={c.id} className={c.included ? "" : "excluded"}>
                <td>
                  <div className="small"><b>{c.kind_label}</b>{c.channel ? ` · ${c.channel}` : ""}</div>
                  <div className="tiny muted">{date(c.event_date)} · {c.id}</div>
                  <div className="tiny muted">{[c.spec.ram_gb != null ? `${c.spec.ram_gb}GB` : "RAM ?", c.spec.storage_gb != null ? `${c.spec.storage_gb}GB` : "storage ?", c.spec.condition_grade ? `Gr ${c.spec.condition_grade}` : "grade ?", c.spec.battery_health_pct != null ? `batt ${c.spec.battery_health_pct}%` : null].filter(Boolean).join(" · ")}</div>
                </td>
                <td className="small">
                  <div>{c.seller ?? <span className="muted">seller unknown</span>}{c.platform ? ` · ${c.platform}` : ""}</div>
                  {c.source_url ? <a href={c.source_url} target="_blank" rel="noopener noreferrer nofollow" className="tiny">source link <Icon.external /></a>
                    : <div className="tiny muted">{c.source_document}</div>}
                  {c.source_record_id && <div className="tiny muted mono">{c.source_record_id}</div>}
                  <Synthetic on={c.is_synthetic} />
                </td>
                <td className="num">{c.price != null ? inr(c.price) : "—"}<div className="tiny muted">{c.currency} · {c.tax_basis}</div></td>
                <td className="num">{inr(c.gross_price)}</td>
                {tab === "in" ? (
                  <>
                    <td className="num">
                      {inr(c.adjusted_price)}
                      {c.adjustments.map((a) => (
                        <div key={a.rule_id} className="tiny" style={{ color: "var(--warn)" }} title={a.basis || "no basis recorded"}>
                          {a.dimension_label} {a.comparable_value}→{a.subject_value}: {a.method === "percent" ? `${a.value > 0 ? "+" : ""}${a.value.toFixed(2)}%` : inr(a.value)}{!a.calibrated && " · uncalibrated"}
                        </div>
                      ))}
                    </td>
                    <td>
                      {c.match_tier && <span className={`badge ${TIER[c.match_tier][1]}`}>{TIER[c.match_tier][0]}</span>}
                      {c.unverified_dimensions.length > 0 && <div className="tiny muted">unknown: {c.unverified_dimensions.join(", ").replace(/_key|_gb|_in|_pct/g, "")}</div>}
                    </td>
                    <td className="num small" title="recency × match × source share">
                      <b>{c.weights?.final.toFixed(3)}</b>
                      <div className="tiny muted">{c.weights?.recency.toFixed(2)} × {c.weights?.match} × {c.weights?.source_share.toFixed(2)}</div>
                    </td>
                  </>
                ) : <td className="small" style={{ maxWidth: 380 }}>{c.exclusion}</td>}
                <td className="num small">{c.age_days != null ? `${c.age_days} d` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!list.length && <div className="empty">{tab === "in" ? "No comparables were used." : "Nothing was excluded."}</div>}
      </div>
    </Card>
  );
}
