"""7차 검토 회귀 테스트: 억 단위 한도 문장, 작은 임대료의 '임대료만으로는 어려워요' 판정, 리포트 재사용,
결제 배수(반올림 전 손님 수), 고위험 한줄 결론, 변동비 초과 오류 값, 바꾼 항목(overridden), 예산=투자비 문구,
동 이름 검색, 적합도 소수 둘째 자리."""
import re
from miri_engine.breakeven import BreakEvenInput, calculate
from miri_engine.config import DEFAULT_COGS_RATE
from app.services import narrative as N
from test_round5 import analyze, be, report

API = "/api/v1"


def test_won_floor_below_never_shows_now_in_eok():
    """'1.1억원 이하로 낮추기 (지금 1.1억원, 월 0원)' 방지: 억 단위 두 자리 값 전부(부동소수 곱셈 오차 포함)."""
    for c in range(100, 1000):
        v = c * 1_000_000                                  # 1.00억 ~ 9.99억
        for limit, now in ((v + 100_000, v + 300_000), (v + 400_000, v + 490_000), (v - 1, v + 200_000)):
            lim = N.won_floor_below(limit, now)
            assert lim <= limit, (c, limit, lim)
            assert N.won(lim) != N.won(now), (c, N.won(lim), N.won(now))
            assert N.won_value(now) - lim > 0, (c, lim, now)
    for x in (110_000_000, 229_000_000, 1_000_000_000):
        assert isinstance(N.won_value(x), int) and N.won_value(x) == x


def test_eok_range_checklist_gap_is_positive(client):
    a = analyze(client, area_code="11590", budget=5_000_000_000, monthly_rent_limit=110_300_000, labor_cost=0,
                interests=["CS300008"], cogs_rates={"소매업": 0.619})
    rep = report(client, a["id"], "CS300008")
    text = rep["one_line_summary"] + " | " + " | ".join(x["content"] for x in rep["checklist"])
    assert "월 0원" not in text, text
    for m in re.finditer(r"([\d,.]+(?:만|억)원) 이하로 낮추기 \(지금 ([\d,.]+(?:만|억)원)", text):
        assert m.group(1) != m.group(2), text


def test_small_rent_gap_is_not_called_impossible(client):
    """임대료 60만원·4만원만 줄이면 되는데 '임대료만 줄여서는 어려워요'라고 하면 안 된다(하한은 내 임대료의 절반까지)."""
    a = analyze(client, area_code="11440", budget=100_000_000, monthly_rent_limit=600_000, labor_cost=4_510_000,
                interests=["CS100010"])
    rep = report(client, a["id"], "CS100010")
    items = [x["content"] for x in rep["checklist"]]
    gap_items = [t for t in items if "낮추기" in t and "줄여야 함" in t]
    if gap_items:
        gap = re.search(r"월 ([\d,.]+만원) 줄여야 함", gap_items[0])
        if gap and N.won_value(float(gap.group(1).replace(",", "").replace("만원", "")) * 1e4) <= 300_000:
            assert not any("임대료만 줄여서는 어려워요" in t for t in items), items


def test_report_is_reused_for_same_inputs(client):
    a = analyze(client, area_code="11680", budget=80_000_000, monthly_rent_limit=3_000_000, labor_cost=2_500_000,
                interests=["CS100010"])
    r1 = report(client, a["id"], "CS100010")
    r2 = report(client, a["id"], "CS100010")
    assert r1["id"] == r2["id"]                            # 위험도 화면에서 '대응 액션 보기'를 다시 눌러도 같은 리포트
    b = be(client, a["id"], industry_code="CS100010", owner_salary=3_000_000)
    r3 = report(client, a["id"], "CS100010", b["id"])
    r4 = report(client, a["id"], "CS100010", b["id"])
    assert r3["id"] == r4["id"] and r3["id"] != r1["id"]


def test_overridden_lists_only_changed_fields(client):
    a = analyze(client, area_code="11680", budget=80_000_000, monthly_rent_limit=3_000_000, labor_cost=2_500_000)
    assert be(client, a["id"], industry_code="CS100010")["inputs"]["overridden"] == []
    b = be(client, a["id"], industry_code="CS100010", owner_salary=3_000_000, avg_ticket=9000)
    assert b["inputs"]["overridden"] == ["owner_salary", "avg_ticket"]
    saved = client.get(f"{API}/analyses/{a['id']}/breakeven/{b['id']}").json()
    assert saved["inputs"]["overridden"] == ["owner_salary", "avg_ticket"]


def test_variable_rate_error_reports_default_cogs(client):
    a = analyze(client, area_code="11680", budget=80_000_000, monthly_rent_limit=3_000_000, labor_cost=2_500_000)
    r = client.post(f"{API}/analyses/{a['id']}/breakeven", json={"industry_code": "CS100010", "other_variable_rate": 0.6})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VARIABLE_RATE_TOO_HIGH"
    vals = {f["field"]: f.get("value") for f in r.json()["error"]["fields"]}
    assert vals["cogs_rate"] == DEFAULT_COGS_RATE["외식업"] and vals["other_variable_rate"] == 0.6


def test_customers_vs_market_uses_unrounded_customers():
    """객단가가 큰 업종: 하루 0.04건이 1건으로 올림돼 '지역 평균(0.7건)보다 많아요'가 나오면 안 된다."""
    inp = BreakEvenInput(monthly_rent=1_000_000, labor_cost=0, cogs_rate=0.3, avg_ticket=1_000_000)
    r = calculate(inp, market_sales_ps_m=10_000_000, market_ticket=1_000_000, market_tx_ps_day=0.7)
    assert r["required_daily_customers"] == 1
    assert r["customers_vs_market"] < 1.2, r["customers_vs_market"]


def test_high_risk_one_liner_mentions_good_facts():
    focus = {"industry_name": "일식음식점", "risk_grade": "높음", "pred_annual_rate": 0.12, "location_risk_pct": 30}
    be_ = {"achievability_ratio": 2.23, "composition": {"owner_salary": 0}}
    s = N.one_liner("강남구", focus, None, be_)
    assert "다만" in s and "2.23배" in s and "검토해 볼 만해요" in s, s
    s2 = N.one_liner("강남구", {**focus, "risk_grade": "고위험"}, None, be_)
    assert "창업 재검토" in s2 and "운영자금" in s2, s2
    s3 = N.one_liner("강남구", {**focus, "location_risk_pct": 80}, None, be_)
    assert "다만" not in s3 and "체크리스트" in s3, s3


def test_budget_fully_invested_wording(client):
    a = analyze(client, area_code="11680", budget=80_000_000, monthly_rent_limit=3_000_000, labor_cost=2_500_000,
                initial_investment=80_000_000, interests=["CS100010"])
    items = [x["content"] for x in report(client, a["id"], "CS100010")["checklist"]]
    assert not any("0.0개월" in t for t in items), items
    assert any("운영자금이 없어요" in t for t in items), items


def test_dong_names_find_stations(client):
    for q, area in (("봉천동", "관악구"), ("상도동", "동작구"), ("망원동", "마포구")):
        r = client.get(f"{API}/places/search", params={"q": q}).json()
        assert r and r[0]["area_name"] == area, (q, r)
    r = client.get(f"{API}/places/search", params={"q": "대학동"}).json()
    assert all(p["area_name"] != "종로구" for p in r), r                 # 별칭 '대학로'(혜화역)로 엉뚱하게 가지 않게


def test_suitability_has_two_decimals(client):
    a = analyze(client, area_code="11680", budget=80_000_000, monthly_rent_limit=3_000_000, labor_cost=2_500_000)
    for t in a["top"]:
        assert t["suitability"] is not None and round(t["suitability"], 2) == t["suitability"]
