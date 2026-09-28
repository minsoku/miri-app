"""9차 검토 회귀 테스트: 한줄 결론·체크리스트의 운영자금 기준 일치, 현금 고정비 계산(반올림 찌꺼기), 보정 설명,
입력값 부동소수·같은 값 재입력(changed), 추천 TOP 최소 적합도, 자격 없는 업종 한줄 결론, 목표 월수입 부족액 일치,
오타 검색, 적은 구 합계 추세 숨김, '1개월분도 안 됨'."""
import re
from app.services import narrative as N
from test_round5 import analyze, be, report

API = "/api/v1"


def test_one_liner_uses_checklist_runway_months(client):
    a = analyze(client, area_code="11110", budget=50_000_000, monthly_rent_limit=3_000_000, labor_cost=2_500_000,
                interests=["CS100001"])
    rep = report(client, a["id"], "CS100001")
    text = " | ".join(c["content"] for c in rep["checklist"])
    m = re.search(r"초기 (\d+)개월 운영자금", text)
    if m and "운영비" in text:                          # 체크리스트가 운영비 부족을 말하면 한줄 결론도 같은 기준으로 알린다
        assert f"운영자금({m.group(1)}개월분)" in rep["one_line_summary"] or "운영자금이 없어요" in rep["one_line_summary"], \
            (rep["one_line_summary"], text)


def test_zero_running_cost_has_no_runway_crumbs(client):
    for budget in (50_000_000, 10_000_000):
        a = analyze(client, area_code="11680", budget=budget, monthly_rent_limit=0, labor_cost=0,
                    initial_investment=10_000_000, interests=["CS100010"])
        rep = report(client, a["id"], "CS100010")
        text = rep["one_line_summary"] + " | " + " | ".join(c["content"] for c in rep["checklist"])
        assert not re.search(r"\(\d원\)|\d원:", text), text                       # '(4원)' 같은 찌꺼기 금액 없음
        assert "운영자금이 없어요" not in text, text                               # 나가는 돈이 없으면 운영자금 경고도 없다


def test_smoothing_note_does_not_claim_few_stores(client):
    a = analyze(client, area_code="11710", budget=100_000_000, monthly_rent_limit=3_000_000, labor_cost=2_000_000,
                interests=["CS200006"], licenses=["의사"])
    r = client.get(f"{API}/analyses/{a['id']}/risk/CS200006").json()
    for f in r["factors"]:
        assert "점포가 적어" not in f["detail"], f


def test_changed_ignores_equal_values_and_float_noise(client):
    a = analyze(client, area_code="11680", budget=80_000_000, monthly_rent_limit=3_000_000, labor_cost=2_500_000,
                interests=["CS100010"])
    b0 = be(client, a["id"], industry_code="CS100010")
    b = be(client, a["id"], industry_code="CS100010", monthly_rent=3_000_000, cogs_rate=0.40700000000000003,
           avg_ticket=round(b0["avg_ticket_used"]))
    assert b["inputs"]["changed"] == [] and set(b["inputs"]["overridden"]) == {"monthly_rent", "cogs_rate", "avg_ticket"}
    r0 = report(client, a["id"], "CS100010", b0["id"])
    r1 = report(client, a["id"], "CS100010", b["id"])
    # 객단가를 직접 넣으면(출처 'user') 경고 문구가 달라질 수 있어 다른 입력으로 본다 — 원가율·임대료만 같은 값이면 같은 리포트
    b2 = be(client, a["id"], industry_code="CS100010", monthly_rent=3_000_000, cogs_rate=0.40700000000000003)
    assert report(client, a["id"], "CS100010", b2["id"])["id"] == r0["id"]
    b3 = be(client, a["id"], industry_code="CS100010", owner_salary=2_500_000, avg_ticket=6000)
    assert b3["inputs"]["changed"] == ["owner_salary", "avg_ticket"]
    rep = report(client, a["id"], "CS100010", b3["id"])
    assert rep["breakeven"]["changed"] == {"owner_salary": 2_500_000, "avg_ticket": 6000}
    assert r1["breakeven"]["changed"] == {}


def test_top_skips_very_low_scores(client):
    a = analyze(client, area_code="11440", budget=80_000_000, monthly_rent_limit=2_000_000, labor_cost=1_500_000,
                interests=["CS200028"], categories=["서비스업"], user_type="CONSULTANT")
    import math
    assert all(math.floor(t["suitability"] + 0.5) >= 20 for t in a["top"]), [(t["industry_name"], t["suitability"]) for t in a["top"]]
    if len(a["top"]) < 5:
        assert any("적합도가 20점 미만" in n for n in a["notices"]) or any("추천 업종이" in n for n in a["notices"]), a["notices"]


def test_missing_license_leads_one_liner(client):
    a = analyze(client, area_code="11440", budget=80_000_000, monthly_rent_limit=2_000_000, labor_cost=1_500_000,
                interests=["CS200028"], categories=["서비스업"])
    rep = report(client, a["id"], "CS200028")
    assert rep["one_line_summary"].startswith("마포구 미용실은 미용사(일반) 자격이 있어야 열 수 있어요"), rep["one_line_summary"]
    a2 = analyze(client, area_code="11440", budget=80_000_000, monthly_rent_limit=2_000_000, labor_cost=1_500_000,
                 interests=["CS200028"], categories=["서비스업"], licenses=["미용사(일반)"])
    assert "자격이 있어야" not in report(client, a2["id"], "CS200028")["one_line_summary"]


def test_owner_shortfall_matches_checklist_gap(client):
    a = analyze(client, area_code="11200", budget=50_000_000, monthly_rent_limit=2_000_000, labor_cost=1_500_000,
                business_goal="고수익형", initial_investment=30_000_000, other_fixed=500_000, owner_salary=3_000_000,
                loan_amount=30_000_000, loan_rate_annual=0.055, cogs_rates={"소매업": 0.65}, interests=["CS300011"])
    rep = report(client, a["id"], "CS300011")
    one = rep["one_line_summary"]
    m1 = re.search(r"목표 월수입 [\d,.]+만원보다 월 ([\d,.]+만원) 적어요", one)
    gap = next((re.search(r"월 ([\d,.]+만원) 줄여야 함", c["content"]) for c in rep["checklist"] if "줄여야 함" in c["content"]), None)
    if m1 and gap:
        assert m1.group(1) == gap.group(1), (one, gap.group(0))


def test_typo_last_char_search(client):
    r = client.get(f"{API}/places/search", params={"q": "강남억"}).json()
    assert r and r[0]["name"] == "강남역", r
    assert client.get(f"{API}/places/search", params={"q": "없는지명쿠쿠"}).json() == []


def test_seoul_trend_hidden_for_few_districts(client, db):
    from app.services.engine import get_state
    from app.services.risk_svc import industry_n
    st = get_state(db)
    few = [c for c in st.industries if not st.industry_rows(c).empty and industry_n(st, c) < 5]
    if not few:
        return
    code = few[0]
    area = str(st.industry_rows(code).iloc[0]["area_id"])
    a = analyze(client, area_code=area, budget=100_000_000, monthly_rent_limit=1_000_000, labor_cost=0, interests=[code])
    r = client.get(f"{API}/analyses/{a['id']}/risk/{code}").json()
    assert not any(x["key"] == "ind_sales_growth" for x in r["reference"]), r["reference"]


def test_tiny_reserve_says_less_than_a_month(client):
    a = analyze(client, area_code="11110", budget=30_000_000, monthly_rent_limit=3_000_000, labor_cost=1_000_000,
                initial_investment=29_900_000, interests=["CS100001"])
    rep = report(client, a["id"], "CS100001")
    text = rep["one_line_summary"] + " | " + " | ".join(c["content"] for c in rep["checklist"])
    assert "0.0개월" not in text and "1개월분도 안" in text, text


def test_budget_caveat_months_wording():
    f = {"reserve_months": 9.1, "investment": 0, "runway_months": 12}
    assert N.budget_caveat(f) == "예산으로는 운영비가 9.1개월분뿐이라 운영자금(12개월분)부터 마련하세요."
    assert N.budget_caveat({**f, "runway_months": 6}) is None
    assert N.budget_caveat({**f, "reserve_months": 0.4, "investment": 10}) == "예산에서 투자비를 빼면 운영비가 1개월분도 안 돼 운영자금(12개월분)부터 마련하세요."
