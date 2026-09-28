"""11차 검토 회귀 테스트: 후보 0개일 때 비용 적합도, 효과가 작은 요인 라벨, 대형 점포 매출 단서, 학원 평일 문구,
소리 오타 검색, 20점 미만 업종 이름, 문장 다듬기, 리포트 비용 기준 인근 구 판단(be), 옛 기록의 changed·required 중복,
추천 불가 업종 칩(recommendable), 매출 비교 지역 부족 안내, 인근 대체 지역."""
import json
import re
from app import models as M
from app.services import narrative as N
from app.services.areas import typo_variants
from test_round5 import analyze, be, report

API = "/api/v1"


def test_cost_fit_applies_when_no_candidate(client):
    # 고정비가 너무 커 후보가 0개여도 관심 업종 점수에 비용 적합도를 넣는다(비용이 클수록 점수가 오르지 않게)
    big = analyze(client, area_code="11440", budget=100_000_000, monthly_rent_limit=80_000_000, labor_cost=0,
                  interests=["CS100010"])
    assert big["top"] == [] and big["f_applied"] is True
    it = big["interests"][0]
    assert it["scores"]["F"] is not None
    small = analyze(client, area_code="11440", budget=100_000_000, monthly_rent_limit=3_500_000, labor_cost=2_500_000,
                    interests=["CS100010"])
    assert small["interests"][0]["suitability"] >= it["suitability"]


def test_small_effect_labels_say_slightly():
    f = {"factor_code": "short_life", "effect_pct": 2.0, "label": "지역 전체 폐업 점포 수명 짧은 편"}
    assert N.factor_label(f) == "지역 전체 폐업 점포 수명 약간 짧은 편"
    f = {"factor_code": "short_life", "effect_pct": 5.0, "label": "지역 전체 폐업 점포 수명 짧은 편"}
    assert N.factor_label(f) == "지역 전체 폐업 점포 수명 짧은 편"
    f = {"factor_code": "low_sales", "effect_pct": 1.0, "label": "점포당 매출 낮음"}
    assert N.factor_label(f) == "점포당 매출 약간 낮은 편"


def test_sales_outlier_pill_and_caveat(client):
    a = analyze(client, area_code="11710", budget=100_000_000, monthly_rent_limit=3_000_000, labor_cost=2_500_000,
                categories=["소매업"], interests=["CS300010"])
    it = next(i for i in a["interests"] if i["industry_code"] == "CS300010")
    # 12차: 대형 점포가 섞인 듯한 매출(서울 중간값의 3배 이상)은 추천에서 빼고, 같은 뜻의 주의 알약은 한 번만
    assert not it["eligible"] and it["ineligible_reason"].startswith("점포당 매출이 서울 중간값의"), it
    assert "매출이 유난히 높음(대형 점포 가능)" not in it["cautions"], it
    assert all(t["industry_code"] != "CS300010" for t in a["top"])
    rep = report(client, a["id"], "CS300010")
    assert "대형 점포" in rep["one_line_summary"], rep["one_line_summary"]
    assert N.sales_outlier({"sales_ps_m": 2.9, "sales_med": 1.0}) is None
    assert N.sales_outlier({"sales_ps_m": 3.0, "sales_med": 1.0}) == 3.0


def test_academy_weekday_advice_is_not_for_office_workers():
    prof = {"time_share": {}, "weekend_share": 0.09}
    assert "직장인" not in N.peak_flags(prof, "서비스업", "CS200002")[0]["action"]
    assert "직장인" in N.peak_flags(prof, "서비스업", "CS200028")[0]["action"]


def test_phonetic_typos(client):
    assert typo_variants("강남녁") == ["강남역"] and typo_variants("선능역") == ["선릉역"]
    assert typo_variants("강남역") == []
    for q, want in (("강남녁", "강남역"), ("잠실력", "잠실역"), ("서울녁", "서울역"), ("선능역", "선릉역")):
        got = client.get(f"{API}/places/search", params={"q": q}).json()
        assert got and got[0]["name"] == want, (q, got)
    # 긴 검색어는 422(화면은 '연결 실패'가 아니라 서버가 준 이유를 보여 준다)
    r = client.get(f"{API}/places/search", params={"q": "가" * 51})
    assert r.status_code == 422 and r.json()["error"]["message"] == "검색어가 너무 길어요"


def test_low_score_industries_are_named(client):
    a = analyze(client, area_code="11380", budget=100_000_000, monthly_rent_limit=8_000_000, labor_cost=6_000_000,
                business_goal="안정형", categories=["서비스업"])
    if a["n_low_score"]:
        text = (a["empty_reason"] or "") + " ".join(a["notices"])
        assert re.search(r"\(.+ \d+점", text), text
        assert text.count("나머지") <= 1, text
    assert N.risk_is("낮음", "6.1%", "고") == "폐업 위험이 낮고(예상 연 폐업률 6.1%)"
    assert N.risk_is("보통", "9.0%", "요") == "폐업 위험이 보통 수준이에요(예상 연 폐업률 9.0%)."


def test_risk_screen_uses_report_costs(client):
    a = analyze(client, area_code="11440", budget=300_000_000, monthly_rent_limit=9_000_000, labor_cost=6_000_000,
                interests=["CS100010"])
    b = be(client, a["id"], industry_code="CS100010", monthly_rent=1_000_000, labor_cost=1_000_000)
    rep = report(client, a["id"], "CS100010", b["id"])
    plain = client.get(f"{API}/analyses/{a['id']}/risk/CS100010").json()
    with_be = client.get(f"{API}/analyses/{a['id']}/risk/CS100010", params={"be": b["id"]}).json()
    assert plain["affordability_basis"] == "analysis" and with_be["affordability_basis"] == "report"
    # 리포트가 권한 인근 구는 리포트 비용 기준 위험도 화면에서 '못 미쳐요'로 보이지 않는다
    m = re.search(r"감당할 만한 (\S+?)\(입지 위험", rep["one_line_summary"])
    names = {m.group(1)} if m else set()
    names |= {x["area_name"] for x in with_be["alternatives"] if x["area_name"] in " ".join(c["content"] for c in rep["checklist"])}
    for x in with_be["alternatives"]:
        if x["area_name"] in names:
            assert x["affordable"] is not False, x
    # 다른 분석·업종의 손익분기 id는 무시(분석 조건 기준)
    other = client.get(f"{API}/analyses/{a['id']}/risk/CS100001", params={"be": b["id"]}).json()
    assert other["affordability_basis"] == "analysis"
    assert client.get(f"{API}/analyses/{a['id']}/risk/CS100010", params={"be": 0}).status_code == 422


def test_old_records_do_not_repeat_required_as_changed(client, db):
    a = analyze(client, area_code="11260", budget=60_000_000, monthly_rent_limit=1_500_000, labor_cost=1_000_000,
                interests=["CS200001"])
    b = be(client, a["id"], industry_code="CS200001", cogs_rate=0.3)
    row = db.get(M.BreakEvenAnalysis, b["id"])
    inp = json.loads(row.input_json)
    inp["changed"] = ["cogs_rate"]                    # 10차 이전 기록: changed에 required가 섞여 있음
    row.input_json = json.dumps(inp, ensure_ascii=False)
    db.commit()
    rep = report(client, a["id"], "CS200001", b["id"])
    assert rep["breakeven"]["changed"] == {} and rep["breakeven"]["entered"] == {"cogs_rate": 0.3}


def test_industries_flag_recommendable(client):
    inds = {i["code"]: i for i in client.get(f"{API}/industries").json()["industries"]}
    assert inds["CS200033"]["has_sales_data"] and not inds["CS200033"]["recommendable"]   # 부동산중개업: 카드 매출 지역 부족
    assert inds["CS100010"]["recommendable"]
    assert all(not i["recommendable"] for i in inds.values() if not i["has_sales_data"])


def test_few_sales_areas_note_and_caveat(client):
    a = analyze(client, area_code="11680", budget=300_000_000, monthly_rent_limit=3_000_000, labor_cost=1_000_000,
                cogs_rates={"서비스업": 0.1}, interests=["CS200036"])
    it = next(i for i in a["interests"] if i["industry_code"] == "CS200036")
    assert not it["eligible"] and it["score_note"] and "참고용" in it["score_note"], it
    rep = report(client, a["id"], "CS200036")
    assert "참고용" in rep["one_line_summary"], rep["one_line_summary"]


def test_fallback_lists_nearest_district(client):
    # 이 지역에 같은 업종이 없고 입지 위험 '낮음'인 인근 구도 없으면 가장 가까운 구라도 보여 준다
    a = analyze(client, area_code="11350", budget=100_000_000, monthly_rent_limit=3_000_000, labor_cost=2_000_000,
                interests=["CS200036"])
    r = client.get(f"{API}/analyses/{a['id']}/risk/CS200036").json()
    if r["fallback"]:
        assert r["alternatives"], r
        rep = report(client, a["id"], "CS200036")
        for x in r["alternatives"]:
            if x["location_grade"] != "낮음":
                assert x["area_name"] not in rep["one_line_summary"]


def test_budget_caveat_kept_with_alternative():
    focus = {"industry_name": "편의점", "risk_grade": "높음", "pred_annual_rate": 0.2, "location_risk_pct": 50,
             "investment": 50_000_000, "reserve_months": 0.0, "runway_months": 6}
    alt = {"industry_name": "슈퍼마켓", "pred_annual_rate": 0.12, "risk_grade": "보통"}
    s = N.one_liner("영등포구", focus, alt, {"achievability_ratio": 1.05, "composition": {}})
    assert "슈퍼마켓" in s and "운영자금이 없어요" in s, s
