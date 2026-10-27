"""Configuration matching.

A comparable is either:
* ``exact``       every compared dimension is known on both sides and equal;
* ``unverified``  equal on every dimension known on both sides, but an optional
                  dimension is unknown on one side;
* ``adjusted``    differs on at least one dimension for which an explicit, user-
                  configured adjustment rule exists (the rule is applied and recorded);
* excluded        differs on a dimension with no rule, a required dimension is
                  unknown, or it is a different model.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import AdjustmentRule, PricingConfig
from .types import Evidence, Subject

DIMENSION_LABELS = {
    "cpu_key": "CPU", "ram_gb": "RAM (GB)", "storage_gb": "Storage (GB)", "storage_type": "Storage type",
    "condition_grade": "Condition grade", "gpu_key": "GPU", "display_size_in": "Display size",
    "display_resolution": "Resolution", "charger_included": "Charger", "warranty_months": "Warranty (months)",
    "battery_health_pct": "Battery health",
}


def dim_str(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v).strip().lower()


def dim_display(v) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


@dataclass
class AppliedAdjustment:
    rule_id: str
    dimension: str
    comparable_value: str
    subject_value: str
    method: str
    value: float
    inverse: bool
    calibrated: bool
    basis: str

    def apply(self, price: float) -> float:
        return price * (1 + self.value / 100) if self.method == "percent" else price + self.value

    def to_dict(self, before: float, after: float) -> dict:
        return {
            "rule_id": self.rule_id, "dimension": self.dimension,
            "dimension_label": DIMENSION_LABELS.get(self.dimension, self.dimension),
            "comparable_value": self.comparable_value, "subject_value": self.subject_value,
            "method": self.method, "value": round(self.value, 6), "inverse_of_rule": self.inverse,
            "calibrated": self.calibrated, "basis": self.basis,
            "price_before": round(before, 2), "price_after": round(after, 2),
        }


@dataclass
class MatchOutcome:
    tier: str | None
    exclusion: str | None = None
    unverified: list[str] = field(default_factory=list)
    adjustments: list[AppliedAdjustment] = field(default_factory=list)


def find_rule(rules: list[AdjustmentRule], dim: str, comp_v: str, subj_v: str) -> AppliedAdjustment | None:
    for r in sorted(rules, key=lambda r: r.id):
        if r.dimension != dim:
            continue
        rc, rs = r.comparable_value.strip().lower(), r.subject_value.strip().lower()
        if rc == comp_v and rs == subj_v:
            return AppliedAdjustment(r.id, dim, comp_v, subj_v, r.method, r.value, False, r.calibrated, r.basis)
        if r.symmetric and rc == subj_v and rs == comp_v:
            inv = (100 / (1 + r.value / 100) - 100) if r.method == "percent" else -r.value
            return AppliedAdjustment(r.id, dim, comp_v, subj_v, r.method, inv, True, r.calibrated, r.basis)
    return None


def match(subject: Subject, ev: Evidence, cfg: PricingConfig) -> MatchOutcome:
    if subject.brand_key != ev.brand_key or subject.model_key != ev.model_key:
        return MatchOutcome(None, "Different brand/model")
    m = cfg.matching
    out = MatchOutcome("exact")
    for dim in m.required_dimensions + m.optional_dimensions:
        required = dim in m.required_dimensions
        sv, cv = dim_str(getattr(subject, dim)), dim_str(getattr(ev, dim))
        label = DIMENSION_LABELS.get(dim, dim)
        if sv is None or cv is None:
            if required:
                side = "subject" if sv is None else "comparable"
                return MatchOutcome(None, f"{label} unknown on {side}; configuration cannot be confirmed")
            out.unverified.append(dim)
            continue
        if sv == cv:
            continue
        adj = find_rule(cfg.adjustments, dim, cv, sv)
        if adj is None:
            return MatchOutcome(None, f"Materially incomparable: {label} {dim_display(getattr(ev, dim))} vs subject "
                                      f"{dim_display(getattr(subject, dim))} "
                                      f"(no adjustment rule configured)")
        out.adjustments.append(adj)
    if m.battery_tolerance_pts is not None:
        sb, cb = subject.battery_health_pct, ev.battery_health_pct
        if sb is None or cb is None:
            out.unverified.append("battery_health_pct")
        elif abs(sb - cb) > m.battery_tolerance_pts:
            return MatchOutcome(None, f"Battery health {cb:g}% vs subject {sb:g}% exceeds tolerance "
                                      f"of {m.battery_tolerance_pts:g} pts")
    if out.adjustments:
        out.tier = "adjusted"
    elif out.unverified:
        out.tier = "unverified"
    return out
