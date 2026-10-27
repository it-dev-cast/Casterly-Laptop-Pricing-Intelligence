// Pricing Intelligence API types. Money values arrive as decimal strings (never floats) or null.

export type Money = string | null;

export interface PiJob {
  id: number; batch_id: number | null; provider: string; status: string; total: number; done: number; failed: number;
  cached: number; observations_found: number; cancel_requested: boolean; error: string | null;
  started_at: string | null; finished_at: string | null; created_at: string;
}

export interface PiBatch {
  id: number; name: string; vendor: string | null; original_filename: string; layout: string; sheet_name: string | null;
  header_row: number | null; column_map: Record<string, string>; price_column: string | null; qty_column: string | null;
  detection: {
    headers: string[]; skipped_rows: { row: number; reason: string }[]; skipped_count: number; warnings: string[];
    candidates: { sheet: string; header_row: number; layout: string; score: number }[]; data_rows: number;
    default_grade?: string | null;
  } | null;
  status: string; rule_version_id: number | null; priced_at: string | null; created_at: string; lines: number; units: number;
  by_status: Record<string, { lines: number; units: number }>; estimated_value: Money; products: number;
  open_exceptions: number; latest_job: PiJob | null;
}

export interface PiAsset {
  id: number; batch_id: number; sheet: string; row_number: number; serial: string | null; quantity: number | null;
  category: string; grade: string | null; original_spec: string | null; label: string | null;
  normalized: Record<string, unknown>; identify_confidence: string; product_id: number | null; status: string;
  calculated_price: Money; override_price: Money; override_reason: string | null; final_price: Money; total_value: Money;
  benchmark: Money; confidence: string | null; estimate_status: string | null; estimate_id: number | null; sources: number;
  approved_at: string | null; research_methods?: string[]; pricing_date?: string | null; evidence_urls?: string[];
}

export interface PiEstimate {
  id: number; batch_id: number; product_id: number; grade: string; status: string; benchmark: Money;
  recommended_unit: Money; opening_unit: Money; max_unit: Money; resale_unit: Money; margin_pct: Money;
  confidence: string | null; confidence_score: number | null; group_quantity: number; as_of: string;
  rule_version_id: number; engine_version: string; is_current: boolean; created_at: string; input_hash: string;
}

export interface BreakdownObs {
  id: number; price_type: string; price_type_label: string; match_quality: string; observed: string | null;
  currency: string; tax_basis: string; observed_at: string; source: string; url: string | null; title: string | null;
  included: boolean; exclusion: string | null; ex_gst: string | null; factor: string | null; converted: string | null;
  weight: number | null; stale: boolean; age_days: number; research_mode?: string | null; source_timestamp?: string | null;
}

export interface Breakdown {
  status: string; benchmark: Money; recommended_unit: Money; message: string; rules_name: string; as_of: string;
  steps: { step: string; label: string; value?: string; pct?: string; detail: string }[];
  observations: BreakdownObs[]; assumptions: string[]; flags: string[];
  confidence: string | null; confidence_score: number | null; confidence_parts: { label: string; points: number }[];
  dispersion?: number;
}

export interface PiObservation {
  id: number; product_id: number; provider: string; price_type: string; match_quality: string; title: string | null;
  price: Money; currency: string; tax_basis: string; condition: string | null; seller: string | null; url: string | null;
  observed_at: string; retrieved_at: string | null; snippet: string | null; status: string; status_reason: string | null;
  attributes: Record<string, unknown> | null;
  source: { id: number; name: string; domain: string; reliability: number } | null;
}

export interface PiGroup {
  product_id: number | null; label: string; category: string | null; grade: string | null; lines: number; units: number;
  observations: number; verified: number; candidates: number; estimate: PiEstimate | null;
}

export interface PiException {
  id: number; batch_id: number; asset_id: number | null; product_id: number | null; code: string; severity: string;
  message: string; impact: string; action: string; resolved: boolean; resolution_note: string | null;
  row_number: number | null; serial: string | null; product: string | null;
}

export interface PiQuote {
  id: number; quote_ref: string; batch_id: number; vendor: string | null; status: string; lines: number; units: number;
  total: Money; excluded_lines: number; valid_until: string | null; notes: string | null; created_at: string;
  created?: boolean;
}

export interface PiMeta {
  categories: Record<string, string>; price_types: Record<string, string>; fields: Record<string, string>;
  providers: { name: string; label: string; configured: boolean; env_var: string | null; note: string | null }[];
  default_provider: string | null; rules_version: number; statuses: string[];
}

export const STATUS_TEXT: Record<string, string> = {
  unpriced: "Unpriced", auto_priced: "Auto-priced", provisional: "Provisional", review: "Review",
  manual_required: "Manual pricing", approved: "Approved",
};

export const STATUS_TONE: Record<string, string> = {
  auto_priced: "good", approved: "dark", provisional: "warn", review: "warn", manual_required: "bad", unpriced: "",
};

export const n = (v: Money | number | undefined): number | null => (v === null || v === undefined || v === "" ? null : Number(v));
