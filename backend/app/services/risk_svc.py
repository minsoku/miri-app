"""UC-03 폐업 위험도 분석(SB-06): 두 축(종합·입지) + 요인 효과(%) + 참고 지표 + 대안 입지."""
from __future__ import annotations
import json
import math
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session
from miri_engine.config import DEFAULT_COGS_RATE, risk_grade, RISK_FACTORS
from miri_engine.suitability import location_grade
from .. import models as M
from ..errors import ApiError
from . import geo
from . import narrative as N
from .analysis import area_code_of, candidate_codes, cogs_of, covers_fixed, user_condition
from .catalog import quarter_label
from .engine import EngineState

RELATIVE_FACTORS = ["area_hist", "sales_decline", "store_surge", "entry_heat", "rent_burden", "density", "low_sales",
                    "short_life"]


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def fallback_row(state: EngineState, area_code: str, industry_code: str) -> pd.Series:
    """UC-03 대안 흐름: 이 지역에 최근 1년 점포가 없으면 '서울 같은 업종의 중립 지역'으로 예측.
    상대 요인(지역 이력·추세·밀도 등)을 0(=업종 중앙값)으로 두고 업종 요인만 반영 → 모델 식 그대로 계산."""
    ind = state.industry_rows(industry_code)
    if ind.empty:
        raise ApiError(404, "NO_INDUSTRY_DATA", "이 업종은 서울 전체에 분석할 데이터가 없어요")
    base = ind.iloc[0].copy()
    base["offset"] = math.log(max(float(base["mu_all"]), 1e-6))     # 모델 오프셋 = log(서울 전 업종 폐업률)
    for f in RELATIVE_FACTORS:
        base["x_" + f] = 0.0
    df = pd.DataFrame([base])
    pr = state.model.predict(df).iloc[0]
    for k, v in pr.items():
        base[k] = v
    a = state.areas[area_code]
    base["area_id"], base["area_name"] = area_code, a["name"]
    base["risk_pct_in_ind"] = None          # 이 지역에 같은 업종이 없으니 '입지 위험'(같은 업종 내 비교)은 정의되지 않음
    base["confidence"] = "낮음"
    base["local_weight"] = 0.0
    for k in ("stores", "openings", "closures", "exp4", "clo4", "ope4", "stores_avg4"):
        base[k] = 0.0
    for k in ("sales_ps_m", "ticket", "tx_ps_day", "demand_D", "sales_growth", "store_growth", "p_rent_burden",
              "p_density", "rate_eb", "profile", "sales_rank", "rent4"):
        base[k] = None
    base["closed_months4"] = None
    return base


MAX_ALT_KM = 7.0          # '인근' 대안 지역: 지역 중심 간 7km 이내(서울 자치구 기준 이웃 구 수준)


def afford_basis(state: EngineState, req: M.AnalysisRequest, industry_code: str,
                 be_row: M.BreakEvenAnalysis | None = None) -> tuple[float, float | None, float, float]:
    """인근 지역 감당 여부 판단 비용: (월 고정비, 원가율(모르면 None), 기타 수수료율, 목표 월수입).
    리포트에서 열었으면 그 리포트에 반영한 손익분기 값, 아니면 분석 조건(원가율은 분야별 입력 → 업종 대분류 평균(외식업만))."""
    cat = state.industries[industry_code]["category"]
    cogs = cogs_of(req).get(cat, DEFAULT_COGS_RATE.get(cat))
    if be_row is not None:
        inp = json.loads(be_row.input_json or "{}")
        fixed, other = float(be_row.monthly_fixed_cost), float(inp.get("other_variable_rate") or 0)
        if _f(inp.get("cogs_rate")) is not None:                    # 손익분기 화면에서 넣은 원가율이 있으면 그 값(_area_alt와 같게)
            cogs = _f(inp.get("cogs_rate"))
        owner = float(inp.get("owner_salary") or 0)
    else:
        fixed, other, owner = user_condition(req, []).monthly_fixed_total(), 0.0, float(req.owner_salary or 0)
    return fixed, cogs, other, owner


def _with_affordability(state: EngineState, req: M.AnalysisRequest, industry_code: str, alts: list[dict],
                        be_row: M.BreakEvenAnalysis | None = None) -> list[dict]:
    """인근 지역마다 그 지역 같은 업종 평균 매출로 비용을 감당하는지 — 리포트는 감당할 수 있는 곳만 권하므로 위험도 화면에서도
    그 이유가 보이게. 기준 비용: 리포트에서 열었으면 그 리포트에 반영한 손익분기(월 고정비·원가율·기타 수수료, report_svc._area_alt와
    같게), 아니면 분석 조건. 원가율을 모르는 업종은 매출 ≥ 월 고정비만 본다."""
    fixed, cogs, other, _ = afford_basis(state, req, industry_code, be_row)
    for a in alts:
        r2 = state.row(a["area_code"], industry_code)
        sales = _f(r2.get("sales_ps_m")) if r2 is not None else None
        x = N.sales_outlier(r2) if r2 is not None else None
        a["sales_ps_m"] = sales
        a["sales_outlier"] = None if x is None else round(x, 1)
        # 평균 매출이 대형 점포 때문에 부풀었을 수 있으면(서울 중간값의 3배 이상) 감당 여부를 판단하지 않는다(리포트도 권하지 않음)
        a["affordable"] = None if sales is None or x is not None else bool(covers_fixed(sales, fixed, cogs, other))
    return alts


def alternatives(state: EngineState, area_code: str, industry_code: str, cur_pct: int | None, k_near: int = 6,
                 extra: list[str] | tuple = ()) -> list[dict]:
    """같은 업종이 있는 인근 지역 중 입지 위험이 더 낮은 곳. 이 지역에 같은 업종이 없으면(cur_pct=None) 입지 위험 '낮음'인 곳.
    extra: SB-02에서 후보로 보였던 구(반경에 걸친 구) — 구 중심이 멀어도(7km 넘음) 함께 본다(사당역 → 서초구 등)."""
    a = state.areas[area_code]
    if a["lat"] is None:
        return []
    dist = {c: geo.haversine_m(a["lat"], a["lng"], state.areas[c]["lat"], state.areas[c]["lng"]) / 1000
            for c in state.areas if c != area_code and state.areas[c]["lat"] is not None}
    near = sorted((c for c in dist if dist[c] <= MAX_ALT_KM), key=lambda c: dist[c])[:k_near]
    near = sorted(set(near) | {c for c in extra if c in dist}, key=lambda c: (dist[c], c))
    limit = cur_pct if cur_pct is not None else 40
    out = []
    for c in near:
        r = state.row(c, industry_code)
        if r is None or int(r["risk_pct_in_ind"]) >= limit:
            continue
        loc = int(r["risk_pct_in_ind"])
        out.append({"area_code": c, "area_name": state.areas[c]["name"], "location_risk_pct": loc,
                    "location_grade": location_grade(loc), "risk_score": int(r["risk_score"]),
                    "pred_annual_rate": float(r["pred_annual_rate"]), "distance_km": round(dist[c], 1)})
    out.sort(key=lambda d: d["location_risk_pct"])
    if not out and cur_pct is None:
        # 이 지역에 같은 업종이 없는데(대체 계산) 입지 위험 '낮음'인 곳도 없으면, 이 업종이 있는 가장 가까운 지역이라도(6.1.4 인근 대체)
        for c in near:
            r = state.row(c, industry_code)
            if r is None:
                continue
            loc = int(r["risk_pct_in_ind"])
            out.append({"area_code": c, "area_name": state.areas[c]["name"], "location_risk_pct": loc,
                        "location_grade": location_grade(loc), "risk_score": int(r["risk_score"]),
                        "pred_annual_rate": float(r["pred_annual_rate"]), "distance_km": round(dist[c], 1)})
    return out[:3]


def unit_short(state: EngineState, area_code: str) -> str:
    return "구" if state.areas[area_code].get("level") == "district" else "상권"


def industry_n(state: EngineState, industry_code: str) -> int:
    """업종 전체(서울) 매출 추세에 실제로 들어간 지역 수 — 올해·작년 모두 카드 매출을 믿을 수 있는 지역만 합산하므로
    (features.py) 이 지역 매출 증감(sales_growth)이 있는 지역 수와 같다."""
    rows = state.industry_rows(industry_code)
    return int(rows["sales_growth"].notna().sum()) if not rows.empty else 0


def _reference(r, rent_latest: float | None = None, n_ind: int | None = None, unit: str = "구") -> list[dict]:
    ref = []

    def add(key, label, value, display, note=None):
        ref.append({"key": key, "label": label, "value": value, "display": display, "note": note})
    v = _f(r.get("sales_growth"))
    if v is not None:
        add("sales_growth", "이 지역 같은 업종 매출 전년 대비", v, N.signed_pct(v))
    v = _f(r.get("store_growth"))
    if v is not None:
        add("store_growth", "이 지역 같은 업종 점포 수 전년 대비", v, N.signed_pct(v))
    v = _f(r.get("ind_sales_growth"))
    if v is not None and not (n_ind is not None and n_ind < 5):     # 4개 구 이하 합계는 '서울 추세'라고 보기 어려워 뺀다
        add("ind_sales_growth", "업종 전체(서울) 매출 전년 대비", v, N.signed_pct(v), f"서울 {n_ind}개 {unit} 합계" if n_ind else None)
    v = _f(r.get("p_rent_burden"))
    if v is not None:
        add("rent_burden", "임대료 부담(같은 업종 중 순위, 0~100)", v, f"{v:.0f}", "50이 중간, 높을수록 매출 대비 임대료 부담이 큼")
    v = _f(r.get("p_density"))
    if v is not None:
        add("density", "유동인구 대비 점포 밀도(같은 업종 중 순위, 0~100)", v, f"{v:.0f}", "50이 중간, 높을수록 점포가 빽빽함")
    v = _f(rent_latest) if rent_latest is not None else _f(r.get("rent4"))
    if v is not None:
        add("rent", "3.3㎡당 월 임대료(지역 평균)", v, N.won1(v), "10평이면 약 " + N.won(v * 10))
    v = _f(r.get("closed_months4"))
    if v is not None:
        add("closed_months", "폐업 점포 평균 영업 기간(이 지역 전 업종)", v, f"{v:.0f}개월")
    ope, clo = _f(r.get("ope4")), _f(r.get("clo4"))
    if ope is not None and clo is not None and (ope or clo):
        add("open_close", "최근 1년 같은 업종 개업 / 폐업", None, f"{ope:,.0f}곳 / {clo:,.0f}곳")
    for it in ref:
        it.setdefault("note", None)
    return ref


def risk_detail(db: Session, state: EngineState, req: M.AnalysisRequest, industry_code: str, persist=True,
                be_id: int | None = None) -> dict:
    if industry_code not in state.industries:
        raise ApiError(404, "UNKNOWN_INDUSTRY", "알 수 없는 업종이에요")
    area_code = area_code_of(db, req)
    # 리포트에서 연 경우 그 리포트에 반영한 손익분기(같은 분석·업종일 때만, 아니면 분석 조건 기준)
    be_row = db.get(M.BreakEvenAnalysis, be_id) if be_id else None
    if be_row is not None and (be_row.request_id != req.request_id
                               or be_row.category_id != state.industries[industry_code]["category_id"]):
        be_row = None
    r = state.row(area_code, industry_code)
    fallback = r is None
    notices = []
    ox = N.sales_outlier(r) if not fallback else None
    if ox is not None:                              # 인근 지역만 '대형 점포 가능'이라 하고 이 지역은 말하지 않으면 안 된다
        notices.append(f"이 지역 점포당 매출이 서울 같은 업종 중간값의 {ox:.1f}배예요 — 대형 점포가 섞인 평균일 수 있어 "
                       "매출 관련 요인·비교는 참고용이에요.")
    if fallback:
        r = fallback_row(state, area_code, industry_code)
        notices.append(f"{state.areas[area_code]['name']}에 최근 1년 {state.industries[industry_code]['name']} 점포가 없어 "
                       "서울 같은 업종 평균 조건으로 계산했어요(신뢰도 낮음).")
    model = state.model
    mu_ind, mu_all = _f(r.get("mu_ind")), _f(r.get("mu_all"))
    ind_avg = None if mu_ind is None else round(1 - (1 - mu_ind) ** 4, 4)
    seoul_avg = None if mu_all is None else round(1 - (1 - mu_all) ** 4, 4)
    ctx = {"ind_avg": ind_avg, "seoul_avg": seoul_avg, **{k: _f(r.get(k)) for k in (
        "clo4", "stores_avg4", "sales_growth", "store_growth", "ope4", "exp4", "mu_ind_entry", "sales_ps_m", "closed_months4",
        "ind_sales_growth", "rate_eb", "local_weight")}, "sales_outlier": ox}
    factors = N.relabel(model.top_factors(r, r, n=len(model.factors)), ctx)     # 라벨을 실제 증감 부호에 맞춤
    fx = [{**f, "direction": "up" if f["effect_pct"] > 0 else "down", "detail": N.factor_detail(f, ctx)} for f in factors]
    for f in fx:
        f.pop("x", None)
    loc = None if fallback else int(r["risk_pct_in_ind"])
    basis = afford_basis(state, req, industry_code, be_row)
    exp4, clo4 = _f(r.get("exp4")) or 0.0, _f(r.get("clo4")) or 0.0
    unit = unit_short(state, area_code)
    out = {
        "analysis_id": req.public_id, "area_code": area_code, "area_name": state.areas[area_code]["name"],
        "industry_code": industry_code, "industry_name": state.industries[industry_code]["name"],
        "category": state.industries[industry_code]["category"], "data_quarter": state.quarter,
        "data_quarter_label": quarter_label(state.quarter),
        "model_version": state.model_version, "risk_score": int(r["risk_score"]), "risk_grade": r["risk_grade"],
        "pred_annual_rate": float(r["pred_annual_rate"]),
        "industry_avg_annual_rate": ind_avg, "seoul_avg_annual_rate": seoul_avg,
        "location_risk_pct": loc, "location_grade": None if loc is None else location_grade(loc),
        "confidence": r["confidence"], "local_data_weight": _f(r.get("local_weight")),
        "grade_cuts": [model.params.cut_normal, model.params.cut_high, model.params.cut_critical],
        "grade_rate_bounds": state.grade_rate_bounds(),
        "summary": N.risk_summary(state.areas[area_code]["name"], r, fallback=fallback),
        "factors": fx,
        "reference": _reference(r, state.area_cards.get(area_code, {}).get("rent_per_3_3m2"),
                                industry_n(state, industry_code), unit),
        "raw": {"stores_now": _f(r.get("stores")), "stores_avg_1y": _f(r.get("stores_avg4")),
                "openings_1y": _f(r.get("ope4")), "closures_1y": clo4,
                "raw_closure_rate_q": round(clo4 / exp4, 4) if exp4 > 0 else None,
                "eb_closure_rate_q": _f(r.get("rate_eb"))},
        "alternatives": _with_affordability(state, req, industry_code,
                                            alternatives(state, area_code, industry_code, loc, extra=candidate_codes(state, req)),
                                            be_row),
        "affordability_basis": "report" if be_row is not None else "analysis",
        # 인근 지역 '못 미쳐요' 문구의 기준: 원가율을 모르면 '월 고정비', 목표 월수입이 있으면 '(목표 월수입 포함)'
        "affordability_cogs_known": basis[1] is not None,
        "affordability_owner_included": basis[3] > 0,
        "recheck": r["risk_grade"] == "고위험", "fallback": fallback,
        "notices": notices + state.notices,
    }
    if persist:
        # 같은 분석·업종·모델 버전의 평가는 결과가 같으므로 재사용(리포트가 risk_id로 참조하므로 삭제하지 않는다)
        cid = state.industries[industry_code]["category_id"]
        existing = db.scalar(select(M.RiskAssessment).where(
            M.RiskAssessment.request_id == req.request_id, M.RiskAssessment.category_id == cid,
            M.RiskAssessment.model_version == state.model_version).order_by(M.RiskAssessment.risk_id.desc()))
        if existing is not None:
            out["_risk_id"] = existing.risk_id
            return out
        ra = M.RiskAssessment(request_id=req.request_id, category_id=cid,
                              area_id=state.areas[area_code]["area_id"], risk_score=out["risk_score"],
                              risk_level=out["risk_grade"], summary=out["summary"],
                              pred_annual_rate=out["pred_annual_rate"], location_risk_pct=loc,
                              location_risk_level=out["location_grade"], confidence=out["confidence"],
                              model_version=state.model_version,
                              reference_json=json.dumps(out["reference"], ensure_ascii=False))
        for f in factors:
            ra.factors.append(M.RiskFactor(factor_code=f["factor_code"], factor_name=f["factor_name"], label=f["label"],
                                           effect_pct=f["effect_pct"], x_value=f.get("x"),
                                           explanation=f["explanation"]))
        db.add(ra)
        db.commit()
        out["_risk_id"] = ra.risk_id
    return out
