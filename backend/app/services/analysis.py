"""UC-01 업종 추천 조회: 분석 요청 저장 → M-03 추천(엔진) → 결과 저장 → 화면 응답(SB-05)."""
from __future__ import annotations
import json
import math
import uuid
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session
from miri_engine.suitability import OUTLIER_REASON, UserCondition, recommend
from miri_engine.breakeven import card_fee_rate
from miri_engine.config import DEFAULT_COGS_RATE, GOAL_WEIGHTS, LICENSED_INDUSTRIES, SuitabilityParams
from .. import models as M
from ..errors import ApiError
from ..schemas import AnalysisIn
from . import narrative as N
from .catalog import quarter_label
from .engine import EngineState

UNIT_LABEL = {"district": "자치구", "trade_area": "상권"}


def _f(x):
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def _s(x):
    return x if isinstance(x, str) else None


def get_analysis(db: Session, public_id: str) -> M.AnalysisRequest:
    """로그인이 없으므로 분석 ID(추측 불가 UUID)를 아는 사람이면 누구나 연다. 이전 버전에서 회원이 만든 분석(user_id 있음)은
    주인이 더는 로그인할 수 없어 404로 숨긴다(본인만 보던 분석이 링크만으로 열리지 않게)."""
    req = db.scalar(select(M.AnalysisRequest).where(M.AnalysisRequest.public_id == public_id))
    if req is None or req.user_id is not None:
        raise ApiError(404, "ANALYSIS_NOT_FOUND", "분석 결과를 찾을 수 없어요")
    return req


def area_code_of(db: Session, req: M.AnalysisRequest) -> str:
    return db.get(M.CommercialArea, req.main_area_id).area_code


def cogs_of(req: M.AnalysisRequest) -> dict:
    """분석 조건에서 넣은 분야별 원가율(없으면 빈 dict)."""
    return json.loads(req.cogs_json) if getattr(req, "cogs_json", None) else {}


def excluded_of(req: M.AnalysisRequest) -> list[str]:
    """분석 조건에서 뺀 업종 코드(없으면 빈 목록) — 리포트의 비슷한 업종·다시 분석에서도 같은 제외를 지킨다."""
    return json.loads(req.excluded_json) if getattr(req, "excluded_json", None) else []


def user_condition(req: M.AnalysisRequest, interests: list[str]) -> UserCondition:
    return UserCondition(
        business_goal=req.business_goal, budget=req.budget, monthly_rent=req.monthly_rent_limit,
        labor_cost=req.labor_cost, other_fixed=req.other_fixed, initial_investment=req.initial_investment,
        loan_amount=req.loan_amount, loan_rate_annual=req.loan_rate_annual, owner_salary=req.owner_salary,
        cogs_by_category=cogs_of(req) or None,
        licenses=tuple(json.loads(req.licenses_json)), interest_industries=tuple(interests),
        excluded_industries=tuple(excluded_of(req)), categories=tuple(json.loads(req.categories_json)))


def covers_fixed(sales, fixed: float, cogs: float | None = None, other: float = 0.0) -> bool:
    """평균 매출로 월 고정비를 감당하는지. 원가율을 알면 원가·카드수수료(·배달 등 기타 수수료)까지 빼고 본다."""
    if sales is None or not isinstance(sales, (int, float)) or sales != sales or sales < fixed:
        return False
    if cogs is None:
        return True
    return sales * (1 - cogs - card_fee_rate(sales * 12) - other) >= fixed


def fixed_phrase(fixed: float, owner: float) -> str:
    """'입력한 월 고정비(X)' — 목표 월수입이 들어 있으면 그 사실을 밝힌다(3,000만원이 임대료·인건비처럼 보이지 않게)."""
    return f"목표 월수입을 포함한 월 고정비({N.won(fixed)})" if owner > 0 else f"입력한 월 고정비({N.won(fixed)})"


def cut_advice(owner: float) -> str:
    return "임대료·인건비나 목표 월수입을 낮춰" if owner > 0 else "임대료·인건비 등 고정비를 낮춰"


def _item(state: EngineState, area_code: str, r: dict, item_type: str, f_applied: bool, owner_included: bool = False,
          fixed_total: float = 1.0) -> dict:
    row = state.row(area_code, r["industry_code"])
    profile = row["profile"] if row is not None and isinstance(row.get("profile"), dict) else None
    ind = state.industries.get(r["industry_code"], {})
    D, F = _f(r.get("D")), _f(r.get("F"))
    it = {
        "industry_code": r["industry_code"], "industry_name": r["industry_name"], "category": r["category"],
        "display_group": ind.get("display_group"), "item_type": item_type,
        "rank": int(r["rank_order"]) if item_type == "TOP" and _f(r.get("rank_order")) is not None else None,
        "suitability": _f(r.get("suitability")), "score_note": None,
        "scores": {"D": D, "S": _f(r.get("S")), "F": F if f_applied else None},
        "risk_score": int(r["risk_score"]), "risk_grade": r["risk_grade"],
        "location_risk_pct": int(r["risk_pct_in_ind"]), "location_grade": r["location_grade"],
        "pred_annual_rate": float(r["pred_annual_rate"]), "sales_ps_m": _f(r.get("sales_ps_m")),
        "avg_ticket": _f(r.get("ticket")), "stores_avg": _f(r.get("stores_avg4")), "confidence": r["confidence"],
        "achievability_ratio": _f(r.get("achievability_ratio")), "eligible": bool(r["eligible"]),
        "ineligible_reason": _s(r.get("ineligible_reason")), "reason": _s(r.get("reason")) or "",
        "caution": _s(r.get("caution")) or "",
    }
    if owner_included and it["ineligible_reason"] in OWNER_REASON:     # 제외 이유도 목표 월수입 포함 기준임을 밝힌다
        it["ineligible_reason"] = OWNER_REASON[it["ineligible_reason"]]
    unit = "구" if state.areas[area_code].get("level") == "district" else "상권"
    if (it["ineligible_reason"] or "").startswith(FEW_AREAS):        # 화면의 다른 문장(…구가 N곳뿐)과 같은 말로
        it["ineligible_reason"] = it["ineligible_reason"].replace("비교할 지역이", f"비교할 {N.josa(unit, '이/가')}")
    # 일부 점수만으로 낸 적합도는 다른 업종 점수와 같은 잣대가 아니다 → 숫자를 숨기거나 표시
    if D is None:
        it["suitability"] = None
        it["score_note"] = "매출 데이터가 없어 적합도를 계산하지 않았어요"
    elif f_applied and F is None:
        it["score_note"] = "비용 적합도 없이 낸 점수라 다른 업종과 바로 비교하기 어려워요"
    elif item_type == "INTEREST" and it["eligible"] and it["location_risk_pct"] >= 90:
        it["score_note"] = "같은 업종끼리 비교해 이 지역 입지 위험이 매우 높아(상위 10%) 추천 TOP에서는 뺐어요"
    elif (item_type == "INTEREST" and it["eligible"] and it["suitability"] is not None
          and math.floor(it["suitability"] + 0.5) < MIN_TOP_SCORE):
        it["score_note"] = f"적합도가 {MIN_TOP_SCORE}점 미만이라 추천 순위에 넣지 않았어요"
    elif (_s(r.get("ineligible_reason")) or "").startswith(FEW_AREAS):
        n_areas = _f(row.get("sales_n")) if row is not None else None
        it["score_note"] = (f"매출을 비교할 구가 {int(n_areas)}곳뿐이라 적합도는 참고용이에요" if n_areas is not None
                            else "매출을 비교할 구가 적어 적합도는 참고용이에요")
    nr = dict(r)
    nr["D"], nr["achievability_ratio"] = D, it["achievability_ratio"]
    if row is not None:
        nr["sales_rank"], nr["sales_n"] = _f(row.get("sales_rank")), _f(row.get("sales_n"))
        nr["sales_outlier"] = N.sales_outlier(row)
        nr["risk_factors"] = N.relabel(r.get("risk_factors") or [], {"sales_outlier": nr["sales_outlier"],
                                                                      "store_growth": _f(row.get("store_growth")),
                                                                      "sales_growth": _f(row.get("sales_growth"))})
    nr["unit"] = unit
    nr["owner_included"] = owner_included
    # '손익분기 미확인(원가율 미입력)' 칩은 답이 정해지지 않았을 때만: 월 고정비 0원(손익분기 0원)이거나 평균 매출이 고정비보다 적어
    # 이미 빠진 업종(적자 확정)에는 달지 않는다
    sales = _f(r.get("sales_ps_m"))
    nr["cogs_missing"] = (bool(r.get("cogs_missing")) and fixed_total > 0
                          and _s(r.get("ineligible_reason")) != INELIGIBLE_FIXED
                          and not (sales is not None and sales < fixed_total))    # 자격 등 다른 이유로 빠졌어도 적자 확정이면
    it["reason_short"] = N.reason_short(nr)
    it["chips"] = N.reason_chips(nr)
    it["cautions"] = N.caution_pills(nr, profile)
    if not it["eligible"] and _s(r.get("ineligible_reason")) in (INELIGIBLE_BEP, INELIGIBLE_FIXED):
        # '추천 제외 · 평균 매출로 손익분기 미달' 줄이 이미 있으니 같은 뜻의 주의 알약은 빼고 다른 위험 신호만
        it["cautions"] = [c for c in it["cautions"] if not c.startswith(("평균 매출로 손익분기", "평균 매출로 필요 매출"))]
    if (_s(r.get("ineligible_reason")) or "").startswith(OUTLIER_REASON):    # '추천 제외 · 점포당 매출이 …배' 줄과 같은 뜻
        it["cautions"] = [c for c in it["cautions"] if c != N.OUTLIER_PILL]
    it["peak"] = N.peak_flags(profile, r["category"], r["industry_code"])
    return it


FEW_AREAS = "매출을 비교할 지역이 적음"
INELIGIBLE_FIXED = "평균 매출이 월 고정비보다 적음"
INELIGIBLE_BEP = "평균 매출로 손익분기 미달"
OWNER_REASON = {INELIGIBLE_FIXED: "평균 매출이 월 고정비(목표 월수입 포함)보다 적음",
                INELIGIBLE_BEP: "평균 매출로 필요 매출(목표 월수입 포함) 미달"}


def _shortfall(rec: dict) -> tuple[int, float | None, str | None, str | None]:
    """비용 때문에 빠진 업종 수(월 고정비 > 평균 매출, 또는 원가까지 넣으면 손익분기 미달), 그중 가장 높은 점포당 월매출과
    그 업종이 빠진 이유. 비용 검사는 자격·대분류 검사 다음이라 여기 걸린 업종은 '비용만 낮으면 후보가 되는' 업종이다."""
    tab = rec["table"]
    hit = tab[tab["ineligible_reason"].isin([INELIGIBLE_FIXED, INELIGIBLE_BEP])]
    if not len(hit):
        return 0, None, None, None
    # '가장 높은 업종 월매출'로는 대형 점포가 섞인 듯한 평균(서울 중간값의 3배 이상)을 인용하지 않는다(모두 그렇다면 어쩔 수 없이)
    plain = hit[hit["sales_outlier"].isna()] if "sales_outlier" in hit else hit
    top = (plain if len(plain) else hit).sort_values(["sales_ps_m", "industry_code"], ascending=[False, True]).iloc[0]
    return int(len(hit)), _f(top["sales_ps_m"]), top["ineligible_reason"], top["industry_name"]


def _licensed_hint(rec: dict, fixed: float, uc: UserCondition) -> str:
    """자격이 없어 빠졌지만 매출은 월 고정비보다 큰 업종이 있으면 알려준다(0개 이유가 비용만은 아님).
    분야를 제한했으면 그 분야 업종만(소매업 의약품을 외식업 분석에서 권하지 않게)."""
    tab = rec["table"]
    lic = tab[tab["ineligible_reason"].fillna("").str.endswith("자격 필요") & (tab["sales_ps_m"] >= fixed)]
    if "sales_outlier" in lic:
        lic = lic[lic["sales_outlier"].isna()]           # 대형 점포가 섞인 듯한 평균으로 '자격만 있으면 후보'라고 하지 않는다
    if uc.categories:
        lic = lic[lic["category"].isin(list(uc.categories))]
    cm = uc.cogs_by_category or {}
    # 자격만 있으면 후보가 되는지: 원가율을 아는 분야는 원가·수수료까지 빼고도 고정비를 넘어야(추천 필터와 같은 기준)
    lic = lic[[covers_fixed(r.sales_ps_m, fixed, cm.get(r.category, DEFAULT_COGS_RATE.get(r.category)))
               for r in lic.itertuples()]] if not lic.empty else lic
    if lic.empty:
        return ""
    top = lic.sort_values(["sales_ps_m", "industry_code"], ascending=[False, True]).iloc[0]
    return f" 자격이 필요한 {top['industry_name']} 등은 보유 자격을 고르면 후보가 될 수 있어요."


MIN_TOP_SCORE = int(SuitabilityParams().min_top_score)     # 추천 TOP 최소 적합도(문장용 정수)


def low_names(rec: dict, k: int = 2) -> str:
    """적합도 하한 미만이라 뺀 업종 이름(점수 높은 순 최대 k개): '노래방 17점, PC방 5점 등'."""
    low = rec.get("low_list") or []
    s = ", ".join(f"{n} {math.floor(v + 0.5)}점" for n, v in low[:k])
    return s + (" 등" if len(low) > k else "")


def outlier_note(rec: dict) -> str | None:
    """매출이 유난히 높아(서울 중간값의 3배 이상) 추천에서 뺀 업종 중 순위에 들 만했던 것(TOP이 다 차면 TOP 마지막보다 점수가
    높은 것만) — 조명용품·문구처럼 도매 상가 평균으로 1위가 되던 업종이 왜 없는지 알린다."""
    tab = rec["table"]
    hit = tab[tab["ineligible_reason"].fillna("").str.startswith(OUTLIER_REASON)]
    # 다른 조건(비용·손익분기·입지 위험 90 미만)은 다 통과한 업종만 이 이유로 빠진다 → 적합도 하한(화면 정수 20점)도 넘어야 '순위에 들 만했던' 업종
    hit = hit[np.floor(hit["suitability"] + 0.5) >= MIN_TOP_SCORE]
    top = rec["top"]
    if len(top) >= SuitabilityParams().top_n and not hit.empty:
        hit = hit[hit["suitability"] > float(top["suitability"].min())]
    if hit.empty:
        return None
    hit = hit.sort_values(["suitability", "industry_code"], ascending=[False, True])
    names = "·".join(hit["industry_name"].head(2)) + (" 등" if len(hit) > 2 else "")
    x = f"{SuitabilityParams().outlier_sales_x:g}"
    cats = set(hit["category"])
    kind = N.BIG_STORE.get(next(iter(cats)), "대형 점포") if len(cats) == 1 else "대형 점포"   # 학원에 '도매 상가'라고 하지 않게
    return (f"점포당 매출이 서울 같은 업종 중간값의 {x}배 이상인 {len(hit)}개 업종({names})은 {N.josa(kind, '이/가')} 섞인 "
            "평균일 수 있어 추천 순위에서 뺐어요.")


VAR100 = "원가·수수료가 매출의 100% 이상"
CAT_ORDER = ("외식업", "서비스업", "소매업")


def _entered_cogs(rec: dict, uc: UserCondition, reasons: tuple[str, ...]) -> str:
    """원가 때문에 빠진 업종의 분야 중 사용자가 원가율을 높게(50% 이상) 넣은 분야: '외식업 95%'. 없으면 ''."""
    cm = uc.cogs_by_category or {}
    tab = rec["table"]
    cats = set(tab[tab["ineligible_reason"].isin(list(reasons))]["category"])
    hit = [c for c in CAT_ORDER if c in cats and c in cm and cm[c] >= 0.5]
    return "·".join(f"{c} {N.pct(cm[c]).replace('.0%', '%')}" for c in hit)


def empty_reason(rec: dict, uc: UserCondition, state: EngineState | None = None) -> str:
    """추천 TOP이 0개일 때 '왜 없는지'(가장 큰 원인 먼저)."""
    cats = list(uc.categories)
    scope = f" {'·'.join(cats)}" if cats else ""
    fixed, owner = uc.monthly_fixed_total(), float(uc.owner_salary or 0)
    n_caution = len(rec["caution_list"])
    n_cost, best, why, best_name = _shortfall(rec)
    # 가장 매출이 높은 업종이 '원가까지 빼면' 모자란 경우: 매출이 고정비보다 커 보여도 왜 안 되는지 밝힌다
    # 비용 때문에 빠진 업종 중 매출이 가장 높은 업종(대형 점포가 섞인 듯한 평균은 빼고)을 예로 든다
    best_s = (f"비용 때문에 빠진 업종 중 매출이 가장 높은 {best_name}도 월매출 {N.won(best)}에서 원가·카드수수료를 빼면 모자라요"
              if why == INELIGIBLE_BEP else
              f"비용 때문에 빠진 업종 중 매출이 가장 높은 {best_name}도 월매출이 {N.josa(N.won(best), '으로/로')} 월 고정비보다 적어요")
    who = "지금 조건으로 열 수 있는" if uc.licenses else "자격 없이 열 수 있는"      # 자격을 골랐으면 자격 업종도 포함
    cost_s = (f"{fixed_phrase(fixed, owner)}로는 이 지역{scope}에서 {who} 업종이 평균 매출로 손익분기를 넘기 어려워요. "
              f"{best_s}. {cut_advice(owner)} 다시 분석해 보세요." if n_cost else "")
    hint = _licensed_hint(rec, fixed, uc) if n_cost else ""
    # 사용자가 넣은 높은 원가율이 원인이면 고정비만 탓하지 않는다
    ec = _entered_cogs(rec, uc, (INELIGIBLE_BEP,)) if n_cost else ""
    if ec:
        hint += f" 입력한 원가율({ec})이 맞는지도 확인해 보세요 — 원가율이 높으면 고정비를 줄여도 남는 몫이 적어요."
    if n_caution and rec["n_candidates"] == n_caution:
        who = "조건에 맞는 업종이 1개뿐인데" if n_caution == 1 else f"조건에 맞는 업종 {n_caution}개가 모두"
        s = f"{who} 같은 업종끼리 비교해 이 지역 입지 위험이 매우 높은 곳이라 추천에서 뺐어요."
        if n_cost:
            return (s + f" 나머지 {n_cost}개 업종은 {fixed_phrase(fixed, owner)}로는 평균 매출로 손익분기를 넘기 어려워요. "
                    f"{cut_advice(owner)} 다시 분석해 보세요." + hint)
        return s + " 아래 주의 업종을 참고하거나 다른 지역과 비교해 보세요."
    n_low = int(rec.get("n_low_score") or 0)
    if n_low:
        # 후보는 있지만 적합도가 모두 기준 미만(매출·안정성이 이 지역에서 낮은 편) → 순위를 채우려고 넣지 않았다
        s = (f"조건에 맞는 업종 중 {n_caution}개는 같은 업종끼리 비교한 입지 위험이 매우 높아 주의 업종으로 뺐고, "
             f"나머지 {n_low}개({low_names(rec)})는 적합도가 {MIN_TOP_SCORE}점 미만이라 추천하지 않았어요." if n_caution else
             f"조건에 맞는 {n_low}개 업종({low_names(rec)})의 적합도가 모두 {MIN_TOP_SCORE}점 미만이라 추천하지 않았어요.")
        if n_cost:
            return (s + f" 그 밖의 {n_cost}개 업종은 {fixed_phrase(fixed, owner)}로는 평균 매출로 손익분기를 넘기 어려워요. "
                    f"{cut_advice(owner)} 다시 분석해 보세요." + hint)
        return s + " 분야 제한을 풀거나 다른 지역과 비교해 보세요."
    if n_cost:
        return cost_s + hint
    v100 = _entered_cogs(rec, uc, (VAR100,))
    if v100:
        return (f"입력한 원가율({v100})에 카드수수료를 더하면 매출의 100% 이상이라 팔수록 손해예요. "
                "원가율을 확인해 다시 분석해 보세요.")
    return f"이 지역{scope}에는 조건에 맞는 추천 업종이 없어요. 분야 제한이나 비용 조건을 조정해 보세요."


def run_analysis(db: Session, state: EngineState, body: AnalysisIn) -> M.AnalysisRequest:
    if body.area_code not in state.areas:
        raise ApiError(404, "UNKNOWN_AREA", "선택한 상권을 찾을 수 없어요. 상권을 다시 골라 주세요")
    notices = []
    area_code = body.area_code
    if state.area_rows(area_code).empty:            # UC-01 대안 흐름: 데이터 없는 상권 → 인근 상권으로 대체
        a = state.areas[area_code]
        near = sorted((c for c in state.areas if c != area_code and not state.area_rows(c).empty),
                      key=lambda c: (state.areas[c]["lat"] - a["lat"]) ** 2 + (state.areas[c]["lng"] - a["lng"]) ** 2)
        if not near:
            raise ApiError(422, "NO_AREA_DATA", "이 상권은 분석할 데이터가 없어요")
        notices.append(f"{a['name']}에 데이터가 부족해 인근 {state.areas[near[0]]['name']} 기준으로 보정 분석했어요.")
        area_code = near[0]
    unknown = [c for c in body.interests + body.excluded_industries if c not in state.industries]
    if unknown:
        raise ApiError(422, "UNKNOWN_INDUSTRY", f"알 수 없는 업종 코드: {', '.join(unknown)}",
                       [{"field": "interests", "message": "업종을 다시 선택해 주세요"}])
    known_lic = set(LICENSED_INDUSTRIES.values())
    if any(x not in known_lic for x in body.licenses):
        raise ApiError(422, "UNKNOWN_LICENSE", "알 수 없는 자격이 있어요. 보유 자격을 다시 선택해 주세요",
                       [{"field": "licenses", "message": "보유 자격을 다시 선택해 주세요"}])
    cand_codes = [c for c in dict.fromkeys(body.candidate_area_codes) if c in state.areas and c != area_code]   # 중복 없이(데모와 같게)

    req = M.AnalysisRequest(
        public_id=str(uuid.uuid4()),
        main_area_id=state.areas[area_code]["area_id"], budget=body.budget, monthly_rent_limit=body.monthly_rent_limit,
        labor_cost=body.labor_cost, initial_investment=body.initial_investment, business_goal=body.business_goal,
        user_type=body.user_type,
        other_fixed=body.other_fixed, loan_amount=body.loan_amount, loan_rate_annual=body.loan_rate_annual,
        owner_salary=body.owner_salary, licenses_json=json.dumps(body.licenses, ensure_ascii=False),
        categories_json=json.dumps(body.categories, ensure_ascii=False), place_name=body.place_name,
        cogs_json=json.dumps(body.cogs_rates, ensure_ascii=False) if body.cogs_rates else None,
        excluded_json=json.dumps(list(dict.fromkeys(body.excluded_industries)), ensure_ascii=False) if body.excluded_industries else None,
        center_lat=body.lat, center_lng=body.lng, radius_meter=body.radius_m, data_quarter=state.quarter,
        model_version=state.model_version)
    uc = user_condition(req, body.interests)
    try:
        uc.validate()
    except ValueError as e:
        msg = str(e).replace("초기 투자비가 총 예산을 초과", "초기 투자비가 총 창업 예산보다 커요")
        raise ApiError(422, "INVALID_CONDITION", msg, [{"field": "initial_investment", "message": msg}])

    rec = recommend(state.table, area_code, state.model, uc, unit_label=UNIT_LABEL[state.areas[area_code]["level"]])

    req.areas.append(M.RequestArea(area_id=state.areas[area_code]["area_id"], is_primary=True))
    for c in cand_codes:
        req.areas.append(M.RequestArea(area_id=state.areas[c]["area_id"], is_primary=False))
    for i, code in enumerate(body.interests, start=1):
        req.industries.append(M.RequestIndustry(category_id=state.industries[code]["category_id"], preference_order=i))
    db.add(req)
    db.flush()

    # 자치구 단위 안내는 화면 맨 위(area.scope_note)에, 관심 업종 누락은 missing_interests 카드에서 설명 → 여기엔 넣지 않는다
    n_top = len(rec["top"])
    empty = empty_reason(rec, uc, state) if n_top == 0 else None
    if 0 < n_top < SuitabilityParams().top_n:
        n_cost = _shortfall(rec)[0]
        n_low = int(rec.get("n_low_score") or 0)
        notices.append(f"조건에 맞는 추천 업종이 {n_top}개예요."
                       + (f" {fixed_phrase(uc.monthly_fixed_total(), float(uc.owner_salary or 0))}로는 평균 매출로 "
                          f"손익분기를 넘기 어려운 {n_cost}개 업종은 뺐어요." if n_cost else "")
                       + (f" 적합도가 {MIN_TOP_SCORE}점 미만인 {n_low}개 업종({low_names(rec)})은 순위를 채우려고 넣지 않았어요."
                          if n_low else "")
                       + (f" 같은 업종끼리 비교한 입지 위험이 매우 높은(상위 10%) {len(rec['caution_list'])}개 업종은 "
                          "‘주의 업종’ 목록에서 따로 보여 드려요." if len(rec["caution_list"]) else ""))
    on = outlier_note(rec)
    if on:
        notices.append(on)
    notices += state.notices
    req.notices_json = json.dumps(notices, ensure_ascii=False)
    result = M.RecommendationResult(request_id=req.request_id, model_type=state.model.meta.get("model_type", "HYBRID"),
                                    model_version=state.model_version, weights_json=json.dumps(rec["weights"]),
                                    f_applied=rec["f_applied"], f_note=rec["f_note"], n_candidates=rec["n_candidates"],
                                    n_low_score=int(rec.get("n_low_score") or 0),
                                    empty_reason=empty)
    groups = [("TOP", rec["top"]), ("INTEREST", rec["interest"]), ("CAUTION", rec["caution_list"])]
    for item_type, df in groups:
        for r in df.to_dict("records"):
            it = _item(state, area_code, r, item_type, rec["f_applied"], body.owner_salary > 0, uc.monthly_fixed_total())
            result.items.append(M.RecommendationItem(
                category_id=state.industries[r["industry_code"]]["category_id"], item_type=item_type,
                rank_order=it["rank"], suitability_score=it["suitability"], reason=it["reason"], caution=it["caution"],
                demand_score=it["scores"]["D"], stability_score=it["scores"]["S"], cost_score=it["scores"]["F"],
                achievability_ratio=it["achievability_ratio"], eligible=it["eligible"],
                ineligible_reason=it["ineligible_reason"],
                detail_json=json.dumps(it, ensure_ascii=False)))
    db.add(result)
    db.flush()
    db.commit()
    return req


def scope_note(area_name: str, level: str) -> str | None:
    """분석 단위 안내: 상권 데이터가 없어 구 전체 합계로 분석한다는 사실을 결과 맨 위에 보여준다."""
    if level != "district":
        return None
    return f"상권 단위 데이터가 아직 없어 {area_name} 전체(자치구) 기준으로 분석했어요. 반경은 후보 구를 고르는 데만 쓰여요."


def conditions_dict(req: M.AnalysisRequest) -> dict:
    uc = user_condition(req, [])
    return {"budget": req.budget, "monthly_rent_limit": req.monthly_rent_limit, "labor_cost": req.labor_cost,
            "initial_investment": req.initial_investment, "other_fixed": req.other_fixed,
            "loan_amount": req.loan_amount, "loan_rate_annual": req.loan_rate_annual, "owner_salary": req.owner_salary,
            "business_goal": req.business_goal, "user_type": req.user_type,
            "licenses": json.loads(req.licenses_json), "categories": json.loads(req.categories_json),
            "cogs_rates": cogs_of(req), "excluded_industries": excluded_of(req),
            "monthly_fixed_total": round(uc.monthly_fixed_total())}


def candidate_codes(state: EngineState, req: M.AnalysisRequest) -> list[str]:
    """분석할 때 SB-02가 후보로 보여 준 다른 구(분석한 구 제외) — 인근 지역 대안·'조건 바꿔 다시 분석'에서 같은 후보를 쓰게."""
    id2code = {v["area_id"]: k for k, v in state.areas.items()}
    return [id2code[ra.area_id] for ra in req.areas if not ra.is_primary and ra.area_id in id2code]


def analysis_out(db: Session, state: EngineState, req: M.AnalysisRequest) -> dict:
    area = db.get(M.CommercialArea, req.main_area_id)
    result = db.scalar(select(M.RecommendationResult).where(M.RecommendationResult.request_id == req.request_id))
    buckets = {"TOP": [], "INTEREST": [], "CAUTION": []}
    for it in result.items:
        buckets[it.item_type].append(json.loads(it.detail_json))
    buckets["TOP"].sort(key=lambda x: x["rank"] or 99)
    notices = json.loads(req.notices_json or "[]")
    if req.model_version != state.model_version:
        if req.data_quarter != state.quarter:
            notices.append(f"이 분석 이후 데이터가 갱신됐어요({quarter_label(req.data_quarter)} → "
                           f"{quarter_label(state.quarter)}). 새로 분석하면 최신 결과를 볼 수 있어요.")
        else:                                   # 같은 분기 데이터로 계산 방식(모델)만 바뀐 경우
            notices.append("이 분석 이후 계산 방식이 업데이트됐어요. 새로 분석하면 최신 결과를 볼 수 있어요.")
    got = {i["industry_code"] for i in buckets["INTEREST"]}
    cat_names = {c.category_id: (c.category_code, c.category_name) for c in
                 db.scalars(select(M.BusinessCategory).where(
                     M.BusinessCategory.category_id.in_([ri.category_id for ri in req.industries])))}
    missing = [{"industry_code": cat_names[ri.category_id][0], "industry_name": cat_names[ri.category_id][1]}
               for ri in sorted(req.industries, key=lambda x: x.preference_order)
               if cat_names[ri.category_id][0] not in got]
    return {
        "id": req.public_id, "created_at": req.created_at,
        "area": {"area_code": area.area_code, "area_name": area.area_name, "level": area.area_level,
                 "place_name": req.place_name, "radius_m": req.radius_meter, "lat": req.center_lat, "lng": req.center_lng,
                 "scope_note": scope_note(area.area_name, area.area_level),
                 "candidate_area_codes": candidate_codes(state, req)},
        "conditions": conditions_dict(req), "data_quarter": req.data_quarter,
        "data_quarter_label": quarter_label(req.data_quarter), "model_version": req.model_version,
        "business_goal": req.business_goal, "weights": json.loads(result.weights_json),
        "f_applied": result.f_applied, "f_note": result.f_note, "n_candidates": result.n_candidates,
        "n_low_score": result.n_low_score or 0,
        "empty_reason": result.empty_reason,
        "top": buckets["TOP"], "interests": buckets["INTEREST"], "cautions": buckets["CAUTION"],
        "missing_interests": missing, "notices": notices,
    }
