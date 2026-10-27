import { Icon } from "./Icons";

export const TEMPLATE_TYPES: { key: string; label: string; rows: string }[] = [
  { key: "inventory", label: "Inventory to value", rows: "one row per model / configuration line in the lot" },
  { key: "transaction", label: "Completed purchases & sales", rows: "one row per invoice line" },
  { key: "listing", label: "Advertised listings", rows: "one row per listing observed" },
  { key: "quote", label: "Supplier quotations", rows: "one row per quoted line" },
];

function fileName(key: string, ext: string) {
  const t = TEMPLATE_TYPES.find((x) => x.key === key);
  return `Casterly - ${t?.label ?? key} upload template.${ext}`;
}

/** Plain link button for page headers. */
export function TemplateButton({ recordType, label = "Download template" }: { recordType: string; label?: string }) {
  return (
    <a className="btn" href={`/templates/${recordType}_template.xlsx`} download={fileName(recordType, "xlsx")}
      title="Excel file with the exact columns the importer expects, plus a column guide">
      <Icon.download /> {label}
    </a>
  );
}

/** Prominent panel: download the sample format, fill it, upload it. */
export function TemplatePanel({ recordType }: { recordType: string }) {
  const t = TEMPLATE_TYPES.find((x) => x.key === recordType)!;
  return (
    <div className="tplpanel fade-in">
      <div className="tplicon"><Icon.download /></div>
      <div style={{ flex: 1, minWidth: 240 }}>
        <h3>Sample format: {t.label}</h3>
        <ol className="small" style={{ margin: "6px 0 0", paddingLeft: 18 }}>
          <li>Download the Excel template.</li>
          <li>Fill the <b>Data</b> sheet ({t.rows}). Keep the header row as it is; dropdowns show the allowed values.</li>
          <li>Leave a cell blank when a value is unknown; enter 0 only when it really is zero.</li>
          <li>Save and upload the file below. The columns are recognised automatically.</li>
        </ol>
        <div className="tiny muted" style={{ marginTop: 6 }}>The <b>Instructions</b> sheet lists every column, whether it is required, and the format expected.</div>
      </div>
      <div className="row wrap">
        <a className="btn primary" href={`/templates/${recordType}_template.xlsx`} download={fileName(recordType, "xlsx")}>
          <Icon.download /> Download Excel template
        </a>
        <a className="btn" href={`/templates/${recordType}_template.csv`} download={fileName(recordType, "csv")}>CSV version</a>
      </div>
    </div>
  );
}

/** All templates at once, before a record type is chosen. */
export function TemplateList() {
  return (
    <table className="t">
      <tbody>
        {TEMPLATE_TYPES.map((t) => (
          <tr key={t.key}>
            <td><b>{t.label}</b><div className="tiny muted">{t.rows}</div></td>
            <td className="right nowrap">
              <a className="btn sm" href={`/templates/${t.key}_template.xlsx`} download={fileName(t.key, "xlsx")}><Icon.download /> Excel</a>{" "}
              <a className="btn sm ghost" href={`/templates/${t.key}_template.csv`} download={fileName(t.key, "csv")}>CSV</a>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
