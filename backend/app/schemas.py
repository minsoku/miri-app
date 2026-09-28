"""요청/응답 스키마 (OpenAPI 문서 = API 명세).  금액 단위는 모두 원(KRW)."""
from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from pydantic_core import PydanticCustomError

Role = Literal["PRE_FOUNDER", "OWNER", "CONSULTANT"]
Goal = Literal["기본", "안정형", "고수익형", "저비용형"]
MAX_WON = 100_000_000_000   # 1,000억 — 입력 오타 방지 상한
MAX_ID = 2 ** 63 - 1


def _no_bool(v):
    """JSON true/false가 숫자 칸에 1/0으로 들어가지 않게(pydantic 기본은 bool을 int로 받아 줌)."""
    if isinstance(v, bool):
        raise PydanticCustomError("int_type", "Input should be a valid number")
    return v


# ── 메타 ─────────────────────────────────────────────────────────────────
class MetaOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    data_quarter: int
    data_quarter_label: str
    model_version: str
    trained_at: str
    analysis_level: Literal["district", "trade_area"]
    grade_cuts: list[float]
    grade_rate_bounds: dict[str, float] = Field(description="등급 경계의 예상 연간 폐업률")
    goals: dict[str, dict[str, float]]
    notices: list[str]


# ── 상권 ─────────────────────────────────────────────────────────────────
class PlaceOut(BaseModel):
    name: str
    kind: str
    lat: float
    lng: float
    area_code: Optional[str] = None
    area_name: Optional[str] = None
    address: Optional[str] = None
    source: Literal["local", "kakao"] = "local"


class AreaMetricsOut(BaseModel):
    floating_daily: Optional[int] = Field(None, description="일평균 유동인구(분기 합계 ÷ 분기 일수)")
    resident_population: Optional[int] = None
    working_population: Optional[int] = None
    store_count: Optional[int] = Field(None, description="서비스 업종 전체 점포 수(프랜차이즈 포함)")
    rent_per_3_3m2: Optional[int] = Field(None, description="3.3㎡당 월 환산임대료(원)")
    rent_level: Optional[str] = None
    change_name: Optional[str] = Field(None, description="상권변화지표(다이나믹·상권확장·정체·상권축소)")
    avg_open_months: Optional[float] = None
    avg_closed_months: Optional[float] = None
    quarter_label: Optional[str] = None


class AreaCardOut(BaseModel):
    area_code: str
    area_name: str
    level: str
    is_center: bool = False
    distance_m: int = 0
    lat: Optional[float] = None
    lng: Optional[float] = None
    metrics: AreaMetricsOut


class CandidatesOut(BaseModel):
    lat: float
    lng: float
    radius_m: int
    place_name: Optional[str] = None
    analysis_level: str
    notice: Optional[str] = None
    candidates: list[AreaCardOut]


class CompareIn(BaseModel):
    area_codes: list[str] = Field(min_length=1, max_length=4)
    industry_code: Optional[str] = None


class CompareSummaryOut(BaseModel):
    avg_risk_score: Optional[float] = Field(None, description="이 지역 전 업종 폐업 위험 점수 평균(0~100)")
    high_risk_share: Optional[float] = Field(None, description="위험 '높음·고위험' 업종 비율(0~1)")


class CompareIndustryOut(BaseModel):
    risk_score: int
    risk_grade: str
    location_risk_pct: int
    pred_annual_rate: float
    sales_ps_m: Optional[float] = None
    sales_outlier: Optional[float] = Field(None, description="점포당 매출 ÷ 서울 같은 업종 중간값(3배 이상일 때만 — 대형 점포 가능)")
    demand_D: Optional[float] = None
    stores_avg: float


class CompareAreaOut(AreaCardOut):
    summary: CompareSummaryOut
    industry: Optional[CompareIndustryOut] = Field(None, description="업종을 지정했을 때 그 업종 값(이 지역에 점포가 없으면 null)")


class CompareOut(BaseModel):
    industry_code: Optional[str] = None
    industry_name: Optional[str] = None
    data_quarter: int
    areas: list[CompareAreaOut]


# ── 분석 요청(SB-02~04 → SB-05) ───────────────────────────────────────────
class AnalysisIn(BaseModel):
    area_code: str = Field(min_length=1, max_length=20, description="분석 대상 지역 코드(후보 카드에서 선택)")
    place_name: Optional[str] = Field(None, max_length=100)
    lat: Optional[float] = Field(None, ge=33, le=39)
    lng: Optional[float] = Field(None, ge=124, le=132)
    radius_m: Optional[int] = Field(None, ge=100, le=5000)
    candidate_area_codes: list[str] = Field(default_factory=list, max_length=10)
    user_type: Role = "PRE_FOUNDER"
    budget: int = Field(ge=0, le=MAX_WON, description="총 창업 예산(원)")
    monthly_rent_limit: int = Field(ge=0, le=MAX_WON, description="월 임대료(원). 구하려는 점포 월세 — 아직 정하지 않았으면 감당할 수 있는 최대치")
    labor_cost: int = Field(ge=0, le=MAX_WON, description="예상 인건비(월, 원)")
    initial_investment: int = Field(0, ge=0, le=MAX_WON, description="인테리어·설비 등 초기 투자비(보증금 제외)")
    other_fixed: int = Field(0, ge=0, le=MAX_WON, description="관리비·공과금 등 기타 월 고정비")
    loan_amount: int = Field(0, ge=0, le=MAX_WON)
    loan_rate_annual: float = Field(0.0, ge=0, le=0.3, description="대출 연이율(0.05 = 5%)")
    owner_salary: int = Field(0, ge=0, le=MAX_WON, description="목표 월수입(대표자, 선택). 넣으면 손익분기에 포함")
    business_goal: Goal = "기본"
    licenses: list[str] = Field(default_factory=list, max_length=20, description="보유 자격(업종 목록의 license 값만)")
    categories: list[Literal["외식업", "서비스업", "소매업"]] = Field(default_factory=list, max_length=3)
    excluded_industries: list[str] = Field(default_factory=list, max_length=100)
    interests: list[str] = Field(default_factory=list, max_length=20, description="관심 업종 코드(SB-04)")
    cogs_rates: dict[Literal["외식업", "서비스업", "소매업"], float] = Field(
        default_factory=dict, description="분야별 원가율(선택, 0~0.95). 넣은 분야는 비용 적합도(F)·손익분기 기본값에 쓰인다. "
                                          "외식업은 비우면 평균 40.7%, 서비스업·소매업은 비우면 비용 적합도를 계산하지 않는다")

    @field_validator("cogs_rates", mode="before")
    @classmethod
    def _cogs(cls, v):
        if isinstance(v, dict):
            for x in v.values():
                # 95% 초과면 카드수수료(최대 2%)까지 더해 팔수록 손해에 가까워 추천·손익분기가 의미 없어진다
                if isinstance(x, bool) or not isinstance(x, (int, float)) or not (0 <= x <= 0.95) or x != x:
                    raise PydanticCustomError("value_error", "원가율은 0~95% 사이로 넣어 주세요")
        return v

    @field_validator("interests", "excluded_industries", "candidate_area_codes", "licenses", "categories")
    @classmethod
    def _dedupe(cls, v):
        seen, out = set(), []
        for x in v:
            if len(x) > 50:
                raise PydanticCustomError("string_too_long", "String should have at most 50 characters", {"max_length": 50})
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    @field_validator("budget", "monthly_rent_limit", "labor_cost", "initial_investment", "other_fixed", "loan_amount",
                     "loan_rate_annual", "owner_salary", "lat", "lng", "radius_m", mode="before")
    @classmethod
    def _numbers(cls, v):
        return _no_bool(v)


class ScoresOut(BaseModel):
    D: Optional[float] = Field(None, description="매출 잠재력(서울 동일 업종 중 백분위)")
    S: Optional[float] = Field(None, description="생존 안정성 = 100 − 위험 점수")
    F: Optional[float] = Field(None, description="내 비용 적합도(손익분기 달성배율 환산). 미적용 시 null")


class PeakFlagOut(BaseModel):
    code: str
    pill: str
    share: float
    action: str


class ItemOut(BaseModel):
    industry_code: str
    industry_name: str
    category: str
    display_group: Optional[str] = None
    item_type: Literal["TOP", "INTEREST", "CAUTION"]
    rank: Optional[int] = None
    suitability: Optional[float] = Field(None, description="적합도(0~100). 매출 데이터가 없어 일부 점수로만 낼 수 있으면 null")
    score_note: Optional[str] = Field(None, description="적합도가 없거나 다른 업종과 같은 잣대가 아닐 때 이유")
    scores: ScoresOut
    risk_score: int
    risk_grade: str
    location_risk_pct: int
    location_grade: str
    pred_annual_rate: float
    sales_ps_m: Optional[float] = None
    avg_ticket: Optional[float] = None
    stores_avg: Optional[float] = None
    confidence: str
    achievability_ratio: Optional[float] = None
    eligible: bool
    ineligible_reason: Optional[str] = None
    reason: str
    reason_short: str
    chips: list[str]
    caution: str
    cautions: list[str]
    peak: list[PeakFlagOut] = []


class AnalysisAreaOut(BaseModel):
    area_code: str
    area_name: str
    level: str
    place_name: Optional[str] = None
    radius_m: Optional[int] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    scope_note: Optional[str] = Field(None, description="분석 단위 안내(자치구 전체 합계로 분석할 때). 결과 화면 맨 위에 표시")
    candidate_area_codes: list[str] = Field([], description="SB-02에서 후보로 보였던 다른 구(분석한 구 제외) — 다시 분석할 때 그대로 보낸다")


class MissingInterestOut(BaseModel):
    industry_code: str
    industry_name: str


class AnalysisOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    id: str
    created_at: datetime
    area: AnalysisAreaOut
    conditions: dict
    data_quarter: int
    data_quarter_label: str
    model_version: str
    business_goal: str
    weights: dict[str, float]
    f_applied: bool
    f_note: Optional[str] = None
    n_candidates: int
    n_low_score: int = Field(0, description="조건은 통과했지만 적합도가 20점 미만이라 TOP에 넣지 않은 업종 수")
    empty_reason: Optional[str] = Field(None, description="추천 TOP이 0개일 때 가장 큰 원인(예: 월 고정비가 모든 업종의 평균 매출보다 큼)")
    top: list[ItemOut]
    interests: list[ItemOut]
    cautions: list[ItemOut]
    missing_interests: list[MissingInterestOut] = Field(default_factory=list, description="이 지역에 점포가 없어 점수를 못 낸 관심 업종")
    notices: list[str]


# ── 위험도(SB-06) ────────────────────────────────────────────────────────
class FactorOut(BaseModel):
    factor_code: str
    factor_name: str
    label: str
    effect_pct: float = Field(description="이 요인 때문에 예상 폐업률이 몇 % 달라졌는지")
    effect_display: int
    direction: Literal["up", "down"]
    explanation: str
    detail: str


class ReferenceOut(BaseModel):
    key: str
    label: str
    value: Optional[float] = None
    display: str
    note: Optional[str] = None


class AlternativeOut(BaseModel):
    area_code: str
    area_name: str
    location_risk_pct: int
    location_grade: str
    risk_score: int
    pred_annual_rate: float
    distance_km: float
    sales_ps_m: Optional[float] = Field(None, description="그 지역 같은 업종 점포당 월매출(카드 매출 추정)")
    affordable: Optional[bool] = Field(None, description="그 평균 매출로 지금 비용(분석 조건 또는 리포트에 반영한 손익분기)을 감당하는지"
                                                         "(원가율 반영). 평균 매출이 대형 점포 때문에 부풀었을 수 있으면 null")
    sales_outlier: Optional[float] = Field(None, description="점포당 매출 ÷ 서울 같은 업종 중간값(3배 이상일 때만)")


class RiskOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    analysis_id: str
    area_code: str
    area_name: str
    industry_code: str
    industry_name: str
    category: str
    data_quarter: int
    data_quarter_label: str
    model_version: str
    risk_score: int
    risk_grade: str
    pred_annual_rate: float
    industry_avg_annual_rate: Optional[float] = None
    seoul_avg_annual_rate: Optional[float] = None
    location_risk_pct: Optional[int] = Field(None, description="같은 업종 안에서의 입지 위험(0~100). 이 지역에 같은 업종이 없으면 null")
    location_grade: Optional[str] = None
    confidence: str
    local_data_weight: Optional[float] = None
    grade_cuts: list[float]
    grade_rate_bounds: dict[str, float]
    summary: str
    factors: list[FactorOut]
    reference: list[ReferenceOut]
    raw: dict
    alternatives: list[AlternativeOut]
    affordability_basis: str = Field("analysis", description="alternatives[].affordable의 비용 기준: analysis(분석 조건) | report(리포트에 반영한 손익분기)")
    affordability_cogs_known: bool = Field(True, description="감당 판단에 원가율을 썼는지(모르면 평균 매출 ≥ 월 고정비만 봄)")
    affordability_owner_included: bool = Field(False, description="감당 판단 비용에 목표 월수입이 들어 있는지")
    recheck: bool = Field(description="고위험 → 창업 재검토 안내 표시")
    fallback: bool = Field(False, description="지역 데이터가 없어 업종 평균으로 대체")
    notices: list[str]


# ── 손익분기(SB-07) ──────────────────────────────────────────────────────
class BreakEvenIn(BaseModel):
    industry_code: str
    monthly_rent: Optional[int] = Field(None, ge=0, le=MAX_WON, description="미입력 시 분석 조건의 월 임대료")
    labor_cost: Optional[int] = Field(None, ge=0, le=MAX_WON)
    other_fixed: Optional[int] = Field(None, ge=0, le=MAX_WON)
    initial_investment: Optional[int] = Field(None, ge=0, le=MAX_WON)
    loan_amount: Optional[int] = Field(None, ge=0, le=MAX_WON)
    loan_rate_annual: Optional[float] = Field(None, ge=0, le=0.3)
    owner_salary: Optional[int] = Field(None, ge=0, le=MAX_WON)
    cogs_rate: Optional[float] = Field(None, ge=0, lt=1, description="원가율. 비우면 분석 조건의 분야별 원가율(cogs_rates) → "
                                       "업종 대분류 평균(외식업만). 둘 다 없으면 COGS_REQUIRED")
    other_variable_rate: Optional[float] = Field(None, ge=0, lt=1, description="배달·플랫폼 수수료 등")
    avg_ticket: Optional[int] = Field(None, ge=100, le=10_000_000, description="미입력 시 이 지역 동일 업종 실제 객단가, "
                                      "그것도 없으면 서울 같은 업종 평균 객단가(100원 이상)")

    @field_validator("monthly_rent", "labor_cost", "other_fixed", "initial_investment", "loan_amount", "loan_rate_annual",
                     "owner_salary", "cogs_rate", "other_variable_rate", "avg_ticket", mode="before")
    @classmethod
    def _numbers(cls, v):
        return _no_bool(v)


class BreakEvenOut(BaseModel):
    id: int
    analysis_id: str
    area_code: str
    area_name: str
    industry_code: str
    industry_name: str
    category: str
    inputs: dict
    monthly_fixed_cost: int
    fixed_breakdown: dict
    variable_cost_rate: float
    variable_breakdown: dict
    contribution_margin_rate: float
    required_monthly_sales: int
    required_daily_sales: int
    required_daily_customers: int
    avg_ticket_used: int
    operating_days: int
    market_sales_ps_m: Optional[int] = None
    achievability_ratio: Optional[float] = None
    cost_pressure: Optional[str] = None
    profit_at_market_avg: Optional[int] = None
    payback_months: Optional[int] = None
    market_tx_ps_day: Optional[float] = None
    customers_vs_market: Optional[float] = None
    max_fixed_for_bep: Optional[int] = Field(None, description="평균 매출로 손익분기를 맞추려면 허용되는 최대 월 고정비")
    composition: dict = Field(description="필요 매출의 구성: 고정비(목표 월수입 제외)·변동비·목표 월수입(대표자)")
    warnings: list[str]
    sales_outlier: Optional[float] = Field(None, description="이 지역 평균 매출 ÷ 서울 같은 업종 중간값(3배 이상일 때만 — 달성배율은 참고용)")


# ── 액션 리포트(SB-08) · 저장(SB-09) ─────────────────────────────────────
class ReportIn(BaseModel):
    industry_code: str
    break_even_id: Optional[int] = Field(None, ge=1, le=MAX_ID)


class ActionOut(BaseModel):
    action_id: int
    action_type: str
    content: str
    priority: int
    done: bool = False


class ActionDoneIn(BaseModel):
    done: StrictBool = Field(description="체크리스트 항목 완료 여부")


class ActionDoneOut(BaseModel):
    action_id: int
    done: bool


class PolicyOut(BaseModel):
    policy_id: int
    name: str
    provider: Optional[str] = None
    support_type: str
    summary: Optional[str] = None
    apply_url: Optional[str] = None
    target_user: str
    target_region: str
    checked_at: Optional[str] = None


class ReportOut(BaseModel):
    id: str
    analysis_id: str
    created_at: datetime
    area_code: str
    area_name: str
    place_name: Optional[str] = None
    radius_m: Optional[int] = None
    industry_code: str
    industry_name: str
    one_line_summary: str
    checklist: list[ActionOut]
    policies: list[PolicyOut]
    risk: dict
    breakeven: Optional[dict] = None
    recommendation: Optional[dict] = None
    saved_report_id: Optional[int] = None
    data_quarter_label: str


class SaveIn(BaseModel):
    report_id: str = Field(min_length=1, max_length=36)
    memo: Optional[str] = Field(None, max_length=500)


class MemoIn(BaseModel):
    memo: Optional[str] = Field(None, max_length=500)
    report_id: Optional[str] = Field(None, min_length=1, max_length=36, description="이 저장 항목의 리포트 id(주면 일치하는지 확인)")


class SavedItemOut(BaseModel):
    saved_report_id: int
    report_id: str
    analysis_id: str
    created_at: datetime
    area_name: str
    place_name: Optional[str] = None
    industry_code: str
    industry_name: str
    suitability: Optional[float] = None
    risk_score: int
    risk_grade: str
    memo: Optional[str] = None
    required_monthly_sales: Optional[float] = Field(None, description="리포트에 반영한 손익분기 필요 월매출")
    monthly_fixed_cost: Optional[float] = Field(None, description="월 고정비(반영한 손익분기, 없으면 분석 조건 — 목표 월수입 포함)")
    achievability_ratio: Optional[float] = None
    owner_included: bool = Field(False, description="필요 월매출에 목표 월수입이 들어 있는지")
    edited: bool = Field(False, description="반영한 손익분기에 분석 조건과 다르게 바꾼 값이 있는지")
    business_goal: Optional[str] = Field(None, description="이 분석의 창업 목표(같은 업종 카드끼리 적합도가 다른 이유)")
    item_type: Optional[str] = Field(None, description="분석 결과에서 이 업종의 자리: TOP · INTEREST · CAUTION")
    rank: Optional[int] = None
    eligible: Optional[bool] = Field(None, description="추천 조건을 통과했는지(관심 업종이면 추천 제외일 수 있음)")
    caution: bool = Field(False, description="주의 업종(같은 업종 중 입지 위험 상위 10%)인지")
    sales_outlier: Optional[float] = Field(None, description="평균 매출 ÷ 서울 같은 업종 중간값(3배 이상일 때만 — 달성배율은 참고용)")
    checklist_total: int = 0
    checklist_done: int = 0


class SavedListOut(BaseModel):
    count: int
    items: list[SavedItemOut]
