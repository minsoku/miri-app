"""15차 검토 회귀 테스트: 저장 목록 카드의 추천 상태(순위·관심·주의)와 주의 업종 적합도, 관심 업종이어도 입지 위험 상위 10%면
주의 업종으로 표시·대출 제외·한줄 결론에 입지 위험, 서울 밖 1km 미만 거리는 m, 작은 요인 효과 '약간'."""
from app.services import narrative as N
from conftest import device
from test_round5 import analyze, report

API = "/api/v1"


def test_saved_cards_show_recommendation_status(client):
    h = device("r15status")
    a = analyze(client, area_code="11680", budget=100_000_000, monthly_rent_limit=1_000_000, labor_cost=1_000_000,
                business_goal="안정형")
    made = []
    if a["top"]:
        made.append(("TOP", report(client, a["id"], a["top"][0]["industry_code"])))
    if a["cautions"]:
        made.append(("CAUTION", report(client, a["id"], a["cautions"][0]["industry_code"])))
    for _, rep in made:
        client.post(f"{API}/me/reports", json={"report_id": rep["id"]}, headers=h)
    items = {i["report_id"]: i for i in client.get(f"{API}/me/reports", headers=h).json()["items"]}
    for kind, rep in made:
        it = items[rep["id"]]
        assert it["item_type"] == kind, it
        if kind == "TOP":
            assert it["rank"] == 1 and not it["caution"]
        else:
            assert it["caution"] and it["suitability"] is not None, it


def test_interest_in_caution_zone_is_labelled_and_not_lent(client):
    a = analyze(client, area_code="11680", budget=100_000_000, monthly_rent_limit=1_000_000, labor_cost=1_000_000,
                interests=["CS100005"])
    it = next(i for i in a["interests"] if i["industry_code"] == "CS100005")
    if it["location_risk_pct"] >= 90:
        rep = report(client, a["id"], "CS100005")
        assert rep["recommendation"]["caution"] is True
        assert all(p["support_type"] != "자금" for p in rep["policies"]), rep["policies"]
        assert f"({it['location_risk_pct']})" in rep["one_line_summary"], rep["one_line_summary"]


def test_high_risk_summary_mentions_caution_zone():
    f = {"industry_name": "외국어학원", "risk_grade": "높음", "pred_annual_rate": 0.12, "location_risk_pct": 98}
    s = N.one_liner("양천구", f, None, {"achievability_ratio": 1.02, "cost_pressure": "빠듯", "composition": {}})
    assert "입지 위험이 매우 높아요(98)" in s, s


def test_outside_seoul_distance_in_metres(client):
    r = client.get(f"{API}/areas/candidates", params={"lat": 37.4690, "lng": 127.1389, "radius_m": 300}).json()
    c = r["candidates"][0]
    if c["distance_m"] > 300 and c["distance_m"] < 1000:
        assert f"{c['distance_m']}m" in r["notice"], r["notice"]


def test_small_ind_base_effect_says_slightly():
    f = {"factor_code": "ind_base", "effect_pct": 1.0, "effect_display": 1, "label": "업종 자체 폐업률 높음"}
    assert N.factor_label(f) == "업종 자체 폐업률 약간 높은 편"
    f = {"factor_code": "ind_base", "effect_pct": 55.7, "effect_display": 56, "label": "업종 자체 폐업률 높음"}
    assert N.factor_label(f) == "업종 자체 폐업률 높음"
