"""14차 검토 회귀 테스트: '왜 없을까요'는 대형 점포 평균을 인용하지 않음, 한줄 결론이 권한 비슷한 업종은 체크리스트에도,
대형 점포 평균이면 대출 상품을 권하지 않음, 리포트·저장 목록에 창업 목표·대형 점포 표시, 주의 업종 순서·안내,
서울 밖 가까운 구 안내, 손익분기 구성 합."""
from app.services import narrative as N
from conftest import device
from test_round5 import analyze, be, report

API = "/api/v1"


def test_empty_reason_never_quotes_outlier_average(client):
    a = analyze(client, area_code="11230", budget=0, monthly_rent_limit=15_000_000, labor_cost=10_000_000,
                categories=["소매업"], cogs_rates={"소매업": 0.75})
    if a["empty_reason"] and "매출이 가장 높은" in a["empty_reason"]:
        assert "9,520만원" not in a["empty_reason"] and "7,141만원" not in a["empty_reason"], a["empty_reason"]


def test_checklist_keeps_cited_industry_without_ind_base_factor(client):
    a = analyze(client, area_code="11590", budget=30_000_000, monthly_rent_limit=500_000, labor_cost=0, interests=["CS300009"])
    rep = report(client, a["id"], "CS300009")
    if "비슷한 업종인" in rep["one_line_summary"]:
        assert any(c["action_type"] == "업종변경" for c in rep["checklist"]), rep["checklist"]


def test_no_loans_on_outlier_average(client):
    a = analyze(client, area_code="11140", budget=100_000_000, monthly_rent_limit=1_500_000, labor_cost=0,
                cogs_rates={"소매업": 0.72}, interests=["CS300017"])
    rep = report(client, a["id"], "CS300017")
    r = client.get(f"{API}/analyses/{a['id']}/risk/CS300017").json()
    if any("중간값의" in n for n in r["notices"]):
        assert all(p["support_type"] != "자금" for p in rep["policies"]), rep["policies"]
        assert rep["breakeven"] is None or rep["breakeven"]["sales_outlier"] is not None


def test_goal_on_report_and_saved_list(client):
    a = analyze(client, area_code="11350", budget=100_000_000, monthly_rent_limit=2_000_000, labor_cost=1_000_000,
                business_goal="저비용형", interests=["CS200025"])
    rep = report(client, a["id"], "CS200025")
    assert rep["recommendation"] and rep["recommendation"]["business_goal"] == "저비용형"
    h = device("r14goal")
    assert client.post(f"{API}/me/reports", json={"report_id": rep["id"]}, headers=h).status_code == 201
    items = client.get(f"{API}/me/reports", headers=h).json()["items"]
    assert items[0]["business_goal"] == "저비용형"


def test_caution_list_sorted_and_explained(client):
    a = analyze(client, area_code="11305", budget=100_000_000, monthly_rent_limit=1_000_000, labor_cost=0, categories=["외식업"])
    locs = [c["location_risk_pct"] for c in a["cautions"]]
    assert locs == sorted(locs, reverse=True), locs
    if 0 < len(a["top"]) < 5 and a["cautions"]:
        assert any("‘주의 업종’ 목록에서 따로" in n for n in a["notices"]), a["notices"]


def test_outside_seoul_notice_mentions_distance(client):
    r = client.get(f"{API}/areas/candidates", params={"lat": 37.694, "lng": 126.978, "radius_m": 500}).json()
    if r["candidates"] and r["candidates"][0]["distance_m"] > 500:
        assert "경계까지" in r["notice"] and "km" in r["notice"], r["notice"]


def test_breakeven_composition_sums_exactly(client):
    a = analyze(client, area_code="11440", budget=100_000_000, monthly_rent_limit=3_000_000, labor_cost=2_000_000,
                interests=["CS200026"])
    b = be(client, a["id"], industry_code="CS200026", monthly_rent=34_681_029_688, avg_ticket=9000, cogs_rate=0.30000001,
           owner_salary=0, other_variable_rate=0.1)
    c = b["composition"]
    assert c["fixed_ex_owner"] + c["variable"] + c["owner_salary"] == c["total"]


def test_loc90_summary_keeps_data_caveat():
    f = {"industry_name": "수산물판매", "risk_grade": "보통", "pred_annual_rate": 0.09, "location_risk_pct": 98,
         "sales_outlier": 5.6, "category": "소매업"}
    s = N.one_liner("강서구", f, None, {"achievability_ratio": 1.96, "cost_pressure": "여유", "composition": {}})
    assert "매우 높아요(98)" in s and "5.6배" in s, s
