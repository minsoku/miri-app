"""M-05 손익분기점 v2.

v1: 필요 월매출 = 고정비 / (1 − 변동비율),  필요 일 고객 = round(월매출 / 객단가 / 30)
    문제: 30일 고정 · round(내림 가능) · 변동비율≥1이면 0으로 나누기 · 초기투자비 미반영
          · 객단가 미입력 시 기본값 제안(UC-04 대안흐름)이 코드에 없음 · 상권 실제 매출과 비교 없음
v2:
    월 고정비 F = 임대료 + 인건비 + 기타고정비 + 초기투자비/상각개월 + 대출이자(월) + 대표자 목표인건비(선택)
    변동비율 v = 원가율 + 카드수수료율(예상 연매출 구간별 우대수수료) + 기타 매출연동비(배달·플랫폼 등)
    손익분기 월매출 S* = F / (1 − v)
    필요 일 고객 수 N* = ceil(S* / 객단가 / 월 영업일수)
    달성배율 ρ = 상권 동일업종 점포당 월매출 / S*   → 비용 압박 수준(위험/빠듯/보통/여유)
    지역 점포당 하루 결제 = 달력일 기준 값 × (365/12) / 월 영업일 → 필요 일 고객 수와 같은 '영업일' 기준으로 비교
    투자금 회수기간 = 초기투자비 / (예상 월매출×(1−v) − 현금 고정비)
"""
from __future__ import annotations
import math
import numbers
from dataclasses import dataclass, asdict
from .config import BreakEvenParams, CARD_FEE_TIERS, CARD_FEE_OVER_3B, DEFAULT_COGS_RATE


def card_fee_rate(annual_sales: float) -> float:
    for cap, rate in CARD_FEE_TIERS:
        if annual_sales <= cap:
            return rate
    return CARD_FEE_OVER_3B


@dataclass
class BreakEvenInput:
    monthly_rent: float                  # 월 임대료(원)
    labor_cost: float                    # 월 인건비(4대보험 포함, 원)
    other_fixed: float = 0.0             # 관리비·공과금·통신·보험 등(원/월)
    initial_investment: float = 0.0      # 인테리어·설비 등(보증금 제외, 원)
    loan_amount: float = 0.0
    loan_rate_annual: float = 0.0        # 예: 0.05
    owner_salary: float = 0.0            # 대표자 목표 인건비(선택) — 0이면 '본인 인건비 미포함' 경고
    cogs_rate: float | None = None       # 원가율. None이면 업종 대분류 기본값(외식업만 존재)
    other_variable_rate: float = 0.0     # 배달·플랫폼 수수료 등
    avg_ticket: float | None = None      # 객단가. None이면 상권·업종 실데이터 객단가 사용
    operating_days: int | None = None


def ratio_floor(x: float) -> float:
    """달성배율 표시값: 소수 둘째 자리에서 내림. 반올림하면 0.9996이 '1.00배'로 보여 '위험'(1 미만) 배지·
    '평균 매출이면 적자' 문장과 어긋난다 → 내림 값으로 배지·문장·추천 제외를 모두 판정한다(부동소수 오차는 1e-9 보정)."""
    return math.floor(x * 100 + 1e-9) / 100


def calculate(inp: BreakEvenInput, category: str | None = None, market_sales_ps_m: float | None = None,
              market_ticket: float | None = None, market_tx_ps_day: float | None = None,
              p: BreakEvenParams = BreakEvenParams(), ticket_label: str = "이 지역 같은 업종 실제 평균") -> dict:
    warnings = []
    days = inp.operating_days or p.operating_days
    cogs = inp.cogs_rate
    if cogs is None:
        cogs = DEFAULT_COGS_RATE.get(category or "", None)
        if cogs is None:
            raise ValueError("원가율 입력 필요: 이 업종 대분류에는 공식 근거가 있는 기본 원가율이 없음")
        warnings.append(f"원가율을 넣지 않아 {category} 평균 원가율 {cogs:.1%}로 계산했어요")
    def _ok(x):
        return isinstance(x, numbers.Real) and math.isfinite(x) and x > 0
    ticket = inp.avg_ticket if _ok(inp.avg_ticket) else (market_ticket if _ok(market_ticket) else None)
    if ticket is None:
        raise ValueError("객단가 입력 필요(상권 실데이터 객단가도 없음)")
    for name in ("monthly_rent", "labor_cost", "other_fixed", "initial_investment", "loan_amount",
                 "loan_rate_annual", "owner_salary", "other_variable_rate"):
        if getattr(inp, name) < 0:
            raise ValueError(f"{name}는 0 이상이어야 함")
    if not _ok(inp.avg_ticket):
        warnings.append(f"객단가를 넣지 않아 {ticket_label} {ticket:,.0f}원으로 계산했어요")

    depreciation = inp.initial_investment / p.depreciation_months
    interest = inp.loan_amount * inp.loan_rate_annual / 12
    fixed = inp.monthly_rent + inp.labor_cost + inp.other_fixed + depreciation + interest + inp.owner_salary
    if inp.owner_salary == 0:
        warnings.append("목표 월수입(대표자)을 넣지 않아 '내 월급 0원' 기준 손익분기예요")

    # 카드수수료는 연매출 구간에 따라 달라짐 → 손익분기 매출 구간과 수수료가 일치할 때까지 반복(최대 5회)
    fee = card_fee_rate(0)
    for _ in range(5):
        v = cogs + fee + inp.other_variable_rate
        if v >= 1:
            raise ValueError(f"변동비율 {v:.1%} ≥ 100%: 팔수록 손해(원가율·수수료 재확인)")
        bep = fixed / (1 - v)
        new_fee = card_fee_rate(bep * 12)
        if new_fee == fee:
            break
        fee = new_fee
    if bep > p.max_required_sales:
        raise ValueError(f"변동비율 {v:.1%}: 매출에서 남는 몫이 거의 없어 필요 매출이 비현실적으로 커요(원가율·수수료 재확인)")
    cm = 1 - v
    out = {
        "monthly_fixed_cost": round(fixed),
        "fixed_breakdown": {"임대료": inp.monthly_rent, "인건비": inp.labor_cost, "기타고정비": inp.other_fixed,
                            "감가상각": round(depreciation), "대출이자": round(interest), "대표자인건비": inp.owner_salary},
        "variable_cost_rate": round(v, 4),
        "variable_breakdown": {"원가율": cogs, "카드수수료": fee, "기타": inp.other_variable_rate},
        "contribution_margin_rate": round(cm, 4),
        "required_monthly_sales": round(bep),
        "required_daily_sales": round(bep / days),
        "required_daily_customers": math.ceil(bep / ticket / days),
        "avg_ticket_used": round(ticket),
        "operating_days": days,
    }
    if _ok(market_sales_ps_m):
        lo, mid, hi = p.pressure_bands
        raw = None
        if bep > 0:
            raw = market_sales_ps_m / bep
            ratio = ratio_floor(raw)            # 배지·문장·추천 제외 판정은 모두 화면에 보이는 내림 값으로
            level = "위험" if ratio < lo else "빠듯" if ratio < mid else "보통" if ratio < hi else "여유"
        else:                                   # 월 고정비 0원 → 손익분기 0원: 배율은 정의되지 않음(무한대)
            ratio, level = None, "여유"
            warnings.append("월 고정비가 0원이라 손익분기 매출도 0원이에요")
        cash_fixed = fixed - depreciation
        monthly_cash_profit = market_sales_ps_m * cm - cash_fixed
        payback = (math.ceil(inp.initial_investment / monthly_cash_profit)
                   if inp.initial_investment > 0 and monthly_cash_profit > 0 else None)
        if payback is not None and payback > p.max_payback_months:
            payback = None                      # 100년 넘게 걸리면 '회수 기간 없음'과 같게(평균 매출로는 회수 어려움)
        out.update({
            "market_sales_ps_m": round(market_sales_ps_m),
            "achievability_ratio": ratio,       # 1.0 = 평균 점포 매출이 딱 손익분기(소수 둘째 자리 내림)
            "ratio_for_score": None if raw is None else round(raw, 3),   # 비용 적합도(F) 연속 점수용(화면 비표시)
            "cost_pressure": level,
            "profit_at_market_avg": round(market_sales_ps_m * cm - fixed),
            "payback_months": payback,
        })
        if _ok(market_tx_ps_day):
            tx_op = market_tx_ps_day * p.days_per_month / days          # 달력일 → 영업일 기준
            out["market_tx_ps_day"] = round(tx_op, 1)
            # 필요 결제는 올림 전 값으로 비교(평균 0.7건인 곳에서 '필요 1건 ÷ 0.7 = 1.4배'처럼 올림이 부풀리지 않게)
            out["customers_vs_market"] = round(bep / ticket / days / tx_op, 2)
    out["warnings"] = warnings
    return out
