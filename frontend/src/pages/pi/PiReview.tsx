import { useState } from "react";
import { Link } from "react-router-dom";
import { api, download } from "../../api";
import { Card, Drawer, Empty, ErrorBox, Kpi, Loading, PageHead } from "../../components/ui";
import { useApp, useLoad } from "../../context";
import { inr, inrShort, num } from "../../format";
import AssetDrawer from "./AssetDrawer";
import AutomaticValuation from "./AutomaticValuation";
import { BatchPicker, Confidence, Field, Pager, PiStatus, Steps, useBatchParam, usePiMeta } from "./shared";
import type { PiAsset, PiBatch } from "./types";
import { n, STATUS_TEXT } from "./types";

interface Page { total: number; page: number; page_size: number; items: PiAsset[] }

export default function PiReview() {
  const { can, toast } = useApp();
  const meta = usePiMeta();
  const [batchId, setBatchId] = useBatchParam();
  const [status, setStatus] = useState("");
  const [category, setCategory] = useState("");
  const [confidence, setConfidence] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("row");
  const [desc, setDesc] = useState(false);
  const [page, setPage] = useState(1);
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [open, setOpen] = useState<number | null>(null);
  const [bulk, setBulk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const PS = 100;

  const batch = useLoad(() => (batchId ? api.get<PiBatch>(`/api/pi/batches/${batchId}`) : Promise.resolve(null)), [batchId]);
  const qs = new URLSearchParams({ page: String(page), page_size: String(PS), sort, desc: String(desc) });
  if (status) qs.set("status", status);
  if (category) qs.set("category", category);
  if (confidence) qs.set("confidence", confidence);
  if (q) qs.set("q", q);
  const assets = useLoad(() => (batchId ? api.get<Page>(`/api/pi/batches/${batchId}/assets?${qs}`) : Promise.resolve(null)),
    [batchId, status, category, confidence, q, sort, desc, page]);

  const refresh = () => { assets.reload(); batch.reload(); };
  const act = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
      toast(msg);
      setSel(new Set());
      refresh();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const items = assets.data?.items ?? [];
  const b = batch.data;
  const sortBy = (k: string) => { if (sort === k) setDesc(!desc); else { setSort(k); setDesc(false); } setPage(1); };
  const th = (k: string, label: string, cls = "") => (
    <th className={cls} style={{ cursor: "pointer" }} onClick={() => sortBy(k)} aria-sort={sort === k ? (desc ? "descending" : "ascending") : "none"}>
      {label}{sort === k ? (desc ? " ↓" : " ↑") : ""}
    </th>
  );
  const filter = (setter: (v: string) => void) => (e: React.ChangeEvent<HTMLSelectElement | HTMLInputElement>) => { setter(e.target.value); setPage(1); };

  return (
    <div className="stack fade-in">
      <PageHead title="Asset pricing review" sub="Recommended Casterly purchase price per asset row (INR, ex-GST). Override with a reason, approve, then quote."
        actions={<>
          <BatchPicker value={batchId} onChange={(id) => { setBatchId(id); setPage(1); setSel(new Set()); }} />

          {b && <button className="btn" disabled={Number(b.estimated_value) <= 0} title={Number(b.estimated_value) <= 0 ? "Run automatic analysis first; no supported prices are available" : "Download current supported prices"} onClick={() => download(`/api/pi/batches/${b.id}/export`, "priced.xlsx")}>Download priced Excel</button>}
          {b && can("pi_quote") && <Link className="btn primary" to={`/pi/quotations?batch=${b.id}`}>Create quotation</Link>}
        </>} />
      <Steps at={3} />
      <ErrorBox error={err} />
      {!batchId ? <Empty>Select a valuation batch, or <Link to="/pi/import">import a vendor workbook</Link>.</Empty> : !b ? <Loading /> : (
        <>
          <AutomaticValuation batchId={b.id} onComplete={refresh} />
          <div className="grid g5">
            <Kpi label="Lines / units" value={`${num(b.lines)} / ${num(b.units)}`} small />
            <Kpi label="Estimated purchase value" value={inrShort(n(b.estimated_value))} tone="accent" small />
            <Kpi label="Approved" value={num(b.by_status.approved?.lines ?? 0)} tone="good" small />
            <Kpi label="Review / provisional" value={num((b.by_status.review?.lines ?? 0) + (b.by_status.provisional?.lines ?? 0))} small />
            <Kpi label="Manual pricing" value={num(b.by_status.manual_required?.lines ?? 0)} tone={b.by_status.manual_required ? "bad" : undefined} small
              foot={<Link to={`/pi/exceptions?batch=${b.id}`}>{num(b.open_exceptions)} open exceptions</Link>} />
          </div>
          {b.status === "imported" && <div className="banner info">Not priced yet. Click <b>Analyze &amp; Calculate Market Prices</b> above to run research, evidence validation and pricing.</div>}
          <Card tight title={
            <div className="row wrap" style={{ gap: 8 }}>
              <input placeholder="Search model, spec or serial" value={q} onChange={filter(setQ)} style={{ width: 240 }} aria-label="Search" />
              <select value={status} onChange={filter(setStatus)} aria-label="Status"><option value="">All statuses</option>{Object.entries(STATUS_TEXT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
              <select value={category} onChange={filter(setCategory)} aria-label="Category"><option value="">All categories</option>{Object.entries(meta.data?.categories ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
              <select value={confidence} onChange={filter(setConfidence)} aria-label="Confidence"><option value="">Any confidence</option>{["High", "Medium", "Low"].map((c) => <option key={c}>{c}</option>)}</select>
            </div>}
            actions={<div className="row" style={{ gap: 6 }}>
              <span className="small muted">{sel.size} selected</span>
              {can("pi_approve") && <button className="btn sm primary" disabled={!sel.size || busy} onClick={() => act(() => api.post("/api/pi/assets/approve", { asset_ids: [...sel] }), "Selected prices approved.")}>Approve</button>}
              {can("pi_override") && <button className="btn sm" disabled={!sel.size} onClick={() => setBulk(true)}>Override…</button>}
              {can("pi_approve") && <button className="btn sm ghost" disabled={busy} title="Approve every auto-priced line (High/Medium confidence, no open high-severity exceptions)"
                onClick={() => act(() => api.post(`/api/pi/batches/${b.id}/approve-all?statuses=auto_priced`), "All auto-priced lines approved.")}>Approve all auto-priced</button>}
            </div>}>
            {assets.error && <ErrorBox error={assets.error} />}
            {assets.loading && !assets.data ? <Loading /> : items.length === 0 ? <Empty>No rows match.</Empty> : (
              <>
                <div className="tablewrap">
                  <table className="t">
                    <thead>
                      <tr>
                        <th><input type="checkbox" aria-label="Select page" checked={items.length > 0 && items.every((a) => sel.has(a.id))}
                          onChange={(e) => { const s = new Set(sel); items.forEach((a) => (e.target.checked ? s.add(a.id) : s.delete(a.id))); setSel(s); }} /></th>
                        {th("row", "Row")}<th>Asset model</th><th>Specifications</th>{th("qty", "Qty", "num")}
                        <th className="num">Market benchmark</th>{th("price", "Market Unit Price", "num")}<th className="num">Total value</th>
                        <th>Confidence</th><th className="num">Sources</th>{th("status", "Status")}
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((a) => (
                        <tr key={a.id} className={`clickable ${sel.has(a.id) ? "sel" : ""}`} onClick={() => setOpen(a.id)}>
                          <td onClick={(e) => e.stopPropagation()}><input type="checkbox" aria-label={`Select row ${a.row_number}`} checked={sel.has(a.id)}
                            onChange={() => { const s = new Set(sel); if (s.has(a.id)) s.delete(a.id); else s.add(a.id); setSel(s); }} /></td>
                          <td className="small">{a.row_number}</td>
                          <td><b>{a.label ?? <span className="muted">unidentified</span>}</b><div className="tiny muted">{a.serial ?? ""}{a.grade ? ` · Grade ${a.grade}` : ""}</div></td>
                          <td className="small clip" title={a.original_spec ?? ""}>{a.original_spec}</td>
                          <td className="num">{a.quantity ?? <span style={{ color: "var(--bad)" }}>?</span>}</td>
                          <td className="num">{inr(n(a.benchmark))}</td>
                          <td className="num"><b>{inr(n(a.final_price))}</b>{a.override_price !== null && <div className="tiny" style={{ color: "var(--warn)" }}>override</div>}</td>
                          <td className="num">{inr(n(a.total_value))}</td>
                          <td><Confidence c={a.confidence} /></td>
                          <td className="num">{a.sources || "—"}</td>
                          <td><PiStatus s={a.status} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <Pager page={page} pageSize={PS} total={assets.data!.total} onPage={setPage} />
              </>
            )}
          </Card>
        </>
      )}
      {open && <AssetDrawer assetId={open} onClose={() => setOpen(null)} onChanged={refresh} />}
      {bulk && <BulkOverride ids={[...sel]} onClose={() => setBulk(false)} onDone={() => { setBulk(false); setSel(new Set()); refresh(); }} />}
    </div>
  );
}

function BulkOverride({ ids, onClose, onDone }: { ids: number[]; onClose: () => void; onDone: () => void }) {
  const { toast } = useApp();
  const [price, setPrice] = useState("");
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    try {
      await api.post("/api/pi/assets/override", { asset_ids: ids, price: price.trim() || null, reason });
      toast(`${ids.length} price(s) overridden.`);
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <Drawer title={`Override ${ids.length} price(s)`} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={reason.trim().length < 5} onClick={save}>Save override</button></>}>
      <div className="stack">
        <ErrorBox error={err} />
        <div className="small muted">The calculated price is kept; the override becomes the Market Unit Price and is recorded with your reason. Leave the price blank to clear overrides.</div>
        <Field label="Unit price (₹, ex-GST)"><input inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} /></Field>
        <Field label="Reason (required)"><input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </div>
    </Drawer>
  );
}
