"""API 퍼징: 모든 엔드포인트에 무작위·경계·잘못된 입력을 대량으로 보내 서버 오류(5xx)·형식 위반을 찾는다.
실행: (서버 실행 중) python e2e/fuzz_api.py http://127.0.0.1:8000 [요청수] [시드] [gentle]
검사: ① 5xx 없음 ② 오류 본문 형식 {"error":{"code","message"}} ③ 정상 응답의 불변식(순위·등급·비율 범위·NaN 없음)
     ④ 저장 목록은 브라우저 저장 키(X-Device-Key)마다 따로 — 다른 키의 저장 항목이 섞이거나 빠지지 않음"""
import json
import math
import random
import string
import sys
import uuid
from collections import Counter

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/") + "/api/v1"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
rnd = random.Random(int(sys.argv[3]) if len(sys.argv) > 3 else 1)
GENTLE = len(sys.argv) > 4 and sys.argv[4] == "gentle"      # 대부분 정상 입력 → 성공 경로(손익분기·리포트·저장)를 더 많이 탐색
c = httpx.Client(timeout=30)
violations: list[str] = []
stats: Counter = Counter()

AREAS = [a["area_code"] for a in c.get(f"{BASE}/areas/candidates", params={"lat": 37.5663, "lng": 126.9779, "radius_m": 5000}).json()["candidates"]]
AREAS = sorted(set(AREAS + ["11680", "11440", "11110", "11470", "11545"]))
INDS = [i["code"] for i in c.get(f"{BASE}/industries").json()["industries"]]
WEIRD_STR = ["", " ", "\t", "0", "-1", "1e309", "NaN", "Infinity", "null", "true", "강남", "홍대", "' OR 1=1 --", "<script>alert(1)</script>",
             "%00", "../../etc/passwd", "😀" * 5, "가" * 200, "a" * 5000, "‮", "１２３", "SELECT * FROM users"]
WEIRD_NUM = [0, -1, 1, 0.5, -0.0, 99, 100, 101, 999, 2 ** 31, 2 ** 53, 2 ** 63, 2 ** 64, 10 ** 20, 1e308, 1e-9, 99_999_999_999,
             100_000_000_000, 100_000_000_001, 0.3, 0.30000001, 1.0, 0.999999]


def weird():
    k = rnd.random()
    if k < 0.35:
        return rnd.choice(WEIRD_NUM)
    if k < 0.6:
        return rnd.choice(WEIRD_STR)
    return rnd.choice([None, [], {}, [1, 2], {"a": 1}, True, False, ["CS100010"] * 3])


def rand_money():
    return rnd.choice([0, rnd.randrange(0, 50_000) * 10_000, rnd.randrange(0, 10 ** 11), 10 ** 11])


def base_analysis():
    return {"area_code": rnd.choice(AREAS), "budget": rand_money(), "monthly_rent_limit": rand_money(),
            "labor_cost": rand_money(), "initial_investment": rnd.choice([0, rand_money()]),
            "other_fixed": rnd.choice([0, rand_money()]), "owner_salary": rnd.choice([0, rand_money()]),
            "loan_amount": rnd.choice([0, rand_money()]), "loan_rate_annual": rnd.choice([0, 0.05, 0.3, 0.2999]),
            "business_goal": rnd.choice(["기본", "안정형", "고수익형", "저비용형"]),
            "user_type": rnd.choice(["PRE_FOUNDER", "OWNER", "CONSULTANT"]),
            "interests": rnd.sample(INDS, rnd.choice([0, 1, 2, 5])),
            "categories": rnd.choice([[], ["외식업"], ["서비스업"], ["소매업"], ["외식업", "소매업"]]),
            "licenses": rnd.choice([[], ["약사"], ["미용사(일반)", "세무사"]]),
            "radius_m": rnd.choice([None, 100, 500, 5000]), "place_name": rnd.choice([None, "강남역", "가" * 100]),
            "lat": rnd.choice([None, 37.5, 33, 39]), "lng": rnd.choice([None, 127.0, 124, 132])}


def mutate(body: dict, n=None):
    b = dict(body)
    for _ in range(n if n is not None else rnd.choice([0, 0, 0, 0, 0, 0, 0, 1] if GENTLE else [0, 0, 1, 1, 2, 3])):
        k = rnd.choice(list(b.keys()) + ["unknown_field"])
        r = rnd.random()
        if r < 0.15:
            b.pop(k, None)
        else:
            b[k] = weird()
    return b


def no_nan(o, path="$"):
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return path
    if isinstance(o, dict):
        for k, v in o.items():
            p = no_nan(v, f"{path}.{k}")
            if p:
                return p
    if isinstance(o, list):
        for i, v in enumerate(o):
            p = no_nan(v, f"{path}[{i}]")
            if p:
                return p
    return None


def check(name, r, body=None, invariants=None):
    stats[(name, r.status_code)] += 1
    ctx = f"{name} {r.request.method} {r.request.url.path}{'?' + r.request.url.query.decode() if r.request.url.query else ''} body={json.dumps(body, ensure_ascii=False, default=str)[:300]}"
    if r.status_code >= 500:
        violations.append(f"5xx {r.status_code} · {ctx} · {r.text[:200]}")
        return None
    try:
        data = r.json() if r.content else None
    except ValueError:
        violations.append(f"JSON 아님 · {ctx} · {r.text[:120]}")
        return None
    if r.status_code >= 400:
        err = (data or {}).get("error") if isinstance(data, dict) else None
        if not err or not err.get("code") or not err.get("message"):
            violations.append(f"오류 형식 위반 {r.status_code} · {ctx} · {str(data)[:160]}")
        elif not any("가" <= ch <= "힣" for ch in err["message"]):
            violations.append(f"한국어 아닌 오류 메시지 {r.status_code} · {ctx} · {err['message'][:120]}")
        return None
    p = no_nan(data)
    if p:
        violations.append(f"NaN/Inf 값 {p} · {ctx}")
    if invariants:
        try:
            for msg in invariants(data) or []:
                violations.append(f"불변식 위반: {msg} · {ctx}")
        except Exception as e:  # noqa: BLE001
            violations.append(f"불변식 검사 오류 {type(e).__name__}: {e} · {ctx}")
    return data


GRADE = lambda s: "고위험" if s >= 90 else "높음" if s >= 70 else "보통" if s >= 40 else "낮음"  # noqa: E731


def inv_analysis(a):
    out = []
    top = a["top"]
    if [t["rank"] for t in top] != list(range(1, len(top) + 1)):
        out.append("TOP 순위가 1..n이 아님")
    s = [t["suitability"] for t in top]
    if any(x is None for x in s) or s != sorted(s, reverse=True):
        out.append(f"적합도 내림차순 아님 {s}")
    for it in top + a["interests"] + a["cautions"]:
        if it["risk_grade"] != GRADE(it["risk_score"]):
            out.append(f"등급 불일치 {it['industry_code']} {it['risk_score']}→{it['risk_grade']}")
        if not (0 <= it["pred_annual_rate"] <= 1):
            out.append(f"폐업률 범위 {it['pred_annual_rate']}")
        if it["suitability"] is not None and not (0 <= it["suitability"] <= 100):
            out.append(f"적합도 범위 {it['suitability']}")
        for k in ("D", "S", "F"):
            v = it["scores"][k]
            if v is not None and not (0 <= v <= 100):
                out.append(f"{k} 범위 {v}")
    if any(t["location_risk_pct"] >= 90 for t in top):
        out.append("TOP에 입지위험 90 이상")
    if any(not t["eligible"] for t in top):
        out.append("TOP에 부적격 업종")
    if bool(top) == bool(a.get("empty_reason")):
        out.append(f"추천 0개 이유 표시 불일치 top={len(top)} empty_reason={a.get('empty_reason')!r}")
    for it in a["interests"]:
        if it["suitability"] is None and not it.get("score_note"):
            out.append(f"적합도 없음인데 이유 없음 {it['industry_code']}")
        if "상위" in it["reason_short"]:
            out.append(f"매출을 백분위로 표시 {it['reason_short'][:40]}")
    return out


def inv_risk(r):
    out = []
    if r["risk_grade"] != GRADE(r["risk_score"]):
        out.append("위험 등급 불일치")
    if r["fallback"]:
        if r["location_risk_pct"] is not None or r["location_grade"] is not None:
            out.append("점포 없는 지역인데 입지 위험 값이 있음")
    elif r["location_grade"] != GRADE(r["location_risk_pct"]):
        out.append("입지 등급 불일치")
    for x in r["alternatives"]:
        if x["distance_km"] > 7.0 or x["location_grade"] != GRADE(x["location_risk_pct"]):
            out.append(f"대안 지역 거리·등급 {x}")
    if "비교해도" in r["summary"]:
        out.append("요약 문구")
    effs = [abs(f["effect_pct"]) for f in r["factors"]]
    if effs != sorted(effs, reverse=True):
        out.append("요인 정렬")
    return out


def inv_be(b):
    out = []
    if b["required_monthly_sales"] < 0 or b["required_daily_customers"] < 0:
        out.append("음수 손익분기")
    if not (0 <= b["variable_cost_rate"] < 1):
        out.append(f"변동비율 범위 {b['variable_cost_rate']}")
    c_ = b["composition"]
    if abs(c_["fixed_ex_owner"] + c_["variable"] + c_["owner_salary"] - c_["total"]) > 3:
        out.append(f"구성 합 불일치 {c_}")
    ratio = b.get("achievability_ratio")
    if ratio is not None:
        band = "위험" if ratio < 1.0 else "빠듯" if ratio < 1.15 else "보통" if ratio < 1.3 else "여유"
        if b["cost_pressure"] != band:
            out.append(f"달성배율 {ratio} ↔ {b['cost_pressure']}")
    if any("→" in w for w in b["warnings"]):
        out.append("개발자식 안내 문구")
    return out


def inv_report(rep):
    out = []
    s, risk, be = rep["one_line_summary"], rep.get("risk") or {}, rep.get("breakeven") or {}
    bad = (risk.get("risk_grade") in ("높음", "고위험") or (risk.get("location_risk_pct") or 0) >= 90
           or (be.get("achievability_ratio") is not None and be["achievability_ratio"] < 1))
    if bad and "진입을 검토해 볼 만해요" in s:
        out.append(f"위험 신호가 있는데 진입 권유: {s[:80]}")
    if "적자" in s and be.get("achievability_ratio") is not None and be["achievability_ratio"] >= 1:
        out.append("손익분기 넘는데 적자 표현")
    return out


analyses: list[str] = []
reports: list[str] = []
bes: list[tuple[str, int]] = []
# 로그인 대신 브라우저 저장 키: 이번 실행에서만 쓰는 키 4개(서로의 저장 목록이 섞이지 않는지 본다) + 형식이 틀린 키
RUN = uuid.uuid4().hex[:12]                                     # 실행마다 새 키(같은 시드로 다시 돌려도 이전 실행의 저장이 섞이지 않게)
DEVICES = [f"fuzz-{RUN}-browser-{k}-{'x' * 20}" for k in range(4)]
BAD_KEYS = ["short", "a" * 129, "a b c d e f g h i j k l m n o p", "abc/def+ghi=" * 4, "a" + " " * 38 + "a", "%41" * 20]   # 앞뒤 공백은 HTTP가 못 보냄
saved: dict[str, dict[int, str]] = {d: {} for d in DEVICES}     # 키별로 서버에 저장돼 있어야 하는 항목(저장 번호 → 리포트)


def pick_headers():
    r = rnd.random()
    if r < 0.6:
        return {"X-Device-Key": rnd.choice(DEVICES)}
    if r < 0.7:
        return {"X-Device-Key": rnd.choice(BAD_KEYS)}
    if r < 0.75:                                                 # 0.1의 로그인 토큰을 보내도 무시돼야
        return {"Authorization": rnd.choice(["Bearer x", "Basic abc", "Bearer", "bearer " + "a" * 500, "Bearer a.b.c"])}
    return {}


for i in range(N):
    op = rnd.choices(["search", "cand", "area", "compare", "analysis", "get", "risk", "be", "be_get", "report", "report_get",
                      "save", "mylist", "delete", "memo", "wipe", "admin", "meta"],
                     weights=[6, 6, 3, 3, 20, 4, 10, 10, 3, 8, 4, 8, 4, 3, 2, 1, 1, 1])[0]
    hdr = pick_headers()
    dev = hdr.get("X-Device-Key") if hdr.get("X-Device-Key") in saved else None
    if op == "search":
        q = rnd.choice(WEIRD_STR + ["강남", "역", "구", "서울", "DMC"])
        check(op, c.get(f"{BASE}/places/search", params={"q": q, "limit": rnd.choice([1, 8, 20, 0, 21, "x"])}), q)
    elif op == "cand":
        p = {"lat": rnd.choice([37.5, 37.4981, 33, 39, 32.9, "x", 36.0, 37.7]), "lng": rnd.choice([127.0, 127.028, 124, 132, 200, "y"]),
             "radius_m": rnd.choice([100, 300, 500, 1000, 5000, 99, 5001, -1, "z"]), "place_name": rnd.choice([None, "가" * 101, "테스트"])}
        check(op, c.get(f"{BASE}/areas/candidates", params={k: v for k, v in p.items() if v is not None}), p)
    elif op == "area":
        code = rnd.choice(AREAS + ["", "0", "99999", "' or 1", "a" * 300])
        check(op, c.get(f"{BASE}/areas/{code}") if code else c.get(f"{BASE}/areas/%20"))
    elif op == "compare":
        body = mutate({"area_codes": rnd.sample(AREAS, rnd.choice([1, 2, 3, 4])), "industry_code": rnd.choice([None, *INDS[:5], "X"])})
        check(op, c.post(f"{BASE}/areas/compare", json=body), body)
    elif op == "analysis":
        body = mutate(base_analysis())
        d = check(op, c.post(f"{BASE}/analyses", json=body, headers=hdr), body, inv_analysis)
        if d:
            analyses.append(d["id"])
    elif op == "get":
        aid = rnd.choice(analyses + [str(uuid.uuid4()), "x", "a" * 100]) if analyses else str(uuid.uuid4())
        check(op, c.get(f"{BASE}/analyses/{aid}", headers=hdr), None, inv_analysis)
    elif op == "risk" and analyses:
        code = rnd.choice(INDS + ["CS999999", "", "x" * 50])
        check(op, c.get(f"{BASE}/analyses/{rnd.choice(analyses)}/risk/{code or '%20'}", headers=hdr), code, inv_risk)
    elif op == "be" and analyses:
        aid = rnd.choice(analyses)
        body = mutate({"industry_code": rnd.choice(INDS), "monthly_rent": rnd.choice([None, rand_money()]),
                       "avg_ticket": rnd.choice([None, 100, 99, 9000, 10_000_000, 10_000_001]),
                       "cogs_rate": rnd.choice([None, 0, 0.3, 0.999, 1, 0.5]), "owner_salary": rnd.choice([None, 0, rand_money()]),
                       "other_variable_rate": rnd.choice([None, 0, 0.1, 0.99])})
        body = {k: v for k, v in body.items() if v is not None}
        d = check(op, c.post(f"{BASE}/analyses/{aid}/breakeven", json=body, headers=hdr), body, inv_be)
        if d:
            bes.append((aid, d["id"]))
    elif op == "be_get" and bes:
        aid, bid = rnd.choice(bes)
        check(op, c.get(f"{BASE}/analyses/{rnd.choice([aid, rnd.choice(analyses)])}/breakeven/{rnd.choice([bid, 0, -1, 10 ** 20, 'x'])}", headers=hdr))
    elif op == "report" and analyses:
        aid = rnd.choice(analyses)
        body = mutate({"industry_code": rnd.choice(INDS), "break_even_id": rnd.choice([None] + [b for a_, b in bes if a_ == aid][-2:])})
        d = check(op, c.post(f"{BASE}/analyses/{aid}/reports", json=body, headers=hdr), body, inv_report)
        if d:
            reports.append(d["id"])
    elif op == "report_get":
        rid = rnd.choice(reports + [str(uuid.uuid4())]) if reports else "x"
        check(op, c.get(f"{BASE}/reports/{rid}", headers=hdr), None, inv_report)
    elif op == "save" and reports:
        body = mutate({"report_id": rnd.choice(reports), "memo": rnd.choice([None, "메모", "가" * 501])})
        d = check(op, c.post(f"{BASE}/me/reports", json=body, headers=hdr), body)
        if d and dev:
            saved[dev][d["saved_report_id"]] = d["report_id"]
    elif op == "mylist":
        d = check(op, c.get(f"{BASE}/me/reports", headers=hdr))
        if d and dev:
            got = {x["saved_report_id"]: x["report_id"] for x in d["items"]}
            if got != saved[dev] or d["count"] != len(d["items"]):
                violations.append(f"저장 목록 불일치(브라우저 키별) · 기대 {saved[dev]} · 받음 {got}")
    elif op == "delete":
        ours = [(k, sid, rid) for k, m in saved.items() for sid, rid in m.items()]
        k, sid, rid = rnd.choice(ours) if ours and rnd.random() < 0.6 else (None, rnd.choice([1, 0, -1, 10 ** 20, "abc", 999999, ""]), None)
        q = {"report_id": rnd.choice([rid, rid, rnd.choice(reports) if reports else "x"])} if rid and rnd.random() < 0.5 else {}
        # id가 빠진 주소('/me/reports/')는 끝 '/' 정리로 '/me/reports'가 된다 — 따라가도 목록 전체가 지워지면 안 된다(아래 목록 검사)
        r = c.delete(f"{BASE}/me/reports/{sid}", params=q, headers=hdr, follow_redirects=True)
        check(op, r)
        if r.status_code == 204:
            if not dev or sid not in saved[dev]:
                violations.append(f"다른 브라우저의 저장 항목이 지워짐 · {sid} · 키 {hdr}")
            else:
                saved[dev].pop(sid)
        elif dev and dev == k and not q and r.status_code == 404:
            violations.append(f"내 저장 항목을 못 지움 · {sid}")
    elif op == "memo":
        ours = [(k, sid, rid) for k, m in saved.items() for sid, rid in m.items()]
        k, sid, rid = rnd.choice(ours) if ours and rnd.random() < 0.7 else (None, rnd.choice([1, 0, 999999, "x"]), None)
        body = mutate({"report_id": rid, "memo": rnd.choice([None, "현장 확인", "가" * 501])})
        r = c.patch(f"{BASE}/me/reports/{sid}", json=body, headers=hdr)
        check(op, r, body)
        if r.status_code == 200 and (not dev or sid not in saved[dev]):
            violations.append(f"다른 브라우저의 메모가 바뀜 · {sid} · 키 {hdr}")
    elif op == "wipe":                                          # 이 브라우저의 저장 목록 모두 지우기
        r = c.post(f"{BASE}/me/reports/clear", headers=hdr)
        d = check(op, r)
        if d is not None and dev:
            if d.get("deleted") != len(saved[dev]):
                violations.append(f"모두 지우기 개수 불일치 · 기대 {len(saved[dev])} · 받음 {d}")
            saved[dev] = {}
        elif r.status_code < 300 and not dev:
            violations.append(f"저장 키 없이 모두 지우기가 성공함 · {hdr}")
    elif op == "admin":
        ah = rnd.choice([{}, {"X-Admin-Key": "x" * 40}, {"X-Admin-Key": ""}])
        r = c.post(f"{BASE}/admin/refresh", headers=ah) if rnd.random() < 0.5 else c.get(f"{BASE}/admin/ingestion-logs", headers=ah)
        check(op, r)
        if r.status_code != 403:
            violations.append(f"관리자 키 없이 관리자 API가 열림 · {r.status_code}")
    elif op == "meta":
        check(op, c.get(f"{BASE}/meta"))

by_status = Counter()
for (name, st), n in stats.items():
    by_status[st // 100 * 100] += n
print(f"요청 {sum(stats.values()):,}건 · 상태 {dict(sorted(by_status.items()))} · 분석 {len(analyses)} · 리포트 {len(reports)} · 손익분기 {len(bes)}")
print(f"위반 {len(violations)}건")
for v in violations[:40]:
    print("  ✗", v)
sys.exit(1 if violations else 0)
