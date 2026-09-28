"""13차 검토 회귀 테스트: 대형 점포가 섞인 듯한 평균(서울 중간값 3배 이상)은 대안 업종·인근 구·감당 여부 판단에 쓰지 않음,
대형 점포 제외는 다른 조건을 다 통과한 업종에만(비용·손익분기·주의 업종 우선), 체크리스트는 한줄 결론이 권한 대안을 지움 없이,
고위험이면 같은 입지 등급이라도 폐업률이 확실히 낮은 인근 구를 권함, 자격 없는 적자 업종 한줄 결론, 손익분기 경고, 개월 수 표기."""
import re
from app.services import narrative as N
from test_round5 import analyze, be, report

API = "/api/v1"


def test_outlier_district_is_not_recommended_or_judged(client):
    a = analyze(client, area_code="11740", budget=100_000_000, monthly_rent_limit=1_000_000, labor_cost=2_000_000,
                interests=["CS200031"])
    r = client.get(f"{API}/analyses/{a['id']}/risk/CS200031").json()
    for x in r["alternatives"]:
        if x.get("sales_outlier") is not None:
            assert x["sales_outlier"] >= 3 and x["affordable"] is None, x
    rep = report(client, a["id"], "CS200031")
    outl = {x["area_name"] for x in r["alternatives"] if x.get("sales_outlier") is not None}
    for name in outl:
        assert name not in rep["one_line_summary"], rep["one_line_summary"]
        assert all(name not in c["content"] for c in rep["checklist"])


def test_outlier_industry_is_not_suggested_as_alternative(client):
    a = analyze(client, area_code="11680", budget=100_000_000, monthly_rent_limit=1_500_000, labor_cost=1_000_000,
                interests=["CS200003"])
    rep = report(client, a["id"], "CS200003")
    assert "외국어학원" not in rep["one_line_summary"], rep["one_line_summary"]


def test_outlier_exclusion_comes_after_cost_and_location(client):
    # 월 고정비가 매출보다 크면 대형 점포가 아니라 비용 이유로 빠진다
    a = analyze(client, area_code="11710", budget=100_000_000, monthly_rent_limit=25_000_000, labor_cost=0,
                categories=["소매업"], interests=["CS300017"])
    it = next(i for i in a["interests"] if i["industry_code"] == "CS300017")
    if it["sales_ps_m"] is not None and it["sales_ps_m"] < 25_000_000:
        assert not (it["ineligible_reason"] or "").startswith("점포당 매출이 서울 중간값"), it
    # 대형 점포 안내에 나오는 업종은 순위에 들 만했던 것(적합도 20점 이상)만
    for n in a["notices"]:
        if "중간값의 3배 이상인" in n:
            names = re.search(r"업종\((.+?)\)", n).group(1).replace(" 등", "").split("·")
            assert "시계및귀금속" not in names or it["eligible"] is False


def test_notice_does_not_depend_on_interest(client):
    base = dict(area_code="11680", budget=100_000_000, monthly_rent_limit=1_000_000, labor_cost=2_000_000, categories=["외식업"])
    a1 = analyze(client, **base)
    a2 = analyze(client, **base, interests=["CS100002"])
    n1 = [n for n in a1["notices"] if "중간값의 3배 이상인" in n]
    n2 = [n for n in a2["notices"] if "중간값의 3배 이상인" in n]
    assert n1 == n2


def test_checklist_keeps_cited_alternative_industry(client):
    a = analyze(client, area_code="11200", budget=5_000_000, monthly_rent_limit=1_000_000, labor_cost=1_000_000,
                cogs_rates={"외식업": 0.71}, interests=["CS100004"])
    rep = report(client, a["id"], "CS100004")
    m = re.search(r"비슷한 업종인 (\S+?)[은는] ", rep["one_line_summary"])
    if m:
        assert any(m.group(1) in c["content"] for c in rep["checklist"]), rep["checklist"]


def test_high_risk_cites_lower_rate_district_in_same_grade(client):
    a = analyze(client, area_code="11200", budget=100_000_000, monthly_rent_limit=3_000_000, labor_cost=2_000_000,
                owner_salary=3_000_000, initial_investment=50_000_000, interests=["CS100010"])
    r = client.get(f"{API}/analyses/{a['id']}/risk/CS100010").json()
    rep = report(client, a["id"], "CS100010")
    ok_alts = [x for x in r["alternatives"] if x["affordable"] and x["pred_annual_rate"] <= r["pred_annual_rate"] * 0.9]
    if r["risk_grade"] in ("높음", "고위험") and ok_alts and "비슷한 업종인" not in rep["one_line_summary"]:
        assert ok_alts[0]["area_name"] in rep["one_line_summary"], rep["one_line_summary"]
        assert any(ok_alts[0]["area_name"] in c["content"] for c in rep["checklist"])


def test_license_summary_mentions_deficit():
    f = {"industry_name": "미용실", "risk_grade": "낮음", "pred_annual_rate": 0.064, "location_risk_pct": 30,
         "license": "미용사(일반)"}
    s = N.one_liner("금천구", f, None, {"achievability_ratio": 0.29, "composition": {}})
    assert "자격이 있어도" in s and "0.29배" in s, s
    s = N.one_liner("금천구", f, None, {"achievability_ratio": 1.4, "composition": {}})
    assert "자격 요건부터 확인하세요" in s


def test_breakeven_warns_on_outlier_average(client):
    a = analyze(client, area_code="11170", budget=100_000_000, monthly_rent_limit=3_000_000, labor_cost=2_500_000,
                cogs_rates={"소매업": 0.7}, interests=["CS300032"])
    b = be(client, a["id"], industry_code="CS300032")
    assert any("중간값의" in w and "참고용" in w for w in b["warnings"]), b["warnings"]


def test_months_and_josa():
    assert N.months_floor(6.0) == "6" and N.months_floor(10.04) == "10" and N.months_floor(5.95) == "5.9"
    s = N.data_caveat({"sales_outlier": 3.03, "category": "외식업"})
    assert "대형 매장이 섞였을" in s, s
