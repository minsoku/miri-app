"""데모 엔진(TypeScript) ↔ 백엔드(Python) 결과 동일성 검사용 케이스 생성.
임시 DB 사본에서 실제 API를 호출해 입력·출력을 기록한다.  사용: python scripts/parity_cases.py out.json [N]"""
import json
import os
os.environ.setdefault("MIRI_NO_DOTENV", "1")
import random
import sqlite3
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
tmp = tempfile.mkdtemp(prefix="miri_parity_")
import atexit, shutil  # noqa: E401,E402
atexit.register(shutil.rmtree, tmp, ignore_errors=True)   # 실행할 때마다 DB 사본(수백 MB)이 쌓이지 않게
_src, _dst = sqlite3.connect(BACKEND / "miri.db"), sqlite3.connect(f"{tmp}/p.db")
_src.backup(_dst)                       # 서버가 쓰는 중(WAL)이어도 일관된 사본
_dst.close(); _src.close()
os.environ["MIRI_DATABASE_URL"] = f"sqlite:///{tmp}/p.db"
os.environ["MIRI_FRONTEND_DIST"] = f"{tmp}/none"
sys.path.insert(0, str(BACKEND))
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.services.engine import get_state  # noqa: E402
from app.db import SessionLocal  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "parity_cases.json")
N = int(sys.argv[2]) if len(sys.argv) > 2 else 60
rnd = random.Random(int(os.environ.get("PARITY_SEED", "20260920")))
API = "/api/v1"


def call(c, method, path, body=None):
    r = c.request(method, API + path, json=body)
    return {"status": r.status_code, "body": r.json() if r.content else None}


cases = {"analyses": [], "candidates": [], "search": [], "compare": []}
with TestClient(app) as c:
    with SessionLocal() as db:
        st = get_state(db)
    areas = list(st.areas)
    codes = sorted(st.industries)
    food = [k for k, v in st.industries.items() if v["category"] == "외식업"]
    for i in range(N):
        interests = rnd.sample(codes, rnd.choice([0, 0, 1, 2, 3]))
        if rnd.random() < 0.3:
            interests = rnd.sample(food, rnd.choice([1, 2]))
        budget = rnd.randrange(3000, 30001, 500) * 10_000
        inv = rnd.choice([0, 0, rnd.randrange(0, budget // 10_000 + 1, 100) * 10_000])
        body = {
            "area_code": rnd.choice(areas), "place_name": rnd.choice([None, "테스트역"]), "radius_m": rnd.choice([300, 500, 1000]),
            "user_type": rnd.choice(["PRE_FOUNDER", "OWNER", "CONSULTANT"]),
            "budget": budget, "monthly_rent_limit": rnd.randrange(0, 801, 10) * 10_000,
            "labor_cost": rnd.randrange(0, 1001, 10) * 10_000, "initial_investment": inv,
            "other_fixed": rnd.choice([0, rnd.randrange(0, 201, 5) * 10_000]),
            "owner_salary": rnd.choice([0, 0, rnd.randrange(150, 501, 10) * 10_000]),
            "loan_amount": rnd.choice([0, rnd.randrange(1000, 10001, 500) * 10_000]),
            "loan_rate_annual": rnd.choice([0.0, 0.035, 0.045, 0.0575]),
            "business_goal": rnd.choice(["기본", "안정형", "고수익형", "저비용형"]),
            "licenses": rnd.choice([[], [], ["약사"], ["미용사(일반)", "공인중개사"]]),
            "categories": [], "interests": interests,
        }
        if rnd.random() < 0.4:              # SB-02 후보 구(인근 지역 대안에 함께 봄)
            body["candidate_area_codes"] = rnd.sample(areas, rnd.choice([1, 2, 3]))
        if rnd.random() < 0.3:              # 분야별 원가율(SB-03 선택 입력) → 비용 적합도·손익분기 기본값
            body["cogs_rates"] = {k: round(rnd.uniform(0.05, 0.8), 3) for k in rnd.sample(["외식업", "서비스업", "소매업"], rnd.choice([1, 2, 3]))}
        if interests and rnd.random() < 0.5:
            body["categories"] = sorted({st.industries[x]["category"] for x in interests})
        elif rnd.random() < 0.15:
            body["categories"] = ["외식업"]
        if rnd.random() < 0.1:              # 고정비 0원(무점포·자가 운영) 경계 사례
            body.update(monthly_rent_limit=0, labor_cost=0, other_fixed=0, initial_investment=0, loan_amount=0, owner_salary=0)
        if rnd.random() < 0.1:              # 추천 0개가 되기 쉬운 조건
            body.update(categories=["소매업"], monthly_rent_limit=30_000_000)
        have = set(st.area_rows(body["area_code"])["industry_code"])
        absent = [c for c in codes if c not in have and not st.industry_rows(c).empty]
        if absent and rnd.random() < 0.3:   # 이 지역에 점포 없는 관심 업종(누락 안내·대체 위험도)
            body["interests"] = list(dict.fromkeys(body["interests"] + [rnd.choice(absent)]))
        rec = {"input": body, "analysis": call(c, "POST", "/analyses", body), "steps": []}
        a = rec["analysis"]["body"]
        if rec["analysis"]["status"] == 201:
            aid = a["id"]
            pick = [x["industry_code"] for x in (a["top"][:1] + a["interests"][:2] + a["cautions"][:1])]
            pick += [m["industry_code"] for m in a.get("missing_interests", [])[:1]]   # 대체(업종 평균) 위험도 경로
            if rnd.random() < 0.3:
                pick.append(rnd.choice(codes))
            for code in dict.fromkeys(pick):
                rec["steps"].append({"op": "risk", "code": code, "out": call(c, "GET", f"/analyses/{aid}/risk/{code}")})
                if rnd.random() < 0.7:
                    rec["steps"].append({"op": "breakeven", "code": code, "body": {"industry_code": code},
                                         "out": call(c, "POST", f"/analyses/{aid}/breakeven", {"industry_code": code})})
                if rnd.random() < 0.5:
                    ov = {"industry_code": code, "avg_ticket": rnd.choice([None, rnd.randrange(3000, 60001, 500)]),
                          "owner_salary": rnd.choice([None, rnd.randrange(0, 501, 50) * 10_000]),
                          "monthly_rent": rnd.choice([None, None, rnd.randrange(100, 3001, 50) * 10_000]),   # 손익분기 미달 경로
                          "cogs_rate": rnd.choice([None, round(rnd.uniform(0.05, 0.8), 3)]),
                          "other_variable_rate": rnd.choice([None, 0.0, 0.05, 0.12])}
                    ov = {k: v for k, v in ov.items() if v is not None}
                    rec["steps"].append({"op": "breakeven", "code": code, "body": ov,
                                         "out": call(c, "POST", f"/analyses/{aid}/breakeven", ov)})
                rec["steps"].append({"op": "report", "code": code,
                                     "out": call(c, "POST", f"/analyses/{aid}/reports", {"industry_code": code})})
                be_ok = [st_["out"]["body"]["id"] for st_ in rec["steps"]
                         if st_["op"] == "breakeven" and st_["out"]["status"] == 200]
                if be_ok and rnd.random() < 0.5:     # 특정 손익분기(마지막 성공분)를 반영한 리포트
                    rec["steps"].append({"op": "report", "code": code, "be": "last",
                                         "out": call(c, "POST", f"/analyses/{aid}/reports",
                                                     {"industry_code": code, "break_even_id": be_ok[-1]})})
            rec["steps"].append({"op": "get", "code": None, "out": call(c, "GET", f"/analyses/{aid}")})
        cases["analyses"].append(rec)
    # 무작위로는 드문 한줄 결론 분기(목표 월수입 미달·빠듯·고정비 0원·진입 검토)를 일부러 만든다
    from miri_engine.breakeven import card_fee_rate
    from miri_engine.config import LICENSED_INDUSTRIES
    t = st.table
    pool = t[(t["category"] != "외식업") & t["risk_grade"].isin(["낮음", "보통"]) & (t["risk_pct_in_ind"] < 90)
             & t["sales_ps_m"].notna() & (t["stores_avg4"] >= 1) & ~t["industry_code"].isin(list(LICENSED_INDUSTRIES))]
    pool = pool.sort_values(["area_id", "industry_code"])
    for _, row in pool.sample(n=min(6, len(pool)), random_state=7).iterrows():
        code, sales = row["industry_code"], float(row["sales_ps_m"])
        body = {**{k: 0 for k in ("other_fixed", "initial_investment", "loan_amount", "owner_salary")},
                "area_code": row["area_id"], "budget": 500_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_500_000,
                "business_goal": "기본", "licenses": [], "categories": [], "interests": [code], "loan_rate_annual": 0.0}
        rec = {"input": body, "analysis": call(c, "POST", "/analyses", body), "steps": []}
        aid = rec["analysis"]["body"]["id"]
        cm = 1 - 0.3 - card_fee_rate(sales / 1.07 * 12)
        for ov in ({"cogs_rate": 0.3}, {"cogs_rate": 0.3, "monthly_rent": max(0, int(sales * cm / 1.07) - 2_500_000)},
                   {"cogs_rate": 0.3, "owner_salary": int(sales * cm * 0.5), "monthly_rent": int(sales * cm * 0.6)},
                   {"cogs_rate": 0.3, "monthly_rent": 0, "labor_cost": 0}):
            ov = {"industry_code": code, **ov}
            rec["steps"].append({"op": "breakeven", "code": code, "body": ov, "out": call(c, "POST", f"/analyses/{aid}/breakeven", ov)})
            if rec["steps"][-1]["out"]["status"] == 200:
                rec["steps"].append({"op": "report", "code": code, "be": "last", "out": call(
                    c, "POST", f"/analyses/{aid}/reports", {"industry_code": code, "break_even_id": rec["steps"][-1]["out"]["body"]["id"]})})
        cases["analyses"].append(rec)
    # 5차 검수 경로: 서울 평균 객단가 대체·투자비>예산·목표 월수입 문구·고위험+매출<고정비·입력 객단가 결제 배수·0원 비용 이름·자격 검증
    def flow(body, steps):
        rec = {"input": body, "analysis": call(c, "POST", "/analyses", body), "steps": []}
        if rec["analysis"]["status"] == 201:
            aid = rec["analysis"]["body"]["id"]
            for op, code, ov in steps:
                if op == "breakeven":
                    rec["steps"].append({"op": "breakeven", "code": code, "body": {"industry_code": code, **ov},
                                         "out": call(c, "POST", f"/analyses/{aid}/breakeven", {"industry_code": code, **ov})})
                elif op == "report":
                    be_ok = [x["out"]["body"]["id"] for x in rec["steps"] if x["op"] == "breakeven" and x["out"]["status"] == 200]
                    body_r = {"industry_code": code, **({"break_even_id": be_ok[-1]} if ov.get("last") and be_ok else {})}
                    rec["steps"].append({"op": "report", "code": code, **({"be": "last"} if "break_even_id" in body_r else {}),
                                         "out": call(c, "POST", f"/analyses/{aid}/reports", body_r)})
                else:
                    be_ok = [x["out"]["body"]["id"] for x in rec["steps"] if x["op"] == "breakeven" and x["out"]["status"] == 200]
                    q = f"?be={be_ok[-1]}" if ov.get("last") and be_ok else ""
                    rec["steps"].append({"op": "risk", "code": code, **({"be": "last"} if q else {}),
                                         "out": call(c, "GET", f"/analyses/{aid}/risk/{code}{q}")})
        cases["analyses"].append(rec)
    Z = {"other_fixed": 0, "initial_investment": 0, "loan_amount": 0, "owner_salary": 0, "loan_rate_annual": 0.0,
         "business_goal": "기본", "licenses": [], "categories": [], "interests": []}
    absent_food = [(a, k) for a in areas[:25] for k in sorted(food)[:12] if st.row(a, k) is None and not st.industry_rows(k).empty][:3]
    for a, k in absent_food:                                                   # 이 지역 데이터 없음 → 서울 평균 객단가
        flow({**Z, "area_code": a, "budget": 100_000_000, "monthly_rent_limit": 2_000_000, "labor_cost": 2_000_000, "interests": [k]},
             [("breakeven", k, {}), ("report", k, {})])
    flow({**Z, "area_code": "11440", "budget": 50_000_000, "monthly_rent_limit": 1_500_000, "labor_cost": 1_000_000,
          "initial_investment": 20_000_000, "interests": ["CS100007"]},
         [("breakeven", "CS100007", {"initial_investment": 80_000_000}), ("report", "CS100007", {"last": True}),
          ("breakeven", "CS100007", {"initial_investment": 0}), ("report", "CS100007", {"last": True})])
    flow({**Z, "area_code": "11680", "budget": 500_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_500_000,
          "owner_salary": 30_000_000, "categories": ["외식업"]}, [])
    flow({**Z, "area_code": "11680", "budget": 500_000_000, "monthly_rent_limit": 30_000_000, "labor_cost": 5_000_000,
          "categories": ["외식업"]}, [])
    flow({**Z, "area_code": "11530", "budget": 500_000_000, "monthly_rent_limit": 15_000_000, "labor_cost": 5_000_000,
          "interests": ["CS200037"]}, [("risk", "CS200037", {}), ("report", "CS200037", {})])
    flow({**Z, "area_code": "11440", "budget": 500_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_500_000,
          "categories": ["외식업"], "interests": ["CS100009"]},
         [("breakeven", "CS100009", {"avg_ticket": 5000}), ("report", "CS100009", {"last": True})])
    flow({**Z, "area_code": "11620", "budget": 500_000_000, "monthly_rent_limit": 0, "labor_cost": 0, "other_fixed": 300_000,
          "owner_salary": 4_000_000, "loan_amount": 30_000_000, "loan_rate_annual": 0.05, "initial_investment": 30_000_000,
          "categories": ["외식업"], "interests": ["CS100007"]},
         [("breakeven", "CS100007", {}), ("report", "CS100007", {"last": True})])
    flow({**Z, "area_code": "11590", "user_type": "OWNER", "budget": 300_000_000, "monthly_rent_limit": 15_000_000,
          "labor_cost": 18_000_000, "other_fixed": 1_000_000, "initial_investment": 30_000_000, "interests": ["CS300002"]},
         [("report", "CS300002", {})])
    flow({**Z, "area_code": "11440", "budget": 100_000_000, "monthly_rent_limit": 1_000_000, "labor_cost": 0,
          "licenses": ["없는 자격"]}, [])
    flow({**Z, "area_code": "11440", "budget": 100_000_000, "monthly_rent_limit": 1_000_000, "labor_cost": 0,
          "categories": ["외식업", "외식업"]}, [])
    # 7차 검수 경로: 억 단위 한도·작은 임대료 하한·예산=투자비·리포트 재사용·변동비 초과(기본 원가율)·고위험 한줄 결론
    flow({**Z, "area_code": "11590", "budget": 5_000_000_000, "monthly_rent_limit": 110_300_000, "labor_cost": 0,
          "interests": ["CS300008"], "cogs_rates": {"소매업": 0.619}},
         [("report", "CS300008", {}), ("report", "CS300008", {})])
    flow({**Z, "area_code": "11440", "budget": 100_000_000, "monthly_rent_limit": 600_000, "labor_cost": 4_510_000,
          "interests": ["CS100010"]}, [("risk", "CS100010", {}), ("report", "CS100010", {})])
    flow({**Z, "area_code": "11680", "budget": 80_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_500_000,
          "initial_investment": 80_000_000, "interests": ["CS100010", "CS100003"]},
         [("breakeven", "CS100010", {"other_variable_rate": 0.6}), ("breakeven", "CS100010", {"owner_salary": 3_000_000}),
          ("report", "CS100010", {"last": True}), ("report", "CS100010", {"last": True}), ("report", "CS100003", {})])
    # 8차 검수 경로: 손익분기 화면 경로 리포트 재사용(같은 입력·분석 조건과 같은 값)·필수 항목·고위험+예산 단서
    flow({**Z, "area_code": "11680", "budget": 80_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_500_000,
          "interests": ["CS100010", "CS300002"]},
         [("report", "CS100010", {}), ("breakeven", "CS100010", {}), ("report", "CS100010", {"last": True}),
          ("breakeven", "CS100010", {"monthly_rent": 3_000_000}), ("report", "CS100010", {"last": True}),
          ("breakeven", "CS300002", {"cogs_rate": 0.7}), ("report", "CS300002", {"last": True})])
    flow({**Z, "area_code": "11140", "user_type": "OWNER", "budget": 30_000_000, "monthly_rent_limit": 2_000_000, "labor_cost": 0,
          "initial_investment": 30_000_000, "cogs_rates": {"서비스업": 0.65}, "interests": ["CS200034", "CS300022"]},
         [("report", "CS200034", {}), ("report", "CS300022", {})])
    flow({**Z, "area_code": "11110", "budget": 50_000_000, "monthly_rent_limit": 1_000_000, "labor_cost": 0,
          "initial_investment": 50_000_000, "cogs_rates": {"서비스업": 0.3}, "interests": ["CS200001"]},
         [("report", "CS200001", {})])
    # 9차 검수 경로: 운영자금 기준(12개월)·현금 고정비 0원·1개월 미만·자격 없는 업종·목표 월수입 부족액·적합도 하한
    flow({**Z, "area_code": "11110", "budget": 50_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_500_000,
          "interests": ["CS100001"]}, [("report", "CS100001", {})])
    flow({**Z, "area_code": "11680", "budget": 10_000_000, "monthly_rent_limit": 0, "labor_cost": 0,
          "initial_investment": 10_000_000, "interests": ["CS100010"]}, [("report", "CS100010", {})])
    flow({**Z, "area_code": "11110", "budget": 30_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 1_000_000,
          "initial_investment": 29_900_000, "interests": ["CS100001"]}, [("report", "CS100001", {})])
    flow({**Z, "area_code": "11440", "user_type": "CONSULTANT", "budget": 80_000_000, "monthly_rent_limit": 2_000_000,
          "labor_cost": 1_500_000, "interests": ["CS200028"], "categories": ["서비스업"]},
         [("report", "CS200028", {}), ("breakeven", "CS200028", {"cogs_rate": 0.40700000000000003, "monthly_rent": 2_000_000}),
          ("report", "CS200028", {"last": True})])
    flow({**Z, "area_code": "11200", "business_goal": "고수익형", "budget": 50_000_000, "monthly_rent_limit": 2_000_000,
          "labor_cost": 1_500_000, "initial_investment": 30_000_000, "other_fixed": 500_000, "owner_salary": 3_000_000,
          "loan_amount": 30_000_000, "loan_rate_annual": 0.055, "cogs_rates": {"소매업": 0.65}, "interests": ["CS300011"]},
         [("report", "CS300011", {}), ("breakeven", "CS300011", {"owner_salary": 2_500_000, "avg_ticket": 6000}),
          ("report", "CS300011", {"last": True})])
    # 10차 검수 경로: 적합도 하한(정수 기준)·직접 넣은 원가율·개월 수 내림·12개월 기준·인근 구 감당 여부·매출 비교 지역 부족
    flow({**Z, "area_code": "11530", "budget": 100_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_500_000,
          "categories": ["서비스업"], "interests": ["CS200037"]}, [("risk", "CS200037", {}), ("report", "CS200037", {})])
    flow({**Z, "area_code": "11260", "budget": 60_000_000, "monthly_rent_limit": 1_500_000, "labor_cost": 1_000_000,
          "interests": ["CS200001"]}, [("breakeven", "CS200001", {"cogs_rate": 0.3}), ("report", "CS200001", {"last": True})])
    flow({**Z, "area_code": "11110", "budget": 75_780_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_500_000,
          "initial_investment": 10_000_000, "interests": ["CS100001"]}, [("report", "CS100001", {})])
    flow({**Z, "area_code": "11350", "budget": 64_000_000, "monthly_rent_limit": 4_000_000, "labor_cost": 4_000_000,
          "cogs_rates": {"소매업": 0.7}, "interests": ["CS300002"]}, [("report", "CS300002", {})])
    flow({**Z, "area_code": "11680", "budget": 100_000_000, "monthly_rent_limit": 2_000_000, "labor_cost": 1_500_000,
          "categories": ["서비스업"], "interests": ["CS200036"]}, [("risk", "CS200036", {})])
    flow({**Z, "area_code": "11380", "business_goal": "안정형", "budget": 100_000_000, "monthly_rent_limit": 5_000_000,
          "labor_cost": 5_000_000, "categories": ["서비스업"], "interests": ["CS200001"]}, [])
    flow({**Z, "area_code": "11440", "budget": 60_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_500_000,
          "initial_investment": 60_000_000, "interests": ["CS100007", "CS100010"]},
         [("risk", "CS100010", {}), ("report", "CS100007", {}), ("report", "CS100010", {})])
    # 11차 검수 경로: 후보 0개일 때 비용 적합도·대형 점포 매출·학원 평일 문구·20점 미만 업종 이름·리포트 비용 기준 인근 구(be)·
    # 매출 비교 지역 부족·인근 대체 지역·대안이 있어도 운영자금 단서
    flow({**Z, "area_code": "11440", "budget": 100_000_000, "monthly_rent_limit": 80_000_000, "labor_cost": 0,
          "interests": ["CS100010"]}, [("report", "CS100010", {})])
    flow({**Z, "area_code": "11710", "budget": 100_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_500_000,
          "categories": ["소매업"], "interests": ["CS300010"]}, [("risk", "CS300010", {}), ("report", "CS300010", {})])
    flow({**Z, "area_code": "11680", "budget": 100_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_500_000,
          "categories": ["서비스업"], "interests": ["CS200002", "CS200001"]}, [("report", "CS200002", {})])
    flow({**Z, "area_code": "11380", "business_goal": "안정형", "budget": 100_000_000, "monthly_rent_limit": 8_000_000,
          "labor_cost": 6_000_000, "categories": ["서비스업"]}, [])
    flow({**Z, "area_code": "11470", "budget": 100_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_500_000,
          "categories": ["외식업"]}, [])
    flow({**Z, "area_code": "11440", "budget": 300_000_000, "monthly_rent_limit": 9_000_000, "labor_cost": 6_000_000,
          "interests": ["CS100010"]},
         [("breakeven", "CS100010", {"monthly_rent": 1_000_000, "labor_cost": 1_000_000}), ("report", "CS100010", {"last": True}),
          ("risk", "CS100010", {"last": True}), ("risk", "CS100010", {}),
          ("breakeven", "CS100010", {"cogs_rate": 0.2, "other_variable_rate": 0.1}), ("risk", "CS100010", {"last": True})])
    flow({**Z, "area_code": "11680", "budget": 300_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 1_000_000,
          "cogs_rates": {"서비스업": 0.1}, "interests": ["CS200036"]}, [("report", "CS200036", {})])
    flow({**Z, "area_code": "11350", "budget": 100_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_000_000,
          "interests": ["CS200036"]}, [("risk", "CS200036", {}), ("report", "CS200036", {})])
    flow({**Z, "area_code": "11560", "budget": 50_000_000, "monthly_rent_limit": 1_500_000, "labor_cost": 1_000_000,
          "initial_investment": 50_000_000, "interests": ["CS300002"]}, [("report", "CS300002", {})])
    # 12차 검수 경로: 대형 점포 매출 추천 제외·안내·한줄 결론 단서, 원가율 모르는 관심 업종과 비용 적합도, 인근 구 체크리스트 유지,
    # 업종별 피크 문구, 요인 라벨(화면 정수 기준)
    flow({**Z, "area_code": "11140", "budget": 80_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_500_000}, [])
    flow({**Z, "area_code": "11590", "budget": 100_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_500_000,
          "categories": ["소매업"], "interests": ["CS300008"], "cogs_rates": {"소매업": 0.6}}, [("report", "CS300008", {})])
    flow({**Z, "area_code": "11680", "budget": 300_000_000, "monthly_rent_limit": 18_500_000, "labor_cost": 2_500_000,
          "categories": ["외식업"], "interests": ["CS100001", "CS200028"], "licenses": ["미용사(일반)"]}, [])
    for code in ("CS200019", "CS200001", "CS300001", "CS200037", "CS200025"):
        flow({**Z, "area_code": "11440", "budget": 100_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_000_000,
              "interests": [code]}, [("risk", code, {}), ("report", code, {})])
    flow({**Z, "area_code": "11680", "budget": 100_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_000_000,
          "cogs_rates": {"서비스업": 0.2}, "interests": ["CS200031", "CS200002", "CS200033"]},
         [("report", "CS200031", {}), ("report", "CS200002", {}), ("risk", "CS200033", {}), ("report", "CS200033", {})])
    flow({**Z, "area_code": "11650", "budget": 100_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_000_000,
          "cogs_rates": {"서비스업": 0.2, "소매업": 0.5}, "categories": ["서비스업", "소매업"]}, [])
    # 13차 검수 경로: 대형 점포 평균은 대안 업종·인근 구·감당 여부 판단에서 제외, 제외 순서(비용·주의 업종 우선), 인용한 대안 유지,
    # 고위험 같은 등급 인근 구, 자격 없는 적자, 손익분기 경고, 리포트 비용 기준 위험도(be)
    flow({**Z, "area_code": "11740", "budget": 100_000_000, "monthly_rent_limit": 1_000_000, "labor_cost": 2_000_000,
          "interests": ["CS200031"]}, [("risk", "CS200031", {}), ("report", "CS200031", {})])
    flow({**Z, "area_code": "11680", "budget": 100_000_000, "monthly_rent_limit": 1_500_000, "labor_cost": 1_000_000,
          "interests": ["CS200003", "CS200004"]}, [("report", "CS200003", {}), ("report", "CS200004", {})])
    flow({**Z, "area_code": "11710", "budget": 100_000_000, "monthly_rent_limit": 25_000_000, "labor_cost": 0,
          "categories": ["소매업"], "interests": ["CS300017"]}, [])
    flow({**Z, "area_code": "11680", "budget": 100_000_000, "monthly_rent_limit": 1_000_000, "labor_cost": 2_000_000,
          "categories": ["외식업"]}, [])
    flow({**Z, "area_code": "11200", "budget": 5_000_000, "monthly_rent_limit": 1_000_000, "labor_cost": 1_000_000,
          "cogs_rates": {"외식업": 0.71}, "interests": ["CS100004"]}, [("report", "CS100004", {})])
    flow({**Z, "area_code": "11200", "budget": 100_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_000_000,
          "owner_salary": 3_000_000, "initial_investment": 50_000_000, "interests": ["CS100010", "CS100005"]},
         [("risk", "CS100010", {}), ("report", "CS100010", {}),
          ("breakeven", "CS100005", {"monthly_rent": 1_200_000, "labor_cost": 0, "owner_salary": 1_500_000}),
          ("report", "CS100005", {"last": True}), ("risk", "CS100005", {"last": True})])
    flow({**Z, "area_code": "11545", "budget": 100_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_000_000,
          "cogs_rates": {"서비스업": 0.15}, "interests": ["CS200028"]}, [("report", "CS200028", {})])
    flow({**Z, "area_code": "11170", "budget": 100_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_500_000,
          "cogs_rates": {"소매업": 0.7}, "interests": ["CS300032"]}, [("breakeven", "CS300032", {}), ("report", "CS300032", {"last": True})])
    for ac, code in (("11215", "CS200019"), ("11500", "CS300019"), ("11290", "CS300009"), ("11110", "CS300017")):
        flow({**Z, "area_code": ac, "budget": 10_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 3_000_000,
              "cogs_rates": {"서비스업": 0.72, "소매업": 0.6}, "interests": [code]}, [("risk", code, {}), ("report", code, {})])
    # 14차 검수 경로: 빈 결과 이유의 최고 매출(대형 점포 제외), 인용한 대안 업종 유지, 대형 점포 대출 제외, 주의 업종 순서·안내,
    # 창업 목표 표시, 손익분기 구성 합(아주 큰 금액)
    flow({**Z, "area_code": "11230", "budget": 0, "monthly_rent_limit": 15_000_000, "labor_cost": 10_000_000,
          "categories": ["소매업"], "cogs_rates": {"소매업": 0.75}}, [])
    flow({**Z, "area_code": "11230", "budget": 0, "monthly_rent_limit": 10_000_000, "labor_cost": 8_000_000,
          "categories": ["소매업"], "cogs_rates": {"소매업": 0.75}}, [])
    flow({**Z, "area_code": "11590", "budget": 30_000_000, "monthly_rent_limit": 500_000, "labor_cost": 0,
          "interests": ["CS300009"]}, [("report", "CS300009", {})])
    flow({**Z, "area_code": "11140", "budget": 100_000_000, "monthly_rent_limit": 1_500_000, "labor_cost": 0,
          "cogs_rates": {"소매업": 0.72}, "interests": ["CS300017"]}, [("risk", "CS300017", {}), ("report", "CS300017", {})])
    flow({**Z, "area_code": "11350", "business_goal": "저비용형", "budget": 100_000_000, "monthly_rent_limit": 2_000_000,
          "labor_cost": 1_000_000, "interests": ["CS200025"]}, [("report", "CS200025", {})])
    flow({**Z, "area_code": "11305", "budget": 100_000_000, "monthly_rent_limit": 1_000_000, "labor_cost": 0,
          "categories": ["외식업"]}, [])
    flow({**Z, "area_code": "11440", "budget": 100_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_000_000,
          "interests": ["CS200026"]},
         [("breakeven", "CS200026", {"monthly_rent": 34_681_029_688, "avg_ticket": 9000, "cogs_rate": 0.30000001,
                                     "owner_salary": 0, "other_variable_rate": 0.1})])
    flow({**Z, "area_code": "11500", "budget": 100_000_000, "monthly_rent_limit": 2_000_000, "labor_cost": 1_000_000,
          "interests": ["CS300008"], "cogs_rates": {"소매업": 0.6}}, [("report", "CS300008", {})])
    # 15차 검수 경로: 관심 업종이 주의 업종(입지 위험 90 이상)인 리포트, 주의 업종 안내 문구, 고위험 TOP
    flow({**Z, "area_code": "11680", "budget": 100_000_000, "monthly_rent_limit": 1_000_000, "labor_cost": 1_000_000,
          "interests": ["CS100005"]}, [("report", "CS100005", {})])
    flow({**Z, "area_code": "11620", "business_goal": "고수익형", "budget": 100_000_000, "monthly_rent_limit": 20_000_000,
          "labor_cost": 0, "categories": ["소매업"]}, [])
    flow({**Z, "area_code": "11350", "business_goal": "안정형", "user_type": "OWNER", "budget": 100_000_000,
          "monthly_rent_limit": 3_000_000, "labor_cost": 3_000_000, "initial_investment": 60_000_000,
          "cogs_rates": {"서비스업": 0.2}, "interests": ["CS200019"]}, [("report", "CS200019", {})])
    # 16차 검수 경로: 추천 조건 미달 관심 업종(입지 위험 90 이상)은 주의 업종 표시 없음, 고위험·빠듯 한줄 결론과 체크리스트,
    # 목표 월수입이 있을 때 카드 근거 칩
    flow({**Z, "area_code": "11680", "budget": 100_000_000, "monthly_rent_limit": 30_000_000, "labor_cost": 5_000_000,
          "interests": ["CS100005"]}, [("report", "CS100005", {})])
    flow({**Z, "area_code": "11305", "budget": 100_000_000, "monthly_rent_limit": 1_000_000, "labor_cost": 2_000_000},
         [("report", "CS100008", {}), ("risk", "CS100008", {})])
    flow({**Z, "area_code": "11680", "budget": 100_000_000, "monthly_rent_limit": 6_000_000, "labor_cost": 2_000_000},
         [("report", "CS100005", {})])
    flow({**Z, "area_code": "11440", "budget": 100_000_000, "monthly_rent_limit": 2_000_000, "labor_cost": 1_000_000,
          "owner_salary": 2_500_000, "categories": ["서비스업"]}, [])
    # 17차 검수 경로: 목표 월수입이 있을 때 한줄 결론의 배율 기준(필요 매출), 대형 점포·빠듯·운영자금 단서 함께,
    # 원가율 없는 분야의 카드 칩·고위험 한줄 결론·인근 구 문구
    flow({**Z, "area_code": "11470", "budget": 200_000_000, "monthly_rent_limit": 1_000_000, "labor_cost": 1_500_000,
          "owner_salary": 2_000_000, "cogs_rates": {"서비스업": 0.15, "소매업": 0.45}},
         [("report", "CS300036", {}), ("breakeven", "CS300036", {}), ("report", "CS300036", {"last": True})])
    flow({**Z, "area_code": "11680", "budget": 150_000_000, "monthly_rent_limit": 8_000_000, "labor_cost": 10_000_000,
          "interests": ["CS100002"]}, [("report", "CS100002", {})])
    flow({**Z, "area_code": "11680", "business_goal": "고수익형", "budget": 200_000_000, "monthly_rent_limit": 20_000_000,
          "labor_cost": 3_000_000}, [("report", "CS300002", {}), ("breakeven", "CS300002", {"cogs_rate": 0.72}),
                                     ("report", "CS300002", {"last": True})])
    flow({**Z, "area_code": "11680", "business_goal": "고수익형", "budget": 200_000_000, "monthly_rent_limit": 20_000_000,
          "labor_cost": 3_000_000, "categories": ["소매업"]}, [])
    # 18차 검수 경로: 인근 지역 감당 기준(원가율 모름·목표 월수입), SB-02 후보 구를 대안에, 높은 원가율 빈 결과,
    # 월 고정비 0원, 자격 없는 업종 체크리스트, 원가율 미입력 칩(고정비 초과로 제외된 업종)
    flow({**Z, "area_code": "11215", "budget": 100_000_000, "monthly_rent_limit": 15_000_000, "labor_cost": 0,
          "owner_salary": 2_000_000, "interests": ["CS200019"]}, [("risk", "CS200019", {}), ("report", "CS200019", {})])
    flow({**Z, "area_code": "11620", "budget": 100_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_000_000,
          "interests": ["CS100010"], "candidate_area_codes": ["11590", "11650"]},
         [("risk", "CS100010", {}), ("report", "CS100010", {})])
    flow({**Z, "area_code": "11200", "budget": 100_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_000_000,
          "categories": ["외식업"], "cogs_rates": {"외식업": 0.95}, "interests": ["CS100010"]}, [])
    flow({**Z, "area_code": "11140", "budget": 100_000_000, "monthly_rent_limit": 0, "labor_cost": 0, "categories": ["소매업"]},
         [("report", "CS300002", {})])
    flow({**Z, "area_code": "11140", "budget": 100_000_000, "monthly_rent_limit": 40_000_000, "labor_cost": 0,
          "interests": ["CS200019"]}, [])
    flow({**Z, "area_code": "11680", "budget": 300_000_000, "monthly_rent_limit": 5_000_000, "labor_cost": 5_000_000,
          "interests": ["CS200006"]}, [("report", "CS200006", {})])
    # 19차: 자격 없는 업종(폐업 이력 요인 → 현장 확인), 적자 확정 업종 칩, 목표 월수입 포함 인근 구 문구
    flow({**Z, "area_code": "11110", "budget": 300_000_000, "monthly_rent_limit": 5_000_000, "labor_cost": 5_000_000,
          "interests": ["CS200006"], "candidate_area_codes": ["11140", "11680"]}, [("report", "CS200006", {})])
    flow({**Z, "area_code": "11440", "budget": 100_000_000, "monthly_rent_limit": 30_000_000, "labor_cost": 5_000_000,
          "interests": ["CS200028"]}, [])
    flow({**Z, "area_code": "11110", "budget": 100_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 1_000_000,
          "owner_salary": 2_000_000, "interests": ["CS200037"]}, [("risk", "CS200037", {}), ("report", "CS200037", {})])
    # 23차 검수 경로: 남는 몫이 거의 없는 손익분기(안내 오류·회수 기간 없음)·인근 구 체크리스트 유지·제외 업종 저장·목표 월수입보다 작은 한도
    flow({**Z, "area_code": "11440", "budget": 100_000_000, "monthly_rent_limit": 2_000_000, "labor_cost": 1_000_000,
          "interests": ["CS100001"]},
         [("breakeven", "CS100001", {"monthly_rent": 100_000_000, "cogs_rate": 0.97, "other_variable_rate": 0.009999999999}),
          ("breakeven", "CS100001", {"monthly_rent": 5_000_000, "labor_cost": 4_000_000, "initial_investment": 100_000_000_000,
                                     "cogs_rate": 0.5579384201562259}), ("report", "CS100001", {"last": True})])
    flow({**Z, "area_code": "11215", "budget": 20_000_000, "monthly_rent_limit": 1_500_000, "labor_cost": 3_000_000,
          "initial_investment": 15_000_000, "cogs_rates": {"서비스업": 0.75}, "interests": ["CS200019"]},
         [("report", "CS200019", {})])
    flow({**Z, "area_code": "11110", "budget": 80_000_000, "monthly_rent_limit": 1_000_000, "labor_cost": 1_000_000,
          "initial_investment": 10_000_000, "interests": ["CS200017"], "excluded_industries": ["CS200024", "CS200024"]},
         [("report", "CS200017", {})])
    flow({**Z, "area_code": "11290", "budget": 80_000_000, "monthly_rent_limit": 500_000, "labor_cost": 0,
          "initial_investment": 20_000_000, "owner_salary": 3_000_000, "cogs_rates": {"소매업": 0.5}, "interests": ["CS300031"]},
         [("report", "CS300031", {}), ("breakeven", "CS300031", {}), ("report", "CS300031", {"last": True})])
    flow({**Z, "area_code": "11440", "budget": 100_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 3_000_000,
          "owner_salary": 6_000_000, "cogs_rates": {"소매업": 0.6}, "interests": ["CS300033"], "user_type": "OWNER"},
         [("report", "CS300033", {}), ("breakeven", "CS300033", {"owner_salary": 8_000_000}), ("report", "CS300033", {"last": True})])
    for i in range(30):                                                        # UC-02 상권 비교
        k = rnd.choice([1, 2, 2, 3, 4])
        body = {"area_codes": rnd.sample(areas, k), "industry_code": rnd.choice([None, rnd.choice(codes)])}
        if i % 7 == 0 and k > 1:
            body["area_codes"][-1] = body["area_codes"][0]                     # 중복 코드
        cases["compare"].append({"body": body, "out": call(c, "POST", "/areas/compare", body)})
    for i in range(80):
        lat, lng = rnd.uniform(37.43, 37.70), rnd.uniform(126.80, 127.18)
        if i == 1:
            lat, lng = 37.694, 126.978                                          # 서울 바로 밖(가장 가까운 구 대체 안내)
        if i == 2:
            lat, lng = 37.4690, 127.1389                                        # 서울 밖 1km 안(거리를 m로)
        if i in (3, 4):                                                         # 1km 경계(999.5m 이상은 1.0km)
            lat, lng = 37.55, (126.75558066952973 if i == 3 else 126.75558066954835)
        if i % 10 == 0:
            lat, lng = rnd.uniform(35.0, 36.5), rnd.uniform(127.5, 129.0)     # 서울 밖
        r = rnd.choice([300, 500, 1000, 2000]) if i not in (2, 3, 4) else 300
        cases["candidates"].append({"lat": lat, "lng": lng, "radius_m": r,
                                    "out": call(c, "GET", f"/areas/candidates?lat={lat}&lng={lng}&radius_m={r}")})
    for q in ["강남", "강남역", "홍대", "성수", "을지로", "마포구", "중", "역", "코엑스", "  신촌 ", "없는지명", "DMC", "dmc", "구로", "서울",
              "망원동", "역삼동", "문래동", "경리단길", "연남동", "광장시장", "봉천동", "상도동", "대학동", "낙성대", "숭실대입구역",
              "상암동", "화곡동", "신촌역", "이대역", "홍대역", "없는역", "강남억", "홍대입구억", "잠실억", "서울시", "강남대", "을지로5",
              "강남녁", "잠실녁", "서울녁", "선능역", "선능", "잠실력", "능동", "정능", "능", "강남구청", "강남구청역",
              "성수동카페거리", "마포구청", "광장동", "먹자골목", "서울 강남구", "서울특별시 관악구", "관악구 신림동", "신림역 사거리",
              "강남역 2번출구", "신림역사거리", "수서역", "화곡역", "중앙대", "서울시청", "광장시장", "경리단길", "서울 없는동",
              "홍대 카페", "목동 학원가", "당산 역 4번 출구", "은평구 신사동", "동작구 사당동", "마포구 연남동 카페거리", "남대문 시장",
              "신촌역앞", "홍대 입구", "관악구 삼성동", "중 구", "강남 역", "서울 강남구 역삼동",
              "서울숲 공원", "여의도 공원", "시청 광장", "반포 한강", "구로 테크노마트", "신도림 테크노마트", "서울시강남구", "서울관악구",
              "관악구신림동", "강남역2번출구", "홍대입구역9번출구", "강남역쪽", "성수동1가", "강남구 서초구", "중구청",
              "마포 연남동", "강남 코엑스", "강남 가로수길", "용산 이태원", "영등포 여의도", "종로 광장시장", "마포 망원시장", "강남 카페",
              "석촌호수", "여의도공원", "광화문광장", "서울숲공원", "강남역2번출구앞", "홍대입구역2번출구앞"]:
        cases["search"].append({"q": q, "out": call(c, "GET", f"/places/search?q={q}")})
OUT.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
n_steps = sum(len(a["steps"]) for a in cases["analyses"])
print(f"케이스 저장: {OUT} · 분석 {len(cases['analyses'])} · 단계 {n_steps} · 후보 {len(cases['candidates'])} · 검색 {len(cases['search'])}")
