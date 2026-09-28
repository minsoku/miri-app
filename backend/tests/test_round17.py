"""17차 검토 회귀 테스트: 목표 월수입이 있으면 한줄 결론의 배율 기준도 '필요 매출(목표 월수입 포함)', 고위험 한줄 결론에
운영자금·대형 점포 단서를 함께, 원가율을 모르면 손익분기 확인 권유·'감당할 만한' 대신 '월 고정비보다 큰', 카드 칩,
위험도 참고 지표는 '같은 업종' 값이라고 밝힘, 대형 점포 평균의 매출 요인 라벨."""
from app.services import narrative as N
from test_round5 import analyze

API = "/api/v1"
BE = lambda ratio, owner=0, pressure="여유": {"achievability_ratio": ratio, "cost_pressure": pressure,  # noqa: E731
                                            "composition": {"owner_salary": owner}}


def test_owner_basis_in_summary():
    f = {"industry_name": "조명용품", "risk_grade": "낮음", "pred_annual_rate": 0.05, "location_risk_pct": 30}
    s = N.one_liner("동작구", f, None, BE(1.09, 2_000_000, "빠듯"))
    assert "필요 매출(목표 월수입 포함)의 1.09배라 여유가 적어요" in s, s
    s = N.one_liner("동작구", f, None, BE(1.6, 2_000_000))
    assert "필요 매출(목표 월수입 포함)의 1.60배예요" in s, s
    s = N.one_liner("동작구", f, None, BE(1.6))
    assert "손익분기의 1.60배예요" in s, s
    hf = dict(f, risk_grade="높음")
    s = N.one_liner("동작구", hf, None, BE(1.05, 2_000_000, "빠듯"))
    assert "필요 매출(목표 월수입 포함)의 1.05배라" in s and "목표 월수입을 포함한 손익분기" not in s, s


def test_high_risk_keeps_both_caveats():
    f = {"industry_name": "양식음식점", "risk_grade": "고위험", "pred_annual_rate": 0.2, "location_risk_pct": 40,
         "sales_outlier": 3.0, "category": "외식업", "reserve_months": 3.0, "runway_months": 6, "investment": 0}
    s = N.one_liner("강남구", f, None, BE(1.12, 0, "빠듯"))
    assert "운영비가" in s and "대형 매장" in s, s
    area = {"area_name": "서초구", "location_risk_pct": 20, "pred_annual_rate": 0.15, "location_grade": "낮음"}
    s = N.one_liner("강남구", f, None, BE(1.12, 0, "빠듯"), area)
    assert "서초구" in s and "운영비가" in s and "대형 매장" in s, s


def test_high_risk_without_breakeven_asks_for_cogs():
    f = {"industry_name": "편의점", "risk_grade": "높음", "pred_annual_rate": 0.12, "location_risk_pct": 40}
    s = N.one_liner("강남구", f, None, None)
    assert "원가율을 넣어 손익분기도 확인하세요" in s, s
    s = N.one_liner("강남구", f, None, BE(1.3))
    assert "원가율을 넣어" not in s, s


def test_area_alternative_wording_when_cogs_unknown():
    f = {"industry_name": "육류판매", "risk_grade": "보통", "pred_annual_rate": 0.08, "location_risk_pct": 95}
    area = {"area_name": "송파구", "location_risk_pct": 30, "pred_annual_rate": 0.07, "location_grade": "낮음"}
    s = N.one_liner("강남구", f, None, None, {**area, "cogs_known": False})
    assert "평균 매출이 지금 월 고정비보다 큰 송파구" in s and "감당할 만한" not in s, s
    s = N.one_liner("강남구", f, None, BE(1.3), {**area, "cogs_known": True})
    assert "감당할 만한 송파구" in s, s


def test_chip_when_cogs_missing():
    chips = N.reason_chips({"sales_ps_m": 30_000_000, "cogs_missing": True})
    assert "손익분기 미확인(원가율 미입력)" in chips, chips
    assert "손익분기 미확인(원가율 미입력)" not in N.reason_chips({"achievability_ratio": 1.2, "cogs_missing": False})


def test_retail_cards_flag_unknown_cogs(client):
    a = analyze(client, area_code="11680", business_goal="고수익형", budget=200_000_000, monthly_rent_limit=20_000_000,
                labor_cost=3_000_000)
    for it in a["top"]:
        if it["category"] in ("소매업", "서비스업") and it["achievability_ratio"] is None:
            assert "손익분기 미확인(원가율 미입력)" in it["chips"], it["chips"]


def test_reference_labels_say_same_industry(client):
    a = analyze(client, area_code="11200", budget=100_000_000, monthly_rent_limit=3_000_000, labor_cost=2_000_000,
                interests=["CS100010"])
    r = client.get(f"{API}/analyses/{a['id']}/risk/CS100010").json()
    labels = {x["key"]: x["label"] for x in r["reference"]}
    for k in ("sales_growth", "store_growth", "open_close"):
        if k in labels:
            assert "같은 업종" in labels[k], labels
    assert "지역 평균" in labels.get("rent", "지역 평균")


def test_outlier_sales_factor_label():
    f = {"factor_code": "low_sales", "effect_pct": -2.0, "effect_display": 2, "label": "점포당 매출 높음"}
    assert N.factor_label(f, {"sales_outlier": 5.6}) == "점포당 매출 높음(대형 점포 가능·참고용)"
    assert N.factor_label(f, {}) == "점포당 매출 약간 높은 편"
