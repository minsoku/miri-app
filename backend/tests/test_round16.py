"""16차 검토 회귀 테스트: 주의 업종 표시는 추천 조건을 통과한 업종에만, 고위험인데 손익분기를 빠듯하게 넘는 한줄 결론과
체크리스트 '빠듯' 항목, 카드 근거 칩(목표 월수입·참고용), 서울 밖 1km 경계 표기, 화면 주소 직접 열기."""
import pytest
from app.services import narrative as N
from test_round5 import analyze, report

API = "/api/v1"


def test_ineligible_interest_is_not_marked_caution(client):
    a = analyze(client, area_code="11680", budget=100_000_000, monthly_rent_limit=30_000_000, labor_cost=5_000_000,
                interests=["CS100005"])
    it = next(i for i in a["interests"] if i["industry_code"] == "CS100005")
    rep = report(client, a["id"], "CS100005")
    if not it["eligible"] and it["location_risk_pct"] >= 90:
        assert rep["recommendation"]["eligible"] is False
        assert rep["recommendation"]["caution"] is False, rep["recommendation"]


def test_tight_high_risk_summary():
    f = {"industry_name": "한식음식점", "risk_grade": "높음", "pred_annual_rate": 0.1, "location_risk_pct": 40}
    s = N.one_liner("강남구", f, None, {"achievability_ratio": 1.05, "cost_pressure": "빠듯", "composition": {}})
    assert "여유가 적어요" in s and "1.05배" in s, s
    f["risk_grade"] = "고위험"
    s = N.one_liner("강남구", f, None, {"achievability_ratio": 1.05, "cost_pressure": "빠듯", "composition": {}})
    assert "여유가 적어 창업 재검토를 권해요" in s, s


def test_tight_report_has_cost_check_item(client):
    a = analyze(client, area_code="11305", budget=100_000_000, monthly_rent_limit=1_000_000, labor_cost=2_000_000)
    it = next((i for i in a["top"] + a["cautions"] if i["achievability_ratio"] is not None and 1 <= i["achievability_ratio"] < 1.15), None)
    if it is None:
        pytest.skip("빠듯한 업종이 없음")
    rep = report(client, a["id"], it["industry_code"])
    if rep["breakeven"] is not None:
        assert "여유가 적" in rep["one_line_summary"], rep["one_line_summary"]
        assert any("여유가 적어요" in c["content"] for c in rep["checklist"]), rep["checklist"]


def test_reason_chips_name_the_basis():
    base = {"achievability_ratio": 1.4}
    assert "평균 매출이 손익분기의 1.40배" in N.reason_chips(base)
    chips = N.reason_chips({**base, "owner_included": True})
    assert any("필요 매출(목표 월수입 포함)의 1.40배" in c for c in chips), chips
    chips = N.reason_chips({**base, "sales_outlier": 4.2})
    assert any(c.endswith("(참고용)") for c in chips), chips


def test_outside_seoul_kilometre_boundary(client):
    # 경계까지 999.5m 이상이면 '1000m'가 아니라 '1.0km', 그보다 가까우면 m
    near = dict(lat=37.55, radius_m=300)
    r = client.get(f"{API}/areas/candidates", params={**near, "lng": 126.75558066952973}).json()
    assert "1.0km" in r["notice"] and "1000m" not in r["notice"], r["notice"]
    r = client.get(f"{API}/areas/candidates", params={**near, "lng": 126.75558066954835}).json()
    assert "999m" in r["notice"], r["notice"]


def test_spa_paths_redirect_to_hash_routes(tmp_path):
    # 테스트 앱은 프론트엔드 빌드 없이 뜨므로, 가짜 빌드 폴더로 새 프로세스를 띄워 확인
    import os, subprocess, sys, textwrap
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>MIRI</title>", encoding="utf-8")
    code = textwrap.dedent("""
        from fastapi.testclient import TestClient
        from app.main import app
        c = TestClient(app)
        r = c.get("/reports", follow_redirects=False)
        assert r.status_code in (302, 307) and r.headers["location"].endswith("/#/reports"), (r.status_code, r.headers)
        assert c.get("/").status_code == 200
        r = c.get("/api/v1/no-such-endpoint")
        assert r.status_code == 404 and r.json()["error"]["code"] == "HTTP_404", r.text
        r = c.post("/api/v1/no-such-endpoint", json={})                  # 다른 방식도 한국어 JSON 404
        assert r.status_code == 404 and r.json()["error"]["message"] == "요청한 주소를 찾을 수 없어요", r.text
        r = c.get("/api/v1/analyses")                                      # POST 전용 → 405(한국어)
        assert r.status_code == 405 and "요청할 수 없어요" in r.json()["error"]["message"], r.text
        r = c.get("/reports?from=%2Farea", follow_redirects=False)          # 검색어 유지
        assert r.headers["location"].endswith("/#/reports?from=%2Farea"), r.headers
        assert c.head("/reports", follow_redirects=False).status_code in (302, 307)
        r = c.get("/api/v1/industries/", follow_redirects=False)            # 끝 '/'는 원래처럼 주소 정리
        assert r.status_code == 307, r.status_code
        assert c.get("/assets/none.js").status_code == 404
        r = c.get("/api", follow_redirects=False)                          # '/api'도 화면 주소가 아니라 JSON 404
        assert r.status_code == 404 and r.json()["error"]["code"] == "HTTP_404", r.text
        print("ok")
    """)
    env = {**os.environ, "MIRI_FRONTEND_DIST": str(tmp_path)}
    out = subprocess.run([sys.executable, "-c", code], cwd=os.path.dirname(os.path.dirname(__file__)), env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0 and "ok" in out.stdout, out.stderr[-2000:]
