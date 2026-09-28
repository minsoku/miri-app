"""18차 검토 회귀 테스트: 위험도 화면 인근 지역 '못 미쳐요'의 기준(원가율·목표 월수입), 원가율 미입력 칩은 답이 정해지지 않았을 때만,
목표 월수입 포함 제외 이유 문구, 주의 업종·고정비 0원 한줄 결론, 자격 없는 업종 체크리스트, 높은 원가율 안내,
SB-02 후보 구를 인근 지역 대안에 포함, 지명 사전 보강, 본문 오류 문구."""
from app.services import narrative as N
from test_round5 import analyze, report

API = "/api/v1"


def test_risk_affordability_basis_flags(client):
    a = analyze(client, area_code="11215", budget=100_000_000, monthly_rent_limit=15_000_000, labor_cost=0,
                owner_salary=2_000_000, interests=["CS200019"])
    r = client.get(f"{API}/analyses/{a['id']}/risk/CS200019").json()
    assert r["affordability_cogs_known"] is False and r["affordability_owner_included"] is True, r
    a = analyze(client, area_code="11215", budget=100_000_000, monthly_rent_limit=3_000_000, labor_cost=0,
                interests=["CS100010"])
    r = client.get(f"{API}/analyses/{a['id']}/risk/CS100010").json()
    assert r["affordability_cogs_known"] is True and r["affordability_owner_included"] is False, r


def test_cogs_chip_only_when_undecided(client):
    a = analyze(client, area_code="11140", budget=100_000_000, monthly_rent_limit=40_000_000, labor_cost=0,
                interests=["CS200019"])
    it = next(i for i in a["interests"] if i["industry_code"] == "CS200019")
    if (it["ineligible_reason"] or "").startswith("평균 매출이 월 고정비"):
        assert "손익분기 미확인(원가율 미입력)" not in it["chips"], it["chips"]
    a = analyze(client, area_code="11140", budget=100_000_000, monthly_rent_limit=0, labor_cost=0, categories=["소매업"])
    for it in a["top"]:
        assert "손익분기 미확인(원가율 미입력)" not in it["chips"], it["chips"]


def test_owner_reason_wording():
    it = {"achievability_ratio": 0.8, "owner_included": True}
    assert N.caution_pills(it, None)[0] == "평균 매출로 필요 매출(목표 월수입 포함) 미달"


def test_caution_zone_without_breakeven_asks_for_cogs():
    f = {"industry_name": "철물점", "risk_grade": "보통", "pred_annual_rate": 0.06, "location_risk_pct": 95}
    assert "원가율을 넣어 손익분기도 확인하세요" in N.one_liner("성동구", f, None, None)
    f["fixed_zero"] = True
    assert "원가율을 넣어" not in N.one_liner("성동구", f, None, None)


def test_zero_fixed_cost_summary_does_not_ask_for_cogs():
    f = {"industry_name": "문구", "risk_grade": "낮음", "pred_annual_rate": 0.05, "location_risk_pct": 30, "fixed_zero": True}
    s = N.one_liner("중구", f, None, None)
    assert "월 고정비가 0원" in s and "원가율을 넣어" not in s, s
    hf = dict(f, risk_grade="높음")
    assert "원가율을 넣어" not in N.one_liner("중구", hf, None, None)


def test_unlicensed_checklist_skips_area_comparison(client):
    a = analyze(client, area_code="11680", budget=300_000_000, monthly_rent_limit=5_000_000, labor_cost=5_000_000,
                interests=["CS200006"])
    rep = report(client, a["id"], "CS200006")
    assert "자격" in rep["one_line_summary"]
    assert all(c["action_type"] != "입지변경" for c in rep["checklist"]), rep["checklist"]
    assert rep["checklist"][0]["action_type"] == "자격확인"


def test_empty_reason_names_entered_cogs(client):
    a = analyze(client, area_code="11200", budget=100_000_000, monthly_rent_limit=3_000_000, labor_cost=2_000_000,
                categories=["외식업"], cogs_rates={"외식업": 0.95}, interests=["CS100010"])
    if not a["top"]:
        assert "입력한 원가율(외식업 95%)" in a["empty_reason"], a["empty_reason"]


def test_candidate_districts_are_considered_as_alternatives(client):
    a = analyze(client, area_code="11620", budget=100_000_000, monthly_rent_limit=3_000_000, labor_cost=2_000_000,
                interests=["CS100010"], candidate_area_codes=["11590", "11650"])
    r = client.get(f"{API}/analyses/{a['id']}/risk/CS100010").json()
    b = analyze(client, area_code="11650", budget=100_000_000, monthly_rent_limit=3_000_000, labor_cost=2_000_000,
                interests=["CS100010"])
    seocho = next(i for i in b["interests"] if i["industry_code"] == "CS100010")["location_risk_pct"]
    if r["location_risk_pct"] is not None and seocho < r["location_risk_pct"]:
        assert "서초구" in [x["area_name"] for x in r["alternatives"]], r["alternatives"]


def test_more_places_in_dictionary(client):
    for q, want in (("수서역", "수서역"), ("화곡역", "화곡역"), ("중앙대", "흑석역"), ("서울시청", "시청역"), ("광장시장", "광장시장")):
        res = client.get(f"{API}/places/search", params={"q": q}).json()
        assert res and res[0]["name"] == want, (q, res[:2])


def test_whole_body_validation_messages(client):
    r = client.post(f"{API}/analyses", content=b"{bad json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["error"]["message"] == "요청 내용(JSON) 형식을 확인해 주세요", r.text
    r = client.post(f"{API}/analyses")
    assert r.status_code == 422 and r.json()["error"]["message"].startswith("요청 내용"), r.text
