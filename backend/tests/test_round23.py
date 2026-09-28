"""23차 검토 회귀 테스트: 손익분기 극단값(남는 몫이 거의 없음)이 500 대신 안내 오류·회수 기간 없음,
한줄 결론이 권한 인근 구가 1·2순위 항목만 있어도 체크리스트에 남음, 분석에서 뺀 업종 저장·대안 제외,
목표 월수입보다 작은 고정비 한도를 '낮추라'고 권하지 않음."""
import re
from test_round5 import analyze, report

API = "/api/v1"


def test_breakeven_extremes_do_not_500(client):
    a = analyze(client, area_code="11440", budget=100_000_000, monthly_rent_limit=2_000_000, labor_cost=1_000_000,
                interests=["CS100001"])
    r = client.post(f"{API}/analyses/{a['id']}/breakeven",
                    json={"industry_code": "CS100001", "monthly_rent": 100_000_000, "cogs_rate": 0.97,
                          "other_variable_rate": 0.009999999999})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VARIABLE_RATE_TOO_HIGH", r.text
    assert "100%에 너무 가까워" in r.json()["error"]["message"]
    r = client.post(f"{API}/analyses/{a['id']}/breakeven",
                    json={"industry_code": "CS100001", "monthly_rent": 5_000_000, "labor_cost": 4_000_000,
                          "initial_investment": 100_000_000_000, "cogs_rate": 0.5579384201562259})
    assert r.status_code == 200, r.text
    pm = r.json()["payback_months"]
    assert pm is None or pm <= 1200, pm


def test_one_liner_area_kept_in_checklist(client):
    a = analyze(client, area_code="11215", budget=20_000_000, monthly_rent_limit=1_500_000, labor_cost=3_000_000,
                initial_investment=15_000_000, cogs_rates={"서비스업": 0.75}, interests=["CS200019"])
    rep = report(client, a["id"], "CS200019")
    m = re.search(r"([가-힣]+구)\(입지 위험 \d+", rep["one_line_summary"])
    if m:
        assert any(m.group(1) in c["content"] for c in rep["checklist"]), (rep["one_line_summary"], rep["checklist"])


def test_excluded_industries_persist_and_skip_alternative(client):
    a = analyze(client, area_code="11110", budget=80_000_000, monthly_rent_limit=1_000_000, labor_cost=1_000_000,
                initial_investment=10_000_000, interests=["CS200017"], excluded_industries=["CS200024"])
    got = client.get(f"{API}/analyses/{a['id']}").json()
    assert got["conditions"]["excluded_industries"] == ["CS200024"]
    rep = report(client, a["id"], "CS200017")
    assert "스포츠클럽" not in rep["one_line_summary"]
    assert all("스포츠클럽" not in c["content"] for c in rep["checklist"])


def test_no_impossible_cost_cap_below_target_income(client):
    a = analyze(client, area_code="11290", budget=80_000_000, monthly_rent_limit=500_000, labor_cost=0,
                initial_investment=20_000_000, owner_salary=3_000_000, cogs_rates={"소매업": 0.5}, interests=["CS300031"])
    rep = report(client, a["id"], "CS300031")
    text = rep["one_line_summary"]
    m = re.search(r"목표 월수입 포함\)를 ([\d,.]+)(만|억)원 이하로 낮추거나", text)
    if m:
        cap = float(m.group(1).replace(",", "")) * (10_000 if m.group(2) == "만" else 100_000_000)
        assert cap >= 3_000_000, text
    for c in rep["checklist"]:
        m = re.search(r"목표 월수입 포함\)를 ([\d,.]+)(만|억)원 이하로 낮추기", c["content"])
        if m:
            cap = float(m.group(1).replace(",", "")) * (10_000 if m.group(2) == "만" else 100_000_000)
            assert cap >= 3_000_000, c["content"]


def test_deficit_branch_cap_below_target_income(client):
    """24차: 가게 비용도 못 버는 적자 문장에서도 목표 월수입보다 작은 한도를 '낮추라'고 권하지 않는다(체크리스트와 같게)."""
    a = analyze(client, area_code="11440", budget=100_000_000, monthly_rent_limit=3_000_000, labor_cost=3_000_000,
                owner_salary=6_000_000, cogs_rates={"소매업": 0.6}, interests=["CS300033"], user_type="OWNER")
    rep = report(client, a["id"], "CS300033")
    text = rep["one_line_summary"]
    for m in re.finditer(r"목표 월수입 포함\)를 ([\d,.]+)(만|억)원 이하로 낮춰야", text):
        cap = float(m.group(1).replace(",", "")) * (10_000 if m.group(2) == "만" else 100_000_000)
        assert cap >= 6_000_000, text
    if any("목표 월수입만으로도" in c["content"] or "목표 월수입(" in c["content"] for c in rep["checklist"]):
        assert "목표를 낮추거나" in text, (text, rep["checklist"])
