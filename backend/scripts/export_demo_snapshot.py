"""데모(서버 없는 단일 HTML)용 스냅샷 내보내기.

요청 시점 계산(필터·가중합·손익분기·문장)은 프런트 데모 엔진(TypeScript)이 같은 규칙으로 다시 계산하고,
모델이 필요한 값(위험 점수·요인 효과·업종 평균 대체값)은 여기서 미리 계산해 넣는다.
사용: python scripts/export_demo_snapshot.py ../frontend/src/api/demo/snapshot.json
"""
import json
import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import select
from miri_engine.config import (GOAL_WEIGHTS, SuitabilityParams, BreakEvenParams, CARD_FEE_TIERS, CARD_FEE_OVER_3B,
                                DEFAULT_COGS_RATE, LICENSED_INDUSTRIES, RiskParams, RISK_FACTORS, RISK_FACTOR_LABELS)
from app.services.features_batch import TIME_KEYS, AGE_KEYS
from app.db import SessionLocal
from app import models as M
from app.services.engine import load_state
from app.services import areas as area_svc, risk_svc
from app.services.catalog import quarter_label, DISPLAY_GROUPS, REGISTRATION_NOTES
from app.schemas import AreaMetricsOut

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "../frontend/src/api/demo/snapshot.json")
KEEP = ["area_id", "industry_code", "category", "has_sales_data", "stores", "exp4", "clo4", "ope4", "stores_avg4",
        "sales_ps_m", "ticket", "tx_ps_day", "demand_D", "risk_score", "risk_grade", "risk_pct_in_ind",
        "pred_annual_rate", "confidence", "local_weight", "rate_eb", "sales_growth",
        "store_growth", "ind_sales_growth", "p_rent_burden", "p_density", "rent4", "closed_months4", "mu_ind_entry"]


def compact_factors(fs):
    """[code, effect_pct, effect_display] — 이름·라벨·설명 문장은 프런트가 같은 규칙으로 복원."""
    return [[f["factor_code"], f["effect_pct"], f["effect_display"]] for f in fs]


def compact_profile(pr):
    if not isinstance(pr, dict):
        return None
    ts, ag = pr.get("time_share") or {}, pr.get("age_share") or {}
    return ([ts.get(k) for k in TIME_KEYS] + [pr.get("weekend_share"), pr.get("female_share")]
            + ([ag.get(k) for k in AGE_KEYS] if ag else []))


def clean(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if hasattr(v, "item"):
        v = v.item()
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
    return v


def main():
    with SessionLocal() as db:
        st = load_state(db)
        model = st.model
        cols = KEEP + ["factors", "ind_avg_rate", "seoul_avg_rate", "profile"]
        data = []
        for _, r in st.table.iterrows():
            d = [clean(r[k]) for k in KEEP]
            mu_i, mu_a = clean(r["mu_ind"]), clean(r["mu_all"])
            d += [compact_factors(model.top_factors(r, r, n=len(model.factors))),
                  None if mu_i is None else round(1 - (1 - mu_i) ** 4, 4),
                  None if mu_a is None else round(1 - (1 - mu_a) ** 4, 4),
                  compact_profile(r["profile"])]
            data.append(d)
        rows = {"cols": cols, "data": data}
        any_area = next(iter(st.areas))
        fallback = {}
        for code in st.industries:
            if st.industry_rows(code).empty:
                continue
            fr = risk_svc.fallback_row(st, any_area, code)
            fallback[code] = {
                "risk_score": int(fr["risk_score"]), "risk_grade": fr["risk_grade"],
                "pred_annual_rate": float(fr["pred_annual_rate"]),
                "factors": compact_factors(model.top_factors(fr, fr, n=len(model.factors))),
                "ind_avg_rate": round(1 - (1 - float(fr["mu_ind"])) ** 4, 4),
                "seoul_avg_rate": round(1 - (1 - float(fr["mu_all"])) ** 4, 4),
                "ind_sales_growth": clean(fr.get("ind_sales_growth")), "category": fr["category"],
                "industry_code": code}
        places = [{"name": p.name, "aliases": p.aliases, "kind": p.kind, "lat": p.latitude, "lng": p.longitude,
                   "area_id": p.area_id} for p in db.scalars(select(M.Place).order_by(M.Place.place_id))]
        code_by_id = {a["area_id"]: c for c, a in st.areas.items()}
        for p in places:
            p["area_code"] = code_by_id.get(p.pop("area_id"))
        policies = [{"policy_id": p.policy_id, "name": p.policy_name, "provider": p.provider,
                     "target_region": p.target_region, "target_category": p.target_category,
                     "target_user": p.target_user, "support_type": p.support_type, "summary": p.summary,
                     "apply_url": p.apply_url, "checked_at": p.checked_at.isoformat() if p.checked_at else None}
                    for p in db.scalars(select(M.PolicySupport).order_by(M.PolicySupport.policy_id))]
        inds = sorted(st.industries.values(), key=lambda d: d["code"])
        names = {d["code"]: d["name"] for d in inds}
        rp = model.params
        snap = {
            "version": 1,
            "meta": {"data_quarter": st.quarter, "data_quarter_label": quarter_label(st.quarter),
                     "model_version": st.model_version, "trained_at": st.trained_at, "analysis_level": "district",
                     "grade_cuts": [rp.cut_normal, rp.cut_high, rp.cut_critical],
                     "grade_rate_bounds": st.grade_rate_bounds(), "goals": GOAL_WEIGHTS, "notices": st.notices,
                     "area_order": list(st.areas)},
            "industries": {"groups": [{**g, "names": [names.get(c, c) for c in g["codes"]]} for g in DISPLAY_GROUPS],
                           "industries": [{"code": d["code"], "name": d["name"], "category": d["category"],
                                           "has_sales_data": d["has_sales_data"], "recommendable": d["recommendable"],
                                           "license": d["license"], "display_group": d["display_group"], "family": d["family"],
                                           "seoul_ticket": d.get("seoul_ticket")} for d in inds]},
            "areas": {c: {"name": a["name"], "level": a["level"], "lat": a["lat"], "lng": a["lng"],
                          "geometry": a["geometry"]} for c, a in st.areas.items()},
            "area_cards": {c: AreaMetricsOut(**m).model_dump() for c, m in st.area_cards.items()},   # 응답 스키마와 같은 필드만
            "map": area_svc.simplified_map(st, db),
            "places": places,
            "policies": policies,
            "rows": rows,
            "fallback": fallback,
            "params": {
                "suitability": SuitabilityParams().__dict__, "breakeven": {**BreakEvenParams().__dict__,
                                                                            "pressure_bands": list(BreakEvenParams().pressure_bands)},
                "card_fee_tiers": CARD_FEE_TIERS, "card_fee_over_3b": CARD_FEE_OVER_3B,
                "default_cogs": DEFAULT_COGS_RATE, "licensed": LICENSED_INDUSTRIES,
                "risk_cuts": [RiskParams().cut_normal, RiskParams().cut_high, RiskParams().cut_critical],
                "factor_names": RISK_FACTORS, "factor_labels": RISK_FACTOR_LABELS, "registration_notes": REGISTRATION_NOTES,
                "time_keys": TIME_KEYS, "age_keys": AGE_KEYS,
            },
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"스냅샷 저장: {OUT} ({OUT.stat().st_size / 1e6:.2f} MB, 행 {len(rows['data']):,})")


if __name__ == "__main__":
    main()
