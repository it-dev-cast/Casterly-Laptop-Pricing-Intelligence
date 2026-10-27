import { useState } from "react";
import { api } from "../../api";
import { Card, Empty, ErrorBox, Loading, PageHead } from "../../components/ui";
import { useApp, useLoad } from "../../context";
import { num } from "../../format";
import { BatchPicker, Pager, Severity, useBatchParam } from "./shared";
import type { PiException } from "./types";

interface Res { summary: Record<string, number>; items: PiException[] }

export default function PiExceptions() {
  const { can, toast } = useApp();
  const [batchId, setBatchId] = useBatchParam();
  const [severity, setSeverity] = useState("high,medium");
  const [code, setCode] = useState("");
  const [resolved, setResolved] = useState("false");
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [note, setNote] = useState("");
  const [page, setPage] = useState(1);
  const PS = 100;
  const qs = new URLSearchParams({ ...(batchId ? { batch_id: String(batchId) } : {}), ...(severity ? { severity } : {}), ...(code ? { code } : {}),
    ...(resolved !== "all" ? { resolved } : {}), limit: "10000" });
  const r = useLoad(() => (batchId ? api.get<Res>(`/api/pi/exceptions?${qs}`) : Promise.resolve(null)), [batchId, severity, code, resolved]);
  const items = r.data?.items ?? [];
  const pageItems = items.slice((page - 1) * PS, page * PS);
  const resolve = async () => {
    try {
      const x = await api.post<{ resolved: number }>("/api/pi/exceptions/resolve", { ids: [...sel], note: note || null });
      toast(`${x.resolved} exception(s) resolved.`);
      setSel(new Set());
      r.reload();
    } catch (e) {
      toast((e as Error).message, true);
    }
  };
  return (
    <div className="stack fade-in">
      <PageHead title="Review exceptions" sub="Issues to verify before purchase, with their business impact and the recommended verification action." actions={<BatchPicker value={batchId} onChange={(id) => { setBatchId(id); setPage(1); }} />} />
      {!batchId ? <Empty>Select a valuation batch.</Empty> : (
        <>
          {r.data && (
            <div className="row wrap" style={{ gap: 6 }}>
              <button className={`chip ${code === "" ? "on" : ""}`} onClick={() => { setCode(""); setPage(1); }}>All open types</button>
              {Object.entries(r.data.summary).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
                <button key={k} className={`chip ${code === k ? "on" : ""}`} onClick={() => { setCode(k); setPage(1); }}>{k.replace(/_/g, " ")} {num(v)}</button>
              ))}
            </div>
          )}
          <Card tight title={<div className="row" style={{ gap: 8 }}>
            <select value={severity} onChange={(e) => { setSeverity(e.target.value); setPage(1); }} aria-label="Severity">
              <option value="high,medium">High & medium</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option><option value="">All severities</option>
            </select>
            <select value={resolved} onChange={(e) => { setResolved(e.target.value); setPage(1); }} aria-label="Resolution"><option value="false">Open</option><option value="true">Resolved</option><option value="all">All</option></select>
          </div>} actions={can("pi_approve") && <div className="row" style={{ gap: 6 }}>
            <input placeholder="Resolution note" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Resolution note" />
            <button className="btn sm primary" disabled={!sel.size} onClick={resolve}>Resolve {sel.size || ""}</button>
          </div>}>
            {r.error && <ErrorBox error={r.error} />}
            {r.loading && !r.data ? <Loading /> : items.length === 0 ? <Empty>No exceptions match.</Empty> : (
              <>
                <div className="tablewrap">
                  <table className="t">
                    <thead><tr>
                      <th><input type="checkbox" aria-label="Select all matching" checked={sel.size === items.length} onChange={(e) => setSel(e.target.checked ? new Set(items.map((x) => x.id)) : new Set())} /></th>
                      <th>Severity</th><th>Issue</th><th>Row</th><th>Product</th><th>Business impact</th><th>Verification action</th>
                    </tr></thead>
                    <tbody>{pageItems.map((x) => (
                      <tr key={x.id} className={x.resolved ? "excluded" : ""}>
                        <td><input type="checkbox" aria-label="select" checked={sel.has(x.id)} onChange={() => { const s = new Set(sel); if (s.has(x.id)) s.delete(x.id); else s.add(x.id); setSel(s); }} /></td>
                        <td><Severity s={x.severity} /></td>
                        <td className="small"><b>{x.code.replace(/_/g, " ")}</b><div className="muted">{x.message}</div></td>
                        <td className="small">{x.row_number ?? "all rows"}{x.serial ? <div className="tiny muted">{x.serial}</div> : null}</td>
                        <td className="small">{x.product}</td><td className="small">{x.impact}</td><td className="small">{x.action}{x.resolution_note && <div className="tiny muted">Resolved: {x.resolution_note}</div>}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
                <Pager page={page} pageSize={PS} total={items.length} onPage={setPage} />
              </>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
