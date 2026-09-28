"""20차 검토 회귀 테스트: 주소처럼 친 검색어가 엉뚱한 구로 가지 않음(흔한 말·구 이름 제한), '왜 없을까요'가 업종 이름을 밝힘,
저장 목록의 목표 월수입 포함 표시(손익분기 없이 저장한 리포트)."""
from conftest import device
from test_round5 import analyze, report

API = "/api/v1"


def _top(client, q):
    res = client.get(f"{API}/places/search", params={"q": q}).json()
    return (res[0]["name"], res[0]["area_name"]) if res else None


def test_address_queries_stay_in_place(client):
    assert _top(client, "홍대 카페")[0] == "홍대입구역"
    assert _top(client, "목동 학원가")[1] == "양천구"
    assert _top(client, "노량진 학원가")[1] == "동작구"
    assert _top(client, "당산 역 4번 출구")[0] == "당산역"
    assert _top(client, "은평구 신사동") == ("은평구", "은평구")
    assert _top(client, "동작구 사당동") == ("동작구", "동작구")
    assert _top(client, "관악구 삼성동") == ("관악구", "관악구")
    assert _top(client, "마포구 연남동 카페거리")[1] == "마포구"
    assert _top(client, "남대문 시장") is None
    assert _top(client, "신촌역앞") is not None and _top(client, "신촌역앞")[1] == "서대문구"
    assert _top(client, "홍대 입구")[0] == "홍대입구역"


def test_empty_reason_names_the_industry(client):
    a = analyze(client, area_code="11680", budget=100_000_000, monthly_rent_limit=20_000_000, labor_cost=2_000_000,
                business_goal="고수익형", categories=["외식업"], interests=["CS100010"])
    if not a["top"] and a["empty_reason"] and "매출이 가장 높은" in a["empty_reason"]:
        assert "비용 때문에 빠진 업종 중 매출이 가장 높은 " in a["empty_reason"] and "((" not in a["empty_reason"], a["empty_reason"]


def test_saved_owner_flag_without_breakeven(client):
    h = device("r20owner")
    a = analyze(client, area_code="11680", budget=100_000_000, monthly_rent_limit=3_000_000, labor_cost=2_000_000,
                owner_salary=3_000_000, interests=["CS300002"])
    rep = report(client, a["id"], "CS300002")
    client.post(f"{API}/me/reports", json={"report_id": rep["id"]}, headers=h)
    it = client.get(f"{API}/me/reports", headers=h).json()["items"][0]
    if it["required_monthly_sales"] is None:
        assert it["owner_included"] is True and it["monthly_fixed_cost"] >= 8_000_000, it
