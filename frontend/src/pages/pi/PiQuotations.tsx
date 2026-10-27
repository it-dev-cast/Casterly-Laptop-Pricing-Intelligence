import { useState } from "react";
import { api, download } from "../../api";
import { Card, Drawer, Empty, ErrorBox, Loading, PageHead } from "../../components/ui";
import { useApp, useLoad } from "../../context";
import { date, dateTime, inr, num } from "../../format";
import { BatchPicker, Field, Steps, useBatchParam } from "./shared";
import type { PiBatch, PiQuote } from "./types";
import { n } from "./types";

interface QuoteDetail extends PiQuote {
  items: { asset_id: number; row_number: number; serial: string | null; description: string; quantity: number; unit_price: string; line_total: string; basis: string }[];
}

export default function PiQuotations() {
  const { can, toast } = useApp();
  const [batchId, setBatchId] = useBatchParam();
  const batch = useLoad(() => (batchId ? api.get<PiBatch>(`/api/pi/batches/${batchId}`) : Promise.resolve(null)), [batchId]);
  const quotes = useLoad(() => api.get<PiQuote[]>(`/api/pi/quotations${batchId ? `?batch_id=${batchId}` : ""}`), [batchId]);
  const [vendor, setVendor] = useState("");
  const [notes, setNotes] = useState("");
  const [days, setDays] = useState("7");
  const [unapproved, setUnapproved] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const b = batch.data;

  const create = async () => {
    if (!b) return;
    setBusy(true);
    setErr(null);
    try {
      const q = await api.post<PiQuote>(`/api/pi/batches/${b.id}/quotations`, { vendor: vendor || null, notes: notes || null, valid_days: Number(days) || 7, include_unapproved: unapproved });
      toast(q.created ? `Quotation ${q.quote_ref} created.` : `Prices unchanged: existing quotation ${q.quote_ref} returned.`);
      quotes.reload();
      setOpen(q.id);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack fade-in">
      <PageHead title="Vendor purchase quotation" sub="Quote approved Market Unit Prices to the vendor. Creating the same quotation twice returns the existing one." actions={<BatchPicker value={batchId} onChange={setBatchId} autoSelect={false} />} />
      <Steps at={4} />
      <ErrorBox error={err} />
      {b && can("pi_quote") && (
        <Card title={`New quotation for #${b.id} ${b.name}`}>
          <div className="small muted" style={{ marginBottom: 10 }}>{num(b.by_status.approved?.lines ?? 0)} approved lines of {num(b.lines)}. Lines without a price are always excluded.</div>
          <div className="formgrid">
            <Field label="Vendor"><input value={vendor} placeholder={b.vendor ?? ""} onChange={(e) => setVendor(e.target.value)} /></Field>
            <Field label="Valid for (days)"><input inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value)} /></Field>
            <Field label="Notes"><input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="subject to inspection, 7-day DOA return" /></Field>
            <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}><input type="checkbox" checked={unapproved} onChange={(e) => setUnapproved(e.target.checked)} />Include priced but unapproved lines</label>
          </div>
          <div className="row" style={{ marginTop: 10 }}><div className="spacer" /><button className="btn primary" disabled={busy} onClick={create}>{busy ? <span className="spin" /> : "Create quotation"}</button></div>
        </Card>
      )}
      <Card title="Quotations" tight>
        {quotes.loading && !quotes.data ? <Loading /> : (quotes.data ?? []).length === 0 ? <Empty>No quotations yet.</Empty> : (
          <table className="t">
            <thead><tr><th>Reference</th><th>Vendor</th><th className="num">Lines</th><th className="num">Units</th><th className="num">Total (ex-GST)</th><th>Valid until</th><th>Status</th><th /></tr></thead>
            <tbody>{quotes.data!.map((q) => (
              <tr key={q.id} className="clickable" onClick={() => setOpen(q.id)}>
                <td><b>{q.quote_ref}</b><div className="tiny muted">batch #{q.batch_id} · {dateTime(q.created_at)}</div></td><td>{q.vendor ?? "—"}</td>
                <td className="num">{num(q.lines)}{q.excluded_lines ? <div className="tiny muted">{q.excluded_lines} excluded</div> : null}</td><td className="num">{num(q.units)}</td>
                <td className="num"><b>{inr(n(q.total))}</b></td><td>{date(q.valid_until)}</td><td><span className={`badge ${q.status === "issued" ? "good" : q.status === "superseded" ? "" : "info"}`}>{q.status}</span></td>
                <td onClick={(e) => e.stopPropagation()}><button className="btn sm" onClick={() => download(`/api/pi/quotations/${q.id}/export`, `${q.quote_ref}.xlsx`)}>Excel</button></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Card>
      {open && <QuoteDrawer id={open} onClose={() => setOpen(null)} onChanged={() => quotes.reload()} />}
    </div>
  );
}

function QuoteDrawer({ id, onClose, onChanged }: { id: number; onClose: () => void; onChanged: () => void }) {
  const { can, toast } = useApp();
  const q = useLoad(() => api.get<QuoteDetail>(`/api/pi/quotations/${id}`), [id]);
  const issue = async () => {
    try {
      await api.post(`/api/pi/quotations/${id}/issue`);
      toast("Quotation marked as issued.");
      q.reload();
      onChanged();
    } catch (e) {
      toast((e as Error).message, true);
    }
  };
  const d = q.data;
  return (
    <Drawer title={d ? d.quote_ref : "Quotation"} onClose={onClose} footer={d && <>
      {can("pi_quote") && d.status === "draft" && <button className="btn" onClick={issue}>Mark as issued</button>}
      <button className="btn primary" onClick={() => download(`/api/pi/quotations/${id}/export`, `${d.quote_ref}.xlsx`)}>Download Excel</button>
    </>}>
      {!d ? <Loading /> : (
        <div className="stack">
          <dl className="kv small"><dt>Vendor</dt><dd>{d.vendor ?? "—"}</dd><dt>Total</dt><dd>{inr(n(d.total))} ex-GST</dd><dt>Valid until</dt><dd>{date(d.valid_until)}</dd><dt>Notes</dt><dd>{d.notes ?? "—"}</dd></dl>
          <table className="t">
            <thead><tr><th>Row</th><th>Description</th><th className="num">Qty</th><th className="num">Unit</th><th className="num">Total</th><th>Basis</th></tr></thead>
            <tbody>{d.items.slice(0, 500).map((l) => (
              <tr key={l.asset_id}><td className="small">{l.row_number}</td><td className="small">{l.description}<div className="tiny muted">{l.serial}</div></td><td className="num">{l.quantity}</td>
                <td className="num">{inr(n(l.unit_price))}</td><td className="num">{inr(n(l.line_total))}</td><td className="tiny">{l.basis}</td></tr>
            ))}</tbody>
          </table>
          {d.items.length > 500 && <div className="small muted">Showing 500 of {d.items.length} lines; download the Excel for all.</div>}
        </div>
      )}
    </Drawer>
  );
}
