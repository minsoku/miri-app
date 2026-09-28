"""21차 검토 회귀 테스트: 저장 항목 삭제·메모는 리포트 번호를 확인(지운 번호 재사용 보호, 메모는 다시 저장하지 않음),
지원사업은 분석할 때 고른 사용자 유형 기준(저장해도 그대로), 붙여 쓴·두 낱말 주소 검색, '왜 없을까요' 문구."""
from conftest import device
from test_round5 import analyze, report

API = "/api/v1"


def test_delete_and_memo_check_report_id(client):
    h = device("r21saved")
    a = analyze(client, area_code="11350", budget=100_000_000, monthly_rent_limit=2_000_000, labor_cost=1_000_000,
                interests=["CS100001", "CS100002"])
    r1 = report(client, a["id"], "CS100001")
    r2 = report(client, a["id"], "CS100002")
    s1 = client.post(f"{API}/me/reports", json={"report_id": r1["id"]}, headers=h).json()
    s2 = client.post(f"{API}/me/reports", json={"report_id": r2["id"]}, headers=h).json()
    # 다른 리포트 번호로는 지우지 못한다
    assert client.delete(f"{API}/me/reports/{s1['saved_report_id']}", params={"report_id": r2["id"]}, headers=h).status_code == 404
    assert client.delete(f"{API}/me/reports/{s1['saved_report_id']}", params={"report_id": r1["id"]}, headers=h).status_code == 204
    # 지운 항목의 메모는 다시 저장하지 않고 404
    r = client.patch(f"{API}/me/reports/{s1['saved_report_id']}", json={"report_id": r1["id"], "memo": "x"}, headers=h)
    assert r.status_code == 404
    r = client.patch(f"{API}/me/reports/{s2['saved_report_id']}", json={"report_id": r2["id"], "memo": "현장 확인"}, headers=h)
    assert r.status_code == 200 and r.json()["memo"] == "현장 확인"
    items = client.get(f"{API}/me/reports", headers=h).json()["items"]
    assert [i["report_id"] for i in items] == [r2["id"]] and items[0]["memo"] == "현장 확인"


def test_saving_keeps_policies_of_chosen_user_type(client):
    """지원사업은 분석할 때 고른 사용자 유형으로 정해지고, 다른 브라우저가 저장하거나 다시 열어도 바뀌지 않는다(계정 유형이 없음)."""
    a = analyze(client, area_code="11200", budget=100_000_000, monthly_rent_limit=2_000_000, labor_cost=1_000_000,
                interests=["CS100001"], user_type="PRE_FOUNDER")
    rep = report(client, a["id"], "CS100001")
    assert rep["policies"] and all(p["target_user"] in ("전체", "예비창업자") for p in rep["policies"]), rep["policies"]
    h = device("r21owner")
    assert client.post(f"{API}/me/reports", json={"report_id": rep["id"]}, headers=h).status_code == 201
    after = client.get(f"{API}/reports/{rep['id']}", headers=h).json()["policies"]
    assert after == rep["policies"]


def test_compact_and_two_word_addresses(client):
    def top(q):
        res = client.get(f"{API}/places/search", params={"q": q}).json()
        return (res[0]["name"], res[0]["area_name"]) if res else None
    assert top("서울시강남구") == ("강남구", "강남구")
    assert top("관악구신림동")[1] == "관악구"
    assert top("강남역2번출구")[0] == "강남역"
    assert top("강남역쪽")[0] == "강남역"
    assert top("서울숲 공원")[1] == "성동구"
    assert top("여의도 공원")[1] == "영등포구"
    assert top("시청 광장")[1] == "중구"
    assert top("구로 테크노마트")[1] == "구로구"


def test_empty_reason_mentions_licence_scope(client):
    a = analyze(client, area_code="11500", budget=100_000_000, monthly_rent_limit=7_000_000, labor_cost=11_000_000,
                owner_salary=1_300_000, licenses=["의사"], cogs_rates={"서비스업": 0.78, "소매업": 0.74})
    if not a["top"] and a["empty_reason"] and "열 수 있는 업종" in a["empty_reason"]:
        assert "지금 조건으로 열 수 있는 업종" in a["empty_reason"] and "((" not in a["empty_reason"], a["empty_reason"]


def test_district_short_names_and_glued_landmarks(client):
    def top(q):
        res = client.get(f"{API}/places/search", params={"q": q}).json()
        return (res[0]["name"], res[0]["area_name"]) if res else None
    assert top("마포 연남동") == ("연남동", "마포구")
    assert top("강남 코엑스")[0] == "삼성역"
    assert top("영등포 여의도")[0] == "여의도역"
    assert top("종로 광장시장")[0] == "광장시장"
    assert top("강남 카페")[0] == "강남역"
    assert top("석촌호수")[0] == "석촌역"
    assert top("광화문광장")[0] == "광화문역"
    assert top("강남역2번출구앞")[0] == "강남역"
