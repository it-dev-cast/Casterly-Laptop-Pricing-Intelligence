export interface User {
  id: number;
  email: string;
  name: string;
  role: "admin" | "procurement" | "sales";
  is_active: boolean;
  permissions: string[];
}

export interface ValuationSummary {
  id: number;
  inventory_item_id: number;
  created_at: string;
  as_of: string;
  status: "ok" | "insufficient_evidence" | "needs_input";
  rating: string | null;
  is_synthetic: boolean;
  channel: string;
  selling_p25: number | null;
  selling_p50: number | null;
  selling_p75: number | null;
  selling_basis: string | null;
  listing_price: number | null;
  target_buy: number | null;
  max_safe_buy: number | null;
  recommended_buy: number | null;
  expected_margin: number | null;
  expected_contribution_unit: number | null;
  asking_verdict: string | null;
  flags: string[];
  quantity: number | null;
  recommended_buy_total: number | null;
  max_safe_buy_total: number | null;
  expected_contribution_total: number | null;
  total_lot_value: number | null;
  asking_total: number | null;
  comparables_included: number;
  comparables_considered: number;
  output_hash: string;
  label?: string | null;
}

export interface InventoryItem {
  id: number;
  label: string;
  item_ref: string | null;
  lot_id: number | null;
  lot_ref: string | null;
  brand: string;
  model: string;
  cpu: string | null;
  ram_gb: number | null;
  storage_gb: number | null;
  storage_type: string | null;
  condition_grade: string | null;
  quantity: number | null;
  asking_price: number | null;
  asking_tax_basis: string;
  refurbishment_cost: number | null;
  intended_channel: string | null;
  target_margin_pct: number | null;
  expected_yield_pct: number | null;
  faults: string[] | null;
  fault_category: string | null;
  is_synthetic: boolean;
  status: string;
  latest_valuation: ValuationSummary | null;
  [k: string]: unknown;
}

export interface Adjustment {
  rule_id: string;
  dimension: string;
  dimension_label: string;
  comparable_value: string;
  subject_value: string;
  method: string;
  value: number;
  inverse_of_rule: boolean;
  calibrated: boolean;
  basis: string;
  price_before: number;
  price_after: number;
}

export interface Comparable {
  id: string;
  kind: string;
  kind_label: string;
  channel: string | null;
  seller: string | null;
  platform: string | null;
  source_key: string;
  source_url: string | null;
  source_document: string | null;
  source_record_id: string | null;
  event_date: string | null;
  price: number | null;
  currency: string | null;
  tax_basis: string;
  availability: string | null;
  is_synthetic: boolean;
  spec: Record<string, unknown>;
  gross_price: number | null;
  adjusted_price: number | null;
  age_days: number | null;
  match_tier: string | null;
  unverified_dimensions: string[];
  adjustments: Adjustment[];
  weights: { recency: number; match: number; source_share: number; final: number } | null;
  included: boolean;
  exclusion: string | null;
  set: string | null;
  duplicate_of: string | null;
}

export interface Estimate {
  set: string;
  count: number;
  independent_sources: number;
  effective_n: number;
  broadened_with_adjustments: boolean;
  exact_count: number;
  exact_share: number | null;
  adjusted_count: number;
  weighted_median_age_days: number | null;
  p10: number | null;
  p25: number | null;
  p50: number | null;
  p75: number | null;
  p90: number | null;
  dispersion_iqr_over_median: number | null;
  sufficient: boolean;
  requirement: string;
}

export interface EconLine {
  label: string;
  amount: number;
  subtotal?: boolean;
}

export interface Economics {
  revenue: number;
  contribution: number;
  margin: number | null;
  markup: number | null;
  total_cost: number;
  net_sale_price: number;
  output_tax_per_sold_unit: number;
  buy_price: number;
  gross_sale_price: number;
  lines: EconLine[];
}

export interface ValuationResult {
  engine_version: string;
  as_of: string;
  status: string;
  messages: string[];
  needs_input: string[];
  subject: { id: number; label: string; is_synthetic: boolean; missing_fields: string[] };
  channel: string;
  selling: null | {
    basis: string;
    basis_note: string;
    channel: string;
    [k: string]: number | string | null;
  };
  listing_recommendation: null | { price_gross: number; basis: string; range_gross: number[] };
  wholesale: { supported: boolean; note?: string; basis?: string; p25_gross?: number; p50_gross?: number; p75_gross?: number; count?: number };
  procurement_market: Record<string, { label: string; count: number; sufficient: boolean; p25_buy_basis: number | null; p50_buy_basis: number | null; p75_buy_basis: number | null }>;
  economics: {
    inputs: Record<string, unknown> & { cost_lines: { name: string; type: string; value: number | null; configured: boolean }[] };
    flags: { code: string; severity: string; text: string }[];
    target_buy?: number | null;
    max_safe_buy?: number | null;
    recommended_buy?: number | null;
    at_recommended?: Economics;
    at_ceiling_conservative?: Economics;
    asking?: {
      asking_price: number;
      asking_tax_basis: string;
      asking_buy_basis: number;
      economics: Economics;
      verdict: string;
      verdict_text: string;
      gap_to_target: number | null;
      gap_to_ceiling: number | null;
    };
  };
  lot: null | Record<string, number | string | null>;
  confidence: null | {
    grade: string;
    score: number;
    max_score: number;
    components: { component: string; value: string; points: number; max_points: number }[];
    note: string;
  };
  estimates: Record<string, Estimate>;
  comparables: Comparable[];
  summary_counts: { considered: number; included: number; excluded: number };
  assumptions: { code: string; text: string; severity: string; count?: number }[];
  definitions: Record<string, string>;
  input_hash: string;
  output_hash: string;
}
