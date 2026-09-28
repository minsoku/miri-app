"""DB 스키마 = 보고서 6.3 ERD(v1) + 계산로직 v2 명세서 §9 변경분.

표기: [v2] 가 붙은 컬럼·테이블은 v1 ERD에 없던 것(명세서 §9 반영). 제거된 v1 컬럼은 각 테이블 docstring에 적었다.
      [0.2] 는 앱 0.2에서 로그인을 없애며 바뀐 것(저장 리포트를 계정 대신 브라우저로 구분).
금액 단위는 전부 원(KRW). 분기는 20252(=2025년 2분기) 형식 정수.
"""
from __future__ import annotations
from datetime import datetime, date, timezone
from sqlalchemy import (BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint, Index, false, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

# SQLite는 INTEGER PRIMARY KEY만 자동증가 → BIGINT는 SQLite에서만 INTEGER로
PK = BigInteger().with_variant(Integer, "sqlite")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)      # DB에는 UTC naive로 저장


# ════════════════════════ 6.3.2 사용자 및 분석 요청 ════════════════════════
class User(Base):
    """[0.2] 로그인 기능을 없애 새 계정은 만들지 않는다. 이전 버전 DB의 계정·외래키와 호환되도록 테이블만 남긴다."""
    __tablename__ = "users"
    user_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(50), default="")
    role: Mapped[str] = mapped_column(String(30), default="PRE_FOUNDER")  # PRE_FOUNDER, OWNER, CONSULTANT, ADMIN
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AnalysisRequest(Base):
    """analysis_requests. [0.2] 로그인이 없어 누구나 분석하고, 추측할 수 없는 ID(public_id)를 아는 사람만 연다.
    user_id·claim_token_hash는 이전 버전(회원·비회원 구분) DB 호환용으로만 남긴다 — 새 분석은 둘 다 NULL이고,
    이전 버전에서 회원이 만든 분석(user_id 있음)은 주인이 더는 로그인할 수 없으므로 열지 않는다(404)."""
    __tablename__ = "analysis_requests"
    request_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)   # [v2] URL용 추측 불가 ID
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), nullable=True, index=True)
    claim_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # (이전 버전) 비회원 분석 소유권 증명
    main_area_id: Mapped[int] = mapped_column(ForeignKey("commercial_areas.area_id"))
    budget: Mapped[int] = mapped_column(BigInteger)
    monthly_rent_limit: Mapped[int] = mapped_column(BigInteger)
    labor_cost: Mapped[int] = mapped_column(BigInteger)
    initial_investment: Mapped[int] = mapped_column(BigInteger, default=0)
    business_goal: Mapped[str] = mapped_column(String(100), default="기본")
    user_type: Mapped[str] = mapped_column(String(30), default="PRE_FOUNDER")          # [v2] 시작 화면(SB-01)에서 고른 사용자 유형
    other_fixed: Mapped[int] = mapped_column(BigInteger, default=0)                 # [v2]
    loan_amount: Mapped[int] = mapped_column(BigInteger, default=0)                 # [v2]
    loan_rate_annual: Mapped[float] = mapped_column(Float, default=0.0)            # [v2]
    owner_salary: Mapped[int] = mapped_column(BigInteger, default=0)                # [v2] 대표자 목표 인건비
    licenses_json: Mapped[str] = mapped_column(Text, default="[]")                 # [v2] 보유 자격
    categories_json: Mapped[str] = mapped_column(Text, default="[]")               # [v2] 대분류 제한
    cogs_json: Mapped[str | None] = mapped_column(Text, nullable=True)             # [v2.1] 분야별 원가율(선택) {"소매업": 0.7}
    excluded_json: Mapped[str | None] = mapped_column(Text, nullable=True)         # [v2.1] 사용자가 뺀 업종 코드(선택)
    place_name: Mapped[str | None] = mapped_column(String(100), nullable=True)     # [v2] 사용자가 검색한 위치명
    center_lat: Mapped[float | None] = mapped_column(Float, nullable=True)         # [v2]
    center_lng: Mapped[float | None] = mapped_column(Float, nullable=True)         # [v2]
    radius_meter: Mapped[int | None] = mapped_column(Integer, nullable=True)       # [v2]
    data_quarter: Mapped[int] = mapped_column(Integer)                             # [v2] 분석에 쓴 데이터 분기
    model_version: Mapped[str] = mapped_column(String(30))                         # [v2]
    notices_json: Mapped[str] = mapped_column(Text, default="[]")                  # [v2] 분석 당시 안내 문구
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    areas: Mapped[list["RequestArea"]] = relationship(back_populates="request", cascade="all, delete-orphan")
    industries: Mapped[list["RequestIndustry"]] = relationship(back_populates="request", cascade="all, delete-orphan")


class RequestArea(Base):
    __tablename__ = "request_areas"
    request_area_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("analysis_requests.request_id", ondelete="CASCADE"), index=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("commercial_areas.area_id"))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    request: Mapped[AnalysisRequest] = relationship(back_populates="areas")


class RequestIndustry(Base):
    __tablename__ = "request_industries"
    request_industry_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("analysis_requests.request_id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("business_categories.category_id"))
    preference_order: Mapped[int] = mapped_column(Integer, default=1)
    request: Mapped[AnalysisRequest] = relationship(back_populates="industries")


# ════════════════════════ 6.3.3 상권·업종 원천 데이터 ════════════════════════
class CommercialArea(Base):
    """분석 단위 지역. 현재 적재 데이터는 자치구(area_level='district'). 상권 데이터 적재 시 'trade_area' 행 추가."""
    __tablename__ = "commercial_areas"
    area_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    area_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)   # [v2] 자치구_코드 / 상권_코드
    area_name: Mapped[str] = mapped_column(String(100))
    area_level: Mapped[str] = mapped_column(String(20), default="district")      # [v2] district | trade_area
    parent_area_id: Mapped[int | None] = mapped_column(ForeignKey("commercial_areas.area_id"), nullable=True)  # [v2]
    province: Mapped[str] = mapped_column(String(50), default="서울특별시")
    city: Mapped[str | None] = mapped_column(String(50), nullable=True)           # 시/군/구
    district: Mapped[str | None] = mapped_column(String(50), nullable=True)       # 읍/면/동
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    radius_meter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    boundary_geojson: Mapped[str | None] = mapped_column(Text, nullable=True)    # [v2] 경계(반경 내 후보 계산·지도)


class BusinessCategory(Base):
    __tablename__ = "business_categories"
    category_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    category_code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    category_name: Mapped[str] = mapped_column(String(100))
    parent_category: Mapped[str] = mapped_column(String(100))                    # 외식업/서비스업/소매업
    has_sales_data: Mapped[bool] = mapped_column(Boolean, default=False)         # [v2] 추정매출 제공 여부(추천 대상)
    display_group: Mapped[str | None] = mapped_column(String(50), nullable=True) # [v2] 관심 업종 칩(카페·디저트 등)


class AreaMetric(Base):
    """area_metrics. 유동인구는 원천 그대로 '분기 합계'(일평균은 API에서 ÷ 분기 일수)."""
    __tablename__ = "area_metrics"
    __table_args__ = (UniqueConstraint("area_id", "base_quarter"),)
    metric_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("commercial_areas.area_id"), index=True)
    metric_date: Mapped[date] = mapped_column(Date)
    base_quarter: Mapped[int] = mapped_column(Integer)                           # [v2]
    floating_population: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    resident_population: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    working_population: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    consumption_index: Mapped[float | None] = mapped_column(Float, nullable=True)  # 정의 확정 전(현재 NULL)
    avg_monthly_income: Mapped[int | None] = mapped_column(BigInteger, nullable=True)   # [v2] 소득소비 원천
    total_spending: Mapped[int | None] = mapped_column(BigInteger, nullable=True)       # [v2]
    avg_open_months: Mapped[float | None] = mapped_column(Float, nullable=True)         # [v2] 운영 영업개월 평균
    avg_closed_months: Mapped[float | None] = mapped_column(Float, nullable=True)       # [v2] 폐업 영업개월 평균
    change_indicator: Mapped[str | None] = mapped_column(String(20), nullable=True)     # [v2] 상권변화지표(HH 등)
    change_indicator_name: Mapped[str | None] = mapped_column(String(30), nullable=True)


class StoreStatistic(Base):
    """store_statistics v2: substitute_store_count(오해 소지) → total_store_count(=유사_업종_점포_수, 폐업률 분모).
    density_score·new_entry_rate 같은 파생값은 저장하지 않는다(특징은 area_category_features)."""
    __tablename__ = "store_statistics"
    __table_args__ = (UniqueConstraint("area_id", "category_id", "base_quarter"),)
    store_stat_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("commercial_areas.area_id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("business_categories.category_id"), index=True)
    base_quarter: Mapped[int] = mapped_column(Integer)
    base_date: Mapped[date] = mapped_column(Date)
    store_count: Mapped[int] = mapped_column(Integer, default=0)            # 점포_수(프랜차이즈 제외)
    total_store_count: Mapped[int] = mapped_column(Integer, default=0)      # [v2] 유사_업종_점포_수
    franchise_count: Mapped[int] = mapped_column(Integer, default=0)        # [v2]
    opening_count: Mapped[int] = mapped_column(Integer, default=0)          # [v2]
    closure_count: Mapped[int] = mapped_column(Integer, default=0)          # [v2]


class RentMetric(Base):
    """rent_metrics. 원천(서울시 우리마을가게 임대시세)은 3.3㎡당 월 환산임대료(원)."""
    __tablename__ = "rent_metrics"
    __table_args__ = (UniqueConstraint("area_id", "base_quarter"),)
    rent_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("commercial_areas.area_id"), index=True)
    avg_monthly_rent: Mapped[int | None] = mapped_column(BigInteger, nullable=True)   # 점포 단위 월세(원천 없음 → NULL)
    rent_per_square_meter: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 원/㎡·월
    rent_per_3_3m2: Mapped[int | None] = mapped_column(Integer, nullable=True)         # [v2] 원/3.3㎡·월 (원천값)
    rent_level: Mapped[str | None] = mapped_column(String(30), nullable=True)         # 낮음/보통/높음 (분기 내 3분위)
    base_quarter: Mapped[int] = mapped_column(Integer)
    base_date: Mapped[date] = mapped_column(Date)


class SalesMetric(Base):
    """sales_metrics v2: 원천 그대로 분기 합계만 저장(점포당 매출·객단가·증감률은 파생 → 특징 테이블)."""
    __tablename__ = "sales_metrics"
    __table_args__ = (UniqueConstraint("area_id", "category_id", "base_quarter"),)
    sales_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("commercial_areas.area_id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("business_categories.category_id"), index=True)
    base_quarter: Mapped[int] = mapped_column(Integer)
    base_date: Mapped[date] = mapped_column(Date)
    quarterly_sales: Mapped[int | None] = mapped_column(BigInteger, nullable=True)      # [v2] 당월_매출_금액(분기 합계)
    quarterly_tx_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)   # [v2] 당월_매출_건수
    breakdown_json: Mapped[str | None] = mapped_column(Text, nullable=True)            # [v2] 요일·시간대·성별·연령 매출


class StartupClosureHistory(Base):
    """startup_closure_history v2: 점포 테이블과 중복되므로 '연 단위 집계' 전용(완결된 연도만)."""
    __tablename__ = "startup_closure_history"
    __table_args__ = (UniqueConstraint("area_id", "category_id", "base_year"),)
    history_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("commercial_areas.area_id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("business_categories.category_id"), index=True)
    startup_count: Mapped[int] = mapped_column(Integer, default=0)
    closure_count: Mapped[int] = mapped_column(Integer, default=0)
    closure_rate: Mapped[float | None] = mapped_column(Float, nullable=True)   # 연 폐업 수 / 연평균 점포 수 × 100
    survival_rate_3y: Mapped[float | None] = mapped_column(Float, nullable=True)  # 원천 없음 → NULL
    base_year: Mapped[int] = mapped_column(Integer)


# ════════════════════════ [v2] 분기 배치 산출물 ════════════════════════
class ScoringModelVersion(Base):
    __tablename__ = "scoring_model_versions"
    model_version: Mapped[str] = mapped_column(String(30), primary_key=True)
    model_type: Mapped[str] = mapped_column(String(30), default="HYBRID")
    params_json: Mapped[str] = mapped_column(Text)            # 계수·기준분위·c_t·EB 모수 (risk_model_v2.json)
    train_quarters_json: Mapped[str] = mapped_column(Text, default="[]")
    metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # 검증 지표(백테스트)
    trained_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)


class AreaCategoryFeature(Base):
    """지역×업종×분기 특징·예측. 배치가 쓰고 API는 조회만 한다."""
    __tablename__ = "area_category_features"
    __table_args__ = (UniqueConstraint("area_id", "category_id", "base_quarter", "model_version"),
                      Index("ix_acf_q_model", "base_quarter", "model_version"))
    feature_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("commercial_areas.area_id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("business_categories.category_id"), index=True)
    base_quarter: Mapped[int] = mapped_column(Integer)
    model_version: Mapped[str] = mapped_column(ForeignKey("scoring_model_versions.model_version"))
    exposure_4q: Mapped[float] = mapped_column(Float)            # E4 점포·분기
    closures_4q: Mapped[float] = mapped_column(Float)            # C4
    openings_4q: Mapped[float] = mapped_column(Float)
    stores_avg_4q: Mapped[float] = mapped_column(Float)
    rate_eb: Mapped[float | None] = mapped_column(Float, nullable=True)
    local_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    sales_ps_m: Mapped[float | None] = mapped_column(Float, nullable=True)     # 점포당 월매출(원)
    avg_ticket: Mapped[float | None] = mapped_column(Float, nullable=True)
    tx_ps_day: Mapped[float | None] = mapped_column(Float, nullable=True)
    demand_score: Mapped[float | None] = mapped_column(Float, nullable=True)   # D
    pred_q_rate: Mapped[float] = mapped_column(Float)
    pred_annual_rate: Mapped[float] = mapped_column(Float)
    risk_score: Mapped[int] = mapped_column(Integer)
    risk_level: Mapped[str] = mapped_column(String(10))
    location_risk_pct: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[str] = mapped_column(String(10))
    payload_json: Mapped[str] = mapped_column(Text)              # x_*, eff_*, p_*, 증감률 등 나머지


class CategoryCostProfile(Base):
    __tablename__ = "category_cost_profiles"
    parent_category: Mapped[str] = mapped_column(String(100), primary_key=True)
    default_cogs_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)


class IndustryLicense(Base):
    __tablename__ = "industry_licenses"
    category_id: Mapped[int] = mapped_column(ForeignKey("business_categories.category_id"), primary_key=True)
    license_name: Mapped[str] = mapped_column(String(50))
    legal_basis: Mapped[str | None] = mapped_column(String(100), nullable=True)


class Place(Base):
    """[v2] 위치 검색용 지명(역·상권·자치구). 실서비스는 카카오 로컬 API로 대체/보강."""
    __tablename__ = "places"
    place_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    aliases: Mapped[str] = mapped_column(String(255), default="")    # 쉼표 구분
    kind: Mapped[str] = mapped_column(String(20))                    # station | street | district
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("commercial_areas.area_id"), nullable=True)


# ════════════════════════ 6.3.4 추천·위험도·리포트 결과 ════════════════════════
class RecommendationResult(Base):
    __tablename__ = "recommendation_results"
    recommendation_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("analysis_requests.request_id", ondelete="CASCADE"), unique=True)
    model_type: Mapped[str] = mapped_column(String(50), default="HYBRID")
    model_version: Mapped[str] = mapped_column(String(30))                   # [v2]
    weights_json: Mapped[str] = mapped_column(Text)                          # [v2] 목표별 가중치
    f_applied: Mapped[bool] = mapped_column(Boolean, default=False)          # [v2] 비용 적합도 반영 여부
    f_note: Mapped[str | None] = mapped_column(Text, nullable=True)          # [v2]
    n_candidates: Mapped[int] = mapped_column(Integer, default=0)            # [v2]
    n_low_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")   # [v2.1] 적합도 하한 미만이라 TOP에서 뺀 후보 수
    empty_reason: Mapped[str | None] = mapped_column(Text, nullable=True)    # [v2] TOP 0개일 때 원인
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    items: Mapped[list["RecommendationItem"]] = relationship(cascade="all, delete-orphan", order_by="RecommendationItem.item_id")


class RecommendationItem(Base):
    __tablename__ = "recommendation_items"
    item_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendation_results.recommendation_id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("business_categories.category_id"))
    item_type: Mapped[str] = mapped_column(String(10), default="TOP")      # [v2] TOP | INTEREST | CAUTION
    rank_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suitability_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    caution: Mapped[str | None] = mapped_column(Text, nullable=True)
    demand_score: Mapped[float | None] = mapped_column(Float, nullable=True)      # [v2] D
    stability_score: Mapped[float | None] = mapped_column(Float, nullable=True)   # [v2] S
    cost_score: Mapped[float | None] = mapped_column(Float, nullable=True)        # [v2] F
    achievability_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)  # [v2]
    eligible: Mapped[bool] = mapped_column(Boolean, default=True)                 # [v2]
    ineligible_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)  # [v2]
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)          # [v2] 화면용 근거 칩 등


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"
    risk_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("analysis_requests.request_id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("business_categories.category_id"))
    area_id: Mapped[int] = mapped_column(ForeignKey("commercial_areas.area_id"))       # [v2]
    risk_score: Mapped[int] = mapped_column(Integer)
    risk_level: Mapped[str] = mapped_column(String(30))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    pred_annual_rate: Mapped[float] = mapped_column(Float)                            # [v2]
    location_risk_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)     # [v2] 지역에 같은 업종이 없으면 NULL
    location_risk_level: Mapped[str | None] = mapped_column(String(30), nullable=True)  # [v2]
    confidence: Mapped[str] = mapped_column(String(10))                               # [v2]
    model_version: Mapped[str] = mapped_column(String(30))                            # [v2]
    reference_json: Mapped[str | None] = mapped_column(Text, nullable=True)           # [v2] 참고 지표
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    factors: Mapped[list["RiskFactor"]] = relationship(cascade="all, delete-orphan", order_by="RiskFactor.factor_id")


class RiskFactor(Base):
    """risk_factors v2: factor_score/max_score(임의 배점) → factor_code·label·effect_pct(모델 요인 효과 %)."""
    __tablename__ = "risk_factors"
    factor_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    risk_id: Mapped[int] = mapped_column(ForeignKey("risk_assessments.risk_id", ondelete="CASCADE"), index=True)
    factor_code: Mapped[str] = mapped_column(String(30))
    factor_name: Mapped[str] = mapped_column(String(100))
    label: Mapped[str] = mapped_column(String(100))
    effect_pct: Mapped[float] = mapped_column(Float)
    x_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)


class BreakEvenAnalysis(Base):
    __tablename__ = "break_even_analyses"
    break_even_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("analysis_requests.request_id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("business_categories.category_id"))   # [v2]
    monthly_fixed_cost: Mapped[int] = mapped_column(BigInteger)
    variable_cost_rate: Mapped[float] = mapped_column(Float)
    avg_transaction_amount: Mapped[int] = mapped_column(BigInteger)
    required_monthly_sales: Mapped[int] = mapped_column(BigInteger)
    required_daily_customers: Mapped[int] = mapped_column(BigInteger)
    other_fixed: Mapped[int] = mapped_column(BigInteger, default=0)          # [v2]
    depreciation: Mapped[int] = mapped_column(BigInteger, default=0)         # [v2]
    card_fee_rate: Mapped[float] = mapped_column(Float, default=0.0)         # [v2]
    cogs_rate: Mapped[float] = mapped_column(Float, default=0.0)             # [v2]
    operating_days: Mapped[int] = mapped_column(Integer, default=26)         # [v2]
    achievability_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)  # [v2]
    cost_pressure: Mapped[str | None] = mapped_column(String(10), nullable=True)    # [v2]
    payback_months: Mapped[int | None] = mapped_column(BigInteger, nullable=True)   # [v2]
    input_json: Mapped[str] = mapped_column(Text, default="{}")                      # [v2] 입력 원본
    result_json: Mapped[str] = mapped_column(Text, default="{}")                     # [v2] 계산 결과 원본
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PolicySupport(Base):
    __tablename__ = "policy_supports"
    policy_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    policy_name: Mapped[str] = mapped_column(String(150))
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)       # [v2]
    target_region: Mapped[str] = mapped_column(String(100), default="전국")
    target_category: Mapped[str] = mapped_column(String(100), default="전체")      # 전체/외식업/...
    target_user: Mapped[str] = mapped_column(String(50), default="전체")           # [v2] 예비창업자/자영업자/전체
    support_type: Mapped[str] = mapped_column(String(50))                          # 자금, 교육, 컨설팅 ...
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)               # [v2]
    apply_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    checked_at: Mapped[date | None] = mapped_column(Date, nullable=True)           # [v2] 정보 확인일


class ActionReport(Base):
    __tablename__ = "action_reports"
    report_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)                     # [v2]
    request_id: Mapped[int] = mapped_column(ForeignKey("analysis_requests.request_id", ondelete="CASCADE"), index=True)
    recommendation_id: Mapped[int | None] = mapped_column(ForeignKey("recommendation_results.recommendation_id"), nullable=True)
    risk_id: Mapped[int | None] = mapped_column(ForeignKey("risk_assessments.risk_id"), nullable=True)
    break_even_id: Mapped[int | None] = mapped_column(ForeignKey("break_even_analyses.break_even_id"), nullable=True)  # [v2]
    category_id: Mapped[int] = mapped_column(ForeignKey("business_categories.category_id"))           # [v2] 대상 업종
    one_line_summary: Mapped[str] = mapped_column(Text)
    # 지원사업을 고른 근거(업종 분야·종합 위험·적자 여부·대출 권유 가능) — 어떤 조건으로 골랐는지 남겨 둔다
    policy_ctx_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    items: Mapped[list["ActionItem"]] = relationship(cascade="all, delete-orphan", order_by="ActionItem.priority")


class ActionItem(Base):
    __tablename__ = "action_items"
    action_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("action_reports.report_id", ondelete="CASCADE"), index=True)
    policy_id: Mapped[int | None] = mapped_column(ForeignKey("policy_supports.policy_id"), nullable=True)
    action_type: Mapped[str] = mapped_column(String(50))     # 비용절감, 업종변경, 입지변경, 현장확인, 운영, 운영자금, 자격확인, 인허가
    action_content: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())   # 체크리스트 완료 표시(SB-08·09)


class SavedReport(Base):
    """saved_reports. [0.2] 로그인 대신 '이 브라우저'가 저장한다: device_key_hash = 브라우저 저장 키(X-Device-Key)의 SHA-256.
    user_id는 이전 버전(회원 저장) 호환용 — 새 저장은 NULL이고, 회원이 저장했던 행은 목록에 나오지 않는다."""
    __tablename__ = "saved_reports"
    # 지운 번호를 다시 쓰지 않게(다른 탭의 옛 목록에서 '삭제'가 새로 저장한 리포트를 지우지 않도록) — 새 DB부터 적용,
    # 기존 DB는 삭제·메모 요청에 리포트 번호를 함께 받아 확인한다
    __table_args__ = (UniqueConstraint("device_key_hash", "report_id", name="uq_saved_reports_device_report"),
                      {"sqlite_autoincrement": True})
    saved_report_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    device_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)   # [0.2]
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), nullable=True, index=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("action_reports.report_id", ondelete="CASCADE"))
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ════════════════════════ 6.3.5 데이터 수집 관리 ════════════════════════
class DataSource(Base):
    __tablename__ = "data_sources"
    source_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String(100), unique=True)
    source_type: Mapped[str] = mapped_column(String(50))          # API, CSV, MANUAL
    update_cycle: Mapped[str] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    dataset_code: Mapped[str | None] = mapped_column(String(30), nullable=True)   # [v2] OA-22173 등
    url: Mapped[str | None] = mapped_column(String(255), nullable=True)           # [v2]
    file_name: Mapped[str | None] = mapped_column(String(100), nullable=True)     # [v2] 적재 파일명


class DataIngestionLog(Base):
    __tablename__ = "data_ingestion_logs"
    log_id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.source_id"), index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    status: Mapped[str] = mapped_column(String(30))               # SUCCESS, FAIL
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_quarter: Mapped[int | None] = mapped_column(Integer, nullable=True)   # [v2] 적재된 최신 분기
