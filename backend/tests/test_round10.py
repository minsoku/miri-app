"""10차 검토 회귀 테스트: 적합도 하한은 화면 정수 기준·관심 업종 설명, 직접 넣은 값(entered) vs 바꾼 값(changed),
운영자금 개월 수 내림, 12개월 기준의 요인 결정, 인근 구 감당 가능 여부, 오타 대체 검색 제한, 매출 비교 지역 부족,
매출 순위 표현, 빈 결과 문구, 같은 말 되풀이 없는 체크리스트."""
import math
import re
from app.services import narrative as N
from test_round5 import analyze, be, report

API = "/api/v1"


def test_low_score_cut_uses_displayed_integer(client):
    a = analyze(client, area_code="11530", budget=100_000_000, monthly_rent_limit=3_000_000, labor_cost=2_500_000,
                categories=["서비스업"], interests=["CS200037"])
    for t in a["top"]:
        assert math.floor(t["suitability"] + 0.5) >= 20
    for it in a["interests"]:
        if it["eligible"] and it["suitability"] is not None and it["location_risk_pct"] < 90:
            shown = math.floor(it["suitability"] + 0.5)
            if shown < 20:
                assert it["score_note"] and "20점 미만" in it["score_note"], it
            else:
                assert not (it["score_note"] or "").count("20점 미만"), it
    assert "n_low_score" in a


def test_required_input_is_entered_not_changed(client):
    a = analyze(client, area_code="11260", budget=60_000_000, monthly_rent_limit=1_500_000, labor_cost=1_000_000,
                interests=["CS200001"])
    b = be(client, a["id"], industry_code="CS200001", cogs_rate=0.3)
    assert b["inputs"]["required"] == ["cogs_rate"] and b["inputs"]["changed"] == []
    rep = report(client, a["id"], "CS200001", b["id"])
    assert rep["breakeven"]["changed"] == {} and rep["breakeven"]["entered"] == {"cogs_rate": 0.3}


def test_runway_months_are_floored(client):
    a = analyze(client, area_code="11110", budget=75_780_000, monthly_rent_limit=3_000_000, labor_cost=2_500_000,
                initial_investment=10_000_000, interests=["CS100001"])
    rep = report(client, a["id"], "CS100001")
    text = rep["one_line_summary"] + " | " + " | ".join(c["content"] for c in rep["checklist"])
    assert "12.0개월분" not in text and "6.0개월분뿐" not in text, text
    assert N.months_floor(11.96) == "11.9" and N.months_floor(6.0) == "6"


def test_twelve_months_follow_the_factor_not_the_item(client):
    a = analyze(client, area_code="11350", budget=64_000_000, monthly_rent_limit=4_000_000, labor_cost=4_000_000,
                cogs_rates={"소매업": 0.7}, interests=["CS300002"])
    rep = report(client, a["id"], "CS300002")
    r = client.get(f"{API}/analyses/{a['id']}/risk/CS300002").json()
    ind = next((f for f in r["factors"] if f["factor_code"] == "ind_base"), None)
    text = " | ".join(c["content"] for c in rep["checklist"])
    if ind and ind["direction"] == "up" and ind["effect_pct"] >= 10:
        assert "초기 6개월 운영자금" not in text, text


def test_alternatives_say_if_costs_are_covered(client):
    a = analyze(client, area_code="11440", budget=80_000_000, monthly_rent_limit=3_000_000, labor_cost=2_500_000,
                interests=["CS100010"])
    r = client.get(f"{API}/analyses/{a['id']}/risk/CS100010").json()
    assert r["alternatives"], r
    for x in r["alternatives"]:
        assert "affordable" in x and "sales_ps_m" in x
    rep = report(client, a["id"], "CS100010")
    if "도 비교해 보세요" in rep["one_line_summary"] and "같은 업종이면" in rep["one_line_summary"]:
        assert "평균 매출로 지금 비용을 감당할 만한" in rep["one_line_summary"]


def test_typo_fallback_only_for_yeok_like_endings(client):
    assert client.get(f"{API}/places/search", params={"q": "강남억"}).json()[0]["name"] == "강남역"
    for q in ("강남대", "을지로5"):
        assert client.get(f"{API}/places/search", params={"q": q}).json() == [], q
    # '서울시'는 오타 대체로 '서울역'이 되지 않는다('서울시청' 별칭으로 시청역은 찾을 수 있음)
    assert "서울역" not in [p["name"] for p in client.get(f"{API}/places/search", params={"q": "서울시"}).json()]


def test_industry_with_few_sales_areas_is_not_ranked(client):
    a = analyze(client, area_code="11680", budget=100_000_000, monthly_rent_limit=2_000_000, labor_cost=1_500_000,
                categories=["서비스업"], interests=["CS200036"])
    assert all(t["industry_code"] != "CS200036" for t in a["top"])
    it = next((i for i in a["interests"] if i["industry_code"] == "CS200036"), None)
    if it is not None:
        assert not it["eligible"] and "매출을 비교할 구가 적음" in (it["ineligible_reason"] or ""), it


def test_reason_short_uses_rank_share():
    base = {"D": 70, "risk_grade": "보통", "unit": "구"}
    assert "높은 편" in N.reason_short({**base, "sales_rank": 3, "sales_n": 25})
    assert "중간" in N.reason_short({**base, "sales_rank": 8, "sales_n": 25})
    assert "중간" in N.reason_short({**base, "sales_rank": 8, "sales_n": 24})
    assert "낮은 편" in N.reason_short({**base, "sales_rank": 20, "sales_n": 25})
    s = N.reason_short({**base, "sales_rank": 1, "sales_n": 2})       # 비교 대상이 적으면 평가('높은 편') 없이 순위만
    assert "2개 구 중 1위예요." in s and "높은 편" not in s


def test_empty_reason_with_caution_and_low_scores(client):
    a = analyze(client, area_code="11380", budget=100_000_000, monthly_rent_limit=5_000_000, labor_cost=5_000_000,
                business_goal="안정형", categories=["서비스업"], interests=["CS200001"])
    if not a["top"] and a["cautions"] and a.get("n_low_score"):
        assert "나머지" in a["empty_reason"] and "모두 20점 미만" not in a["empty_reason"], a["empty_reason"]


def test_no_repeated_twelve_month_advice(client):
    a = analyze(client, area_code="11440", budget=60_000_000, monthly_rent_limit=3_000_000, labor_cost=2_500_000,
                initial_investment=60_000_000, interests=["CS100007"])
    items = [c["content"] for c in report(client, a["id"], "CS100007")["checklist"]]
    assert sum("12개월" in t for t in items) <= 1, items
