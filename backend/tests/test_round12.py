"""12차 검토 회귀 테스트: 대형 점포가 섞인 듯한 매출(서울 중간값 3배 이상)은 추천 제외·안내, 매출 추정이 흔들리면
'진입 검토' 문구를 쓰지 않음, 요인 라벨·체크리스트 기준은 화면 숫자(정수 %), 원가율 모르는 관심 업종은 비용 적합도 기준에서 제외,
한줄 결론이 권한 인근 구는 체크리스트에도, 소리 오타 한 글자 제외·구청 이름 검색, 업종별 피크 문구."""
import re
from app.services import narrative as N
from app.services.areas import typo_variants
from test_round5 import analyze, be, report

API = "/api/v1"


def test_outlier_sales_are_not_ranked_and_explained(client):
    a = analyze(client, area_code="11140", budget=80_000_000, monthly_rent_limit=3_000_000, labor_cost=2_500_000)
    tab_reasons = [i for i in a["top"] if (i["ineligible_reason"] or "").startswith("점포당 매출이 서울 중간값")]
    assert not tab_reasons
    for t in a["top"]:
        assert "매출이 유난히 높음(대형 점포 가능)" not in t["cautions"], t
    note = next((n for n in a["notices"] if "중간값의 3배 이상인" in n), None)
    assert note and "추천 순위에서 뺐어요" in note, a["notices"]


def test_no_entry_verdict_on_unreliable_average():
    f = {"industry_name": "수산물판매", "risk_grade": "낮음", "pred_annual_rate": 0.05, "location_risk_pct": 30,
         "sales_outlier": 22.8, "category": "소매업"}
    s = N.one_liner("동작구", f, None, {"achievability_ratio": 24.18, "cost_pressure": "여유", "composition": {}})
    assert "진입을 검토해 볼 만해요" not in s and "하지만" in s and "도매 상가" in s, s
    f = {**f, "sales_outlier": None, "few_sales_areas": 2}
    s = N.one_liner("동작구", f, None, {"achievability_ratio": 1.5, "cost_pressure": "여유", "composition": {}})
    assert "진입을 검토해 볼 만해요" not in s and "2곳뿐" in s, s
    f = {**f, "few_sales_areas": None}
    s = N.one_liner("동작구", f, None, {"achievability_ratio": 1.5, "cost_pressure": "여유", "composition": {}})
    assert s.endswith("진입을 검토해 볼 만해요."), s
    # 서비스업·외식업은 '도매시장'이라고 하지 않는다
    s = N.data_caveat({"sales_outlier": 3.2, "category": "서비스업"})
    assert "도매" not in s and "대형·기업형 점포" in s


def test_labels_follow_displayed_effect():
    f = {"factor_code": "short_life", "effect_pct": 2.7, "effect_display": 3, "label": "지역 전체 폐업 점포 수명 짧은 편"}
    assert N.factor_label(f) == "지역 전체 폐업 점포 수명 짧은 편"          # 화면에 +3%면 '약간'이 아니다
    f = {"factor_code": "short_life", "effect_pct": -3.1, "effect_display": -3, "label": "지역 전체 폐업 점포 수명 긴 편"}
    assert N.factor_label(f) == "지역 전체 폐업 점포 수명 긴 편"
    f = {"factor_code": "short_life", "effect_pct": 2.4, "effect_display": 2, "label": "지역 전체 폐업 점포 수명 짧은 편"}
    assert N.factor_label(f) == "지역 전체 폐업 점포 수명 약간 짧은 편"


def test_cost_fit_base_ignores_interest_without_cogs(client):
    a = analyze(client, area_code="11680", budget=300_000_000, monthly_rent_limit=18_500_000, labor_cost=2_500_000,
                categories=["외식업"], interests=["CS100001", "CS200028"], licenses=["미용사(일반)"])
    if not a["top"]:
        assert a["f_applied"] is True
        food = next(i for i in a["interests"] if i["industry_code"] == "CS100001")
        assert food["scores"]["F"] is not None


def test_checklist_keeps_the_district_the_summary_cites(client):
    for code in ("CS200019", "CS200001", "CS300001", "CS200037", "CS200025"):
        a = analyze(client, area_code="11440", budget=100_000_000, monthly_rent_limit=3_000_000, labor_cost=2_000_000,
                    interests=[code])
        rep = report(client, a["id"], code)
        m = re.search(r"감당할 만한 (\S+?)\(입지 위험", rep["one_line_summary"])
        if m:
            text = " | ".join(c["content"] for c in rep["checklist"])
            assert m.group(1) in text, (code, rep["one_line_summary"], text)
        for c in rep["checklist"]:
            if "폐업 원인(상권 이동·경쟁) 현장 확인" in c["content"]:
                assert c["action_type"] == "현장확인"


def test_search_typos_and_district_office(client):
    assert typo_variants("능") == [] and typo_variants("선능") == ["선릉"]
    assert client.get(f"{API}/places/search", params={"q": "능"}).json() == []
    got = client.get(f"{API}/places/search", params={"q": "강남구청"}).json()
    assert got and got[0]["name"] == "강남구", got
    got = client.get(f"{API}/places/search", params={"q": "성수동카페거리"}).json()
    assert got and got[0]["name"] == "성수역", got


def test_peak_wording_by_industry():
    prof = {"time_share": {"t11": 0.35}, "weekend_share": 0.3}
    assert "수업" in N.peak_flags(prof, "서비스업", "CS200002")[0]["action"]
    assert "맡기고 찾는" in N.peak_flags(prof, "서비스업", "CS200031")[0]["action"]
    assert "예약" in N.peak_flags(prof, "서비스업", "CS200028")[0]["action"]


def test_variable_rate_error_mentions_card_fee(client):
    a = analyze(client, area_code="11440", budget=100_000_000, monthly_rent_limit=3_000_000, labor_cost=2_000_000,
                interests=["CS100010"])
    r = client.post(f"{API}/analyses/{a['id']}/breakeven", json={"industry_code": "CS100010", "cogs_rate": 0.995})
    assert r.status_code == 422 and "카드수수료" in r.json()["error"]["message"]
