import { Link } from "react-router-dom";
import { api, download } from "../../api";
import { Card, Empty, Loading, PageHead } from "../../components/ui";
import { useLoad } from "../../context";
import { dateTime, inrShort, num } from "../../format";
import { Accuracy } from "./PiHistory";
import type { PiBatch } from "./types";
import { n } from "./types";

export default function PiReports() {
  const b = useLoad(() => api.get<PiBatch[]>("/api/pi/batches"), []);
  return (
    <div className="stack fade-in">
      <PageHead title="Valuation reports" sub="Each batch exports as the vendor's original workbook with Market Unit Price filled, plus Valuation Summary, Model Pricing Evidence, Review Before Purchase, Rate Benchmarks and Research Sources sheets." />
      <Card tight>
        {b.loading && !b.data ? <Loading /> : (b.data ?? []).length === 0 ? <Empty>No valuations yet.</Empty> : (
          <table className="t">
            <thead><tr><th>Batch</th><th>Layout</th><th className="num">Lines</th><th className="num">Units</th><th className="num">Est. purchase value</th><th className="num">Approved</th><th className="num">Manual</th><th>Priced</th><th /></tr></thead>
            <tbody>{b.data!.map((x) => (
              <tr key={x.id}>
                <td><Link to={`/pi/review?batch=${x.id}`}><b>#{x.id} {x.name}</b></Link><div className="tiny muted">{x.original_filename}{x.vendor ? ` · ${x.vendor}` : ""}</div></td>
                <td className="small">{x.layout.toUpperCase()}</td><td className="num">{num(x.lines)}</td><td className="num">{num(x.units)}</td>
                <td className="num"><b>{inrShort(n(x.estimated_value))}</b></td><td className="num">{num(x.by_status.approved?.lines ?? 0)}</td>
                <td className="num">{num(x.by_status.manual_required?.lines ?? 0)}</td><td className="small">{x.priced_at ? dateTime(x.priced_at) : "not priced"}</td>
                <td><button className="btn sm" onClick={() => download(`/api/pi/batches/${x.id}/export`, "priced.xlsx")}>Download Excel</button></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Card>
      <Accuracy />
    </div>
  );
}
