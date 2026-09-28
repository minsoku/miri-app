"""19차 검토 회귀 테스트: 분석 결과에 SB-02 후보 구(다시 분석해도 같은 대안), 광장동 검색, 주소처럼 친 검색어,
자격 없는 업종 체크리스트의 폐업 이력 항목, 적자 확정 업종에 원가율 칩 없음, 목표 월수입 포함 인근 구 문구,
저장 목록 월 고정비, 본문 형식 오류 문구."""
from app.services import narrative as N
from app.services.areas import address_tokens
from conftest import device
from test_round5 import analyze, report

API = "/api/v1"


def test_analysis_returns_candidate_districts(client):
    a = analyze(client, area_code="11620", budget=100_000_000, monthly_rent_limit=3_000_000, labor_cost=2_000_000,
                interests=["CS100001"], candidate_area_codes=["11620", "11590", "11650", "11590"])
    assert a["area"]["candidate_area_codes"] == ["11590", "11650"], a["area"]
    got = client.get(f"{API}/analyses/{a['id']}").json()
    assert got["area"]["candidate_area_codes"] == ["11590", "11650"]


def test_gwangjang_dong_goes_to_gwangjin(client):
    res = client.get(f"{API}/places/search", params={"q": "광장동"}).json()
    assert res and res[0]["area_name"] == "광진구", res[:2]
    assert all(p["name"] != "광장시장" for p in client.get(f"{API}/places/search", params={"q": "먹자골목"}).json())


def test_address_like_queries(client):
    assert address_tokens("서울특별시 관악구") == ["관악구"]
    assert address_tokens("강남역 2번 출구") == ["강남역"]
    assert address_tokens("신림역사거리") == ["신림역"]
    for q, area in (("서울 강남구", "강남구"), ("관악구 신림동", "관악구"), ("신림역 사거리", "관악구"),
                    ("마포구 망원동", "마포구"), ("강남역 2번출구", "강남구")):
        res = client.get(f"{API}/places/search", params={"q": q}).json()
        assert res and res[0]["area_name"] == area, (q, res[:2])


def test_unlicensed_checklist_keeps_closure_history_item(client):
    a = analyze(client, area_code="11110", budget=300_000_000, monthly_rent_limit=5_000_000, labor_cost=5_000_000,
                interests=["CS200006"])
    rep = report(client, a["id"], "CS200006")
    r = client.get(f"{API}/analyses/{a['id']}/risk/CS200006").json()
    ups = [f["factor_code"] for f in r["factors"] if f["effect_pct"] > 0][:2]
    assert all(c["action_type"] != "입지변경" for c in rep["checklist"])
    if "area_hist" in ups:
        assert any("폐업 원인" in c["content"] for c in rep["checklist"]), rep["checklist"]


def test_no_cogs_chip_when_sales_below_fixed(client):
    a = analyze(client, area_code="11440", budget=100_000_000, monthly_rent_limit=30_000_000, labor_cost=5_000_000,
                interests=["CS200028"])
    it = next(i for i in a["interests"] if i["industry_code"] == "CS200028")
    if it["sales_ps_m"] is not None and it["sales_ps_m"] < 35_000_000:
        assert "손익분기 미확인(원가율 미입력)" not in it["chips"], it


def test_owner_in_area_alternative_wording():
    f = {"industry_name": "노래방", "risk_grade": "보통", "pred_annual_rate": 0.07, "location_risk_pct": 95}
    area = {"area_name": "중구", "location_risk_pct": 30, "pred_annual_rate": 0.06, "location_grade": "낮음",
            "cogs_known": False, "owner_included": True}
    s = N.one_liner("종로구", f, None, None, area)
    assert "평균 매출이 지금 월 고정비(목표 월수입 포함)보다 큰 중구" in s, s


def test_saved_list_shows_fixed_cost(client):
    h = device("r19fixed")
    a = analyze(client, area_code="11350", budget=100_000_000, monthly_rent_limit=2_000_000, labor_cost=1_000_000,
                interests=["CS100001"])
    rep = report(client, a["id"], "CS100001")
    client.post(f"{API}/me/reports", json={"report_id": rep["id"]}, headers=h)
    it = client.get(f"{API}/me/reports", headers=h).json()["items"][0]
    assert it["monthly_fixed_cost"] and it["monthly_fixed_cost"] >= 3_000_000, it


def test_non_object_body_message(client):
    r = client.post(f"{API}/analyses", json=[1, 2])
    assert r.status_code == 422 and r.json()["error"]["message"] == "요청 내용(JSON 객체)을 확인해 주세요", r.text
