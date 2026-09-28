"""API 통합 테스트 (실데이터 25개 자치구 × 100개 업종, 2019Q1~2025Q2)."""
import json
import math
import httpx
import pytest
from sqlalchemy import func, select
from app import models as M
from app.services import areas as area_svc
from app.services.engine import get_state
from app.settings import settings
from miri_engine.config import MODEL_VERSION
from conftest import BASE_ANALYSIS, device

API = "/api/v1"


def analyze(client, headers=None, **over):
    body = {**BASE_ANALYSIS, **over}
    r = client.post(f"{API}/analyses", json=body, headers=headers or {})
    assert r.status_code == 201, r.text
    return r.json()


# ── 적재·배치 (UC-07) ──────────────────────────────────────────────────
def test_ingestion_all_sources_succeed(ingest_results, db):
    assert all(r["status"] == "SUCCESS" for r in ingest_results), ingest_results
    rows = {r["source"]: r["rows"] for r in ingest_results}
    assert rows["서울시 상권분석서비스(점포-자치구)"] == 64715
    assert rows["서울시 상권분석서비스(추정매출-자치구)"] == 39975
    assert db.scalar(select(M.CommercialArea).where(M.CommercialArea.boundary_geojson.is_(None))) is None
    assert len(list(db.scalars(select(M.Place)))) >= 100
    assert db.scalar(select(M.ScoringModelVersion).where(M.ScoringModelVersion.is_active)).model_version == f"{MODEL_VERSION}@20252"


def test_failed_file_is_logged_and_others_continue(tmp_path):
    """한 파일이 깨져도 나머지는 적재되고 실패 사유가 로그에 남는다(UC-07 대안 흐름)."""
    import shutil
    from app.db import Base, make_engine
    from sqlalchemy.orm import sessionmaker
    from app.services.ingest import run_ingestion
    from conftest import DATA_DIR
    d = tmp_path / "data"
    shutil.copytree(DATA_DIR, d)
    (d / "유동인구_자치구.csv").write_text("기준_년분기_코드,자치구_코드\n20251,11110\n", encoding="utf-8")
    eng = make_engine(f"sqlite:///{tmp_path}/x.db")
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng)() as s:
        res = run_ingestion(s, d, only=["boundary", "stores", "floating", "rent"], log=lambda *_: None)
        by = {r["source"]: r for r in res}
        assert by["서울시 상권분석서비스(길단위인구-자치구)"]["status"] == "FAIL"
        assert "총_유동인구_수" in by["서울시 상권분석서비스(길단위인구-자치구)"]["error"]
        assert by["서울시 우리마을가게 상권분석 임대시세(자치구)"]["status"] == "SUCCESS"
        logs = list(s.scalars(select(M.DataIngestionLog).where(M.DataIngestionLog.status == "FAIL")))
        assert len(logs) == 1 and logs[0].error_message


def test_blank_count_cell_is_zero_not_fail(tmp_path):
    import shutil
    import pandas as pd
    from app.db import Base, make_engine
    from sqlalchemy.orm import sessionmaker
    from app.services.ingest import run_ingestion
    from conftest import DATA_DIR
    d = tmp_path / "data"
    shutil.copytree(DATA_DIR, d)
    df = pd.read_csv(d / "점포_자치구.csv", encoding="utf-8-sig")
    df.loc[0, "프랜차이즈_점포_수"] = None
    df.to_csv(d / "점포_자치구.csv", index=False, encoding="utf-8-sig")
    eng = make_engine(f"sqlite:///{tmp_path}/y.db")
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng)() as s:
        res = run_ingestion(s, d, only=["boundary", "stores"], log=lambda *_: None)
    st = [r for r in res if "점포" in r["source"]][0]
    assert st["status"] == "SUCCESS" and "빈 개수 칸" in (st["note"] or "")


def test_db_trained_model_matches_csv_engine(db):
    """DB 원천 → 배치 모델이 CSV 직접 학습(백테스트 검증본)과 계수·점수까지 동일."""
    from miri_engine import pipeline as P, features as F
    from miri_engine.loaders import quarter_index as q
    from conftest import DATA_DIR
    st, sa, ar = P.load_district_data(str(DATA_DIR))
    panel = F.build_panel(st, sa, ar)
    model, eb, fe = P.train(panel, list(range(q(20204), q(20242) + 1)))
    stored = json.loads(db.scalar(select(M.ScoringModelVersion).where(M.ScoringModelVersion.is_active)).params_json)
    for k, v in model.beta.items():
        assert stored["beta"][k] == pytest.approx(v, abs=1e-12)
    assert stored["ref_quantiles"] == pytest.approx(model.ref_quantiles, abs=1e-12)


# ── 로그인 없음 · 브라우저 저장 키 (SB-01·09, 0.2) ─────────────────────────
def test_auth_endpoints_removed(client):
    """로그인이 없어졌다: 회원가입·로그인·내 정보 주소는 없고, 옛 로그인 토큰을 보내도 무시하고 그대로 쓴다."""
    for method, path in (("POST", "/auth/signup"), ("POST", "/auth/login"), ("GET", "/auth/me")):
        r = client.request(method, f"{API}{path}", json={"email": "a@example.com", "password": "password123"})
        assert r.status_code == 404 and r.json()["error"]["code"] == "HTTP_404", (path, r.text)
    r = client.post(f"{API}/analyses", json={**BASE_ANALYSIS}, headers={"Authorization": "Bearer expired.or.bad"})
    assert r.status_code == 201, r.text
    assert "is_guest" not in r.json() and "claim_token" not in r.json()
    assert client.get(f"{API}/analyses/{r.json()['id']}", headers={"Authorization": "Bearer x"}).status_code == 200


def test_device_key_required_and_validated(client):
    """저장 목록은 브라우저 저장 키(X-Device-Key)로 구분한다 — 없거나 형식이 틀리면 400(한국어 안내)."""
    r = client.get(f"{API}/me/reports")
    assert r.status_code == 400 and r.json()["error"]["code"] == "DEVICE_KEY_REQUIRED" and "브라우저" in r.json()["error"]["message"]
    assert client.get(f"{API}/me/reports", headers={"X-Device-Key": ""}).json()["error"]["code"] == "DEVICE_KEY_REQUIRED"
    for bad in ("short", "가".encode() * 40, "a" * 129, "a b" * 20, "abc/def+ghi=" * 4):
        r = client.get(f"{API}/me/reports", headers={"X-Device-Key": bad})
        assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_DEVICE_KEY", bad
    assert client.get(f"{API}/me/reports", headers={"X-Device-Key": "a" * 32}).status_code == 200      # 32~128자 영문·숫자·-·_
    assert client.get(f"{API}/me/reports", headers=device("fresh-browser")).json() == {"count": 0, "items": []}


# ── 상권 (SB-02) ───────────────────────────────────────────────────────
def test_place_search(client):
    r = client.get(f"{API}/places/search", params={"q": "홍대"})
    top = r.json()[0]
    assert top["name"] == "홍대입구역" and top["area_name"] == "마포구"
    r = client.get(f"{API}/places/search", params={"q": "강남"})
    assert r.json()[0]["name"] == "강남역" and r.json()[0]["area_name"] == "강남구"
    assert client.get(f"{API}/places/search", params={"q": " "}).status_code == 422


def test_candidates_radius(client):
    p = {"lat": 37.4981, "lng": 127.028, "place_name": "강남역"}
    c300 = client.get(f"{API}/areas/candidates", params={**p, "radius_m": 300}).json()
    assert c300["candidates"][0]["area_name"] == "강남구" and c300["candidates"][0]["is_center"]
    m = c300["candidates"][0]["metrics"]
    assert m["floating_daily"] > 0 and m["store_count"] > 0 and m["rent_per_3_3m2"] > 0
    c1k = client.get(f"{API}/areas/candidates", params={**p, "radius_m": 1000}).json()
    names = [c["area_name"] for c in c1k["candidates"]]
    assert "서초구" in names and len(names) >= len(c300["candidates"])
    r = client.get(f"{API}/areas/candidates", params={"lat": 35.1, "lng": 129.0, "radius_m": 500})
    assert r.status_code == 422 and r.json()["error"]["code"] == "OUT_OF_COVERAGE"


def test_map_geojson(client):
    fc = client.get(f"{API}/areas/map").json()
    assert len(fc["features"]) == 25
    n = sum(len(f["geometry"]["coordinates"][0]) for f in fc["features"])
    assert n < 3000


def test_compare(client):
    r = client.post(f"{API}/areas/compare", json={"area_codes": ["11680", "11440"], "industry_code": "CS100010"})
    d = r.json()
    assert r.status_code == 200 and len(d["areas"]) == 2 and all(a["industry"] for a in d["areas"])
    r = client.post(f"{API}/areas/compare", json={"area_codes": ["11680"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NEED_MORE_AREAS"


# ── 분석 (SB-03~05) ────────────────────────────────────────────────────
def test_analysis_top5(client):
    a = analyze(client, interests=["CS100010", "CS100008"])
    top = a["top"]
    assert 1 <= len(top) <= 5 and [t["rank"] for t in top] == list(range(1, len(top) + 1))
    s = [t["suitability"] for t in top]
    assert s == sorted(s, reverse=True)
    assert all(t["location_risk_pct"] < 90 for t in top)                 # 입지 위험 상위 10%는 TOP 제외
    assert all(t["eligible"] for t in top)
    assert {i["industry_code"] for i in a["interests"]} == {"CS100010", "CS100008"}
    assert a["weights"] == {"D": 0.25, "S": 0.5, "F": 0.25}
    assert "자치구" in a["area"]["scope_note"] and not any("상권 단위" in n for n in a["notices"])   # 분석 단위 안내는 맨 위에 한 번
    for t in top:
        assert t["reason_short"] and isinstance(t["chips"], list)
    again = client.get(f"{API}/analyses/{a['id']}").json()
    assert [t["industry_code"] for t in again["top"]] == [t["industry_code"] for t in top]


def test_analysis_food_only_applies_cost_fit(client):
    a = analyze(client, categories=["외식업"], interests=["CS100010"])
    assert a["f_applied"] is True
    assert all(t["category"] == "외식업" for t in a["top"])
    assert all(t["scores"]["F"] is not None for t in a["top"])


def test_licensed_industry_needs_license(client):
    a = analyze(client, interests=["CS300018"])          # 의약품 → 약사
    it = a["interests"][0]
    assert not it["eligible"] and "약사" in it["ineligible_reason"]
    assert all(t["industry_code"] != "CS300018" for t in a["top"])
    b = analyze(client, interests=["CS300018"], licenses=["약사"])
    assert b["interests"][0]["ineligible_reason"] != "약사 자격 필요"


def test_analysis_validation(client):
    body = {k: v for k, v in BASE_ANALYSIS.items() if k != "budget"}
    r = client.post(f"{API}/analyses", json=body)
    assert r.status_code == 422 and r.json()["error"]["message"] == "총 창업 예산을 입력해 주세요"
    r = client.post(f"{API}/analyses", json={**BASE_ANALYSIS, "initial_investment": 90_000_000})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_CONDITION"
    r = client.post(f"{API}/analyses", json={**BASE_ANALYSIS, "interests": ["CS999999"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNKNOWN_INDUSTRY"
    r = client.post(f"{API}/analyses", json={**BASE_ANALYSIS, "area_code": "99999"})
    assert r.status_code == 404
    r = client.post(f"{API}/analyses", json={**BASE_ANALYSIS, "labor_cost": -1})
    assert r.status_code == 422 and "예상 인건비" in r.json()["error"]["message"]


def test_goal_changes_weights(client):
    a = analyze(client, business_goal="고수익형")
    assert a["weights"]["D"] == 0.55


# ── 위험도 (SB-06) ────────────────────────────────────────────────────
def test_risk_detail(client):
    a = analyze(client)
    r = client.get(f"{API}/analyses/{a['id']}/risk/CS100010")
    d = r.json()
    assert r.status_code == 200
    cuts = d["grade_cuts"]
    g = "고위험" if d["risk_score"] >= cuts[2] else "높음" if d["risk_score"] >= cuts[1] else "보통" if d["risk_score"] >= cuts[0] else "낮음"
    assert d["risk_grade"] == g
    eff = [abs(f["effect_pct"]) for f in d["factors"]]
    assert eff == sorted(eff, reverse=True) and d["factors"][0]["factor_code"] == "ind_base"
    assert all(x["location_risk_pct"] < d["location_risk_pct"] for x in d["alternatives"])
    b = d["grade_rate_bounds"]
    assert b["보통"] < b["높음"] < b["고위험"]
    assert d["recheck"] == (d["risk_grade"] == "고위험")
    assert 0 < d["pred_annual_rate"] < 1 and d["summary"]


def test_risk_fallback_when_no_local_stores(client, db):
    st = get_state(db)
    have = set(zip(st.table["area_id"], st.table["industry_code"]))
    target = None
    for code in st.industries:
        if not st.industry_rows(code).empty:
            for ac in st.areas:
                if (ac, code) not in have:
                    target = (ac, code)
                    break
        if target:
            break
    assert target, "점포 없는 지역×업종 조합이 있어야 함"
    a = analyze(client, area_code=target[0])
    d = client.get(f"{API}/analyses/{a['id']}/risk/{target[1]}").json()
    assert d["fallback"] is True and d["confidence"] == "낮음"
    assert d["location_risk_pct"] is None and d["location_grade"] is None         # 같은 업종이 없으면 입지 비교값을 지어내지 않는다
    assert "입지 위험은" not in d["summary"] and all(x["location_grade"] == "낮음" for x in d["alternatives"])
    rep = client.post(f"{API}/analyses/{a['id']}/reports", json={"industry_code": target[1]})
    assert rep.status_code == 201
    rep = rep.json()
    assert "점포가 없어" in rep["one_line_summary"] and "진입해 볼 만" not in rep["one_line_summary"]
    assert rep["risk"]["location_risk_pct"] is None


# ── 손익분기 (SB-07) ──────────────────────────────────────────────────
def test_breakeven_defaults_and_override(client):
    a = analyze(client)
    r = client.post(f"{API}/analyses/{a['id']}/breakeven", json={"industry_code": "CS100008"})
    d = r.json()
    assert r.status_code == 200
    assert d["monthly_fixed_cost"] == 3_000_000 + 2_500_000
    assert d["operating_days"] == 26 and d["inputs"]["cogs_is_default"]
    assert d["required_daily_customers"] == math.ceil(d["required_monthly_sales"] / d["avg_ticket_used"] / 26)
    c = d["composition"]
    assert c["fixed_ex_owner"] + c["variable"] + c["owner_salary"] == pytest.approx(c["total"], abs=2)
    r2 = client.post(f"{API}/analyses/{a['id']}/breakeven",
                     json={"industry_code": "CS100008", "avg_ticket": 9000, "owner_salary": 3_000_000})
    d2 = r2.json()
    assert d2["avg_ticket_used"] == 9000 and d2["monthly_fixed_cost"] == d["monthly_fixed_cost"] + 3_000_000
    assert d2["composition"]["owner_salary"] == 3_000_000


def test_breakeven_requires_cogs_outside_food(client):
    a = analyze(client)
    r = client.post(f"{API}/analyses/{a['id']}/breakeven", json={"industry_code": "CS200028"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "COGS_REQUIRED"
    r = client.post(f"{API}/analyses/{a['id']}/breakeven", json={"industry_code": "CS200028", "cogs_rate": 0.15})
    assert r.status_code == 200
    r = client.post(f"{API}/analyses/{a['id']}/breakeven", json={"industry_code": "CS200028", "cogs_rate": 0.995})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VARIABLE_RATE_TOO_HIGH"


# ── 리포트·저장 (SB-08·09, UC-06) ─────────────────────────────────────
def test_report_and_save_flow(client):
    a = analyze(client, interests=["CS100010"])
    r = client.post(f"{API}/analyses/{a['id']}/reports", json={"industry_code": "CS100010"})
    rep = r.json()
    assert r.status_code == 201 and rep["one_line_summary"]
    assert 1 <= len(rep["checklist"]) <= 5 and [c["priority"] for c in rep["checklist"]] == list(range(1, len(rep["checklist"]) + 1))
    assert 1 <= len(rep["policies"]) <= 3 and all(p["apply_url"].startswith("https://") for p in rep["policies"])
    assert rep["risk"]["risk_grade"] and rep["breakeven"]["required_monthly_sales"] > 0
    assert client.get(f"{API}/reports/{rep['id']}").status_code == 200

    r = client.post(f"{API}/me/reports", json={"report_id": rep["id"]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "DEVICE_KEY_REQUIRED"   # 브라우저 저장 키 없이 → 저장 불가
    h = device("saver")
    r = client.post(f"{API}/me/reports", json={"report_id": rep["id"], "memo": "1순위"}, headers=h)
    assert r.status_code == 201
    saved_id = r.json()["saved_report_id"]
    again = client.post(f"{API}/me/reports", json={"report_id": rep["id"]}, headers=h)   # 중복 저장 → 같은 행
    assert again.json()["saved_report_id"] == saved_id
    lst = client.get(f"{API}/me/reports", headers=h).json()
    assert lst["count"] == 1 and lst["items"][0]["memo"] == "1순위"
    assert client.get(f"{API}/reports/{rep['id']}", headers=h).json()["saved_report_id"] == saved_id
    assert client.get(f"{API}/reports/{rep['id']}").json()["saved_report_id"] is None              # 키 없이 열면 저장 여부 모름
    assert client.get(f"{API}/reports/{rep['id']}", headers=device("not-saver")).json()["saved_report_id"] is None
    again = client.post(f"{API}/analyses/{a['id']}/reports", json={"industry_code": "CS100010"}, headers=h).json()
    assert again["id"] == rep["id"] and again["saved_report_id"] == saved_id                     # 같은 리포트 → 저장 표시도 그대로


def test_risk_revisit_after_report(client):
    """리포트가 위험도 평가를 참조한 뒤에도 위험도 화면을 다시 열 수 있어야 한다(FK 회귀)."""
    a = analyze(client, interests=["CS100010"])
    r1 = client.get(f"{API}/analyses/{a['id']}/risk/CS100010").json()
    rep = client.post(f"{API}/analyses/{a['id']}/reports", json={"industry_code": "CS100010"})
    assert rep.status_code == 201
    r2 = client.get(f"{API}/analyses/{a['id']}/risk/CS100010")
    assert r2.status_code == 200 and r2.json()["risk_score"] == r1["risk_score"]
    rep2 = client.post(f"{API}/analyses/{a['id']}/reports", json={"industry_code": "CS100010"})
    assert rep2.status_code == 201 and rep2.json()["risk"]["risk_score"] == r1["risk_score"]


def test_rent_display_consistent(client):
    a = analyze(client, interests=["CS100010"])
    card = client.get(f"{API}/areas/11680").json()["metrics"]["rent_per_3_3m2"]
    ref = {x["key"]: x for x in client.get(f"{API}/analyses/{a['id']}/risk/CS100010").json()["reference"]}
    assert ref["rent"]["value"] == card
    rep = client.post(f"{API}/analyses/{a['id']}/reports", json={"industry_code": "CS100010"}).json()
    rent_item = [c for c in rep["checklist"] if "임대료" in c["content"]][0]
    assert f"{card / 1e4:.1f}만원" in rent_item["content"]                   # 3.3㎡당 임대료는 소수 첫째 자리(10.6만원)
    assert ref["rent"]["display"] == f"{card / 1e4:.1f}만원"


def test_saved_reports_are_per_browser(client):
    """저장 목록은 브라우저(저장 키)마다 따로: 다른 브라우저는 내 목록을 보거나 지우거나 메모를 고칠 수 없다.
    리포트 자체는 링크를 아는 누구나 연다."""
    a = analyze(client, interests=["CS100008"])
    rep = client.post(f"{API}/analyses/{a['id']}/reports", json={"industry_code": "CS100008"}).json()
    mine, other = device("per-browser-mine"), device("per-browser-other")
    assert client.post(f"{API}/me/reports", json={"report_id": rep["id"], "memo": "후보"}, headers=mine).status_code == 201
    lst = client.get(f"{API}/me/reports", headers=mine).json()
    assert lst["count"] == 1
    it = lst["items"][0]
    assert it["industry_name"] == "분식전문점" and it["risk_grade"] and it["memo"] == "후보"
    assert client.get(f"{API}/me/reports", headers=other).json()["count"] == 0
    assert client.get(f"{API}/analyses/{a['id']}", headers=other).status_code == 200          # 링크를 알면 누구나
    assert client.get(f"{API}/reports/{rep['id']}", headers=other).status_code == 200
    sid = it["saved_report_id"]
    assert client.delete(f"{API}/me/reports/{sid}", headers=other).status_code == 404
    assert client.patch(f"{API}/me/reports/{sid}", json={"memo": "남의 메모"}, headers=other).status_code == 404
    assert client.get(f"{API}/me/reports", headers=mine).json()["items"][0]["memo"] == "후보"
    assert client.delete(f"{API}/me/reports/{sid}", headers=mine).status_code == 204
    assert client.get(f"{API}/me/reports", headers=mine).json()["count"] == 0


def test_delete_all_saved_only_this_browser(client):
    """'모두 지우기'(공용 컴퓨터 정리)는 이 브라우저의 저장 목록만 비운다 — 다른 브라우저의 목록·리포트는 그대로."""
    a = analyze(client, interests=["CS100010", "CS100008"])
    r1 = client.post(f"{API}/analyses/{a['id']}/reports", json={"industry_code": "CS100010"}).json()
    r2 = client.post(f"{API}/analyses/{a['id']}/reports", json={"industry_code": "CS100008"}).json()
    mine, other = device("wipe-mine"), device("wipe-other")
    for r in (r1, r2):
        assert client.post(f"{API}/me/reports", json={"report_id": r["id"], "memo": "공용 PC"}, headers=mine).status_code == 201
    assert client.post(f"{API}/me/reports", json={"report_id": r1["id"]}, headers=other).status_code == 201
    assert client.post(f"{API}/me/reports/clear").json()["error"]["code"] == "DEVICE_KEY_REQUIRED"
    # 단건 삭제 주소를 잘못 쓴 요청(끝 '/', id 없음·쿼리만)은 전체 삭제가 되지 않는다
    for bad in (client.delete(f"{API}/me/reports", headers=mine),
                client.delete(f"{API}/me/reports", params={"report_id": r1["id"]}, headers=mine),
                client.delete(f"{API}/me/reports/", headers=mine)):
        assert bad.status_code in (404, 405, 422), bad.status_code
    assert client.get(f"{API}/me/reports", headers=mine).json()["count"] == 2
    r = client.post(f"{API}/me/reports/clear", headers=mine)
    assert r.status_code == 200 and r.json() == {"deleted": 2}
    assert client.get(f"{API}/me/reports", headers=mine).json()["count"] == 0
    assert client.get(f"{API}/me/reports", headers=other).json()["count"] == 1
    assert client.get(f"{API}/reports/{r1['id']}").status_code == 200                 # 리포트 자체는 링크로 계속
    assert client.post(f"{API}/me/reports/clear", headers=mine).json() == {"deleted": 0}


def test_saving_a_shared_report_keeps_it_open_for_everyone(client):
    """링크로 받은 리포트를 다른 브라우저가 저장해도 만든 사람을 포함해 누구나 계속 열 수 있고, 각자의 목록에 따로 들어간다."""
    a = analyze(client, interests=["CS100010"])
    r1 = client.post(f"{API}/analyses/{a['id']}/reports", json={"industry_code": "CS100010"}).json()
    creator, friend = device("shared-creator"), device("shared-friend")
    assert client.post(f"{API}/me/reports", json={"report_id": r1["id"]}, headers=creator).status_code == 201
    assert client.post(f"{API}/me/reports", json={"report_id": r1["id"], "memo": "친구 것"}, headers=friend).status_code == 201
    assert client.get(f"{API}/analyses/{a['id']}").status_code == 200
    assert client.get(f"{API}/reports/{r1['id']}").status_code == 200
    items = [client.get(f"{API}/me/reports", headers=h).json()["items"] for h in (creator, friend)]
    assert [len(x) for x in items] == [1, 1] and items[0][0]["saved_report_id"] != items[1][0]["saved_report_id"]
    assert items[0][0]["memo"] is None and items[1][0]["memo"] == "친구 것"                   # 메모도 브라우저마다


def test_legacy_member_analysis_stays_hidden(client, db):
    """이전 버전에서 회원이 만든 분석·리포트(user_id 있음)는 주인이 더는 로그인할 수 없으므로 링크로도 열리지 않는다."""
    a = analyze(client, interests=["CS100010"])
    rep = client.post(f"{API}/analyses/{a['id']}/reports", json={"industry_code": "CS100010"}).json()
    h = device("legacy-owner")
    assert client.post(f"{API}/me/reports", json={"report_id": rep["id"]}, headers=h).status_code == 201
    u = M.User(email="legacy-member@example.com", password_hash="x", name="", role="PRE_FOUNDER")
    db.add(u)
    db.flush()
    db.scalar(select(M.AnalysisRequest).where(M.AnalysisRequest.public_id == a["id"])).user_id = u.user_id
    db.commit()
    assert client.get(f"{API}/analyses/{a['id']}").status_code == 404
    assert client.get(f"{API}/analyses/{a['id']}/risk/CS100010").status_code == 404
    assert client.post(f"{API}/analyses/{a['id']}/reports", json={"industry_code": "CS100010"}).status_code == 404
    assert client.get(f"{API}/reports/{rep['id']}").status_code == 404
    act = rep["checklist"][0]["action_id"]
    assert client.patch(f"{API}/reports/{rep['id']}/items/{act}", json={"done": True}).status_code == 404
    assert client.get(f"{API}/me/reports", headers=h).json()["count"] == 0            # 저장 목록에서도 빠진다
    assert client.post(f"{API}/me/reports", json={"report_id": rep["id"]}, headers=h).status_code == 404


def test_zero_fixed_cost_does_not_crash(client):
    a = analyze(client, monthly_rent_limit=0, labor_cost=0, categories=["외식업"])
    assert a["top"] and a["f_applied"] is True and all(t["scores"]["F"] == 100.0 for t in a["top"])
    be = client.post(f"{API}/analyses/{a['id']}/breakeven", json={"industry_code": "CS100001"})
    assert be.status_code == 200 and be.json()["required_monthly_sales"] == 0 and be.json()["cost_pressure"] == "여유"
    assert client.post(f"{API}/analyses/{a['id']}/reports", json={"industry_code": "CS100001"}).status_code == 201


def test_purge_legacy_accounts_removes_only_old_account_data(client, db, tmp_path):
    """(선택) 0.1 계정 정리: 계정·회원 분석(딸린 리포트까지)·계정 저장 목록·소유 확인 해시만 지우고, 새 분석·브라우저 저장은 그대로."""
    import sqlite3
    from sqlalchemy.orm import sessionmaker
    from app.db import make_engine
    from app.services.maintenance import purge_legacy_accounts
    from conftest import _TMP
    keep = analyze(client, interests=["CS100010"])
    krep = client.post(f"{API}/analyses/{keep['id']}/reports", json={"industry_code": "CS100010"}).json()
    assert client.post(f"{API}/me/reports", json={"report_id": krep["id"]}, headers=device("purge-keep")).status_code == 201
    old = analyze(client, interests=["CS100008"])
    orep = client.post(f"{API}/analyses/{old['id']}/reports", json={"industry_code": "CS100008"}).json()
    u = M.User(email="purge-member@example.com", password_hash="scrypt$x", name="옛 회원", role="OWNER")
    db.add(u)
    db.flush()
    db.scalar(select(M.AnalysisRequest).where(M.AnalysisRequest.public_id == old["id"])).user_id = u.user_id
    rep_row = db.scalar(select(M.ActionReport).where(M.ActionReport.public_id == orep["id"]))
    db.add(M.SavedReport(user_id=u.user_id, report_id=rep_row.report_id, memo="옛 메모"))
    db.scalar(select(M.AnalysisRequest).where(M.AnalysisRequest.public_id == keep["id"])).claim_token_hash = "0" * 64
    db.commit()
    copy = tmp_path / "purge.db"
    with sqlite3.connect(f"{_TMP}/test.db") as src, sqlite3.connect(copy) as dst:
        src.backup(dst)
    eng = make_engine(f"sqlite:///{copy}")
    S = sessionmaker(bind=eng)
    try:
        with S() as s:
            n = purge_legacy_accounts(s)                                    # 기본은 세기만
            assert n["users"] >= 1 and n["member_analyses"] >= 1 and n["member_saved"] >= 1 and n["claim_hashes"] >= 1
            assert s.scalar(select(func.count()).select_from(M.User)) == n["users"]
            purge_legacy_accounts(s, apply=True)
        with S() as s:
            assert s.scalar(select(func.count()).select_from(M.User)) == 0
            assert s.scalar(select(M.AnalysisRequest).where(M.AnalysisRequest.public_id == old["id"])) is None
            assert s.scalar(select(M.ActionReport).where(M.ActionReport.public_id == orep["id"])) is None   # 딸린 리포트까지
            kept = s.scalar(select(M.AnalysisRequest).where(M.AnalysisRequest.public_id == keep["id"]))
            assert kept is not None and kept.claim_token_hash is None
            assert s.scalar(select(func.count()).select_from(M.SavedReport).where(M.SavedReport.user_id.is_not(None))) == 0
            import hashlib
            kh = hashlib.sha256(device("purge-keep")["X-Device-Key"].encode()).hexdigest()   # 브라우저 저장은 그대로
            krow = s.scalar(select(M.ActionReport).where(M.ActionReport.public_id == krep["id"]))
            assert s.scalar(select(M.SavedReport).where(M.SavedReport.device_key_hash == kh,
                                                        M.SavedReport.report_id == krow.report_id)) is not None
        raw = sqlite3.connect(copy)
        assert raw.execute("PRAGMA foreign_key_check").fetchall() == []
        raw.close()
    finally:
        eng.dispose()


def test_bad_device_key_on_report_view_is_400_not_silent(client):
    """리포트 조회에 형식이 틀린 저장 키를 보내면 조용히 '저장 안 함'으로 보이지 않게 400. 키가 없으면 그냥 열린다."""
    a = analyze(client, interests=["CS100010"])
    rep = client.post(f"{API}/analyses/{a['id']}/reports", json={"industry_code": "CS100010"}).json()
    r = client.get(f"{API}/reports/{rep['id']}", headers={"X-Device-Key": "bad key"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_DEVICE_KEY"
    assert client.get(f"{API}/reports/{rep['id']}").status_code == 200


def test_alternative_respects_licenses(client):
    a = analyze(client, area_code="11545", monthly_rent_limit=30_000_000, interests=["CS200016"])
    rep = client.post(f"{API}/analyses/{a['id']}/reports", json={"industry_code": "CS200016"}).json()
    text = rep["one_line_summary"] + " ".join(c["content"] for c in rep["checklist"])
    for licensed in ("치과의원", "일반의원", "한의원", "변호사사무소", "약국", "의약품"):
        assert licensed not in text


def test_missing_interest_and_notices_persist(client):
    a = analyze(client, area_code="11470", interests=["CS200036", "CS100001"])
    assert [m["industry_code"] for m in a["missing_interests"]] == ["CS200036"]
    assert not any("고시원" in n for n in a["notices"])                     # 누락 안내는 관심 업종 카드에서 한 번만
    again = client.get(f"{API}/analyses/{a['id']}").json()
    assert again["notices"] == a["notices"] and again["missing_interests"] == a["missing_interests"]


def test_saved_breakeven_roundtrip(client):
    a = analyze(client)
    be = client.post(f"{API}/analyses/{a['id']}/breakeven", json={"industry_code": "CS100008", "avg_ticket": 9000}).json()
    got = client.get(f"{API}/analyses/{a['id']}/breakeven/{be['id']}").json()
    assert got["required_monthly_sales"] == be["required_monthly_sales"] and got["inputs"]["avg_ticket"] == 9000
    other = analyze(client)
    assert client.get(f"{API}/analyses/{other['id']}/breakeven/{be['id']}").status_code == 404


def test_huge_ids_are_422_not_500(client):
    a = analyze(client)
    r = client.post(f"{API}/analyses/{a['id']}/reports", json={"industry_code": "CS100008", "break_even_id": 10 ** 20})
    assert r.status_code == 422
    h = device("ids")
    assert client.delete(f"{API}/me/reports/{10 ** 20}", headers=h).status_code == 422
    assert client.post(f"{API}/analyses/{a['id']}/breakeven", json={"industry_code": "CS100008", "avg_ticket": 1}).status_code == 422


def test_user_type_from_request_picks_policies(client):
    """사용자 유형은 시작 화면(SB-01)에서 고른 값(user_type)으로: 예비창업자 전용 지원사업이 자영업자에게 나오지 않고 반대도 같다."""
    reps = {}
    for ut in ("PRE_FOUNDER", "OWNER", "CONSULTANT"):
        a = analyze(client, user_type=ut, interests=["CS100001"])
        assert a["conditions"]["user_type"] == ut
        reps[ut] = client.post(f"{API}/analyses/{a['id']}/reports", json={"industry_code": "CS100001"}).json()
        assert reps[ut]["policies"], ut
    targets = {ut: {p["target_user"] for p in r["policies"]} for ut, r in reps.items()}
    assert "자영업자" not in targets["PRE_FOUNDER"] and "예비창업자" not in targets["OWNER"]


def test_admin_needs_admin_key(client, monkeypatch):
    """로그인이 없으므로 관리자 API는 서버의 MIRI_ADMIN_KEY와 같은 X-Admin-Key 헤더로만 — 지정하지 않은 서버는 꺼져 있다."""
    r = client.get(f"{API}/admin/ingestion-logs")
    assert r.status_code == 403 and r.json()["error"]["code"] == "ADMIN_DISABLED"
    assert client.post(f"{API}/admin/refresh", headers={"X-Admin-Key": "k" * 40}).json()["error"]["code"] == "ADMIN_DISABLED"
    monkeypatch.setattr(settings, "admin_key", "k" * 40)
    r = client.post(f"{API}/admin/refresh")
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
    assert client.get(f"{API}/admin/ingestion-logs", headers={"X-Admin-Key": "x" * 40}).status_code == 403
    assert client.get(f"{API}/admin/ingestion-logs", headers={"X-Admin-Key": "관리자".encode()}).status_code == 403
    r = client.get(f"{API}/admin/ingestion-logs", headers={"X-Admin-Key": "k" * 40})
    assert r.status_code == 200 and r.json() and r.json()[0]["status"] in ("SUCCESS", "FAIL")


# ── 외부 검색(선택) ───────────────────────────────────────────────────
def test_kakao_search_mocked(db, monkeypatch):
    st = get_state(db)
    monkeypatch.setattr(settings, "kakao_rest_key", "dummy")

    def handler(req: httpx.Request):
        assert req.headers["Authorization"] == "KakaoAK dummy"
        return httpx.Response(200, json={"documents": [
            {"place_name": "성수연방", "x": "127.0535", "y": "37.5446", "road_address_name": "서울 성동구 성수이로14길 14"},
            {"place_name": "부산역", "x": "129.0413", "y": "35.1151"}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = area_svc.search_kakao(st, "성수", client=c)
    assert len(out) == 1 and out[0]["area_name"] == "성동구" and out[0]["source"] == "kakao"

    def fail(req):
        return httpx.Response(500)
    with httpx.Client(transport=httpx.MockTransport(fail)) as c:
        assert area_svc.search_kakao(st, "성수", client=c) == []


def test_meta(client):
    m = client.get(f"{API}/meta").json()
    assert m["data_quarter"] == 20252 and m["analysis_level"] == "district"
    ind = client.get(f"{API}/industries").json()
    assert len(ind["groups"]) == 6 and len(ind["industries"]) == 100
    assert ind["groups"][3]["names"] == ["치킨전문점", "호프-간이주점"]


def test_old_db_gets_new_columns(tmp_path):
    """이전 버전 DB(새 컬럼 없음)도 서버 시작 시 자동으로 컬럼이 추가돼 분석이 된다."""
    import sqlite3
    from sqlalchemy import inspect
    from app.db import make_engine, migrate
    from conftest import _TMP
    src = f"{_TMP}/test.db"
    old = tmp_path / "old.db"
    with sqlite3.connect(src) as a, sqlite3.connect(old) as b:
        a.backup(b)
    with sqlite3.connect(old) as c:            # 이전 스키마 흉내: 새 컬럼 제거
        c.execute("ALTER TABLE analysis_requests DROP COLUMN claim_token_hash")
        c.execute("ALTER TABLE analysis_requests DROP COLUMN notices_json")
    eng = make_engine(f"sqlite:///{old}")
    assert "claim_token_hash" not in {c["name"] for c in inspect(eng).get_columns("analysis_requests")}
    assert set(migrate(eng)) == {"analysis_requests.claim_token_hash", "analysis_requests.notices_json"}
    cols = {c["name"] for c in inspect(eng).get_columns("analysis_requests")}
    assert {"claim_token_hash", "notices_json"} <= cols and migrate(eng) == []


def test_short_or_placeholder_admin_key_rejected(monkeypatch):
    from app.settings import Settings
    for bad in ("여기에-32자-이상-임의-문자열을-넣으세요-관리자-키-예시", "short-key", "change-me-" + "x" * 30,
                "관리자" * 12, "x" * 20 + " " + "x" * 20, "é" * 40):     # 헤더로 보낼 수 없는 값(한글·공백·비ASCII)도
        monkeypatch.setenv("MIRI_ADMIN_KEY", bad)
        with pytest.raises(RuntimeError):
            Settings()
    monkeypatch.setenv("MIRI_ADMIN_KEY", "x" * 40)
    assert Settings().admin_key == "x" * 40
    monkeypatch.delenv("MIRI_ADMIN_KEY")
    assert Settings().admin_key == ""                                   # 비워 두면 관리자 API만 꺼지고 서버는 뜬다
