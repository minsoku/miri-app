"""2차 검토 회귀 테스트: 사용자에게 보이는 문장·숫자가 계산과 서로 모순되지 않는지(한줄 결론·체크리스트·위험도 문장·용어)."""
import re
import pytest
from miri_engine.config import LICENSED_INDUSTRIES, risk_grade
from app.services import narrative as N
from app.services.engine import get_state
from app.services.report_svc import build_checklist
from conftest import BASE_ANALYSIS

API = "/api/v1"
POSITIVE = "진입을 검토해 볼 만해요"


def analyze(client, **over):
    r = client.post(f"{API}/analyses", json={**BASE_ANALYSIS, **over})
    assert r.status_code == 201, r.text
    return r.json()


def report(client, aid, code, be_id=None):
    r = client.post(f"{API}/analyses/{aid}/reports", json={"industry_code": code, "break_even_id": be_id})
    assert r.status_code == 201, r.text
    return r.json()


def pick(st, cond, n=1):
    t = st.table
    rows = t[cond(t)].sort_values(["area_id", "industry_code"])
    assert len(rows) >= n, "테스트용 행이 없음"
    return rows.head(n)


@pytest.fixture()
def st(db):
    return get_state(db)


# ── 한줄 결론 ──────────────────────────────────────────────────────────
def test_caution_industry_is_not_encouraged(client, st):
    """같은 업종 중 입지 위험 상위 10%(주의 업종)는 폐업 위험 등급이 낮아도 '진입 검토' 문장을 쓰면 안 된다."""
    r = pick(st, lambda t: (t["risk_pct_in_ind"] >= 90) & t["risk_grade"].isin(["낮음", "보통"])
             & ~t["industry_code"].isin(list(LICENSED_INDUSTRIES)) & t["sales_ps_m"].notna()).iloc[0]
    a = analyze(client, area_code=r["area_id"], interests=[r["industry_code"]])
    rep = report(client, a["id"], r["industry_code"])
    s = rep["one_line_summary"]
    assert POSITIVE not in s and ("입지 위험이 매우 높아요" in s or "적자" in s or "못 미쳐요" in s), s


def test_license_block_is_not_encouraged(client, st):
    r = pick(st, lambda t: t["industry_code"].isin(list(LICENSED_INDUSTRIES)) & (t["risk_pct_in_ind"] < 90)
             & t["risk_grade"].isin(["낮음", "보통"])).iloc[0]
    a = analyze(client, area_code=r["area_id"], interests=[r["industry_code"]], licenses=[])
    s = report(client, a["id"], r["industry_code"])["one_line_summary"]
    assert "자격이 있어야" in s and POSITIVE not in s, s


def _retail_row(st):
    return pick(st, lambda t: (t["category"] == "소매업") & t["risk_grade"].isin(["낮음", "보통"]) & (t["risk_pct_in_ind"] < 90)
                & t["sales_ps_m"].notna() & (t["stores_avg4"] >= 1) & (t["confidence"] != "낮음")
                & ~t["industry_code"].isin(list(LICENSED_INDUSTRIES))).iloc[0]


def test_owner_salary_shortfall_is_not_called_loss(client, st):
    """목표 월수입이 포함된 손익분기에 못 미쳐도 가게가 남으면 '적자'가 아니라 '목표 월수입에 못 미침'."""
    r = _retail_row(st)
    code, sales = r["industry_code"], float(r["sales_ps_m"])
    a = analyze(client, area_code=r["area_id"], interests=[code], monthly_rent_limit=0, labor_cost=0)
    cm = 0.69                                                          # 원가율 30% + 카드수수료 ≈ 1%
    be = client.post(f"{API}/analyses/{a['id']}/breakeven", json={
        "industry_code": code, "cogs_rate": 0.3, "monthly_rent": int(sales * cm * 0.6), "owner_salary": int(sales * cm * 0.6)}).json()
    assert be["achievability_ratio"] < 1 and be["profit_at_market_avg"] + be["composition"]["owner_salary"] > 0
    assert be["cost_pressure"] == "위험"                                 # 손익분기 미달은 '빠듯'이 아니라 '위험'
    rep = report(client, a["id"], code, be["id"])
    s = rep["one_line_summary"]
    assert "적자" not in s and "목표 월수입" in s and "보다 월" in s and "적어요" in s, s     # 모자란 금액을 직접 밝힌다
    first = rep["checklist"][0]["content"]
    assert first.startswith("월 고정비(목표 월수입 포함)를"), first


def test_report_from_risk_ignores_unapplied_whatif(client):
    """손익분기 화면에서 '리포트에 반영'하지 않은 가정값(임대료 2천만원)은 위험도 화면의 리포트에 쓰이면 안 된다."""
    a = analyze(client, interests=["CS100008"])
    client.post(f"{API}/analyses/{a['id']}/breakeven", json={"industry_code": "CS100008", "monthly_rent": 20_000_000})
    rep = report(client, a["id"], "CS100008")
    assert rep["breakeven"]["monthly_fixed_cost"] == BASE_ANALYSIS["monthly_rent_limit"] + BASE_ANALYSIS["labor_cost"]
    assert "2,000만원" not in " ".join(c["content"] for c in rep["checklist"])


def test_checklist_follows_applied_breakeven_inputs(client):
    """리포트에 반영한 손익분기의 임대료로 체크리스트를 만든다(분석 조건의 임대료와 섞이지 않게)."""
    a = analyze(client, interests=["CS100008"])
    be = client.post(f"{API}/analyses/{a['id']}/breakeven", json={"industry_code": "CS100008", "monthly_rent": 1_200_000}).json()
    rep = report(client, a["id"], "CS100008", be["id"])
    rent_items = [c["content"] for c in rep["checklist"] if "임대료" in c["content"]]
    assert rent_items and "120만원" in rent_items[0] and "300만원" not in rent_items[0], rent_items


def test_short_checklist_is_self_consistent(client):
    """'월 고정비를 X 이하로'와 임대료 목표가 서로 맞아야: 임대료 목표 = 지금 임대료 − 줄여야 할 금액."""
    a = analyze(client, interests=["CS100008"])
    be = client.post(f"{API}/analyses/{a['id']}/breakeven", json={"industry_code": "CS100008", "monthly_rent": 9_000_000}).json()
    assert be["achievability_ratio"] < 1
    rep = report(client, a["id"], "CS100008", be["id"])
    items = [c["content"] for c in rep["checklist"]]
    target = N.won_floor_below(be["max_fixed_for_bep"], be["monthly_fixed_cost"])          # 한도는 표시 단위 내림
    gap = N.won_value(be["monthly_fixed_cost"]) - target                                     # 화면 표시값끼리의 차이
    assert any(N.won(target) in x and N.won(gap) in x for x in items), items
    rent = [x for x in items if x.startswith("임대료")]
    assert rent and N.won(9_000_000 - gap) in rent[0] and "우선 검토" not in rent[0], rent


# ── 체크리스트 문구 ────────────────────────────────────────────────────
def test_store_surge_not_claimed_when_stores_fell():
    """상대 요인(같은 업종 대비 점포 증가율 높음)이어도 실제로 점포가 줄었으면 '늘어' 문구를 쓰지 않는다."""
    class Req:
        monthly_rent_limit, owner_salary, initial_investment, budget = 0, 0, 0, 0
        labor_cost, other_fixed, loan_amount, loan_rate_annual = 0, 0, 0, 0.0
        business_goal, licenses_json, categories_json = "기본", "[]", "[]"
    focus = {"category": "서비스업", "factors": [{"factor_code": "store_surge", "direction": "up", "effect_pct": 8.0}],
             "alternatives": [], "raw": {"closures_1y": 0}}
    items = build_checklist(Req(), focus, {"store_growth": -0.05}, None, None, None, None)
    assert not any("늘어" in i["content"] for i in items)
    items = build_checklist(Req(), focus, {"store_growth": 0.12}, None, None, None, None)
    assert any("+12%" in i["content"] and "서비스" in i["content"] and "메뉴" not in i["content"] for i in items)


def test_non_food_checklist_has_no_menu_wording(client, st):
    rows = pick(st, lambda t: (t["category"] != "외식업") & t["sales_ps_m"].notna() & (t["risk_pct_in_ind"] < 90)
                & ~t["industry_code"].isin(list(LICENSED_INDUSTRIES)), n=40)
    seen = 0
    for _, r in rows.iloc[::8].iterrows():
        a = analyze(client, area_code=r["area_id"], interests=[r["industry_code"]])
        text = " ".join(c["content"] for c in report(client, a["id"], r["industry_code"])["checklist"])
        assert "메뉴" not in text and "회전율" not in text, text
        seen += 1
    assert seen >= 4


# ── 위험도 문장 ──────────────────────────────────────────────────────
def test_risk_summary_matches_badges(client, st):
    a = analyze(client, interests=[])
    codes = list(st.area_rows("11680")["industry_code"])[::7]
    for code in codes:
        d = client.get(f"{API}/analyses/{a['id']}/risk/{code}").json()
        s = d["summary"]
        assert N.LOC_WORD[d["location_grade"]] + "이에요" in s, (d["location_grade"], s)
        word = {"낮음": "낮은 편", "보통": "중간 수준", "높음": "높은 편", "고위험": "매우 높아요"}[d["risk_grade"]]
        assert word in s.split(" 같은 업종")[0], (d["risk_grade"], s)
        assert "비교해도" not in s
        for x in d["alternatives"]:
            assert x["distance_km"] <= 7.0 and x["location_grade"] == risk_grade(x["location_risk_pct"])
        for f in d["factors"]:
            check_trend_label(f)


def check_trend_label(f):
    """추세 요인 라벨이 옆에 보이는 실제 증감과 모순되지 않는지(점포 증가율 높음 + '-0.9%' 같은 조합 금지)."""
    if f["factor_code"] not in ("store_surge", "sales_decline"):
        return
    m = re.search(r"전년 대비 ([+\-−]?\d+\.\d)%", f["detail"])
    if not m:
        return
    v, lab, up = float(m.group(1).replace("−", "-")), f["label"], f["direction"] == "up"
    if "거의 그대로" in lab:
        assert v == 0.0, (lab, f["detail"])
    elif "늘어나는 중" in lab:
        assert v > 0, (lab, f["detail"])
    elif "줄어드는 중" in lab:
        assert v < 0, (lab, f["detail"])
    elif "감소 폭이 작음" in lab:
        assert v <= 0, (lab, f["detail"])
    elif "증가 폭이 작음" in lab:
        assert v >= 0, (lab, f["detail"])
    else:
        raise AssertionError(f"추세 라벨이 실제 값과 무관함: {lab} / {f['detail']}")


def test_trend_labels_match_values_everywhere(client, st):
    """모든 지역×업종의 SB-06 요인에서 추세 라벨과 실제 증감 부호가 맞아야(2차 검토 479건 모순)."""
    n = 0
    for area in ("11680", "11440", "11545"):
        a = analyze(client, area_code=area, interests=[])
        for code in st.area_rows(area)["industry_code"]:
            for f in client.get(f"{API}/analyses/{a['id']}/risk/{code}").json()["factors"]:
                check_trend_label(f)
                n += f["factor_code"] in ("store_surge", "sales_decline")
    assert n > 50


def test_reason_short_uses_rank_not_top_percent(client):
    a = analyze(client, interests=["CS100001"])
    for it in a["top"] + a["interests"]:
        assert "상위" not in it["reason_short"], it["reason_short"]
        if it["scores"]["D"] is not None:
            assert re.search(r"서울 \d+개 구 중 \d+위", it["reason_short"]), it["reason_short"]


def test_scope_note_and_budget_not_in_ranking(client):
    a = analyze(client, budget=80_000_000)
    b = analyze(client, budget=900_000_000)
    assert [t["industry_code"] for t in a["top"]] == [t["industry_code"] for t in b["top"]]     # 예산은 순위에 안 쓴다
    assert [t["suitability"] for t in a["top"]] == [t["suitability"] for t in b["top"]]
    assert "자치구" in a["area"]["scope_note"]


def test_zero_result_explains_fixed_cost(client):
    a = analyze(client, monthly_rent_limit=300_000_000, labor_cost=100_000_000, budget=900_000_000)
    assert a["top"] == [] and "월 고정비" in a["empty_reason"] and "손익분기를 넘기 어려워요" in a["empty_reason"]
    assert "자격 없이" in a["empty_reason"]                                  # 자격 업종까지 포함한 것처럼 말하지 않는다
    b = analyze(client, area_code="11740", budget=300_000_000, monthly_rent_limit=30_000_000, labor_cost=15_000_000)
    if not b["top"]:
        assert "보유 자격을 고르면" in b["empty_reason"], b["empty_reason"]      # 매출이 큰 자격 업종이 있으면 알려준다
    assert not any("추천 업종이 없어요" in n for n in a["notices"])         # 같은 안내를 두 번 하지 않는다


def test_breakeven_warnings_are_plain_language(client):
    a = analyze(client)
    be = client.post(f"{API}/analyses/{a['id']}/breakeven", json={"industry_code": "CS100008"}).json()
    assert be["warnings"] and all("→" not in w and "미입력" not in w for w in be["warnings"])


def test_money_formatting():
    assert N.won(520_000_000) == "5.2억원" and N.won(300_000_000) == "3억원" and N.won(99_999_999) == "1억원"
    assert N.won1(105_600) == "10.6만원" and N.won1(1_056_000) == "106만원"


def test_gzip_for_large_json(client):
    r = client.get(f"{API}/areas/map", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers.get("content-encoding") == "gzip"


# ── 3차 검토 회귀 ─────────────────────────────────────────────────────
def test_report_from_breakeven_uses_its_costs_in_conclusion(client):
    """손익분기에서 낮춘 비용을 반영한 리포트의 한줄 결론이 분석 조건의 월 고정비를 들먹이면 안 된다."""
    a = analyze(client, area_code="11110", monthly_rent_limit=2_500_000, labor_cost=2_000_000, licenses=["미용사(일반)"],
                interests=["CS200028"], categories=["서비스업"])
    be = client.post(f"{API}/analyses/{a['id']}/breakeven", json={
        "industry_code": "CS200028", "cogs_rate": 0.35, "monthly_rent": 800_000, "labor_cost": 700_000}).json()
    rep = report(client, a["id"], "CS200028", be["id"])
    assert "450만원" not in rep["one_line_summary"], rep["one_line_summary"]
    if be["achievability_ratio"] >= 1:
        assert "보다 적어요" not in rep["one_line_summary"]


def test_alternative_industry_is_similar_and_safer(client, st):
    from app.services.catalog import INDUSTRY_FAMILY
    fam_of = {v["name"]: INDUSTRY_FAMILY.get(k) for k, v in st.industries.items()}
    order = N.GRADE_ORDER
    for area, code in [("11545", "CS200019"), ("11440", "CS200037"), ("11680", "CS100010"), ("11710", "CS200029")]:
        a = analyze(client, area_code=area, interests=[code])
        rep = report(client, a["id"], code)
        s = rep["one_line_summary"]
        m = re.search(r"비슷한 업종인 (.+?)[은는] 예상 연 폐업률이 [\d.]+%\(위험 (\S+)\)", s)
        if m:
            name, grade = m.group(1), m.group(2)
            assert fam_of[name] == INDUSTRY_FAMILY[code], (code, name)
            assert order[grade] < order[rep["risk"]["risk_grade"]], (s, rep["risk"]["risk_grade"])
        assert "자동차수리" not in s or code in ("CS200025",), s


def test_below_breakeven_pill_comes_first(client):
    a = analyze(client, area_code="11470", monthly_rent_limit=3_000_000, labor_cost=3_000_000, initial_investment=50_000_000,
                owner_salary=4_000_000, business_goal="저비용형", budget=100_000_000,
                interests=["CS100010", "CS100008", "CS100001", "CS100007", "CS100005"])
    cards = [it for it in a["top"] + a["interests"] if it["achievability_ratio"] is not None and it["achievability_ratio"] < 1]
    assert cards
    for it in cards:
        if it["ineligible_reason"] in ("평균 매출로 필요 매출(목표 월수입 포함) 미달", "평균 매출이 월 고정비(목표 월수입 포함)보다 적음"):
            # '추천 제외 · …' 줄이 같은 말을 하므로 알약은 겹치지 않게 빼고, 제외 이유가 목표 월수입 포함 기준임을 밝힌다
            assert not any(c.startswith("평균 매출로 손익분기") for c in it["cautions"]), it["cautions"]
        else:
            assert it["cautions"][0] == "평균 매출로 필요 매출(목표 월수입 포함) 미달", it["cautions"]   # 목표 월수입을 넣은 분석
    assert all(it["eligible"] is False or it["item_type"] != "TOP" for it in cards)            # 손익분기 미달은 TOP에 없음
    assert not any(t["achievability_ratio"] is not None and t["achievability_ratio"] < 1 for t in a["top"])


def test_no_loans_for_structural_deficit_without_breakeven(client):
    """원가율 기본값이 없는 업종(세탁소)은 손익분기를 못 내도, 평균 매출 < 월 고정비면 대출 상품을 권하지 않는다."""
    a = analyze(client, user_type="OWNER", monthly_rent_limit=9_000_000, labor_cost=6_000_000, interests=["CS200031"])
    rep = report(client, a["id"], "CS200031")
    assert rep["breakeven"] is None
    assert all(p["support_type"] != "자금" for p in rep["policies"]), [p["name"] for p in rep["policies"]]
    items = [c["content"] for c in rep["checklist"]]
    assert items[0].startswith("월 고정비를 이 지역 점포당 평균 월매출"), items
    assert not any(x.startswith("월 임대료") and "우선 검토" in x for x in items), items


def test_implausible_card_sales_are_not_shown(client, st):
    """카드 매출이 거의 안 잡히는 셀(점포당 월 50만원 미만)은 매출 지표로 쓰지 않는다(2차: '점포당 월매출 77원')."""
    t = st.table
    assert (t["sales_ps_m"].dropna() >= 500_000).all()
    a = analyze(client, area_code="11740", licenses=["공인중개사"], interests=["CS200033"],
                monthly_rent_limit=1_500_000, labor_cost=1_000_000)
    it = a["interests"][0]
    assert it["sales_ps_m"] is None and it["suitability"] is None and it["score_note"]
    assert not any("월매출" in c and "원" in c for c in it["chips"])
    s = report(client, a["id"], "CS200033")["one_line_summary"]
    assert "카드 매출 데이터가 부족" in s and "점포가 적어" not in s, s


def test_missing_license_always_in_checklist(client):
    a = analyze(client, area_code="11710", monthly_rent_limit=1_500_000, labor_cost=1_000_000, interests=["CS200029"])
    rep = report(client, a["id"], "CS200029")
    assert any("미용사(네일) 자격" in c["content"] for c in rep["checklist"]), rep["checklist"]


def test_no_plus_zero_percent_in_checklists(client, st):
    for area in ("11650", "11470"):
        a = analyze(client, area_code=area)
        for code in list(st.area_rows(area)["industry_code"])[::5]:
            text = " ".join(c["content"] for c in report(client, a["id"], code)["checklist"])
            assert "+0%" not in text and "-0%" not in text, text


def test_market_payments_on_operating_day_basis(client):
    a = analyze(client, interests=["CS100009"])
    be = client.post(f"{API}/analyses/{a['id']}/breakeven", json={"industry_code": "CS100009"}).json()
    # 반올림 전 하루 필요 결제(필요 매출 ÷ 객단가 ÷ 영업일) 기준 — 올림한 건수(1건)로 나누면 고가 업종에서 크게 부풀려진다
    need = be["required_monthly_sales"] / be["avg_ticket_used"] / be["operating_days"]
    assert be["market_tx_ps_day"] and be["customers_vs_market"] == pytest.approx(need / be["market_tx_ps_day"], rel=0.02)


def test_empty_reason_grammar_single_candidate(client):
    a = analyze(client, area_code="11440", budget=200_000_000, monthly_rent_limit=7_000_000, labor_cost=5_000_000,
                interests=["CS200025"], categories=["서비스업"])
    if not a["top"] and a["n_candidates"] == 1:
        assert "1개가 모두" not in a["empty_reason"] and "1개뿐인데" in a["empty_reason"]


# ── 4차 검토 회귀 ─────────────────────────────────────────────────────
def _policy_types(rep):
    return [p["support_type"] for p in rep["policies"]]


def test_no_loans_when_cannot_open_or_judge(client, st):
    """자격 없음·매출 판단 불가·점포 없음·고위험이면 대출(자금) 상품을 권하지 않고, 재기지원과 대출을 함께 내지 않는다."""
    a = analyze(client, area_code="11110", user_type="OWNER", interests=["CS200006"])        # 일반의원, 의사 자격 없음
    assert "자금" not in _policy_types(report(client, a["id"], "CS200006"))
    t = st.table
    nosales = t[t["sales_ps_m"].isna() & (t["stores_avg4"] >= 1)].sort_values(["area_id", "industry_code"]).iloc[0]
    b = analyze(client, area_code=nosales["area_id"], user_type="OWNER", interests=[nosales["industry_code"]])
    assert "자금" not in _policy_types(report(client, b["id"], nosales["industry_code"]))
    hi = t[(t["risk_grade"] == "고위험")].sort_values(["area_id", "industry_code"]).iloc[0]
    c = analyze(client, area_code=hi["area_id"], user_type="OWNER", owner_salary=3_000_000, interests=[hi["industry_code"]])
    types = _policy_types(report(client, c["id"], hi["industry_code"]))
    assert "자금" not in types and not ("재기지원" in types and "자금" in types)


def test_top_never_includes_below_breakeven(client):
    for kw in ({"area_code": "11500", "categories": ["외식업"], "interests": ["CS100010"]},
               {"area_code": "11470", "categories": ["외식업"], "owner_salary": 3_000_000}):
        a = analyze(client, **kw)
        assert all(t["achievability_ratio"] is None or t["achievability_ratio"] >= 1 for t in a["top"]), a["top"]


def test_alternative_is_affordable_under_applied_costs(client, st):
    """SB-07에서 반영한 비용(월 고정비 950만원)으로는 평균 매출이 모자란 업종을 '비슷한 업종'으로 권하지 않는다."""
    a = analyze(client, area_code="11500", user_type="OWNER", interests=["CS300029"])
    be = client.post(f"{API}/analyses/{a['id']}/breakeven", json={"industry_code": "CS300029", "cogs_rate": 0.3,
                                                                     "owner_salary": 4_000_000}).json()
    rep = report(client, a["id"], "CS300029", be["id"])
    m = re.search(r"비슷한 업종인 (.+?)[은는] ", rep["one_line_summary"])
    if m:
        code = next(c for c, v in st.industries.items() if v["name"] == m.group(1))
        assert st.row("11500", code)["sales_ps_m"] >= be["monthly_fixed_cost"]


def test_no_sales_trend_for_unusable_sales(client, st):
    t = st.table
    for _, r in t[t["sales_ps_m"].isna() & (t["stores_avg4"] >= 1)].head(6).iterrows():
        a = analyze(client, area_code=r["area_id"], interests=[r["industry_code"]])
        ref = {x["key"] for x in client.get(f"{API}/analyses/{a['id']}/risk/{r['industry_code']}").json()["reference"]}
        assert "sales_growth" not in ref, (r["area_id"], r["industry_code"])


def test_entry_heat_label_matches_openings(client, st):
    for area in ("11110", "11440"):
        a = analyze(client, area_code=area)
        for code in st.area_rows(area)["industry_code"]:
            for f in client.get(f"{API}/analyses/{a['id']}/risk/{code}").json()["factors"]:
                if f["factor_code"] == "entry_heat" and f["label"] == "신규 개업 많음":
                    r = st.row(area, code)
                    assert r["ope4"] / r["exp4"] >= r["mu_ind_entry"], (area, code, f)


def test_interest_limit_message(client):
    r = client.post(f"{API}/analyses", json={**BASE_ANALYSIS, "interests": [f"CS1000{i:02d}" for i in range(1, 11)]
                                             + [f"CS2000{i:02d}" for i in range(1, 12)]})
    assert r.status_code == 422 and "20개까지" in r.json()["error"]["message"]


def test_checklist_never_empty_and_rent_target_realistic(client):
    a = analyze(client, monthly_rent_limit=0, labor_cost=0, interests=["CS200001"])
    assert report(client, a["id"], "CS200001")["checklist"]
    b = analyze(client, area_code="11110", licenses=["미용사(피부)"], interests=["CS200030"])
    be = client.post(f"{API}/analyses/{b['id']}/breakeven", json={"industry_code": "CS200030", "cogs_rate": 0.1,
                                                                     "owner_salary": 1_500_000, "monthly_rent": 500_000}).json()
    for c in report(client, b["id"], "CS200030", be["id"])["checklist"]:
        m = re.search(r"임대료만 줄인다면 월 ([\d,]+)원 이하", c["content"])
        assert not m, c["content"]                                        # 10만원 미만 목표는 '임대료만으로는 어려워요'


def test_entry_sentence_mentions_short_operating_reserve(client, st):
    r = _retail_row(st)
    a = analyze(client, area_code=r["area_id"], interests=[r["industry_code"]], budget=10_000_000)
    be = client.post(f"{API}/analyses/{a['id']}/breakeven", json={"industry_code": r["industry_code"], "cogs_rate": 0.3,
                                                                     "initial_investment": 9_000_000}).json()
    s = report(client, a["id"], r["industry_code"], be["id"])["one_line_summary"]
    if POSITIVE in s:
        assert "운영자금" in s, s
    assert any("총 창업 예산" in w for w in be["warnings"]) is False or be["inputs"]["initial_investment"] > 10_000_000


def test_breakeven_warns_when_no_market_sales(client, st):
    t = st.table
    r = t[t["sales_ps_m"].isna() & (t["stores_avg4"] >= 1)].sort_values(["area_id", "industry_code"]).iloc[0]
    a = analyze(client, area_code=r["area_id"], interests=[r["industry_code"]])
    be = client.post(f"{API}/analyses/{a['id']}/breakeven", json={"industry_code": r["industry_code"], "cogs_rate": 0.3,
                                                                     "avg_ticket": 20_000})
    assert be.status_code == 200 and any("매출 데이터가 부족" in w for w in be.json()["warnings"])
