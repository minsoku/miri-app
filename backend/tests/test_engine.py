"""MIRI 엔진 v2 단위 테스트 (합성 데이터, 실데이터 불필요).  실행: python -m pytest -q tests"""
import sys, os, math, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
import pytest
from miri_engine.normalize import pct_rank, eb_rate, eb_prior_strength, local_weight
from miri_engine.config import risk_grade, RiskParams, GOAL_WEIGHTS, SuitabilityParams, LICENSED_INDUSTRIES
from miri_engine.risk import RiskModel
from miri_engine.breakeven import BreakEvenInput, calculate, card_fee_rate
from miri_engine import suitability as SU
from miri_engine import features as F

RNG = np.random.default_rng(7)


# ── 정규화 ───────────────────────────────────────────────────────────────
def test_pct_rank_midrank_ties_groups_nan():
    v = pd.Series([10, 20, 20, 40, np.nan, 5, 6])
    g = pd.Series(["a", "a", "a", "a", "a", "b", "b"])
    p = pct_rank(v, g)
    assert p.iloc[:4].tolist() == [12.5, 50.0, 50.0, 87.5]      # 동점은 평균 순위
    assert math.isnan(p.iloc[4])                                 # 결측 유지
    assert p.iloc[5:].tolist() == [25.0, 75.0]                   # 그룹 독립


def test_eb_rate_limits_and_monotone_shrinkage():
    prior, k = 0.03, 40.0
    assert eb_rate([0], [0], [prior], [k])[0] == pytest.approx(prior)          # 데이터 없음 → 사전값
    big = eb_rate([3000], [100000], [prior], [k])[0]
    assert big == pytest.approx(0.03, abs=1e-4)                                # 데이터 많음 → 자기 값
    small = eb_rate([1], [2], [prior], [k])[0]                                 # 원 폐업률 50%
    assert prior < small < 0.1                                                 # 강하게 당겨짐
    assert local_weight([40], [40])[0] == pytest.approx(0.5)


def test_eb_prior_strength_recovers_cv():
    true_cv, rows = 0.30, []
    for ind, mu in [("A", 0.03), ("B", 0.05), ("C", 0.02)]:
        for t in range(8):
            for a in range(60):
                p = max(1e-4, mu * (1 + true_cv * RNG.standard_normal()))
                e = int(RNG.integers(200, 2000))
                rows.append((ind, t, RNG.binomial(e, p), e))
    d = pd.DataFrame(rows, columns=["ind", "t", "y", "e"])
    k, cv = eb_prior_strength(d.y, d.e, d.ind, d.t, 1, 1e6)
    assert abs(cv - true_cv) < 0.05
    assert k["C"] > k["A"] > k["B"]      # 기저율 낮은 업종일수록 k(점포·분기) 큼: k ≈ (1-μ)/(CV²μ)


# ── 등급 ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("s,g", [(0, "낮음"), (39, "낮음"), (40, "보통"), (69, "보통"), (70, "높음"),
                                 (89, "높음"), (90, "고위험"), (100, "고위험")])
def test_grade_cutoffs(s, g):
    assert risk_grade(s) == g


# ── 위험 모델 ─────────────────────────────────────────────────────────────
def _synthetic_risk_df(n=6000):
    x_good = RNG.uniform(-1, 1, n)      # 진짜 위험 요인 (β=0.5)
    x_rev = RNG.uniform(-1, 1, n)       # 실제로는 위험을 '낮추는' 요인 (β=-0.4) → 부호 제약으로 0이어야 함
    off = np.full(n, np.log(0.027))
    E = RNG.integers(50, 500, n).astype(float)
    lam = np.exp(off + 0.1 + 0.5 * x_good - 0.4 * x_rev)
    y = RNG.poisson(lam * E)
    df = pd.DataFrame({"x_f_good": x_good, "x_f_rev": x_rev, "offset": off, "exp4": E, "fwd_exp4": E,
                       "fwd_clo4": y, "quarter": 20241})
    return df


def test_risk_model_sign_constraint_and_recovery():
    df = _synthetic_risk_df()
    m = RiskModel(factors=["f_good", "f_rev"], params=RiskParams(l2=0.0)).fit(df)
    assert m.beta["f_good"] == pytest.approx(0.5, abs=0.06)
    assert m.beta["f_rev"] == pytest.approx(0.0, abs=1e-6)       # 설명 불가능한 음(-)의 효과는 0으로
    pr = m.predict(df)
    assert pr["risk_score"].between(0, 100).all()
    order = np.argsort(df["x_f_good"].to_numpy())
    assert np.all(np.diff(pr["pred_q_rate"].to_numpy()[order]) >= -1e-12)   # 위험 요인↑ → 예측↑ (단조)


def test_risk_model_json_roundtrip():
    df = _synthetic_risk_df(2000)
    m = RiskModel(factors=["f_good", "f_rev"]).fit(df)
    m2 = RiskModel.from_json(m.to_json())
    pd.testing.assert_frame_equal(m.predict(df), m2.predict(df))


# ── 손익분기 ─────────────────────────────────────────────────────────────
def test_breakeven_worked_example():
    r = calculate(BreakEvenInput(monthly_rent=2_500_000, labor_cost=4_000_000, other_fixed=800_000,
                                 initial_investment=60_000_000),
                  category="외식업", market_sales_ps_m=22_000_000, market_ticket=38_000, market_tx_ps_day=19.4)
    assert r["monthly_fixed_cost"] == 8_300_000                         # 250+400+80+6000/60
    assert r["variable_cost_rate"] == pytest.approx(0.407 + 0.004)      # 연매출 3억 이하 → 0.40%
    assert r["required_monthly_sales"] == round(8_300_000 / (1 - 0.411))
    assert r["required_daily_customers"] == math.ceil(8_300_000 / 0.589 / 38_000 / 26)   # 올림
    assert r["cost_pressure"] == "여유" and r["payback_months"] == 11


def test_breakeven_card_fee_tier_iterates():
    r = calculate(BreakEvenInput(monthly_rent=10_000_000, labor_cost=20_000_000, cogs_rate=0.3, avg_ticket=10_000))
    annual = r["required_monthly_sales"] * 12
    assert r["variable_breakdown"]["카드수수료"] == card_fee_rate(annual)
    assert annual > 300_000_000 and r["variable_breakdown"]["카드수수료"] > 0.004


def test_breakeven_guards():
    with pytest.raises(ValueError):   # 변동비율 ≥ 100%
        calculate(BreakEvenInput(monthly_rent=1, labor_cost=1, cogs_rate=0.999, avg_ticket=1000))
    with pytest.raises(ValueError):   # 소매업은 기본 원가율 없음 → 입력 필요
        calculate(BreakEvenInput(monthly_rent=1, labor_cost=1, avg_ticket=1000), category="소매업")
    with pytest.raises(ValueError):   # 객단가 없음
        calculate(BreakEvenInput(monthly_rent=1, labor_cost=1, cogs_rate=0.3), category="외식업")


# ── 적합도 규칙 ───────────────────────────────────────────────────────────
def test_combine_renormalizes_missing_component():
    w = GOAL_WEIGHTS["기본"]
    assert SU.combine(80, 60, float("nan"), w) == pytest.approx((0.40 * 80 + 0.35 * 60) / 0.75)
    assert SU.combine(80, 60, 100, w) == pytest.approx(0.40 * 80 + 0.35 * 60 + 0.25 * 100)


def test_f_score_mapping():
    p = SuitabilityParams()
    assert SU.f_score(0.8, p) == 0 and SU.f_score(1.5, p) == 100
    assert SU.f_score(1.15, p) == pytest.approx(50)


def _area_rows(codes_names_cats):
    rows = []
    for i, (code, name, cat) in enumerate(codes_names_cats):
        rows.append({"area_id": "A", "industry_code": code, "industry_name": name, "category": cat,
                     "has_sales_data": True, "stores_avg4": 10.0, "sales_ps_m": 20_000_000.0,
                     "ticket": 30_000.0, "tx_ps_day": 20.0, "demand_D": 50.0 + i, "risk_score": 30,
                     "risk_grade": "낮음", "risk_pct_in_ind": 50, "pred_annual_rate": 0.08,
                     "confidence": "높음", "x_ind_base": 0.0, "eff_ind_base": 0.0})
    return pd.DataFrame(rows)


class _StubModel:
    factors = ["ind_base"]

    def top_factors(self, row, pred, n=3):
        return []


def test_license_filter_and_f_consistency():
    rows = _area_rows([("CS100001", "한식음식점", "외식업"), ("CS200028", "미용실", "서비스업")])
    u = SU.UserCondition(monthly_rent=2_000_000, labor_cost=3_000_000)
    tab, f_applied = SU.score_area(rows, _StubModel(), u)
    hair = tab[tab.industry_code == "CS200028"].iloc[0]
    assert not hair.eligible and "미용사" in hair.ineligible_reason       # 면허 없으면 제외
    assert f_applied                                                      # 후보(한식)만 남음 → 전부 원가율 있음
    u2 = SU.UserCondition(monthly_rent=2_000_000, labor_cost=3_000_000, licenses=("미용사(일반)",))
    tab2, f2 = SU.score_area(rows, _StubModel(), u2)
    assert tab2.eligible.all() and not f2                                 # 서비스업 원가율 없음 → F 전체 미적용


def test_location_exclusion_rule():
    rows = _area_rows([("CS100001", "한식음식점", "외식업"), ("CS100010", "커피-음료", "외식업")])
    rows.loc[1, "risk_pct_in_ind"] = 95
    res = SU.recommend(rows, "A", _StubModel(), SU.UserCondition())
    assert list(res["top"].industry_code) == ["CS100001"]
    assert list(res["caution_list"].industry_code) == ["CS100010"]


def test_invalid_user_input():
    with pytest.raises(ValueError):
        SU.UserCondition(budget=10, initial_investment=20).validate()
    with pytest.raises(ValueError):
        SU.UserCondition(business_goal="대박형").validate()


# ── 특징: 미래 정보 누수 없음 ───────────────────────────────────────────────
def _toy_panel(perturb_last=False):
    qs = [20231, 20232, 20233, 20234, 20241, 20242, 20243, 20244, 20251, 20252]
    st, sa = [], []
    for a in ["A1", "A2", "A3"]:
        for q in qs:
            clo = 5 + (int(a[1]) * 7 + q) % 4          # 결정적(실행마다 동일)
            if perturb_last and q == 20252:
                clo += 50
            st.append({"area_id": a, "area_name": a, "industry_code": "CS100001", "industry_name": "한식음식점",
                       "quarter": q, "stores": 100.0, "stores_nf": 90.0, "franchise": 10.0,
                       "openings": 6.0, "closures": float(clo)})
            sa.append({"area_id": a, "industry_code": "CS100001", "quarter": q, "sales_q": 3e9, "tx_q": 1e5})
    ar = pd.DataFrame([{"area_id": a, "quarter": q, "floating_pop": 1e7, "closed_months": 50.0,
                        "op_months": 100.0, "change_code": "LL", "rent": 1e5}
                       for a in ["A1", "A2", "A3"] for q in qs])
    return pd.DataFrame(st), pd.DataFrame(sa), ar


def test_no_lookahead_in_features():
    base = F.build_panel(*_toy_panel(False))
    pert = F.build_panel(*_toy_panel(True))
    cols = ["exp4", "clo4", "sales_growth", "store_growth", "sales_ps_m", "mu_ind", "mu_all"]
    t = base["quarter"] <= 20251       # 마지막 분기(20252)만 바꿨으므로 그 이전 특징은 동일해야 함
    pd.testing.assert_frame_equal(base.loc[t, cols], pert.loc[t, cols])
    assert not base.loc[t, "fwd_clo4"].equals(pert.loc[t, "fwd_clo4"])   # 정답(미래) 컬럼만 달라짐
    # 모델 입력(x_*)·EB 보정률·수요점수까지: 같은 학습 분기(≤20244)로 EB를 추정하면 20251 이전은 동일
    fit_q = list(base.loc[base["quarter"] <= 20244, "qidx"].unique())
    fb = F.add_model_features(base, F.estimate_eb(base, fit_q))
    fp = F.add_model_features(pert, F.estimate_eb(pert, fit_q))
    xcols = [c for c in fb.columns if c.startswith("x_")] + ["rate_eb", "entry_eb", "demand_D", "offset"]
    pd.testing.assert_frame_equal(fb.loc[t, xcols].reset_index(drop=True), fp.loc[t, xcols].reset_index(drop=True))


def test_revenue_scale_filter_needs_no_cogs():
    rows = _area_rows([("CS100001", "한식음식점", "외식업"), ("CS300033", "철물점", "소매업")])
    rows.loc[1, "sales_ps_m"] = 3_000_000                        # 월 300만원 < 고정비 500만원
    tab, _ = SU.score_area(rows, _StubModel(), SU.UserCondition(monthly_rent=2_000_000, labor_cost=3_000_000))
    r = tab.set_index("industry_code").loc["CS300033"]
    assert not r.eligible and "고정비" in r.ineligible_reason


def test_breakeven_bad_market_values_do_not_crash():
    with pytest.raises(ValueError):          # 객단가가 입력·실데이터 모두 NaN → 명확한 오류
        calculate(BreakEvenInput(monthly_rent=1_000_000, labor_cost=2_000_000, cogs_rate=0.3),
                  category="외식업", market_ticket=float("nan"))
    r = calculate(BreakEvenInput(monthly_rent=1_000_000, labor_cost=2_000_000, cogs_rate=0.3, avg_ticket=10_000),
                  category="외식업", market_sales_ps_m=0.0)            # 시장 매출 0 → 비교 항목만 생략
    assert "achievability_ratio" not in r
    with pytest.raises(ValueError):
        calculate(BreakEvenInput(monthly_rent=-1, labor_cost=0, cogs_rate=0.3, avg_ticket=10_000))


def test_recommend_unknown_area_and_negative_inputs():
    rows = _area_rows([("CS100001", "한식음식점", "외식업")])
    with pytest.raises(ValueError):
        SU.recommend(rows, "NOPE", _StubModel(), SU.UserCondition())
    with pytest.raises(ValueError):
        SU.UserCondition(other_fixed=-5).validate()


def test_fixed_cost_includes_interest_and_owner_salary():
    u = SU.UserCondition(monthly_rent=1_000_000, labor_cost=2_000_000, initial_investment=60_000_000,
                         loan_amount=12_000_000, loan_rate_annual=0.05, owner_salary=2_500_000)
    assert u.monthly_fixed_total() == pytest.approx(1_000_000 + 2_000_000 + 1_000_000 + 50_000 + 2_500_000)


def test_effect_display_rounds_half_up_from_unrounded_value():
    m = RiskModel(factors=["short_life"])
    m.beta0, m.beta = 0.0, {"short_life": 1.0}
    row = pd.Series({"x_short_life": float(np.log(1.0455))})
    pred = pd.Series({"eff_short_life": 0.0455})
    f = m.top_factors(row, pred)[0]
    assert f["effect_pct"] == 4.5 and f["effect_display"] == 5 and f["explanation"].endswith("+5%")


def test_level_calibration_matches_market_rate():
    df = _synthetic_risk_df(3000)
    df["quarter"] = np.where(np.arange(len(df)) % 2 == 0, 20241, 20242)
    m = RiskModel(factors=["f_good", "f_rev"]).fit(df)
    pr = m.predict(df)
    for q, g in df.assign(lam=pr["pred_q_rate"].values).groupby("quarter"):
        mu_all = float(np.exp(g["offset"].iloc[0]))
        assert (g["lam"] * g["exp4"]).sum() / g["exp4"].sum() == pytest.approx(mu_all, rel=1e-9)


def test_missing_level_const_raises_instead_of_partial_calibration():
    df = _synthetic_risk_df(1000)
    m = RiskModel(factors=["f_good", "f_rev"]).fit(df)
    other = df.head(10).assign(quarter=20251)
    with pytest.raises(ValueError):
        m.predict(other)


def test_interest_industry_gets_breakeven_even_if_filtered():
    rows = _area_rows([("CS100001", "한식음식점", "외식업"), ("CS100007", "치킨전문점", "외식업")])
    rows.loc[1, "sales_ps_m"] = 3_000_000                       # 고정비 미달 → 부적격
    u = SU.UserCondition(monthly_rent=2_000_000, labor_cost=3_000_000, interest_industries=("CS100007",))
    tab, f_applied = SU.score_area(rows, _StubModel(), u)
    chicken = tab.set_index("industry_code").loc["CS100007"]
    assert not chicken.eligible and chicken.achievability_ratio is not None and chicken.achievability_ratio < 1
    assert f_applied                                             # 후보(한식)만으로 F 적용 여부 판단


def test_breakeven_zero_fixed_cost_no_crash():
    """고정비 0원(임대료·인건비·투자비 모두 0) → 0으로 나누기 없이 손익분기 0원, 배율 생략, 여유."""
    r = calculate(BreakEvenInput(monthly_rent=0, labor_cost=0), category="외식업",
                  market_sales_ps_m=20_000_000, market_ticket=10_000, market_tx_ps_day=50)
    assert r["required_monthly_sales"] == 0 and r["required_daily_customers"] == 0
    assert r["achievability_ratio"] is None and r["cost_pressure"] == "여유"
    assert any("고정비가 0원" in w for w in r["warnings"])
