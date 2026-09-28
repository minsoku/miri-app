"""UC-04 손익분기점 계산(SB-07). 기본값은 분석 조건, 화면에서 바꾼 값만 덮어쓴다."""
from __future__ import annotations
import json
import math
from sqlalchemy.orm import Session
from miri_engine.breakeven import BreakEvenInput, calculate
from miri_engine.config import DEFAULT_COGS_RATE
from .. import models as M
from ..errors import ApiError
from ..schemas import BreakEvenIn
from .analysis import area_code_of, cogs_of
from .engine import EngineState
from . import narrative as N


OVERRIDE_KEYS = ("monthly_rent", "labor_cost", "other_fixed", "initial_investment", "loan_amount", "loan_rate_annual",
                 "owner_salary", "cogs_rate", "other_variable_rate", "avg_ticket")


def _ok(x):
    return x is not None and isinstance(x, (int, float)) and not (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))


def compute(db: Session, state: EngineState, req: M.AnalysisRequest, body: BreakEvenIn, persist=True) -> dict:
    code = body.industry_code
    ind = state.industries.get(code)
    if ind is None:
        raise ApiError(404, "UNKNOWN_INDUSTRY", "알 수 없는 업종이에요")
    area_code = area_code_of(db, req)
    r = state.row(area_code, code)

    def pick(v, default):
        return default if v is None else v
    # 원가율 기본값: 이 화면에서 넣은 값 → 분석 조건(SB-03)에서 넣은 분야별 원가율 → 업종 대분류 평균(외식업만)
    cond_cogs = cogs_of(req).get(ind["category"])
    cogs_source = "user" if body.cogs_rate is not None else "analysis" if cond_cogs is not None else "default"
    inp = BreakEvenInput(
        monthly_rent=pick(body.monthly_rent, req.monthly_rent_limit), labor_cost=pick(body.labor_cost, req.labor_cost),
        other_fixed=pick(body.other_fixed, req.other_fixed),
        initial_investment=pick(body.initial_investment, req.initial_investment),
        loan_amount=pick(body.loan_amount, req.loan_amount), loan_rate_annual=pick(body.loan_rate_annual, req.loan_rate_annual),
        owner_salary=pick(body.owner_salary, req.owner_salary), cogs_rate=pick(body.cogs_rate, cond_cogs),
        other_variable_rate=pick(body.other_variable_rate, 0.0), avg_ticket=body.avg_ticket)
    mkt = {k: (None if r is None or not _ok(r.get(k)) else float(r[k])) for k in ("sales_ps_m", "ticket", "tx_ps_day")}
    # 객단가 기본값(UC-04 대안 흐름): 입력값 → 이 지역 같은 업종 실제 평균 → 서울 같은 업종 평균
    ticket_source = "user" if body.avg_ticket is not None else "local" if mkt["ticket"] is not None else \
        "seoul" if _ok(ind.get("seoul_ticket")) else None
    market_ticket = mkt["ticket"] if ticket_source == "local" else float(ind["seoul_ticket"]) if ticket_source == "seoul" else None
    label = "서울 같은 업종 평균(이 지역 데이터 없음)" if ticket_source == "seoul" else "이 지역 같은 업종 실제 평균"
    try:
        res = calculate(inp, category=ind["category"], market_sales_ps_m=mkt["sales_ps_m"],
                        market_ticket=market_ticket, market_tx_ps_day=mkt["tx_ps_day"], ticket_label=label)
    except ValueError as e:
        msg = str(e)
        if "변동비율" in msg:
            # value: 계산에 쓴 원가율(분석 조건에서 넣은 값일 수 있음) → 화면이 입력칸을 그 값으로 채운다
            huge = "비현실" in msg      # 100% 미만이지만 남는 몫이 거의 없어 필요 매출이 비현실적으로 큰 경우
            raise ApiError(422, "VARIABLE_RATE_TOO_HIGH", ("원가율에 카드수수료와 기타 수수료를 더하면 100%에 너무 가까워 필요 매출이 비현실적으로 커요. 원가율을 확인해 주세요" if huge else
                           "원가율에 카드수수료(필요 매출 규모에 따라 0.4~2%)와 기타 수수료를 더하면 100% 이상이라 팔수록 손해예요. 원가율을 확인해 주세요"),
                           [{"field": "cogs_rate", "message": "원가율을 낮춰 주세요",
                             "value": inp.cogs_rate if inp.cogs_rate is not None else DEFAULT_COGS_RATE.get(ind["category"])},
                            {"field": "other_variable_rate", "message": "배달·기타 수수료를 확인해 주세요", "value": inp.other_variable_rate}])
        if "원가율 입력 필요" in msg:
            raise ApiError(422, "COGS_REQUIRED", f"{N.josa(ind['category'], '은/는')} 공식 기본 원가율이 없어요. 원가율(매출 대비 재료·상품 원가)을 입력해 주세요",
                           [{"field": "cogs_rate", "message": "원가율을 입력해 주세요"}])
        if "객단가" in msg:
            raise ApiError(422, "TICKET_REQUIRED", "이 지역 실제 객단가 데이터가 없어요. 객단가를 입력해 주세요",
                           [{"field": "avg_ticket", "message": "객단가를 입력해 주세요"}])
        raise ApiError(422, "INVALID_INPUT", msg)

    bep, v = res["required_monthly_sales"], res["variable_cost_rate"]
    owner = float(inp.owner_salary)
    # 변동비는 나머지로(필요 매출 = 고정비 + 변동비 + 목표 월수입이 원 단위까지 맞게 — 반올림한 변동비율로 곱하면
    # 아주 큰 금액에서 몇백 원이 어긋난다)
    fe, ow = round(res["monthly_fixed_cost"] - owner), round(owner)
    comp = {"fixed_ex_owner": fe, "variable": bep - fe - ow, "owner_salary": ow, "total": bep}
    max_fixed = round(mkt["sales_ps_m"] * res["contribution_margin_rate"]) if mkt["sales_ps_m"] else None
    inputs = {"monthly_rent": inp.monthly_rent, "labor_cost": inp.labor_cost, "other_fixed": inp.other_fixed,
              "initial_investment": inp.initial_investment, "loan_amount": inp.loan_amount,
              "loan_rate_annual": inp.loan_rate_annual, "owner_salary": inp.owner_salary,
              "cogs_rate": res["variable_breakdown"]["원가율"], "cogs_is_default": cogs_source == "default",
              "cogs_source": cogs_source,
              "other_variable_rate": inp.other_variable_rate, "avg_ticket": body.avg_ticket,
              "ticket_is_market": body.avg_ticket is None, "ticket_source": ticket_source,
              # 이 계산에서 화면이 덮어쓴 항목(나머지는 분석 조건·기본값) — 저장된 계산을 다시 열 때 '바꾼 값'을 구분하는 데 쓴다
              "overridden": [k for k in OVERRIDE_KEYS if getattr(body, k) is not None],
              # 기본값이 없어 꼭 넣어야 했던 항목(원가율: 조건 입력값·업종 평균 없음 / 객단가: 지역·서울 평균 없음)
              "required": [k for k, need in (("cogs_rate", cond_cogs is None and DEFAULT_COGS_RATE.get(ind["category"]) is None),
                                             ("avg_ticket", mkt["ticket"] is None and not _ok(ind.get("seoul_ticket"))))
                           if need and getattr(body, k) is not None]}
    # 덮어쓴 항목 중 기본값(분석 조건·조건 원가율·업종 평균·지역 평균 객단가)과 실제로 다른 것 — '바꾼 값 적용 중' 표시 기준
    defaults = {"monthly_rent": req.monthly_rent_limit, "labor_cost": req.labor_cost, "other_fixed": req.other_fixed,
                "initial_investment": req.initial_investment, "loan_amount": req.loan_amount,
                "loan_rate_annual": req.loan_rate_annual, "owner_salary": req.owner_salary,
                "cogs_rate": cond_cogs if cond_cogs is not None else DEFAULT_COGS_RATE.get(ind["category"]),
                "other_variable_rate": 0.0,
                "avg_ticket": mkt["ticket"] if mkt["ticket"] is not None else
                float(ind["seoul_ticket"]) if _ok(ind.get("seoul_ticket")) else None}
    tol = {"avg_ticket": 1.0}                     # 평균 객단가는 원 단위로 보여 주므로 1원 차이는 같은 값
    # 기본값이 없어 꼭 넣어야 했던 값(inputs.required)은 '바꾼 값'이 아니라 '직접 넣은 값'이라 뺀다
    inputs["changed"] = [k for k in inputs["overridden"] if k not in inputs["required"]
                         and (defaults[k] is None or abs(float(getattr(body, k)) - float(defaults[k])) > tol.get(k, 1e-6))]
    out = {"analysis_id": req.public_id, "area_code": area_code, "area_name": state.areas[area_code]["name"],
           "industry_code": code, "industry_name": ind["name"], "category": ind["category"],
           "inputs": inputs, **{k: res.get(k) for k in (
               "monthly_fixed_cost", "fixed_breakdown", "variable_cost_rate", "variable_breakdown",
               "contribution_margin_rate", "required_monthly_sales", "required_daily_sales", "required_daily_customers",
               "avg_ticket_used", "operating_days", "market_sales_ps_m", "achievability_ratio", "cost_pressure",
               "profit_at_market_avg", "payback_months", "market_tx_ps_day", "customers_vs_market", "warnings")},
           "max_fixed_for_bep": max_fixed, "composition": comp}
    out["fixed_breakdown"] = {k: round(float(v)) for k, v in out["fixed_breakdown"].items()}
    out["warnings"] = list(out["warnings"] or [])
    if mkt["sales_ps_m"] is None:
        out["warnings"].append("이 지역 같은 업종의 카드 매출 데이터가 부족해 평균 매출과의 비교(달성 가능성)는 할 수 없어요")
    x = N.sales_outlier(r) if r is not None else None
    out["sales_outlier"] = None if x is None else round(x, 1)
    if x is not None:                              # SB-05에서 추천 제외한 '대형 점포 가능' 평균 — 배율·회수 기간도 참고용
        kind = N.BIG_STORE.get(ind["category"], "대형 점포")
        out["warnings"].append(f"이 지역 점포당 매출이 서울 같은 업종 중간값의 {x:.1f}배예요 — {N.josa(kind, '이/가')} 섞인 평균일 수 있어 "
                               "달성 가능성·투자 회수 기간은 참고용이에요")
    if req.budget > 0 and inp.initial_investment > req.budget:
        out["warnings"].append(f"초기 투자비가 총 창업 예산({N.won(req.budget)})보다 커요 — 예산으로는 운영자금을 마련할 수 없어요")
    cvm = res.get("customers_vs_market")
    if ticket_source == "user" and _ok(cvm) and cvm >= 1.2:
        # 매출 기준 달성배율은 '평균 점포 매출'과 비교하므로, 입력 객단가가 지역 평균보다 낮으면 손님 수로는 훨씬 어려울 수 있다
        out["warnings"].append(
            f"입력한 객단가({res['avg_ticket_used']:,}원)로는 하루 {res['required_daily_customers']:,}건이 필요해 "
            f"이 지역 점포 평균 결제({res['market_tx_ps_day']:,}건)의 {cvm:.1f}배예요 — 매출 기준 달성 가능성보다 어려울 수 있어요")
    if persist:
        be = M.BreakEvenAnalysis(
            request_id=req.request_id, category_id=ind["category_id"], monthly_fixed_cost=res["monthly_fixed_cost"],
            variable_cost_rate=v, avg_transaction_amount=res["avg_ticket_used"], required_monthly_sales=bep,
            required_daily_customers=res["required_daily_customers"], other_fixed=round(inp.other_fixed),
            depreciation=res["fixed_breakdown"]["감가상각"], card_fee_rate=res["variable_breakdown"]["카드수수료"],
            cogs_rate=res["variable_breakdown"]["원가율"], operating_days=res["operating_days"],
            achievability_ratio=res.get("achievability_ratio"), cost_pressure=res.get("cost_pressure"),
            payback_months=res.get("payback_months"), input_json=json.dumps(inputs, ensure_ascii=False),
            result_json=json.dumps({k: out[k] for k in out if k not in ("inputs",)}, ensure_ascii=False, default=float))
        db.add(be)
        db.commit()
        out["id"] = be.break_even_id
    else:
        out["id"] = 0
    return out


def get_saved(db: Session, req: M.AnalysisRequest, break_even_id: int) -> dict:
    """저장된 손익분기 결과(리포트에 반영한 값)를 그대로 돌려준다."""
    be = db.get(M.BreakEvenAnalysis, break_even_id)
    if be is None or be.request_id != req.request_id:
        raise ApiError(404, "BREAKEVEN_NOT_FOUND", "손익분기 계산 결과를 찾을 수 없어요")
    out = json.loads(be.result_json)
    out["inputs"] = json.loads(be.input_json)
    out["id"] = be.break_even_id
    return out
