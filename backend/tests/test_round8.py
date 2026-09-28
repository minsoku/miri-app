"""8차 검토 회귀 테스트: 손익분기 화면 경로의 리포트 재사용(저장본 우선), 입력 필수 항목(required), 체크리스트 완료 표시,
저장 목록 요약, 동·역 이름 검색, 고위험 한줄 결론의 예산 단서·대안, 운영자금 기준(6·12개월) 일관성, 지역 폐업 이력 설명."""
import re
from app.services import narrative as N
from conftest import device
from test_round5 import analyze, be, report

API = "/api/v1"
BASE = dict(area_code="11680", budget=80_000_000, monthly_rent_limit=3_000_000, labor_cost=2_500_000)


def test_breakeven_path_reuses_report_and_prefers_saved(client):
    h = device("r8reuse")
    r = client.post(f"{API}/analyses", json={**BASE, "other_fixed": 0, "initial_investment": 0, "loan_amount": 0, "owner_salary": 0,
                                             "loan_rate_annual": 0.0, "business_goal": "기본", "licenses": [], "categories": [],
                                             "interests": ["CS100010"]}, headers=h)
    aid = r.json()["id"]
    r1 = client.post(f"{API}/analyses/{aid}/reports", json={"industry_code": "CS100010"}, headers=h).json()
    assert client.post(f"{API}/me/reports", json={"report_id": r1["id"]}, headers=h).status_code == 201
    # 손익분기 화면을 열 때마다 계산이 새로 저장돼도(다른 id) 입력값이 같으면 저장해 둔 그 리포트
    for _ in range(2):
        b = client.post(f"{API}/analyses/{aid}/breakeven", json={"industry_code": "CS100010"}, headers=h).json()
        rr = client.post(f"{API}/analyses/{aid}/reports", json={"industry_code": "CS100010", "break_even_id": b["id"]}, headers=h).json()
        assert rr["id"] == r1["id"] and rr["saved_report_id"], rr
    # 분석 조건과 같은 값을 직접 넣어도 같은 입력
    b = client.post(f"{API}/analyses/{aid}/breakeven", json={"industry_code": "CS100010", "monthly_rent": 3_000_000}, headers=h).json()
    assert b["inputs"]["overridden"] == ["monthly_rent"]
    rr = client.post(f"{API}/analyses/{aid}/reports", json={"industry_code": "CS100010", "break_even_id": b["id"]}, headers=h).json()
    assert rr["id"] == r1["id"]
    items = client.get(f"{API}/me/reports", headers=h).json()["items"]
    assert len(items) == 1


def test_required_lists_only_missing_defaults(client):
    a = analyze(client, **BASE, interests=["CS300002", "CS100010"])
    b = be(client, a["id"], industry_code="CS300002", cogs_rate=0.7)          # 소매업: 기본 원가율 없음 → 필수
    assert b["inputs"]["required"] == ["cogs_rate"]
    b = be(client, a["id"], industry_code="CS100010", cogs_rate=0.3, avg_ticket=9000)   # 외식업 평균·지역 객단가 있음
    assert b["inputs"]["required"] == [] and b["inputs"]["overridden"] == ["cogs_rate", "avg_ticket"]
    a2 = analyze(client, **BASE, cogs_rates={"소매업": 0.7}, interests=["CS300002"])
    b = be(client, a2["id"], industry_code="CS300002", cogs_rate=0.6)        # 조건에서 넣은 원가율이 기본값
    assert b["inputs"]["required"] == []


def test_checklist_done_is_saved(client):
    a = analyze(client, **BASE, interests=["CS100010"])
    rep = report(client, a["id"], "CS100010")
    first = rep["checklist"][0]
    assert first["done"] is False and first["action_id"] > 0
    r = client.patch(f"{API}/reports/{rep['id']}/items/{first['action_id']}", json={"done": True})
    assert r.status_code == 200 and r.json() == {"action_id": first["action_id"], "done": True}
    again = client.get(f"{API}/reports/{rep['id']}").json()
    assert next(c for c in again["checklist"] if c["action_id"] == first["action_id"])["done"] is True
    assert client.patch(f"{API}/reports/{rep['id']}/items/999999", json={"done": True}).status_code == 404
    assert client.patch(f"{API}/reports/{rep['id']}/items/{first['action_id']}", json={"done": "yes"}).status_code == 422
    # 다른 리포트의 항목 id로는 바꿀 수 없다
    other = report(client, analyze(client, **BASE, interests=["CS100001"])["id"], "CS100001")
    r = client.patch(f"{API}/reports/{other['id']}/items/{first['action_id']}", json={"done": False})
    assert r.status_code == 404 and r.json()["error"]["code"] == "ACTION_NOT_FOUND"


def test_report_items_open_to_anyone_with_link(client):
    """로그인이 없으므로 체크리스트 완료 표시는 리포트 링크를 아는 사람 누구나(브라우저 저장 키와 무관)."""
    h1, h2 = device("r8own1"), device("r8own2")
    body = {**BASE, "other_fixed": 0, "initial_investment": 0, "loan_amount": 0, "owner_salary": 0, "loan_rate_annual": 0.0,
            "business_goal": "기본", "licenses": [], "categories": [], "interests": ["CS100010"]}
    aid = client.post(f"{API}/analyses", json=body, headers=h1).json()["id"]
    rep = client.post(f"{API}/analyses/{aid}/reports", json={"industry_code": "CS100010"}, headers=h1).json()
    act = rep["checklist"][0]["action_id"]
    assert client.patch(f"{API}/reports/{rep['id']}/items/{act}", json={"done": True}, headers=h2).json()["done"] is True
    assert client.patch(f"{API}/reports/{rep['id']}/items/{act}", json={"done": False}).json()["done"] is False
    assert client.get(f"{API}/reports/{rep['id']}", headers=h1).json()["checklist"][0]["done"] is False


def test_saved_list_shows_breakeven_summary_and_progress(client):
    h = device("r8list")
    body = {**BASE, "other_fixed": 0, "initial_investment": 0, "loan_amount": 0, "owner_salary": 0, "loan_rate_annual": 0.0,
            "business_goal": "기본", "licenses": [], "categories": [], "interests": ["CS100010"]}
    aid = client.post(f"{API}/analyses", json=body, headers=h).json()["id"]
    b = client.post(f"{API}/analyses/{aid}/breakeven", json={"industry_code": "CS100010", "owner_salary": 3_000_000}, headers=h).json()
    rep = client.post(f"{API}/analyses/{aid}/reports", json={"industry_code": "CS100010", "break_even_id": b["id"]}, headers=h).json()
    client.post(f"{API}/me/reports", json={"report_id": rep["id"]}, headers=h)
    client.patch(f"{API}/reports/{rep['id']}/items/{rep['checklist'][0]['action_id']}", json={"done": True}, headers=h)
    it = client.get(f"{API}/me/reports", headers=h).json()["items"][0]
    assert it["required_monthly_sales"] == b["required_monthly_sales"] and it["owner_included"] is True
    assert it["achievability_ratio"] == b["achievability_ratio"]
    assert it["checklist_total"] == len(rep["checklist"]) and it["checklist_done"] == 1


def test_dong_and_station_suffix_search(client):
    for q, name in (("상암동", "디지털미디어시티역"), ("신촌역", "신촌 연세로"), ("홍대역", "홍대입구역"), ("반포동", "고속터미널역")):
        r = client.get(f"{API}/places/search", params={"q": q}).json()
        assert r and r[0]["name"] == name, (q, r)
    assert client.get(f"{API}/places/search", params={"q": "대학동"}).json() == []


def test_high_risk_good_one_liner_keeps_budget_caveat_and_alternative():
    focus = {"industry_name": "여관", "risk_grade": "높음", "pred_annual_rate": 0.12, "location_risk_pct": 30,
             "reserve_months": 0.0, "investment": 30_000_000}
    be_ = {"achievability_ratio": 2.71, "composition": {"owner_salary": 0}}
    s = N.one_liner("중구", focus, None, be_)
    assert "검토해 볼 만해요" not in s and "모두 써서 운영자금이 없어요" in s and "2.71배예요" in s, s
    s = N.one_liner("중구", {**focus, "reserve_months": None, "over_budget": 30_000_000}, None, be_)
    assert "검토해 볼 만해요" not in s and "예산보다 3,000만원 많아" in s, s
    area_alt = {"area_name": "서초구", "location_risk_pct": 10, "pred_annual_rate": 0.142}
    s = N.one_liner("강남구", {**focus, "risk_grade": "고위험", "reserve_months": None}, None, be_, area_alt)
    assert "창업 재검토" in s and "서초구" in s, s
    # 보통 위험의 운영비 0개월도 같은 문구
    s = N.one_liner("중구", {**focus, "risk_grade": "보통", "industry_name": "화장품"}, None, {**be_, "cost_pressure": "여유"})
    assert "0.0개월" not in s and "모두 써서" in s, s


def test_runway_months_are_consistent(client):
    from app.services.engine import get_state
    from app.db import SessionLocal
    with SessionLocal() as db:
        state = get_state(db)
    t = state.table
    rows = t[(t["category"] == "외식업") & t["sales_ps_m"].notna()].sort_values(["area_id", "industry_code"]).head(40)
    seen12 = 0
    for _, row in rows.iterrows():
        a = analyze(client, area_code=row["area_id"], budget=60_000_000, monthly_rent_limit=2_000_000, labor_cost=2_000_000,
                    initial_investment=40_000_000, interests=[row["industry_code"]])
        text = [c["content"] for c in report(client, a["id"], row["industry_code"])["checklist"]]
        joined = " | ".join(text)
        if "12개월" in joined:                                         # '최소 12개월분' 또는 '초기 12개월 운영자금'
            seen12 += 1
            assert "초기 6개월 운영자금" not in joined, text           # 6개월·12개월 기준이 섞이지 않게
    assert seen12 >= 1


def test_zero_investment_is_not_told_to_cut_investment(client):
    from app.services.engine import get_state
    from app.db import SessionLocal
    with SessionLocal() as db:
        state = get_state(db)
    t = state.table
    rows = t[(t["category"] == "외식업") & t["sales_ps_m"].notna()].sort_values(["area_id", "industry_code"]).head(30)
    for _, row in rows.iterrows():
        a = analyze(client, area_code=row["area_id"], budget=80_000_000, monthly_rent_limit=3_000_000, labor_cost=2_500_000,
                    interests=[row["industry_code"]])
        text = " | ".join(c["content"] for c in report(client, a["id"], row["industry_code"])["checklist"])
        assert "초기 투자비를 줄이고" not in text, text


def test_area_history_detail_matches_label(client):
    a = analyze(client, **BASE)
    for code in ("CS100010", "CS100001", "CS300002", "CS200028"):
        r = client.get(f"{API}/analyses/{a['id']}/risk/{code}").json()
        for f in r["factors"]:
            if f["factor_code"] != "area_hist":
                continue
            m = re.search(r"폐업률 ([\d.]+)%.*업종 평균 ([\d.]+)%", f["detail"])
            m2 = re.search(r"업종 평균\(([\d.]+)%\) 쪽으로 보정한 폐업률 ([\d.]+)%", f["detail"])
            assert m or m2, f
            local, avg = (float(m.group(1)), float(m.group(2))) if m else (float(m2.group(2)), float(m2.group(1)))
            if "많음" in f["label"] or "많은 편" in f["label"]:
                assert local > avg, f
            elif "적음" in f["label"] or "적은 편" in f["label"]:
                assert local < avg, f
            else:
                assert local == avg and "평균 수준" in f["label"], f
