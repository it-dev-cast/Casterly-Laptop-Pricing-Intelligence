import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import { Card, ErrorBox, PageHead } from "../../components/ui";
import { useApp } from "../../context";
import { Field, usePiMeta } from "./shared";
import type { PiBatch } from "./types";

interface Line { description: string; make: string; model: string; cpu: string; ram: string; storage: string; grade: string; quantity: string; category: string }
const EMPTY: Line = { description: "", make: "", model: "", cpu: "", ram: "", storage: "", grade: "B", quantity: "1", category: "" };

export default function PiNewValuation() {
  const { toast } = useApp();
  const nav = useNavigate();
  const meta = usePiMeta();
  const [name, setName] = useState("");
  const [vendor, setVendor] = useState("");
  const [lines, setLines] = useState<Line[]>([{ ...EMPTY }]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const up = (i: number, k: keyof Line, v: string) => setLines(lines.map((l, j) => (j === i ? { ...l, [k]: v } : l)));

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      const assets = lines.filter((l) => l.description.trim()).map((l) => ({
        description: l.description, make: l.make || null, model: l.model || null, cpu: l.cpu || null, ram: l.ram || null,
        storage: l.storage || null, grade: l.grade || null, quantity: Number(l.quantity) || 1, category: l.category || null,
      }));
      const b = await api.post<PiBatch>("/api/pi/batches/manual", { name: name || "Quick valuation", vendor: vendor || null, assets });
      await api.post(`/api/pi/batches/${b.id}/price`);
      toast("Valuation created.");
      nav(`/pi/review?batch=${b.id}`);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack fade-in">
      <PageHead title="New market valuation" sub="Value a few assets without a workbook. Each line is identified and priced from verified evidence; research can be started from the review screen." />
      <ErrorBox error={err} />
      <Card title="Valuation">
        <div className="formgrid">
          <Field label="Name"><input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Acme lease return — Oct" /></Field>
          <Field label="Vendor"><input value={vendor} onChange={(e) => setVendor(e.target.value)} /></Field>
        </div>
      </Card>
      <Card title="Assets" actions={<button className="btn sm" onClick={() => setLines([...lines, { ...EMPTY }])}>Add line</button>} tight>
        <div className="tablewrap">
          <table className="t">
            <thead><tr><th>Description *</th><th>Category</th><th>Make</th><th>Model / part no.</th><th>CPU / spec</th><th>RAM</th><th>Storage</th><th>Grade</th><th>Qty</th><th /></tr></thead>
            <tbody>
              {lines.map((l, i) => (
                <tr key={i}>
                  <td><input value={l.description} onChange={(e) => up(i, "description", e.target.value)} placeholder="Dell Latitude 5430 i7-1265U 16GB 512GB" style={{ minWidth: 240 }} /></td>
                  <td><select value={l.category} onChange={(e) => up(i, "category", e.target.value)}><option value="">auto-detect</option>
                    {Object.entries(meta.data?.categories ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></td>
                  {(["make", "model", "cpu", "ram", "storage"] as const).map((k) => <td key={k}><input value={l[k]} onChange={(e) => up(i, k, e.target.value)} style={{ width: k === "model" || k === "cpu" ? 150 : 80 }} /></td>)}
                  <td><select value={l.grade} onChange={(e) => up(i, "grade", e.target.value)}><option value="">?</option>{["A+", "A", "B", "C", "D"].map((g) => <option key={g}>{g}</option>)}</select></td>
                  <td><input value={l.quantity} inputMode="numeric" onChange={(e) => up(i, "quantity", e.target.value)} style={{ width: 60 }} /></td>
                  <td><button className="btn sm ghost" aria-label="Remove line" disabled={lines.length === 1} onClick={() => setLines(lines.filter((_, j) => j !== i))}>✕</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <div className="row"><div className="spacer" />
        <button className="btn primary" disabled={busy || !lines.some((l) => l.description.trim())} onClick={submit}>{busy ? <span className="spin" /> : "Identify and price"}</button>
      </div>
    </div>
  );
}
