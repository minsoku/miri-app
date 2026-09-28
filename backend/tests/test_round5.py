"""5차 검토 회귀 테스트: 달성배율 표시·배지 일치, 목표 월수입 문구, 대출 권유 조건, 고위험+매출<고정비 결론,
객단가 대체(서울 평균), 결제 배수 경고, 표시값 차이, 투자비>예산, 0원 비용 이름, 업종 추세 표본, 입력 검증, 비교 API."""
import math
import pytest
from fastapi.testclient import TestClient
from miri_engine.breakeven import BreakEvenInput, calculate, ratio_floor
from miri_engine.config import DEFAULT_COGS_RATE, LICENSED_INDUSTRIES
from app.services import narrative as N
from app.services import engine as E
from app.services.engine import get_state
from conftest import BASE_ANALYSIS

API = "/api/v1"
Z = {"other_fixed": 0, "initial_investment": 0, "loan_amount": 0, "owner_salary": 0, "loan_rate_annual": 0.0,
     "business_goal": "기본", "licenses": [], "categories": [], "interests": []}


def analyze(client, **kw):
    r = client.post(f"{API}/analyses", json={**Z, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def be(client, aid, **kw):
    r = client.post(f"{API}/analyses/{aid}/breakeven", json=kw)
    assert r.status_code == 200, r.text
    return r.json()


def report(client, aid, code, be_id=None):
    r = client.post(f"{API}/analyses/{aid}/reports", json={"industry_code": code, "break_even_id": be_id})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def st(db):
    return get_state(db)


# ── 달성배율: 표시값(소수 둘째 자리 내림)과 배지·문장이 같은 값을 본다 ─────────────
@pytest.mark.parametrize("sales, level, shown", [(0.99996, "위험", 0.99), (1.0, "빠듯", 1.0), (1.14999, "빠듯", 1.14),
                                                  (1.29999, "보통", 1.29), (1.3, "여유", 1.3)])
def test_ratio_floor_and_band_agree(sales, level, shown):
    inp = BreakEvenInput(monthly_rent=1_000_000, labor_cost=0, cogs_rate=0.0, avg_ticket=10_000)
    r0 = calculate(inp, market_sales_ps_m=1e8)                     # 손익분기 매출(카드수수료 반영)을 먼저 구해
    bep = r0["monthly_fixed_cost"] / (1 - r0["variable_cost_rate"])
    r = calculate(inp, market_sales_ps_m=bep * sales)
    assert r["achievability_ratio"] == shown and r["cost_pressure"] == level, r
    assert (r["profit_at_market_avg"] < 0) == (r["achievability_ratio"] < 1) or r["profit_at_market_avg"] == 0
    assert ratio_floor(0.3 * 3) == 0.9 and ratio_floor(1.0) == 1.0          # 부동소수 오차(0.8999…)로 한 칸 내려가지 않게


def test_one_liner_never_encourages_below_one(client, st):
    """평균 매출이 손익분기에 아주 조금 못 미치면(0.99…배) '1.00배예요. 진입을 검토해 볼 만해요'가 나오면 안 된다."""
    t = st.table
    row = t[(t["category"] == "외식업") & t["sales_ps_m"].notna() & (t["risk_pct_in_ind"] < 90)]\
        .sort_values(["area_id", "industry_code"]).iloc[0]
    a = analyze(client, area_code=row["area_id"], budget=500_000_000, monthly_rent_limit=0, labor_cost=0,
                interests=[row["industry_code"]])
    cm = 1 - DEFAULT_COGS_RATE["외식업"] - 0.005                      # 대략의 공헌이익률 → 실제 값은 첫 계산에서
    b0 = be(client, a["id"], industry_code=row["industry_code"], monthly_rent=int(row["sales_ps_m"] * cm))
    cm = b0["contribution_margin_rate"]
    rent = math.ceil(row["sales_ps_m"] * cm / 0.99995)                  # 평균 매출 ≈ 손익분기의 0.99995배
    b = be(client, a["id"], industry_code=row["industry_code"], monthly_rent=rent)
    assert b["achievability_ratio"] < 1 and b["cost_pressure"] == "위험", b
    rep = report(client, a["id"], row["industry_code"], b["id"])
    assert "진입을 검토해 볼 만해요" not in rep["one_line_summary"] and "1.00배" not in rep["one_line_summary"]


# ── 비어 있는 추천: 분야 제한 안의 자격 업종만, 목표 월수입이면 그렇다고 ─────────────
def test_empty_reason_license_hint_respects_categories_and_owner(client, st):
    a = analyze(client, area_code="11680", budget=500_000_000, monthly_rent_limit=30_000_000, labor_cost=5_000_000,
                categories=["외식업"])
    assert not a["top"] and a["empty_reason"]
    other = [n for c, n in ((c, st.industries[c]["name"]) for c in LICENSED_INDUSTRIES) if st.industries[c]["category"] != "외식업"]
    assert not any(f"자격이 필요한 {n}" in a["empty_reason"] for n in other), a["empty_reason"]
    a = analyze(client, area_code="11680", budget=500_000_000, monthly_rent_limit=3_000_000, labor_cost=2_500_000,
                owner_salary=30_000_000, categories=["외식업"])
    assert "목표 월수입을 포함한 월 고정비" in a["empty_reason"] and "목표 월수입을 낮춰" in a["empty_reason"], a["empty_reason"]


def test_owner_included_reason_and_no_duplicate_pill(client):
    a = analyze(client, area_code="11470", monthly_rent_limit=3_000_000, labor_cost=3_000_000, initial_investment=50_000_000,
                owner_salary=4_000_000, business_goal="저비용형", budget=100_000_000,
                interests=["CS100010", "CS100008", "CS100001", "CS100007", "CS100005"])
    for it in a["interests"]:
        if it["ineligible_reason"] and "손익분기" in it["ineligible_reason"] or "월 고정비" in (it["ineligible_reason"] or ""):
            assert "(목표 월수입 포함)" in it["ineligible_reason"], it
            assert not any(c.startswith("평균 매출로 손익분기") for c in it["cautions"]), it["cautions"]


# ── 리포트 ─────────────────────────────────────────────────────────────
def test_no_loans_without_breakeven(client, st):
    """원가율이 없어 손익분기를 못 냈으면(판단 불가) 대출·보증 상품을 권하지 않는다."""
    t = st.table
    row = t[(t["category"] == "소매업") & t["sales_ps_m"].notna() & (t["risk_grade"] != "고위험")
            & ~t["industry_code"].isin(list(LICENSED_INDUSTRIES))].sort_values(["area_id", "industry_code"]).iloc[0]
    a = analyze(client, area_code=row["area_id"], user_type="OWNER", budget=300_000_000, monthly_rent_limit=1_000_000,
                labor_cost=0, interests=[row["industry_code"]])
    rep = report(client, a["id"], row["industry_code"])
    assert rep["breakeven"] is None
    assert not any(p["support_type"] == "자금" for p in rep["policies"]), rep["policies"]


def test_high_risk_without_breakeven_mentions_sales_below_fixed(client, st):
    t = st.table
    rows = t[(t["category"] != "외식업") & t["risk_grade"].isin(["높음", "고위험"]) & t["sales_ps_m"].notna()
             & (t["stores_avg4"] >= 1) & ~t["industry_code"].isin(list(LICENSED_INDUSTRIES))].sort_values(["area_id", "industry_code"])
    row = rows.iloc[0]
    rent = int(row["sales_ps_m"] * 3)
    a = analyze(client, area_code=row["area_id"], budget=500_000_000, monthly_rent_limit=rent, labor_cost=0,
                interests=[row["industry_code"]])
    rep = report(client, a["id"], row["industry_code"])
    s = rep["one_line_summary"]
    assert "보다 적어요" in s and "비용 조건부터" in s, s
    assert "도 비교해 보세요" not in s, s          # 매출 < 고정비 이유를 두고 비용을 감당 못 하는 다른 지역을 권하지 않는다


def test_gap_equals_difference_of_shown_amounts(client):
    a = analyze(client, area_code="11620", categories=["외식업"], monthly_rent_limit=0, labor_cost=0, other_fixed=300_000,
                owner_salary=4_000_000, loan_amount=30_000_000, loan_rate_annual=0.05, initial_investment=30_000_000,
                budget=500_000_000, interests=["CS100007"])
    b = be(client, a["id"], industry_code="CS100007")
    rep = report(client, a["id"], "CS100007", b["id"])
    item = next((c["content"] for c in rep["checklist"] if "줄여야 함" in c["content"]), None)
    if item:
        import re
        nums = [int(x.replace(",", "")) for x in re.findall(r"([\d,]+)만원", item)]
        target, now, gap = nums[:3]
        assert now - target == gap, item
    # 운영자금 항목은 같은 취지의 '운영자금은 최소 12개월분' 항목이 있으면 생략된다 → 둘 중 하나는 꼭 있어야
    runway = next((c["content"] for c in rep["checklist"] if c["action_type"] == "운영자금"), None)
    assert runway or any("최소 12개월분" in c["content"] for c in rep["checklist"]), rep["checklist"]
    if runway:
        assert "임대료" not in runway and "인건비" not in runway, runway    # 임대료·인건비 0원이면 그 이름을 쓰지 않는다
    from types import SimpleNamespace
    from app.services.report_svc import _cash_items
    req = SimpleNamespace(loan_amount=0, loan_rate_annual=0.0, monthly_rent_limit=0, labor_cost=0, other_fixed=0)
    names = _cash_items(b["inputs"], req)
    assert "임대료" not in names and "인건비" not in names and "기타 고정비" in names, names


def test_investment_over_budget_is_named(client, st):
    t = st.table
    row = t[(t["category"] == "소매업") & t["sales_ps_m"].notna() & t["risk_grade"].isin(["낮음", "보통"])
            & (t["risk_pct_in_ind"] < 70) & ~t["industry_code"].isin(list(LICENSED_INDUSTRIES))
            & (t["sales_ps_m"] > 20_000_000)].sort_values(["area_id", "industry_code"]).iloc[0]
    a = analyze(client, area_code=row["area_id"], budget=50_000_000, monthly_rent_limit=1_500_000, labor_cost=1_000_000,
                initial_investment=20_000_000, interests=[row["industry_code"]])
    b = be(client, a["id"], industry_code=row["industry_code"], cogs_rate=0.3, initial_investment=80_000_000)
    rep = report(client, a["id"], row["industry_code"], b["id"])
    text = rep["one_line_summary"] + " ".join(c["content"] for c in rep["checklist"])
    assert "0.0개월분" not in text and "예산보다 3,000만원 많" in text, text


# ── 손익분기: 객단가 대체와 결제 배수 경고 ───────────────────────────────────
def test_seoul_ticket_fallback_when_area_has_no_data(client, st):
    def no_local_ticket(a, c):          # 이 지역에 점포가 없거나, 있어도 카드 매출이 적어 객단가를 믿을 수 없는 경우
        r = st.row(a, c)
        return (r is None or not (r["ticket"] == r["ticket"])) and not st.area_rows(a).empty
    code, area = next((c, a) for c, v in sorted(st.industries.items()) if v["category"] == "외식업" and v.get("seoul_ticket")
                      for a in sorted(st.areas) if no_local_ticket(a, c))
    a = analyze(client, area_code=area, budget=100_000_000, monthly_rent_limit=2_000_000, labor_cost=2_000_000, interests=[code])
    b = be(client, a["id"], industry_code=code)
    assert b["inputs"]["ticket_source"] == "seoul" and b["avg_ticket_used"] == st.industries[code]["seoul_ticket"]
    assert any("서울 같은 업종 평균" in w for w in b["warnings"]), b["warnings"]
    rep = report(client, a["id"], code)
    assert rep["breakeven"] is not None                                     # 위험도 화면에서 바로 만든 리포트도 손익분기 포함


def test_customers_warning_for_low_user_ticket(client, st):
    t = st.table
    row = t[(t["category"] == "외식업") & t["ticket"].notna() & (t["ticket"] > 15_000) & t["tx_ps_day"].notna()]\
        .sort_values(["area_id", "industry_code"]).iloc[0]
    a = analyze(client, area_code=row["area_id"], budget=500_000_000, monthly_rent_limit=1_000_000, labor_cost=0,
                interests=[row["industry_code"]])
    b = be(client, a["id"], industry_code=row["industry_code"], avg_ticket=int(row["ticket"] / 4))
    if b["customers_vs_market"] is not None and b["customers_vs_market"] >= 1.2:
        assert any("하루" in w and "배예요" in w for w in b["warnings"]), b["warnings"]


# ── 위험도: 업종 추세의 표본 수 = 실제로 합산한 지역 수 ───────────────────────────
def test_industry_trend_note_counts_contributing_districts(client, st):
    a = analyze(client, area_code="11680", budget=100_000_000, monthly_rent_limit=1_000_000, labor_cost=0)
    for code in sorted(st.industries)[:40]:
        rows = st.industry_rows(code)
        if rows.empty or st.row("11680", code) is None:
            continue
        r = client.get(f"{API}/analyses/{a['id']}/risk/{code}").json()
        ref = next((x for x in r["reference"] if x["key"] == "ind_sales_growth"), None)
        if ref and ref["note"]:
            n = int(ref["note"].split("서울 ")[1].split("개")[0])
            assert n == int(rows["sales_growth"].notna().sum()), (code, ref)


# ── 입력 검증·오류 형식 ───────────────────────────────────────────────────
def test_input_validation_round5(client):
    base = {**Z, "area_code": "11440", "budget": 100_000_000, "monthly_rent_limit": 1_000_000, "labor_cost": 0}
    r = client.post(f"{API}/analyses", json={**base, "licenses": ["없는 자격"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNKNOWN_LICENSE"
    r = client.post(f"{API}/analyses", json={**base, "budget": True})
    assert r.status_code == 422 and "숫자" in r.json()["error"]["message"]
    r = client.post(f"{API}/analyses", json={**base, "categories": ["외식업"] * 5})
    assert r.status_code == 422
    r = client.post(f"{API}/analyses", json={**base, "categories": ["외식업", "외식업"]})
    assert r.status_code == 201 and r.json()["conditions"]["categories"] == ["외식업"]
    r = client.post(f"{API}/analyses/x/breakeven", json={"industry_code": "CS100001", "avg_ticket": True})
    assert r.status_code == 422


def test_unexpected_error_is_json(client, monkeypatch):
    from app.main import app
    from app.services import areas as area_svc

    def boom(*a, **k):
        raise RuntimeError("테스트용 예외")
    monkeypatch.setattr(area_svc, "compare", boom)
    with TestClient(app, raise_server_exceptions=False) as c2:
        r = c2.post(f"{API}/areas/compare", json={"area_codes": ["11680", "11650"]})
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR"


def test_compare_shape_matches_candidates(client):
    r = client.post(f"{API}/areas/compare", json={"area_codes": ["11680", "11650", "11680"], "industry_code": "CS100010"})
    assert r.status_code == 200
    d = r.json()
    assert [x["area_code"] for x in d["areas"]] == ["11680", "11650"]
    for x in d["areas"]:
        assert "change_indicator" not in x["metrics"] and "metrics_quarter" not in x["metrics"]
        assert set(x["summary"]) == {"avg_risk_score", "high_risk_share"}
        assert x["industry"] is None or {"risk_score", "sales_ps_m", "location_risk_pct"} <= set(x["industry"])
    r = client.post(f"{API}/areas/compare", json={"area_codes": ["11680"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NEED_MORE_AREAS"


# ── 여러 워커: 다른 워커가 모델을 바꾸면 알아서 다시 올린다 ─────────────────────
def test_state_reloads_when_active_model_changes(db, monkeypatch):
    from app import models as M
    st0 = get_state(db)
    mv = db.query(M.ScoringModelVersion).filter(M.ScoringModelVersion.is_active).one()
    old = mv.trained_at
    try:
        import datetime as dt
        mv.trained_at = old + dt.timedelta(seconds=7)
        db.commit()
        monkeypatch.setattr(E, "_checked_at", 0.0)
        st1 = get_state(db)
        assert st1 is not st0 and st1.trained_at != st0.trained_at
    finally:
        mv.trained_at = old
        db.commit()
        monkeypatch.setattr(E, "_checked_at", 0.0)
        assert get_state(db).trained_at == st0.trained_at


# ── 분야별 원가율(계산로직 §5.3 '사용자가 원가율을 입력하면 F 적용') ─────────────────────
def test_cogs_rates_enable_cost_fit_and_breakeven_default(client, st):
    base = dict(area_code="11440", budget=200_000_000, monthly_rent_limit=2_000_000, labor_cost=2_000_000, business_goal="저비용형")
    a0 = analyze(client, **base)
    a1 = analyze(client, **base, cogs_rates={"서비스업": 0.15, "소매업": 0.7})
    assert a1["conditions"]["cogs_rates"] == {"서비스업": 0.15, "소매업": 0.7}
    assert a1["f_applied"] and not a0["f_applied"]                       # 모든 분야 원가율을 알면 비용 적합도로 순위
    code = next(t["industry_code"] for t in a1["top"] + a1["interests"] if t["category"] == "소매업") \
        if any(t["category"] == "소매업" for t in a1["top"]) else None
    t = st.table
    code = code or t[(t["area_id"] == "11440") & (t["category"] == "소매업") & t["sales_ps_m"].notna()].iloc[0]["industry_code"]
    b = be(client, a1["id"], industry_code=code)                           # 원가율을 안 보내도 조건 입력값(70%)으로 계산
    assert b["inputs"]["cogs_source"] == "analysis" and b["variable_breakdown"]["원가율"] == 0.7
    r = client.post(f"{API}/analyses/{a0['id']}/breakeven", json={"industry_code": code})
    assert r.status_code == 422 and r.json()["error"]["code"] == "COGS_REQUIRED"   # 조건 입력이 없으면 전처럼 필요
    bad = client.post(f"{API}/analyses", json={**Z, **base, "cogs_rates": {"소매업": 1.2}})
    assert bad.status_code == 422 and "원가율" in bad.json()["error"]["message"]
    bad = client.post(f"{API}/analyses", json={**Z, **base, "cogs_rates": {"기타": 0.2}})
    assert bad.status_code == 422 and "분야별 원가율" in bad.json()["error"]["message"]


# ── 6차 검토 회귀 ──────────────────────────────────────────────────────
def test_cogs_cap_and_variable_rate_exclusion(client):
    base = dict(area_code="11440", budget=200_000_000, monthly_rent_limit=2_000_000, labor_cost=2_000_000, categories=["외식업"])
    r = client.post(f"{API}/analyses", json={**Z, **base, "cogs_rates": {"외식업": 0.98}})
    assert r.status_code == 422 and "95%" in r.json()["error"]["message"]
    from miri_engine.suitability import UserCondition, recommend
    from app.services.engine import get_state as gs
    from app.db import SessionLocal
    with SessionLocal() as db:
        st = gs(db)
        uc = UserCondition(monthly_rent=2_000_000, labor_cost=2_000_000, categories=("외식업",), cogs_by_category={"외식업": 0.99})
        rec = recommend(st.table, "11440", st.model, uc)
    assert rec["top"].empty                                                  # 원가+수수료 ≥ 100%는 추천에서 빠진다
    assert (rec["table"]["ineligible_reason"] == "원가·수수료가 매출의 100% 이상").any()


def test_near_breakeven_limits_never_equal_now(client, st):
    t = st.table
    row = t[(t["category"] == "소매업") & t["sales_ps_m"].notna() & (t["sales_ps_m"] > 10_000_000)
            & ~t["industry_code"].isin(list(LICENSED_INDUSTRIES))].sort_values(["area_id", "industry_code"]).iloc[0]
    a = analyze(client, area_code=row["area_id"], budget=500_000_000, monthly_rent_limit=0, labor_cost=0, owner_salary=3_000_000,
                interests=[row["industry_code"]])
    b0 = be(client, a["id"], industry_code=row["industry_code"], cogs_rate=0.3, monthly_rent=0)
    cm = b0["contribution_margin_rate"]
    rent = int(row["sales_ps_m"] * cm - 3_000_000) + 3_000             # 평균 매출이 손익분기에 아주 조금 못 미치게
    b = be(client, a["id"], industry_code=row["industry_code"], cogs_rate=0.3, monthly_rent=rent)
    assert b["achievability_ratio"] < 1, b
    rep = report(client, a["id"], row["industry_code"], b["id"])
    text = rep["one_line_summary"] + " | " + " | ".join(c["content"] for c in rep["checklist"])
    assert "월 0원" not in text, text
    import re
    for m in re.finditer(r"([\d,.]+(?:만|억)원) 이하로 낮추기 \(지금 ([\d,.]+(?:만|억)원)", text):
        assert m.group(1) != m.group(2), text
    if "목표 월수입" in rep["one_line_summary"] and "남아" in rep["one_line_summary"]:
        assert "적어요" in rep["one_line_summary"], rep["one_line_summary"]


def test_area_alternative_uses_reflected_breakeven_costs(client, st):
    """손익분기에서 원가율을 바꿔 반영했으면, 권하는 인근 구도 그 원가율로 버틸 수 있어야 한다."""
    from app.services.report_svc import _can_cover
    t = st.table
    rows = t[(t["category"] == "외식업") & t["sales_ps_m"].notna() & (t["risk_pct_in_ind"] >= 40) & (t["risk_pct_in_ind"] < 90)]
    checked = 0
    for _, row in rows.sort_values(["area_id", "industry_code"]).head(40).iterrows():
        if checked >= 3:
            break
        a = analyze(client, area_code=row["area_id"], budget=500_000_000, monthly_rent_limit=1_500_000, labor_cost=1_500_000,
                    interests=[row["industry_code"]])
        b = be(client, a["id"], industry_code=row["industry_code"], cogs_rate=0.5, other_variable_rate=0.05)
        rep = report(client, a["id"], row["industry_code"], b["id"])
        s = rep["one_line_summary"]
        for code, info in st.areas.items():
            if f"더 낮은 {info['name']}(" in s or f"감당할 만한 {info['name']}(" in s:
                r2 = st.row(code, row["industry_code"])
                assert _can_cover(r2, b["monthly_fixed_cost"], {"외식업": 0.5}, 0.05), (s, code)
                checked += 1
    assert checked >= 1, "인근 구를 권하는 한줄 결론이 하나도 없으면 이 검사는 아무것도 확인하지 못한다"


def test_search_suffix_fallback(client):
    r = client.get(f"{API}/places/search", params={"q": "망원동"}).json()
    assert r and any("망원" in p["name"] for p in r), r


def test_short_life_is_labeled_district_wide(client, st):
    a = analyze(client, area_code="11680", budget=100_000_000, monthly_rent_limit=1_000_000, labor_cost=0)
    r = client.get(f"{API}/analyses/{a['id']}/risk/CS100010").json()
    for f in r["factors"]:
        if f["factor_code"] == "short_life":
            assert "지역 전체" in f["label"] and "전 업종" in f["detail"], f
    ref = [x for x in r["reference"] if x["key"] == "closed_months"]
    assert not ref or "전 업종" in ref[0]["label"]
