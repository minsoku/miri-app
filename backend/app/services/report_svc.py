"""UC-05 액션 리포트(SB-08) · UC-06 저장/조회(SB-09)."""
from __future__ import annotations
import json
import math
import uuid
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .. import models as M
from ..errors import ApiError
from ..schemas import BreakEvenIn
from . import narrative as N
from . import breakeven_svc, risk_svc
from .analysis import area_code_of, cogs_of, covers_fixed, excluded_of, fixed_phrase, user_condition
from .catalog import REGISTRATION_NOTES, quarter_label
from miri_engine.breakeven import card_fee_rate
from miri_engine.config import DEFAULT_COGS_RATE, LICENSED_INDUSTRIES, SuitabilityParams
from .engine import EngineState

ROLE_TO_TARGET = {"PRE_FOUNDER": "예비창업자", "OWNER": "자영업자"}


def _ok(x):
    return x is not None and not (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))


def _top_items(db: Session, req: M.AnalysisRequest) -> list[dict]:
    res = db.scalar(select(M.RecommendationResult).where(M.RecommendationResult.request_id == req.request_id))
    if res is None:
        return []
    return [json.loads(i.detail_json) for i in res.items if i.item_type == "TOP"]


def _user_can_open(row, req: M.AnalysisRequest, fixed_total: float) -> bool:
    """추천 필터와 같은 기준: 사용자 제외 업종 아님, 면허 보유, 매출 데이터·점포 존재, 매출을 비교할 지역 5곳 이상, 평균 매출 ≥ 월 고정비."""
    if row["industry_code"] in excluded_of(req):
        return False
    lic = LICENSED_INDUSTRIES.get(row["industry_code"])
    if lic and lic not in json.loads(req.licenses_json):
        return False
    n = row.get("sales_n")
    if _ok(n) and n < SuitabilityParams().min_sales_areas:
        return False
    if N.sales_outlier(row) is not None:              # 평균 매출이 대형 점포 때문에 부풀었을 수 있으면 대안으로 권하지 않음
        return False
    return bool(row["has_sales_data"]) and row["stores_avg4"] >= 1.0 and _ok(row["sales_ps_m"]) \
        and row["sales_ps_m"] >= fixed_total


def _can_cover(row, fixed_total: float, cogs_map: dict | None = None, other_rate: float = 0.0) -> bool:
    """평균 매출로 월 고정비를(원가율을 아는 업종은 원가·카드수수료·기타 수수료까지 빼고) 감당하는지 — 대안도 적자면 권하지 않는다.
    원가율은 cogs_map(리포트에 반영한 손익분기 값 또는 분석 조건의 분야별 값) → 업종 대분류 평균(외식업만)."""
    sales = row["sales_ps_m"]
    cogs = (cogs_map or {}).get(row["category"], DEFAULT_COGS_RATE.get(row["category"]))
    return covers_fixed(float(sales) if _ok(sales) else None, fixed_total, cogs, other_rate)


def _pick_alternative(state: EngineState, area_code: str, focus: dict, tops: list[dict],
                      req: M.AnalysisRequest | None = None, fixed_total: float | None = None) -> dict | None:
    """비슷한 업종(같은 계열, catalog.INDUSTRY_FAMILY) 중 확실히 안전한 업종: 예상 폐업률 15% 이상 낮고 위험 등급도 한 단계 이상 낮음.
    1순위: 추천 TOP 중 적합도 최고 / 2순위: 이 지역 같은 계열 업종 중 매출 잠재력(D) 50 이상에서 D 최고.
    계열이 다른 업종(PC방 → 자동차수리 등)은 대안으로 제시하지 않는다."""
    fam = state.industries.get(focus["industry_code"], {}).get("family")
    if not fam:
        return None
    lim, g0 = focus["pred_annual_rate"] * 0.85, N.GRADE_ORDER.get(focus["risk_grade"], 0)

    excl = set(excluded_of(req)) if req is not None else set()

    def same_family(code):                           # 사용자가 뺀 업종은 대안으로도 권하지 않는다
        return code != focus["industry_code"] and code not in excl and state.industries.get(code, {}).get("family") == fam
    ft = fixed_total if fixed_total is not None else (user_condition(req, []).monthly_fixed_total() if req is not None else 0.0)
    cm = cogs_of(req) if req is not None else {}

    def affordable(code):                            # 리포트에 반영한 비용(ft)으로도 평균 매출로 버틸 수 있는지
        r = state.row(area_code, code)
        return r is not None and _can_cover(r, ft, cm)
    alts = [t for t in tops if same_family(t["industry_code"]) and t["pred_annual_rate"] <= lim
            and N.GRADE_ORDER.get(t["risk_grade"], 9) < g0 and affordable(t["industry_code"])]
    if alts:
        best = max(alts, key=lambda t: t["suitability"] or 0)
        return {k: best[k] for k in ("industry_code", "industry_name", "category", "pred_annual_rate", "risk_grade")}
    rows = state.area_rows(area_code)
    rows = rows[rows["industry_code"].map(same_family) & (rows["pred_annual_rate"] <= lim) & (rows["demand_D"] >= 50)
                & rows["has_sales_data"] & (rows["risk_pct_in_ind"] < 90)
                & rows["risk_grade"].map(lambda g: N.GRADE_ORDER.get(g, 9) < g0)]
    if req is not None and not rows.empty:
        rows = rows[[_user_can_open(r, req, ft) and _can_cover(r, ft, cm) for _, r in rows.iterrows()]]
    if rows.empty:
        return None
    r = rows.sort_values(["demand_D", "industry_code"], ascending=[False, True]).iloc[0]   # 동률은 코드순(결정적)
    return {"industry_code": r["industry_code"], "industry_name": r["industry_name"], "category": r["category"],
            "pred_annual_rate": float(r["pred_annual_rate"]), "risk_grade": r["risk_grade"]}


def match_policies(db: Session, user_type: str, category: str, risk_grade: str, deficit: bool, lend_ok: bool = True,
                   k: int = 3):
    """지원사업 매칭. deficit = 평균 매출로 손익분기(또는 월 고정비)를 못 넘는 구조.
    lend_ok = 대출을 권해도 되는지(자격 보유·매출 확인 가능·지역 점포 있음·고위험 아님·적자 아님) — 아니면 자금 상품 제외.
    폐업·재기 지원(재기지원)과 대출은 함께 권하지 않는다."""
    target = ROLE_TO_TARGET.get(user_type)
    scored = []
    for p in db.scalars(select(M.PolicySupport).order_by(M.PolicySupport.policy_id)):
        if p.target_region not in ("서울", "전국") or p.target_category not in ("전체", category):
            continue
        if target and p.target_user not in ("전체", target):
            continue
        s = 0.0
        if p.support_type == "교육" and user_type == "PRE_FOUNDER":
            s += 2
        if p.support_type == "컨설팅":
            s += 2 if (risk_grade in ("높음", "고위험") or deficit) else 1
        if p.support_type == "자금":
            s += 1 if (lend_ok and not deficit) else -3        # 적자·판단 불가·고위험에 대출 권유 금지
        if p.support_type == "재기지원":
            s += 2 if (user_type == "OWNER" and risk_grade == "고위험") else -5
        if p.support_type == "정보":
            s += 0.5
        if p.target_region == "서울":
            s += 0.3
        if s > 0:
            scored.append((s, p))
    scored.sort(key=lambda t: -t[0])
    return [p for _, p in scored[:k]]


def _row_f(row, k):
    if row is None:
        return None
    v = row.get(k)
    return float(v) if _ok(v) else None


def entry_block(req: M.AnalysisRequest, row, industry_code: str, fixed_total: float, owner: float = 0.0) -> str | None:
    """추천 필터(자격·수요 검증·평균 매출 ≥ 월 고정비)에 걸리는 이유를 한줄 결론용 문장으로. 없으면 None."""
    lic = LICENSED_INDUSTRIES.get(industry_code)
    if lic and lic not in json.loads(req.licenses_json):
        return f"{lic} 자격이 있어야 열 수 있어요. 자격 요건부터 확인하세요."
    if row is None:
        return None
    sales = _row_f(row, "sales_ps_m")
    if float(row["stores_avg4"]) < SuitabilityParams().min_avg_stores:
        return "이 지역 점포가 적어 수요가 충분히 검증되지 않았어요. 현장 수요를 먼저 확인하세요."
    if not bool(row["has_sales_data"]) or sales is None:
        return "이 지역 카드 매출 데이터가 부족해 매출로는 판단할 수 없어요. 비슷한 점포의 실제 매출을 먼저 확인하세요."
    if sales < fixed_total:
        return (f"점포당 평균 월매출({N.won(sales)})이 {fixed_phrase(fixed_total, owner)}보다 적어요. "
                + ("비용 조건이나 목표 월수입부터 다시 보세요." if owner > 0 else "비용 조건부터 다시 보세요."))
    return None


def _area_alt(state: EngineState, focus_risk: dict, industry_code: str, fixed_total: float,
              cogs_map: dict | None = None, other_rate: float = 0.0) -> dict | None:
    """같은 업종 입지 위험이 한 등급 이상 낮고, 그 지역 평균 매출로 지금 비용(월 고정비)을 감당할 수 있는 인근 지역.
    종합 위험이 높음·고위험이면(창업 재검토 대상) 입지 등급이 같아도 예상 연 폐업률이 10% 이상 낮은 곳까지 — SB-06이 보여 주는
    인근 지역 대안을 리포트에서도 권한다. 평균 매출이 대형 점포 때문에 부풀었을 수 있는 지역(서울 중간값의 3배 이상)은 권하지 않는다."""
    lg = N.GRADE_ORDER.get(focus_risk.get("location_grade") or "", None)
    high = focus_risk.get("risk_grade") in ("높음", "고위험")
    rate0 = focus_risk.get("pred_annual_rate")
    for a in focus_risk["alternatives"]:
        if lg is not None and N.GRADE_ORDER[a["location_grade"]] >= lg:
            if not (high and _ok(rate0) and a["pred_annual_rate"] <= rate0 * 0.9):
                continue
        if lg is None and a["location_grade"] != "낮음":    # 이 지역에 같은 업종이 없으면 '낮음'인 곳만(가까운 곳 대체 목록 제외)
            continue
        r = state.row(a["area_code"], industry_code)
        if r is not None and N.sales_outlier(r) is None and _can_cover(r, fixed_total, cogs_map, other_rate):
            # 원가율을 모르는 업종은 '평균 매출 ≥ 월 고정비'만 본 것 — 한줄 결론이 '감당할 만한'이라고 하지 않게
            cogs = (cogs_map or {}).get(r["category"], DEFAULT_COGS_RATE.get(r["category"]))
            return {**a, "cogs_known": cogs is not None}
    return None


def cash_monthly(inp: dict | None, req: M.AnalysisRequest) -> float:
    """가게에서 실제로 나가는 월 비용 = 임대료 + 인건비 + 기타 고정비 + 대출 이자(대표자 월수입·감가상각 제외).
    월 고정비(반올림)에서 빼서 구하면 0원일 때 ±0.3원 같은 찌꺼기가 남아 '운영자금(4원)'이 된다 → 항목을 더한다.
    1만원 미만은 0으로 본다(운영자금 항목을 만들 만한 금액이 아님)."""
    inp = inp or {}
    g = lambda k, d: float(inp.get(k, d) or 0)
    v = (g("monthly_rent", req.monthly_rent_limit) + g("labor_cost", req.labor_cost) + g("other_fixed", req.other_fixed)
         + g("loan_amount", req.loan_amount) * g("loan_rate_annual", req.loan_rate_annual) / 12)
    return v if v >= 10_000 else 0.0


def _cash_items(inp: dict, req: M.AnalysisRequest) -> str:
    """운영자금 문구의 비용 이름: 0원이 아닌 현금 고정비만(임대료·인건비가 0이면 '임대료·인건비 등'이라 쓰지 않는다)."""
    g = lambda k, d: float(inp.get(k, d) or 0)
    interest = g("loan_amount", req.loan_amount) * g("loan_rate_annual", req.loan_rate_annual) / 12
    names = [k for k, v in (("임대료", g("monthly_rent", req.monthly_rent_limit)), ("인건비", g("labor_cost", req.labor_cost)),
                            ("기타 고정비", g("other_fixed", req.other_fixed)), ("대출 이자", interest)) if v > 0]
    return "·".join(names[:2]) + (" 등" if len(names) > 2 else "")


def build_checklist(req: M.AnalysisRequest, focus_risk: dict, row, be: dict | None, alt: dict | None,
                    profile: dict | None, rent_latest: float | None = None, be_inputs: dict | None = None,
                    better_area: dict | None = None, out_meta: dict | None = None, keep_area: bool = False,
                    keep_alt: bool = False) -> list[dict]:
    """실행 체크리스트(최대 5개). 비용 항목은 리포트에 반영한 손익분기 입력값(be_inputs)을 기준으로 해서
    '월 고정비를 X 이하로'와 '임대료 Y 이하 매물'이 서로 모순되지 않게 한다.
    better_area: 입지 위험이 더 낮고 지금 비용을 감당할 수 있는 인근 지역(_area_alt)."""
    items = []

    def add(t, content, pr):
        items.append({"action_type": t, "content": content, "priority": pr})
    cat = focus_risk.get("category")
    offer = N.OFFER.get(cat, "상품·서비스")
    lic = LICENSED_INDUSTRIES.get(focus_risk.get("industry_code"))
    if lic and lic not in json.loads(req.licenses_json):
        add("자격확인", f"{lic} 자격이 있어야 열 수 있어요 — 자격 요건·취득 기간부터 확인", 1)
        # 자격이 없으면 한줄 결론은 '자격 요건부터'만 말한다 — 체크리스트도 다른 구 비교를 권하지 않는다
        # (이 지역 폐업 이력 요인은 인근 구 대신 현장 확인 항목으로)
        better_area, keep_area = None, False
    reg = REGISTRATION_NOTES.get(focus_risk.get("industry_code"))
    if reg:
        add("인허가", reg, 2)
    inp = be_inputs or {}
    rent = float(inp.get("monthly_rent", req.monthly_rent_limit) or 0)
    owner = float(inp.get("owner_salary", req.owner_salary) or 0)
    inv = float(inp.get("initial_investment", req.initial_investment) or 0)
    ratio = be.get("achievability_ratio") if be else None
    max_f = be.get("max_fixed_for_bep") if be else None
    short = _ok(ratio) and ratio < 1 and _ok(max_f)
    # 목표 금액은 표시 단위에서 내림(넘으면 안 되는 한도라서), 줄여야 할 금액은 화면에 보이는 두 금액의 차이(492만원 − 315만원 = 177만원)
    target = N.won_floor_below(max_f, be["monthly_fixed_cost"]) if short else 0.0
    gap = N.won_value(be["monthly_fixed_cost"]) - target if short else 0.0
    fixed_total = float(be["monthly_fixed_cost"]) if be else user_condition(req, []).monthly_fixed_total()
    sales = _row_f(row, "sales_ps_m")
    no_be_deficit = be is None and sales is not None and sales < fixed_total   # 원가율이 없어 손익분기는 못 냈지만 이미 적자
    what = "월 고정비(목표 월수입 포함)" if owner > 0 else "월 고정비"
    if no_be_deficit:
        add("비용절감", f"{what}를 이 지역 점포당 평균 월매출({N.won(sales)})보다 충분히 낮추기 (지금 {N.won(fixed_total)})"
                        " — 원가율을 넣으면 정확한 한도를 계산해요", 1)
    v = be.get("variable_cost_rate") if be else None
    if _ok(v) and v >= 0.7:                          # 원가·수수료가 매출 대부분이면 고정비만 줄여서는 해결 안 됨
        other_v = float(((be.get("variable_breakdown") or {}).get("기타")) or 0)
        add("비용절감", f"원가율·수수료가 매출의 {N.pct(v, 0)}라 팔아도 남는 몫이 {N.pct(1 - v, 0)}뿐 — "
                        + ("원가·배달 수수료부터 점검" if other_v > 0 else "원가(재료·상품 매입가)부터 점검"), 1)
    if short and owner > 0 and target < owner:       # 한도가 목표 월수입보다 작으면 비용만 줄여서는 안 된다
        add("비용절감", f"{what}를 {N.won(target)} 이하로 낮춰야 하는데 목표 월수입({N.won(owner)})만으로도 넘어요 — "
                        "목표 월수입을 낮추거나 업종·입지부터 다시 검토", 1)
    elif short:
        add("비용절감", f"{what}를 {N.won(target)} 이하로 낮추기 (지금 {N.won(be['monthly_fixed_cost'])}, "
                        f"월 {N.won(gap)} 줄여야 함)", 1)
    if be is not None and _ok(ratio) and 1 <= ratio < 1.15:          # 손익분기는 넘지만 빠듯 — 한줄 결론의 '여유가 적어요'를 실행 항목으로
        base = "필요 매출(목표 월수입 포함)" if owner > 0 else "손익분기"
        add("비용절감", f"평균 매출이 {base}의 {N.times(ratio)}로 여유가 적어요 — 월 고정비를 더 줄일 수 있는지 먼저 점검", 3)
    rent33 = rent_latest if rent_latest is not None else _row_f(row, "rent4")
    area_rent = f" · 이 지역 3.3㎡당 평균 {N.won1(rent33)}(10평 약 {N.won(rent33 * 10)})" if _ok(rent33) else ""
    # 임대료만 줄여 맞추라는 제안이 현실적인지: 남는 임대료가 10만원 미만이거나, 이 지역 10평 평균의 절반과
    # 지금 임대료의 절반보다 모두 낮으면(원래 싼 매물을 조금 줄이는 건 현실적) 비현실적
    half = min(0.5 * rent33 * 10, 0.5 * rent) if _ok(rent33) else 0.0
    floor_rent = max(100_000.0, half)
    if rent > 0 and not no_be_deficit:
        if short and (gap >= rent or rent - gap < floor_rent):
            others = [k for k, x in (("인건비", inp.get("labor_cost", req.labor_cost)), ("기타 고정비", inp.get("other_fixed", req.other_fixed)),
                                     ("목표 월수입", owner), ("초기 투자비", inv)) if (x or 0) > 0]
            add("비용절감", "임대료만 줄여서는 어려워요 — " + ("·".join(others) + "도 함께 조정" if others else "업종·입지부터 다시 검토"), 2)
        elif short:
            add("비용절감", f"임대료만 줄인다면 월 {N.won(rent - gap)} 이하 매물 찾기 (지금 {N.won(rent)}){area_rent}", 2)
        else:
            add("비용절감", f"월 임대료 {N.won(rent)} 이하 매물 우선 검토{area_rent}", 2)
    cash_fixed = cash_monthly(inp, req)                  # 가게에서 실제로 나가는 월 비용(대표자 월수입·감가상각 제외)
    # 업종·지역 특성상 오래 버텨야 하는 곳이면 운영자금 기준을 12개월로(운영자금 항목·한줄 결론도 같은 기준 — 6·12개월이 섞이지 않게)
    long_done = False                                    # '오래 버티기' 항목(업종 자체 폐업률·지역 수명)은 하나만

    def long_tail(kind: str) -> str:
        """'오래 버티기' 항목의 뒷부분. 나가는 돈이 없으면 현장 확인, 예산이 12개월분에 못 미치면(아래 운영자금 항목이
        12개월 기준 금액을 따로 말함) 같은 말을 되풀이하지 않고, 아니면 12개월분 금액을 밝힌다."""
        if cash_fixed <= 0:
            return "현장 수요부터 확인" if kind == "ind" else "상권이 오래가는지 현장에서 먼저 확인"
        if req.budget > 0 and req.budget - inv < 12 * cash_fixed:
            return "비슷한 업종의 실제 매출·폐업 사례부터 확인" if kind == "ind" else "상권이 오래가는지 현장에서 먼저 확인"
        return f"운영자금은 최소 12개월분({N.won(12 * cash_fixed)})으로 계획"
    ups = [f for f in focus_risk["factors"] if f["direction"] == "up" and N.shown_effect(f) >= 3]   # 화면 숫자(+3%) 기준
    # 운영자금 12개월 기준은 요인 자체로 정한다(비슷한 업종 비교 항목이 대신 들어가도 기준은 같게)
    twelve = cash_fixed > 0 and any(f["factor_code"] == "ind_base" and N.shown_effect(f) >= 10 for f in ups)
    added = 0
    for f in ups:
        if added >= 2:
            break
        n0, c = len(items), f["factor_code"]
        if c == "ind_base" and alt:
            add("업종변경", f"폐업률이 낮은 비슷한 업종 {N.josa(alt['industry_name'], '과/와')} 비교 후 결정 "
                            f"(예상 연 폐업률 {N.pct(alt['pred_annual_rate'])}, 위험 {alt['risk_grade']})", 3)
        elif c == "ind_base" and N.shown_effect(f) >= 10:
            # 대안 업종이 없어도 가장 큰 위험 요인(업종 자체 폐업률)에 대한 행동을 준다(투자비가 0원이면 줄이라고 하지 않는다)
            # 나가는 돈(임대료·인건비 등)이 없으면 운영자금 기간 대신 수요 확인을 권한다
            add("운영", "업종 자체 폐업률이 높은 업종 — " + ("초기 투자비를 줄이고 " if inv > 0 else "") + long_tail("ind"), 3)
            long_done = True
        elif c == "area_hist" and better_area:
            a = better_area
            add("입지변경", f"같은 업종 입지 위험이 더 낮은 {a['area_name']}(입지 위험 {a['location_risk_pct']}·{a['location_grade']}, "
                            f"예상 연 폐업률 {N.pct(a['pred_annual_rate'])})도 비교", 3)
        elif c == "area_hist":
            add("현장확인", f"이 지역 같은 업종 최근 1년 폐업 {focus_risk['raw']['closures_1y']:,.0f}곳 — 폐업 원인(상권 이동·경쟁) 현장 확인", 3)
        elif c == "store_surge":
            g = _row_f(row, "store_growth")
            if g is not None and g > 0 and f"{g:+.0%}" != "+0%":   # 실제로 줄었거나 +0%면 '늘어' 문구를 쓰지 않는다
                add("운영", f"점포 수가 전년보다 {g:+.0%} 늘어 경쟁이 세지는 중 — 차별화 {offer}·콘셉트 먼저 준비", 4)
        elif c == "sales_decline":
            g = _row_f(row, "sales_growth")
            if g is not None and g < 0 and f"{g:+.0%}" != "-0%":
                add("운영", f"이 지역 같은 업종 매출이 전년보다 {g:+.0%} 줄어드는 중 — 매출 목표를 보수적으로 잡고 비용 계획", 4)
        elif c == "entry_heat":
            add("운영", "신규 개업이 몰리는 곳 — 오픈 초기 3개월 고객 확보(마케팅) 계획", 4)
        elif c == "short_life" and not long_done:          # 같은 취지(오래 버티기) 항목은 하나만
            m = _row_f(row, "closed_months4")
            add("운영", (f"이 지역은 폐업한 가게(전 업종)의 평균 영업 기간이 {m:.0f}개월로 서울에서 짧은 편 — " if m is not None
                         else "이 지역은 폐업한 가게의 영업 기간이 서울에서 짧은 편 — ")
                + long_tail("life"), 4)
            twelve, long_done = twelve or cash_fixed > 0, True
        elif c == "low_sales":
            add("운영", f"점포당 매출이 같은 업종 다른 지역보다 낮은 편 — {N.TARGETS.get(cat, '객단가')} 목표 먼저 설정", 4)
        elif c == "rent_burden":
            add("비용절감", "매출 대비 임대료 부담이 큰 지역 — 임대료 협상·면적 줄이기 검토", 4)
        elif c == "density":
            add("현장확인", "유동인구 대비 점포가 많은 곳 — 점포 앞 동선·경쟁점 위치 현장 확인", 4)
        if len(items) > n0:
            added += 1
    if better_area and not any(it["action_type"] == "입지변경" and better_area["area_name"] in it["content"] for it in items):
        # 입지 요인이 위험 상위가 아니어도, 같은 업종 입지 위험이 더 낮고 비용을 감당할 인근 구가 있으면 알려 준다
        a = better_area
        add("입지변경", f"같은 업종 입지 위험이 더 낮은 {a['area_name']}(입지 위험 {a['location_risk_pct']}·{a['location_grade']}, "
                        f"예상 연 폐업률 {N.pct(a['pred_annual_rate'])})도 비교", 4)
    ox = N.sales_outlier(row) if row is not None else None
    if ox is not None:                                # 한줄 결론의 '실제 매출을 확인하세요'를 실행 항목으로
        add("현장확인", f"비슷한 규모 점포의 실제 매출부터 확인 — 이 지역 평균은 서울 같은 업종 중간값의 {ox:.1f}배라 "
                        "대형 점포가 섞였을 수 있어요", 2)
    flags = N.peak_flags(profile, cat, focus_risk.get("industry_code"))
    if flags:
        add("운영", flags[0]["action"], 5)
    if cash_fixed > 0:
        months = 12 if twelve else 6
        need = months * cash_fixed
        reserve = req.budget - inv
        if req.budget > 0 and reserve < 0:             # 투자비가 예산보다 크면 '운영비 0.0개월분'보다 실제 부족액을
            add("운영자금", f"초기 투자비가 예산보다 {N.won(-reserve)} 많아요 — 투자비를 줄이거나 자금을 더 마련하고, "
                            f"초기 {months}개월 운영자금({N.won(need)})도 따로 확보", 2)
        elif req.budget > 0 and reserve == 0:
            add("운영자금", f"예산을 초기 투자비로 모두 써서 운영자금이 없어요 — 초기 {months}개월 운영자금({N.won(need)}) 따로 마련", 2)
        elif req.budget > 0 and reserve < need:
            lead = "예산에서 투자비를 빼면" if inv > 0 else "예산으로는"
            have = "1개월분도 안 됨" if reserve / cash_fixed < 1 else f"{N.months_floor(reserve / cash_fixed)}개월분"   # 내림(12.0 방지)
            add("운영자금", f"{lead} 운영비 {have} — 초기 {months}개월 운영자금({N.won(need)}) 확보", 2)
        elif not long_done:                            # '오래 버티기' 항목이 이미 기간·금액을 말하면 생략
            add("운영자금", f"초기 {months}개월 운영자금({N.won(need)}: {_cash_items(inp, req)} {months}개월분) 별도 확보", 6)
    if out_meta is not None:
        out_meta["runway_months"] = 12 if twelve else 6
    if keep_alt and alt and not any(it["action_type"] == "업종변경" for it in items):
        # 한줄 결론이 권한 비슷한 업종은 업종 자체 폐업률 요인이 없어도 체크리스트에 남긴다
        add("업종변경", f"폐업률이 낮은 비슷한 업종 {N.josa(alt['industry_name'], '과/와')} 비교 후 결정 "
                        f"(예상 연 폐업률 {N.pct(alt['pred_annual_rate'])}, 위험 {alt['risk_grade']})", 3)
    if not items:                                    # 비용 0원 등으로 챙길 항목이 없을 때도 빈 목록은 보이지 않게
        add("현장확인", "계약 전 평일·주말 점포 앞 유동인구와 가까운 경쟁점을 직접 확인", 1)
    items.sort(key=lambda d: d["priority"])
    seen, out = set(), []
    for it in items:
        if it["content"] not in seen:
            seen.add(it["content"])
            out.append(it)
    res = out[:5]
    # 한줄 결론이 권한 인근 구·비슷한 업종은 체크리스트에도 남긴다: 3순위 이하 항목 중 마지막 것과 바꾼다
    # (없으면 임대료 매물 항목 → 2순위 항목 순. 1순위 항목·자격·대안 업종 항목은 건드리지 않음)
    keep = []
    if keep_area and better_area:
        keep.append(next((it for it in out if it["action_type"] == "입지변경" and better_area["area_name"] in it["content"]), None))
    if keep_alt and alt:
        keep.append(next((it for it in out if it["action_type"] == "업종변경"), None))
    keep = [k for k in keep if k is not None]
    for k in keep:
        if k in res:
            continue
        victims = [i for i, it in enumerate(res) if it["priority"] > 2 and it["action_type"] != "업종변경" and it not in keep]
        if not victims:     # 1·2순위만 남았으면 임대료 매물 항목(월 고정비 한도 항목이 같은 뜻을 이미 말함)과 바꾼다
            victims = [i for i, it in enumerate(res) if it["action_type"] == "비용절감" and it["priority"] == 2
                       and ("매물" in it["content"] or "임대료만" in it["content"]) and it not in keep]
        if not victims:     # 그것도 없으면 2순위 항목 중 마지막(자격·대안 업종 항목은 두고)
            victims = [i for i, it in enumerate(res) if it["priority"] == 2 and it["action_type"] not in ("업종변경", "자격확인")
                       and it not in keep]
        if not victims:
            break
        res = sorted(res[:victims[-1]] + res[victims[-1] + 1:] + [k], key=lambda d: d["priority"])
    for i, it in enumerate(res, start=1):
        it["priority"] = i
    return res


# 계산 결과를 바꾸지 않는 표시용 항목(어느 칸을 직접 넣었는지 등)은 '같은 입력' 비교에서 뺀다
_KEY_SKIP = ("overridden", "required", "changed", "cogs_is_default", "cogs_source", "ticket_is_market")


def input_key(inputs: dict | None) -> str | None:
    """손익분기 입력값 비교 키: 실제 계산에 쓴 값만(분석 조건과 같은 값을 직접 넣었어도 같은 입력).
    소수는 9자리에서 반올림(화면에서 40.7% → 0.40700000000000003처럼 들어와도 같은 입력)."""
    if inputs is None:
        return None
    def norm(v):
        if isinstance(v, float):
            v = round(v, 9)
            return int(v) if v.is_integer() else v       # 3000000.0과 3000000을 같은 값으로(데모의 숫자 표기와도 같게)
        return v
    return json.dumps({k: norm(inputs[k]) for k in sorted(inputs) if k not in _KEY_SKIP}, ensure_ascii=False)


def _be_key(db: Session, break_even_id: int) -> str | None:
    be = db.get(M.BreakEvenAnalysis, break_even_id)
    return input_key(json.loads(be.input_json)) if be is not None and be.input_json else None


def _existing_report(db: Session, req: M.AnalysisRequest, category_id: int, model_version: str, match) -> M.ActionReport | None:
    """같은 분석·업종에서 같은 손익분기 입력으로 이미 만든 리포트. 지금 모델로 만든 것만 재사용하고,
    저장한 리포트가 있으면 그것을(저장 목록에 같은 리포트가 두 번 생기지 않게), 없으면 가장 최근 것을 돌려준다."""
    reps = db.scalars(select(M.ActionReport).where(M.ActionReport.request_id == req.request_id,
                                                    M.ActionReport.category_id == category_id)
                      .order_by(M.ActionReport.report_id.desc())).all()
    found = None
    for r in reps:
        risk = db.get(M.RiskAssessment, r.risk_id) if r.risk_id else None
        if risk is not None and risk.model_version == model_version and match(r):
            if db.scalar(select(M.SavedReport.saved_report_id).where(M.SavedReport.report_id == r.report_id).limit(1)):
                return r
            found = found or r
    return found


def create_report(db: Session, state: EngineState, req: M.AnalysisRequest, industry_code: str,
                  break_even_id: int | None) -> M.ActionReport:
    if industry_code not in state.industries:
        raise ApiError(404, "UNKNOWN_INDUSTRY", "알 수 없는 업종이에요")
    ind = state.industries[industry_code]
    focus = risk_svc.risk_detail(db, state, req, industry_code, persist=True)
    area_code = area_code_of(db, req)
    row = state.row(area_code, industry_code)
    profile = row["profile"] if row is not None and isinstance(row.get("profile"), dict) else None

    be_row = None
    if break_even_id is not None:
        be_row = db.get(M.BreakEvenAnalysis, break_even_id)
        if be_row is None or be_row.request_id != req.request_id or be_row.category_id != ind["category_id"]:
            raise ApiError(404, "BREAKEVEN_NOT_FOUND", "손익분기 계산 결과를 찾을 수 없어요")
        # 같은 손익분기(또는 입력값이 같은 계산)를 다시 반영 → 같은 리포트(저장 목록 중복 방지).
        # 손익분기 화면은 열 때마다 계산을 새로 저장하므로 id만 비교하면 매번 새 리포트가 생긴다.
        key = _be_key(db, break_even_id)
        same = _existing_report(db, req, ind["category_id"], state.model_version,
                                lambda r: r.break_even_id == break_even_id or
                                (r.break_even_id is not None and key is not None and _be_key(db, r.break_even_id) == key))
        if same is not None:
            return same
    else:
        # 위험도 화면에서 바로 만든 리포트: 손익분기 화면에서 '리포트에 반영'하지 않은 가정값은 쓰지 않고 분석 조건으로 계산
        try:
            preview = breakeven_svc.compute(db, state, req, BreakEvenIn(industry_code=industry_code), persist=False)
            key = input_key(preview["inputs"])
        except ApiError:
            preview, key = None, None
        # 분석 조건으로 만든 리포트가 이미 있으면 그대로 돌려준다(뒤로 갔다가 '대응 액션 보기'를 다시 눌러도 같은 리포트)
        same = _existing_report(db, req, ind["category_id"], state.model_version,
                                lambda r: (r.break_even_id is None and key is None) or
                                (r.break_even_id is not None and key is not None and _be_key(db, r.break_even_id) == key))
        if same is not None:
            return same
        if preview is not None:
            res = breakeven_svc.compute(db, state, req, BreakEvenIn(industry_code=industry_code), persist=True)
            be_row = db.get(M.BreakEvenAnalysis, res["id"])
    be = json.loads(be_row.result_json) if be_row else None
    be_inputs = json.loads(be_row.input_json) if be_row and be_row.input_json else None
    if be is not None:
        be["id"] = be_row.break_even_id

    tops = _top_items(db, req)
    # 비용 기준: 리포트에 반영한 손익분기가 있으면 그 입력값(월 고정비), 없으면 분석 조건
    fixed_total = float(be["monthly_fixed_cost"]) if be else user_condition(req, []).monthly_fixed_total()
    inv = float((be_inputs or {}).get("initial_investment", req.initial_investment) or 0)
    owner = float((be_inputs or {}).get("owner_salary", req.owner_salary) or 0)
    cash_fixed = cash_monthly(be_inputs, req)
    reserve_months = max(req.budget - inv, 0) / cash_fixed if cash_fixed > 0 and req.budget > 0 else None
    over_budget = inv - req.budget if req.budget > 0 and inv > req.budget else None
    block = entry_block(req, row, industry_code, fixed_total, owner)
    focus_item = {"industry_code": industry_code, "industry_name": ind["name"], "risk_grade": focus["risk_grade"],
                  "pred_annual_rate": focus["pred_annual_rate"], "category": ind["category"],
                  "fixed_zero": fixed_total <= 0,           # 월 고정비 0원이면 원가율과 상관없이 손익분기 0원
                  "location_risk_pct": focus["location_risk_pct"], "fallback": focus["fallback"],
                  "confidence": focus["confidence"], "block": block, "reserve_months": reserve_months,
                  "over_budget": over_budget, "investment": inv,
                  # 매출 추정이 흔들리는 경우(비교할 구 5곳 미만·대형 점포가 섞인 듯한 매출) — 한줄 결론의 단서
                  "few_sales_areas": (float(row["sales_n"]) if row is not None and _ok(row.get("sales_n"))
                                      and row["sales_n"] < SuitabilityParams().min_sales_areas else None),
                  "sales_outlier": N.sales_outlier(row)}
    alt = _pick_alternative(state, area_code, focus_item, tops, req, fixed_total)
    area_name = focus["area_name"]
    # 같은 업종의 다른 구: 리포트에 반영한 손익분기의 원가율·기타 수수료로 판단(없으면 분석 조건의 분야별 원가율)
    alt_cogs, alt_other = cogs_of(req), 0.0
    if be_inputs:
        alt_cogs = {**alt_cogs, ind["category"]: float(be_inputs.get("cogs_rate"))} if _ok(be_inputs.get("cogs_rate")) else alt_cogs
        alt_other = float(be_inputs.get("other_variable_rate") or 0)
    area_alt = _area_alt(state, focus, industry_code, fixed_total, alt_cogs, alt_other)
    if area_alt:
        area_alt["owner_included"] = owner > 0          # '월 고정비(목표 월수입 포함)보다 큰' — SB-06 문구와 같게
    meta: dict = {}
    checklist = build_checklist(req, focus, row, be, alt, profile,
                                state.area_cards.get(area_code, {}).get("rent_per_3_3m2"), be_inputs, area_alt, meta)
    # 한줄 결론도 체크리스트와 같은 운영자금 기준(6·12개월)과 자격 조건을 쓴다
    focus_item["runway_months"] = meta.get("runway_months", 6)
    lic_need = LICENSED_INDUSTRIES.get(industry_code)
    focus_item["license"] = lic_need if lic_need and lic_need not in json.loads(req.licenses_json) else None
    one = N.one_liner(area_name, focus_item, alt, be, area_alt)
    cite_area = bool(area_alt) and area_alt["area_name"] in one
    cite_alt = bool(alt) and f"비슷한 업종인 {alt['industry_name']}" in one
    if (cite_area and not any(area_alt["area_name"] in c["content"] for c in checklist)) or \
            (cite_alt and not any(c["action_type"] == "업종변경" for c in checklist)):
        # 한줄 결론이 권한 인근 구·비슷한 업종이 체크리스트에 없으면 그 항목을 남겨 다시 만든다
        checklist = build_checklist(req, focus, row, be, alt, profile,
                                    state.area_cards.get(area_code, {}).get("rent_per_3_3m2"), be_inputs, area_alt, None,
                                    keep_area=cite_area, keep_alt=cite_alt)
    ratio = be.get("achievability_ratio") if be else None
    sales = _row_f(row, "sales_ps_m")
    deficit = (_ok(ratio) and ratio < 1) or (be is None and sales is not None and sales < fixed_total)
    lic = LICENSED_INDUSTRIES.get(industry_code)
    # 대출(자금) 상품은 손익을 확인할 수 있을 때만: 자격 없음·지역 점포 없음·매출 없음·고위험·손익분기 계산 불가면 권하지 않는다
    lend_ok = not ((lic and lic not in json.loads(req.licenses_json)) or focus["fallback"] or sales is None
                   or focus["risk_grade"] == "고위험" or be is None
                   or focus_item.get("sales_outlier") is not None or focus_item.get("few_sales_areas") is not None
                   or (_ok(focus["location_risk_pct"]) and focus["location_risk_pct"] >= 90))   # 주의 업종(입지 위험 상위 10%)
    policies = match_policies(db, req.user_type, ind["category"], focus["risk_grade"], deficit, lend_ok)
    res = db.scalar(select(M.RecommendationResult).where(M.RecommendationResult.request_id == req.request_id))
    rep = M.ActionReport(public_id=str(uuid.uuid4()), request_id=req.request_id,
                         recommendation_id=res.recommendation_id if res else None, risk_id=focus.get("_risk_id"),
                         break_even_id=be_row.break_even_id if be_row else None, category_id=ind["category_id"],
                         one_line_summary=one,
                         policy_ctx_json=json.dumps({"category": ind["category"], "risk_grade": focus["risk_grade"],
                                                     "deficit": bool(deficit), "lend_ok": bool(lend_ok)}, ensure_ascii=False))
    for it in checklist:
        rep.items.append(M.ActionItem(action_type=it["action_type"], action_content=it["content"], priority=it["priority"]))
    for i, p in enumerate(policies, start=len(checklist) + 1):
        rep.items.append(M.ActionItem(action_type="정책지원", action_content=f"{p.policy_name} 확인", priority=i,
                                      policy_id=p.policy_id))
    db.add(rep)
    db.commit()
    return rep


def get_report(db: Session, public_id: str) -> tuple[M.ActionReport, M.AnalysisRequest]:
    """리포트 ID(추측 불가 UUID)를 아는 사람이면 누구나 연다(이전 버전의 회원 분석 리포트는 analysis.get_analysis처럼 404)."""
    rep = db.scalar(select(M.ActionReport).where(M.ActionReport.public_id == public_id))
    if rep is None:
        raise ApiError(404, "REPORT_NOT_FOUND", "리포트를 찾을 수 없어요")
    req = db.get(M.AnalysisRequest, rep.request_id)
    if req.user_id is not None:
        raise ApiError(404, "REPORT_NOT_FOUND", "리포트를 찾을 수 없어요")
    return rep, req


def _outlier_of(state: EngineState | None, area_code: str, code: str) -> float | None:
    """이 지역·업종 평균 매출이 서울 중간값의 몇 배인지(3배 이상일 때만) — 손익분기 카드에 '대형 점포 가능'을 붙인다."""
    r = state.row(area_code, code) if state is not None else None
    x = N.sales_outlier(r) if r is not None else None
    return None if x is None else round(x, 1)


def report_out(db: Session, state: EngineState, rep: M.ActionReport, req: M.AnalysisRequest, device: str | None = None) -> dict:
    cat = db.get(M.BusinessCategory, rep.category_id)
    area = db.get(M.CommercialArea, req.main_area_id)
    risk = db.get(M.RiskAssessment, rep.risk_id) if rep.risk_id else None
    be = db.get(M.BreakEvenAnalysis, rep.break_even_id) if rep.break_even_id else None
    checklist, policies = [], []
    for it in rep.items:
        if it.policy_id:
            p = db.get(M.PolicySupport, it.policy_id)
            policies.append({"policy_id": p.policy_id, "name": p.policy_name, "provider": p.provider,
                             "support_type": p.support_type, "summary": p.summary, "apply_url": p.apply_url,
                             "target_user": p.target_user, "target_region": p.target_region,
                             "checked_at": p.checked_at.isoformat() if p.checked_at else None})
        else:
            checklist.append({"action_id": it.action_id, "action_type": it.action_type, "content": it.action_content,
                              "priority": it.priority, "done": bool(it.is_done)})
    rec_item = None
    res = db.scalar(select(M.RecommendationResult).where(M.RecommendationResult.request_id == req.request_id))
    if res:
        order = {"TOP": 0, "INTEREST": 1, "CAUTION": 2}          # 같은 업종이 여러 목록에 있으면 TOP → 관심 → 주의 순
        for i in res.items:
            if i.category_id == rep.category_id and i.item_type in order:
                d = json.loads(i.detail_json)
                if rec_item is None or order[d["item_type"]] < order[rec_item["item_type"]]:
                    rec_item = {"item_type": d["item_type"], "rank": d["rank"], "suitability": d["suitability"],
                                "business_goal": req.business_goal,
                                # 관심 업종이어도 입지 위험 상위 10%면 주의 업종이라는 사실을 함께(SB-05 카드와 같게)
                                "eligible": bool(d.get("eligible")),
                                "caution": d["item_type"] == "CAUTION" or (bool(d.get("eligible"))
                                                                         and (d.get("location_risk_pct") or 0) >= 90)}
    saved_id = None                                     # 이 브라우저가 저장했으면 그 저장 번호(SB-08 '저장 리포트 보기')
    if device is not None:
        saved_id = db.scalar(select(M.SavedReport.saved_report_id).where(M.SavedReport.device_key_hash == device,
                                                                         M.SavedReport.report_id == rep.report_id))
    return {
        "id": rep.public_id, "analysis_id": req.public_id, "created_at": rep.created_at,
        "area_code": area.area_code, "area_name": area.area_name, "place_name": req.place_name,
        "radius_m": req.radius_meter, "industry_code": cat.category_code, "industry_name": cat.category_name,
        "one_line_summary": rep.one_line_summary, "checklist": checklist, "policies": policies,
        "risk": None if risk is None else {"risk_score": risk.risk_score, "risk_grade": risk.risk_level,
                                           "pred_annual_rate": risk.pred_annual_rate,
                                           "location_risk_pct": risk.location_risk_pct,
                                           "location_grade": risk.location_risk_level, "confidence": risk.confidence},
        "breakeven": None if be is None else {"id": be.break_even_id, "required_monthly_sales": be.required_monthly_sales,
                                              "owner_salary": (json.loads(be.input_json or "{}").get("owner_salary") or 0),
                                              "required_daily_customers": be.required_daily_customers,
                                              "achievability_ratio": be.achievability_ratio,
                                              "cost_pressure": be.cost_pressure, "monthly_fixed_cost": be.monthly_fixed_cost,
                                              "payback_months": be.payback_months,
                                              # 손익분기 화면에서 분석 조건과 다르게 바꾼 값 / 기본값이 없어 직접 넣은 값(SB-08 표시)
                                              "sales_outlier": _outlier_of(state, area.area_code, cat.category_code),
                                              "changed": _changed_values(be.input_json),
                                              "entered": _changed_values(be.input_json, "required")},
        "recommendation": rec_item, "saved_report_id": saved_id,
        "data_quarter_label": quarter_label(req.data_quarter),
    }


def _changed_values(input_json: str | None, key: str = "changed") -> dict:
    """손익분기 입력 중 목록(changed·required)에 든 항목의 값. 10차 이전 기록은 changed에 required가 섞여 있어
    '바꾼 값'에서는 required를 뺀다(같은 원가율이 '바꾼 값'과 '직접 입력'에 두 번 나오지 않게)."""
    inp = json.loads(input_json or "{}")
    skip = set(inp.get("required") or []) if key == "changed" else set()
    return {k: inp.get(k) for k in (inp.get(key) or []) if inp.get(k) is not None and k not in skip}


def save_report(db: Session, device: str, report_public_id: str, memo: str | None) -> M.SavedReport:
    """이 브라우저의 저장 목록에 리포트를 넣는다. 이미 있으면 그 행을 돌려준다(메모를 보냈으면 메모만 바꿈).
    링크로 받은 남의 리포트도 저장할 수 있고, 저장해도 분석·리포트는 그대로 링크를 아는 모두가 볼 수 있다."""
    rep, _ = get_report(db, report_public_id)
    existing = db.scalar(select(M.SavedReport).where(M.SavedReport.device_key_hash == device,
                                                     M.SavedReport.report_id == rep.report_id))
    if existing:
        if memo is not None:
            existing.memo = memo
        db.commit()
        return existing
    sr = M.SavedReport(device_key_hash=device, report_id=rep.report_id, memo=memo)
    db.add(sr)
    try:
        db.commit()
    except IntegrityError:                  # 두 탭·재시도로 같은 저장이 동시에 들어온 경우 → 먼저 저장된 것을 돌려준다
        db.rollback()
        existing = db.scalar(select(M.SavedReport).where(M.SavedReport.device_key_hash == device,
                                                         M.SavedReport.report_id == rep.report_id))
        if existing is None:
            raise
        return existing
    return sr


def list_saved(db: Session, device: str, state: EngineState | None = None) -> list[dict]:
    rows = db.execute(select(M.SavedReport, M.ActionReport, M.AnalysisRequest, M.BusinessCategory, M.CommercialArea)
                      .join(M.ActionReport, M.ActionReport.report_id == M.SavedReport.report_id)
                      .join(M.AnalysisRequest, M.AnalysisRequest.request_id == M.ActionReport.request_id)
                      .join(M.BusinessCategory, M.BusinessCategory.category_id == M.ActionReport.category_id)
                      .join(M.CommercialArea, M.CommercialArea.area_id == M.AnalysisRequest.main_area_id)
                      .where(M.SavedReport.device_key_hash == device, M.AnalysisRequest.user_id.is_(None))
                      .order_by(M.SavedReport.created_at.desc(), M.SavedReport.saved_report_id.desc())).all()
    out = []
    for sr, rep, req, cat, area in rows:
        risk = db.get(M.RiskAssessment, rep.risk_id) if rep.risk_id else None
        suit, rec = None, None
        res = db.scalar(select(M.RecommendationResult).where(M.RecommendationResult.request_id == req.request_id))
        if res:
            order = {"TOP": 0, "INTEREST": 1, "CAUTION": 2}      # report_out과 같은 순서(TOP → 관심 → 주의)
            for it in res.items:
                if it.category_id == rep.category_id and it.item_type in order:
                    d = json.loads(it.detail_json)
                    if rec is None or order[d["item_type"]] < order[rec["item_type"]]:
                        rec = d
            suit = rec.get("suitability") if rec else None
        be = db.get(M.BreakEvenAnalysis, rep.break_even_id) if rep.break_even_id else None
        be_in = json.loads(be.input_json) if be is not None and be.input_json else {}
        todo = [it for it in rep.items if it.policy_id is None]
        # 같은 지역·업종을 조건만 바꿔 여러 번 저장해도 카드끼리 구분되게: 반영한 손익분기 요약 + 체크리스트 진행
        out.append({"saved_report_id": sr.saved_report_id, "report_id": rep.public_id, "analysis_id": req.public_id,
                    "created_at": sr.created_at, "area_name": area.area_name, "place_name": req.place_name,
                    "industry_code": cat.category_code, "industry_name": cat.category_name, "suitability": suit,
                    "risk_score": risk.risk_score if risk else 0, "risk_grade": risk.risk_level if risk else "-",
                    "memo": sr.memo,
                    "required_monthly_sales": float(be.required_monthly_sales) if be is not None else None,
                    # 같은 구·업종을 비용만 바꿔 저장한 카드끼리 구분되게(반영한 손익분기 비용, 없으면 분석 조건)
                    "monthly_fixed_cost": (float(be.monthly_fixed_cost) if be is not None
                                           else user_condition(req, []).monthly_fixed_total()),
                    "achievability_ratio": float(be.achievability_ratio) if be is not None and be.achievability_ratio is not None else None,
                    # 반영한 손익분기가 없으면 분석 조건의 목표 월수입(월 고정비 표시에 들어 있는지 밝히게)
                    "owner_included": (float(be_in.get("owner_salary") or 0) > 0 if be is not None
                                       else float(req.owner_salary or 0) > 0),
                    "edited": bool(set(be_in.get("changed") or []) - set(be_in.get("required") or [])),
                    "business_goal": req.business_goal,
                    # 카드에 추천 상태를 함께(추천 1위 · 관심(추천 제외) · 주의 업종) — 적합도만 보면 추천 제외 업종이 가장 좋아 보이지 않게
                    "item_type": rec["item_type"] if rec else None, "rank": rec.get("rank") if rec else None,
                    "eligible": bool(rec.get("eligible")) if rec else None,
                    "caution": bool(rec) and (rec["item_type"] == "CAUTION"
                                              or (bool(rec.get("eligible")) and (rec.get("location_risk_pct") or 0) >= 90)),
                    "sales_outlier": _outlier_of(state, area.area_code, cat.category_code) if be is not None else None,
                    "checklist_total": len(todo), "checklist_done": sum(1 for it in todo if it.is_done)})
    return out


def set_item_done(db: Session, public_id: str, action_id: int, done: bool) -> dict:
    """체크리스트 항목 완료 표시(리포트를 볼 수 있는 사람 = 리포트 주소를 아는 사람)."""
    rep, _ = get_report(db, public_id)
    it = db.get(M.ActionItem, action_id)
    if it is None or it.report_id != rep.report_id or it.policy_id is not None:
        raise ApiError(404, "ACTION_NOT_FOUND", "체크리스트 항목을 찾을 수 없어요")
    it.is_done = bool(done)
    db.commit()
    return {"action_id": it.action_id, "done": bool(it.is_done)}


def _my_saved(db: Session, device: str, saved_report_id: int, report_public_id: str | None) -> M.SavedReport:
    """이 브라우저의 저장 항목. 리포트 번호(report_id)를 함께 받으면 그 리포트를 저장한 항목인지도 확인한다 — 다른 탭에서 지운 뒤
    같은 번호로 새로 저장된 리포트를 옛 목록의 '삭제'·'메모 저장'이 건드리지 않게."""
    sr = db.get(M.SavedReport, saved_report_id)
    if sr is None or sr.device_key_hash is None or sr.device_key_hash != device:
        raise ApiError(404, "SAVED_NOT_FOUND", "저장한 리포트를 찾을 수 없어요")
    if report_public_id is not None:
        rep = db.get(M.ActionReport, sr.report_id)
        if rep is None or rep.public_id != report_public_id:
            raise ApiError(404, "SAVED_NOT_FOUND", "저장한 리포트를 찾을 수 없어요")
    return sr


def delete_saved(db: Session, device: str, saved_report_id: int, report_public_id: str | None = None):
    sr = _my_saved(db, device, saved_report_id, report_public_id)
    db.delete(sr)
    db.commit()


def delete_all_saved(db: Session, device: str) -> int:
    """이 브라우저의 저장 목록을 모두 지운다(공용 컴퓨터를 다 쓴 뒤 — 로그아웃이 하던 정리). 지운 개수를 돌려준다."""
    n = db.execute(delete(M.SavedReport).where(M.SavedReport.device_key_hash == device)).rowcount or 0
    db.commit()
    return n


def update_memo(db: Session, device: str, saved_report_id: int, report_public_id: str | None, memo: str | None) -> M.SavedReport:
    """저장 목록의 메모만 고친다(지운 항목을 다시 저장하지 않는다 — 없으면 404)."""
    sr = _my_saved(db, device, saved_report_id, report_public_id)
    sr.memo = memo
    db.commit()
    return sr
