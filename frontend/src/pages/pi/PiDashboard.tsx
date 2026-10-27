import { Fragment } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { Card, Empty, ErrorBox, Kpi, Loading, PageHead } from "../../components/ui";
import { useApp, useLoad } from "../../context";
import { dateTime, inr, inrShort, num } from "../../format";
import type { PiQuote } from "./types";
import { n, STATUS_TEXT } from "./types";

interface Dash {
  assets: number; units: number; estimated_value: string | null;
  by_category: { category: string; label: string; lines: number; units: number; value: string | null }[];
  by_status: Record<string, number>; confidence: Record<string, number>; research_completion: number | null;
  products: number; products_with_evidence: number; review_required: number; open_exceptions: number;
  recent_quotations: PiQuote[]; recent_batches: { id: number; name: string; status: string; layout: string; created_at: string }[];
  rules: { version: number; name: string; gaps: { category: string; item: string; detail: string }[] };
  providers: { name: string; label: string; configured: boolean; note: string | null }[];
}

export default function PiDashboard() {
  const { can } = useApp();
  const d = useLoad(() => api.get<Dash>("/api/pi/dashboard"), []);
  if (d.loading && !d.data) return <Loading />;
  if (d.error) return <ErrorBox error={d.error} />;
  const x = d.data!;
  const live = x.providers.filter((p) => p.configured);
  const maxUnits = Math.max(1, ...x.by_category.map((c) => c.units));
  return (
    <div className="stack fade-in">
      <PageHead title="Pricing Intelligence" sub="Procurement-side valuation of used IT assets: identify, research the Indian market, calculate a recommended vendor buy price, review, quote."
        actions={<>
          {can("pi_import") && <Link className="btn" to="/pi/new">New market valuation</Link>}
          {can("pi_import") && <Link className="btn primary" to="/pi/import">Import vendor Excel</Link>}
        </>} />
      {live.length === 0 && (
        <div className="banner warn">
          <div><b>No live market-research provider is configured.</b> Research requires a licensed search API key on the server
            (CLPI_BRAVE_API_KEY or CLPI_TAVILY_API_KEY). Pricing still works from verified manual quotes, recorded transactions and
            historical reference valuations; no live coverage is claimed.</div>
        </div>
      )}
      <div className="grid g4">
        <Kpi label="Uploaded asset lines" value={num(x.assets)} foot={`${num(x.units)} units`} />
        <Kpi label="Estimated purchase value" value={inrShort(n(x.estimated_value))} tone="accent" foot="Sum of Market Unit Price × qty, ex-GST" />
        <Kpi label="Verified evidence coverage" value={x.research_completion == null ? "—" : `${x.research_completion}%`} foot={`${x.products_with_evidence} of ${x.products} imported products have verified priced evidence (check dates)`} />
        <Kpi label="Needs review / manual" value={num(x.review_required)} tone={x.review_required ? "bad" : "good"} foot={`${num(x.open_exceptions)} open exceptions`} />
      </div>
      <div className="grid g2">
        <Card title="By product category">
          {x.by_category.length === 0 ? <Empty>No assets imported yet.</Empty> : (
            <table className="t">
              <thead><tr><th>Category</th><th className="num">Lines</th><th className="num">Units</th><th style={{ width: "30%" }} /><th className="num">Value</th></tr></thead>
              <tbody>
                {x.by_category.map((c) => (
                  <tr key={c.category}>
                    <td>{c.label}</td><td className="num">{num(c.lines)}</td><td className="num">{num(c.units)}</td>
                    <td><div className="meter"><i style={{ width: `${(100 * c.units) / maxUnits}%` }} /></div></td>
                    <td className="num">{inrShort(n(c.value))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Pricing status & confidence">
          <div className="grid g2">
            <dl className="kv small">
              {Object.entries(x.by_status).map(([k, v]) => <Fragment key={k}><dt>{STATUS_TEXT[k] ?? k}</dt><dd>{num(v)} lines</dd></Fragment>)}
            </dl>
            <dl className="kv small">
              {["High", "Medium", "Low"].map((k) => <Fragment key={k}><dt>{k} confidence</dt><dd>{num(x.confidence[k] ?? 0)} groups</dd></Fragment>)}
            </dl>
          </div>
          <div className="tiny muted" style={{ marginTop: 10 }}>Confidence is a transparent rule-based score (sources, freshness, exact match, agreement, completeness); it is not a probability.</div>
        </Card>
      </div>
      <div className="grid g2">
        <Card title="Recent valuation batches" actions={<Link className="btn sm ghost" to="/pi/reports">All reports</Link>}>
          {x.recent_batches.length === 0 ? <Empty>Import a vendor workbook to start.</Empty> : (
            <table className="t"><tbody>
              {x.recent_batches.map((b) => (
                <tr key={b.id}><td><Link to={`/pi/review?batch=${b.id}`}>#{b.id} {b.name}</Link><div className="tiny muted">{b.layout.toUpperCase()} · {dateTime(b.created_at)}</div></td><td><span className="badge">{b.status}</span></td></tr>
              ))}
            </tbody></table>
          )}
        </Card>
        <Card title="Recent quotations" actions={<Link className="btn sm ghost" to="/pi/quotations">Quotations</Link>}>
          {x.recent_quotations.length === 0 ? <Empty>No quotations yet.</Empty> : (
            <table className="t"><tbody>
              {x.recent_quotations.map((q) => (
                <tr key={q.id}><td><b>{q.quote_ref}</b><div className="tiny muted">{q.vendor ?? "—"} · {q.lines} lines · {num(q.units)} units</div></td><td className="num">{inr(n(q.total))}</td><td><span className="badge">{q.status}</span></td></tr>
              ))}
            </tbody></table>
          )}
        </Card>
      </div>
      {x.rules.gaps.length > 0 && (
        <Card title={`Pricing rules v${x.rules.version}: configuration gaps`} actions={<Link className="btn sm" to="/pi/rules">Configure</Link>}>
          <div className="small muted" style={{ marginBottom: 8 }}>Nothing is invented: unconfigured conversions stop pricing (manual pricing required); unconfigured adjustments apply 0% and are listed as assumptions.</div>
          <table className="t">
            <thead><tr><th>Category</th><th>Not configured</th></tr></thead>
            <tbody>{Object.entries(x.rules.gaps.reduce<Record<string, string[]>>((acc, g) => {
              (acc[g.category] ??= []).push(g.item === "conversion" ? "retail/second-hand → buy conversion" : g.item === "grade" ? "grade adjustments" : g.item === "quantity" ? "quantity discounts" : "risk adjustments");
              return acc;
            }, {})).map(([c, items]) => <tr key={c}><td className="small">{c === "*" ? "All categories" : c.replace(/_/g, " ")}</td><td className="small muted">{items.join(" · ")}</td></tr>)}</tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
