"""M-03 업종 적합도 v2.

v1: 적합도 = 수요×0.35 + 공급×0.25 + 비용×0.20 + 위험안정성×0.20
    문제: ① 수요(유동·주거·직장인구)가 지역 단위라 같은 지역 안 모든 업종에 동일 → 업종 순위를 못 가름
          ② '경쟁'이 공급 점수와 위험 점수에 이중 반영, 임대료도 비용·위험에 이중 반영
          ③ 공급·비용은 '감점' 항목인데 식에서는 + 로 더함(방향 미정의)
          ④ 입력받은 창업 목표(business_goal)를 계산에 안 씀  ⑤ 가중치 근거 없음  ⑥ 면허 업종도 추천 대상
v2: 적합도 = w_D·D + w_S·S + w_F·F   (모든 항목 0~100, '높을수록 좋음'으로 통일)
    D (매출 잠재력) = 이 지역 동일 업종 점포당 월매출의 서울 내 백분위  → 업종마다 다름 ①
                      (점포당 매출 = 수요 ÷ 공급 → 경쟁이 자연히 반영, 별도 공급 점수 없음 ②)
    S (생존 안정성) = 100 − 폐업 위험점수(M-04)
    F (내 비용 적합도) = 손익분기 달성배율 ρ(= 지역 평균 점포 매출 ÷ 내 손익분기 매출)를 0~100 환산
                      ρ≤0.8 → 0, ρ≥1.5 → 100, 사이 선형.
                      후보 업종 '전부'에 원가율이 있을 때만 적용(일부만 F가 있으면 비교가 불공정) → 아니면 D·S로만 순위
    가중치: 창업 목표별 프리셋(config.GOAL_WEIGHTS) ④ — 정책값이므로 민감도 분석으로 안정성 확인 ⑤
    필터: 매출 데이터 있는 업종 · 최근 1년 평균 점포 1개 이상 · 면허 업종은 자격 보유 시만 ⑥
          · 매출 규모: 이 지역 점포당 평균 월매출 < 사용자 월 고정비 → 제외 (원가율 0%여도 적자이므로 원가율 불필요)
          · (v2.1) 원가율을 아는 업종(외식업)은 평균 매출이 손익분기에 못 미치면(달성배율 < 1) 제외
          · 입지 위험(같은 업종 내 백분위) 상위 10%는 TOP N 제외 → '주의 업종' · 관심 업종은 항상 분석 결과 반환
    위험도 두 축: 종합 위험(risk_score, 업종 간 비교, 등급) / 입지 위험(risk_pct_in_ind, 같은 업종끼리 비교)
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
import pandas as pd
from .config import GOAL_WEIGHTS, SuitabilityParams, DEFAULT_COGS_RATE, LICENSED_INDUSTRIES
from .breakeven import BreakEvenInput, calculate as be_calculate
from .risk import RiskModel
from .normalize import pct_rank
from . import explain


@dataclass
class UserCondition:
    business_goal: str = "기본"               # 기본/안정형/고수익형/저비용형
    budget: float | None = None               # 총 창업 예산
    monthly_rent: float | None = None         # 월 임대료(한도)
    labor_cost: float | None = None           # 월 인건비
    other_fixed: float = 0.0
    initial_investment: float = 0.0
    loan_amount: float = 0.0
    loan_rate_annual: float = 0.0
    owner_salary: float = 0.0                 # 대표자 목표 인건비(선택)
    cogs_by_category: dict | None = None      # 사용자가 아는 원가율 {"소매업": 0.7}
    licenses: tuple = ()                      # 보유 자격 ("미용사(일반)", ...)
    interest_industries: tuple = ()           # 관심 업종 코드 (request_industries)
    excluded_industries: tuple = ()
    categories: tuple = ()                    # 대분류 제한 ("외식업",) — 비우면 전체

    def validate(self):
        errs = []
        for k in ("budget", "monthly_rent", "labor_cost", "other_fixed", "initial_investment",
                  "loan_amount", "loan_rate_annual", "owner_salary"):
            v = getattr(self, k)
            if v is not None and v < 0:
                errs.append(f"{k}는 0 이상이어야 함")
        if self.budget is not None and self.initial_investment > self.budget:
            errs.append("초기 투자비가 총 예산을 초과")
        if self.business_goal not in GOAL_WEIGHTS:
            errs.append(f"창업 목표는 {list(GOAL_WEIGHTS)} 중 하나")
        if errs:
            raise ValueError("; ".join(errs))

    @property
    def has_cost_inputs(self) -> bool:
        return self.monthly_rent is not None and self.labor_cost is not None

    def breakeven_input(self, cogs_rate: float) -> BreakEvenInput:
        return BreakEvenInput(monthly_rent=self.monthly_rent, labor_cost=self.labor_cost,
                              other_fixed=self.other_fixed, initial_investment=self.initial_investment,
                              loan_amount=self.loan_amount, loan_rate_annual=self.loan_rate_annual,
                              owner_salary=self.owner_salary, cogs_rate=cogs_rate)

    def monthly_fixed_total(self) -> float:
        """M-05와 같은 정의의 월 고정비(감가상각·이자·대표자 인건비 포함)."""
        from .config import BreakEvenParams
        return (self.monthly_rent + self.labor_cost + self.other_fixed
                + self.initial_investment / BreakEvenParams().depreciation_months
                + self.loan_amount * self.loan_rate_annual / 12 + self.owner_salary)


def location_grade(pct: int) -> str:
    """입지 위험 등급: 같은 업종 안에서의 백분위에 종합 등급과 같은 컷오프 적용."""
    from .config import risk_grade
    return risk_grade(pct)


def f_score(ratio: float, p: SuitabilityParams) -> float:
    return 100.0 * float(np.clip((ratio - p.f_ratio_zero) / (p.f_ratio_full - p.f_ratio_zero), 0.0, 1.0))


def combine(D, S, F, w: dict) -> float:
    items = [(w["D"], D), (w["S"], S), (w["F"], F)]
    items = [(wt, v) for wt, v in items if v is not None and not (isinstance(v, float) and math.isnan(v))]
    tw = sum(wt for wt, _ in items)
    return sum(wt * v for wt, v in items) / tw if tw > 0 else float("nan")


def risk_table(feats_quarter: pd.DataFrame, model: RiskModel) -> pd.DataFrame:
    """한 분기 전 지역×업종 위험도 (배치에서 분기 1회 계산해 저장 → API는 조회만).
    risk_score        : 서울 전체 지역×업종 중 백분위(업종 간 비교 가능, 등급 기준)
    risk_pct_in_ind   : 같은 업종 안에서의 백분위(입지 비교용, '같은 한식끼리 비교')"""
    d = feats_quarter[feats_quarter["exp4"] > 0]
    new_q = sorted(set(d["quarter"].astype(int)) - set(model.level_const))
    if new_q:                                   # 전체 단면이 들어오므로 여기서는 안전하게 보정 가능
        model.calibrate_levels(d[d["quarter"].isin(new_q)])
    pr = model.predict(d)
    out = d.join(pr)
    out["risk_pct_in_ind"] = pct_rank(out["pred_q_rate"], out["industry_code"]).round().astype(int)
    return out


OUTLIER_REASON = "점포당 매출이 서울 중간값"      # 추천 제외 이유 앞부분(화면·문장이 이 말로 알아본다)


def sales_outlier_x(r, p: SuitabilityParams = SuitabilityParams()) -> float | None:
    """점포당 매출 ÷ 서울 같은 업종 중간값 — outlier_sales_x배 이상일 때만(아니면 None)."""
    v, med = r.get("sales_ps_m"), r.get("sales_med")
    if v is None or med is None or pd.isna(v) or pd.isna(med) or med <= 0 or v / med < p.outlier_sales_x:
        return None
    return float(v / med)


def score_area(area_rows: pd.DataFrame, model: RiskModel, user: UserCondition,
               p: SuitabilityParams = SuitabilityParams()) -> tuple[pd.DataFrame, bool]:
    """area_rows: risk_table()에서 해당 지역만 뽑은 행."""
    user.validate()
    w = GOAL_WEIGHTS[user.business_goal]
    fixed_total = user.monthly_fixed_total() if user.has_cost_inputs else None
    rows = []
    for idx, r in area_rows.iterrows():
        code = r["industry_code"]
        lic = LICENSED_INDUSTRIES.get(code)
        why_not = None
        if not r["has_sales_data"]:
            why_not = "매출 데이터 없음"
        elif r["stores_avg4"] < p.min_avg_stores:
            why_not = "이 지역 점포 부족(수요 미검증)"
        elif pd.isna(r["sales_ps_m"]):
            why_not = "카드 매출 데이터 부족"
        elif pd.notna(r.get("sales_n")) and r["sales_n"] < p.min_sales_areas:
            why_not = f"매출을 비교할 지역이 적음({int(r['sales_n'])}곳)"
        elif lic and lic not in user.licenses:
            why_not = f"{lic} 자격 필요"
        elif code in user.excluded_industries:
            why_not = "사용자 제외"
        elif user.categories and r["category"] not in user.categories:
            why_not = "대분류 제한"
        elif fixed_total is not None and r["sales_ps_m"] < fixed_total:
            why_not = "평균 매출이 월 고정비보다 적음"
        D = float(r["demand_D"]) if pd.notna(r["demand_D"]) else float("nan")
        S = 100.0 - float(r["risk_score"])
        F, ratio, cogs_missing, be_error = float("nan"), None, False, False
        is_interest = code in user.interest_industries
        if user.has_cost_inputs and (why_not is None or is_interest) and pd.notna(r["sales_ps_m"]):
            # 후보와 관심 업종만 계산 (한 행 오류가 전체를 멈추지 않게)
            cogs = (user.cogs_by_category or {}).get(r["category"], DEFAULT_COGS_RATE.get(r["category"]))
            if cogs is None:
                cogs_missing = True
            else:
                try:
                    be = be_calculate(user.breakeven_input(cogs), category=r["category"],
                                      market_sales_ps_m=r["sales_ps_m"], market_ticket=r["ticket"],
                                      market_tx_ps_day=r["tx_ps_day"])
                    ratio = be.get("achievability_ratio")
                    if ratio is not None:
                        F = f_score(be["ratio_for_score"], p)     # 점수는 연속값, 표시·제외 판정은 내림 값(ratio)
                    elif be["required_monthly_sales"] == 0:      # 고정비 0원 → 어떤 매출이든 흑자: 비용 적합도 최고
                        F = 100.0
                    else:
                        F = float("nan")
                except ValueError as e:
                    F = float("nan")
                    if "변동비율" in str(e):         # 원가율+카드수수료 ≥ 100%: 팔수록 손해 → 추천 제외(계산 불가로 남기지 않음)
                        why_not = why_not or "원가·수수료가 매출의 100% 이상"
                    else:
                        be_error = True
        if why_not is None and ratio is not None and ratio < 1.0:
            # 원가율 기본값(외식업 40.7%)까지 넣으면 평균 매출로도 손익분기를 못 넘는 업종 → 추천 TOP에서 제외(적자 업종 추천 방지)
            why_not = "평균 매출로 손익분기 미달"
        if (why_not is None and int(r["risk_pct_in_ind"]) < p.exclude_location_pct_ge
                and (x := sales_outlier_x(r, p)) is not None):
            # 다른 조건은 모두 통과했지만 평균 매출이 도매 상가·대형 점포 때문에 부풀었을 수 있는 업종 → 마지막에 제외
            # (비용·손익분기에 걸리면 그 이유를, 입지 위험 90 이상이면 주의 업종으로 — 제외 이유가 하나로 정해지게)
            why_not = f"{OUTLIER_REASON}의 {x:.1f}배(대형 점포 가능)"
        rows.append({
            "industry_code": code, "industry_name": r["industry_name"], "category": r["category"],
            "eligible": why_not is None, "ineligible_reason": why_not,
            "is_interest": is_interest,
            "D": D, "S": S, "F": F, "cogs_missing": cogs_missing, "be_error": be_error,
            "risk_score": int(r["risk_score"]), "risk_grade": r["risk_grade"],
            "risk_pct_in_ind": int(r["risk_pct_in_ind"]),
            "location_grade": location_grade(int(r["risk_pct_in_ind"])),
            "pred_annual_rate": float(r["pred_annual_rate"]),
            "sales_ps_m": float(r["sales_ps_m"]) if pd.notna(r["sales_ps_m"]) else None,
            "ticket": float(r["ticket"]) if pd.notna(r["ticket"]) else None,
            "stores_avg4": float(r["stores_avg4"]), "confidence": r["confidence"],
            "achievability_ratio": ratio, "risk_factors": model.top_factors(r, r, n=4),
            "sales_outlier": sales_outlier_x(r, p),        # 대형 점포가 섞인 듯한 평균(설명 문장에서 인용하지 않게)
        })
    tab = pd.DataFrame(rows)
    elig = tab["eligible"]
    # F는 후보 전부에 계산될 때만 적용 (일부 업종만 F가 있으면 순위가 왜곡됨).
    # 후보가 하나도 없으면 관심 업종(매출 있음)을 기준으로 — 안 그러면 고정비가 너무 커 후보가 0개일 때 F가 빠져
    # 비용이 클수록 관심 업종 점수가 오히려 올라간다
    # (원가율을 모르는 관심 업종은 기준에서 뺀다 — 그 업종 하나 때문에 다른 관심 업종의 비용 적합도가 꺼지지 않게)
    base = elig if elig.any() else (tab["is_interest"] & tab["sales_ps_m"].notna() & ~tab["cogs_missing"])
    f_applied = bool(user.has_cost_inputs and base.any() and tab.loc[base, "F"].notna().all())
    tab["F_applied"] = f_applied
    # 소수 둘째 자리까지(화면은 정수로 반올림) — 첫째 자리로 먼저 반올림하면 76.46 → 76.5 → '77'처럼 두 번 올라간다
    tab["suitability"] = [round(combine(r.D, r.S, r.F if f_applied else float("nan"), w), 2)
                          for r in tab.itertuples()]
    return tab, f_applied


def recommend(risk_tab_quarter: pd.DataFrame, area_id: str, model: RiskModel, user: UserCondition,
              p: SuitabilityParams = SuitabilityParams(), unit_label: str = "지역") -> dict:
    area_rows = risk_tab_quarter[risk_tab_quarter["area_id"] == str(area_id)]
    if area_rows.empty:
        raise ValueError(f"해당 분기에 지역 데이터 없음: {area_id}")
    if "sales_med" not in area_rows.columns:
        # 같은 업종의 서울 점포당 매출 중간값(대형 점포 판정용) — API 엔진 상태(engine.load_state)는 미리 계산해 둔다
        med = risk_tab_quarter.groupby("industry_code")["sales_ps_m"].median()
        area_rows = area_rows.assign(sales_med=area_rows["industry_code"].map(med))
    tab, f_applied = score_area(area_rows, model, user, p)
    cand = tab[tab["eligible"]].sort_values(["suitability", "risk_score", "D"], ascending=[False, True, False])
    bad_loc = cand["risk_pct_in_ind"] >= p.exclude_location_pct_ge
    # 순위를 채우려고 아주 낮은 점수까지 넣지 않는다(화면의 정수 점수로 판단: 19.67은 '20'이라 통과)
    low = np.floor(cand["suitability"] + 0.5) < p.min_top_score
    top = cand[~bad_loc & ~low].head(p.top_n).copy()
    # 주의 업종은 전부 반환 — 입지 위험이 높은 순(같으면 적합도 순)
    caution = cand[bad_loc].sort_values(["risk_pct_in_ind", "suitability", "industry_code"], ascending=[False, False, True]).copy()
    # 관심 업종은 사용자가 고른 순서대로
    pick = {c: i for i, c in enumerate(user.interest_industries)}
    interest = tab[tab["is_interest"]].copy()
    interest = interest.iloc[sorted(range(len(interest)), key=lambda i: pick.get(interest["industry_code"].iloc[i], 1 << 30))]
    for t in (top, caution, interest):
        recs = t.to_dict("records")
        t["reason"] = [explain.recommendation_reason(r, unit_label) for r in recs]
        t["caution"] = [explain.recommendation_caution(r) for r in recs]
    top["rank_order"] = range(1, len(top) + 1)
    elig = tab["eligible"]
    if f_applied:
        note = None
    elif not user.has_cost_inputs:
        note = "비용 입력 없음"
    elif tab.loc[elig, "cogs_missing"].any():
        note = "일부 후보 업종에 원가율 근거가 없어 비용 적합도는 순위에 미반영(표시만)"
    elif tab.loc[elig, "be_error"].any():
        note = "일부 후보 업종의 손익분기 계산 불가(객단가 등 결측)로 비용 적합도는 순위에 미반영"
    else:
        note = "후보 업종 없음"
    return {"weights": GOAL_WEIGHTS[user.business_goal], "f_applied": f_applied, "f_note": note,
            "top": top, "caution_list": caution, "interest": interest,
            "n_candidates": int(len(cand)), "n_low_score": int((~bad_loc & low).sum()),
            "low_list": [(r["industry_name"], float(r["suitability"])) for _, r in cand[~bad_loc & low].iterrows()],
            "table": tab}
