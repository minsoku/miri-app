"""동시 요청 부하 테스트: 여러 사용자가 동시에 분석·위험도·손익분기·리포트·저장을 할 때 오류·지연을 본다.
실행: (서버 실행 중) python e2e/load.py http://127.0.0.1:8000 [동시사용자=30] [라운드=3]"""
import asyncio
import random
import secrets
import statistics
import sys
import time

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/") + "/api/v1"
USERS = int(sys.argv[2]) if len(sys.argv) > 2 else 30
ROUNDS = int(sys.argv[3]) if len(sys.argv) > 3 else 3
AREAS = ["11680", "11440", "11110", "11650", "11710", "11200", "11215", "11560"]
FOOD = ["CS100001", "CS100008", "CS100010", "CS100007", "CS100003"]
lat: dict[str, list[float]] = {}
errors: list[str] = []


async def timed(name, coro):
    t = time.perf_counter()
    r = await coro
    lat.setdefault(name, []).append((time.perf_counter() - t) * 1000)
    if r.status_code >= 400:
        errors.append(f"{name} {r.status_code} {r.text[:160]}")
    return r


async def user(c: httpx.AsyncClient, i: int):
    rnd = random.Random(i)
    h = {"X-Device-Key": secrets.token_urlsafe(32)}              # 로그인 대신 사용자(브라우저)마다 저장 키
    body = {"area_code": rnd.choice(AREAS), "budget": 80_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_500_000,
            "business_goal": rnd.choice(["기본", "안정형", "고수익형", "저비용형"]), "interests": rnd.sample(FOOD, 2),
            "categories": ["외식업"]}
    a = await timed("analysis", c.post(f"{BASE}/analyses", json=body, headers=h))
    if a.status_code != 201:
        return
    aid, code = a.json()["id"], body["interests"][0]
    await timed("get", c.get(f"{BASE}/analyses/{aid}", headers=h))
    await timed("risk", c.get(f"{BASE}/analyses/{aid}/risk/{code}", headers=h))
    be = await timed("breakeven", c.post(f"{BASE}/analyses/{aid}/breakeven", json={"industry_code": code, "avg_ticket": 9000}, headers=h))
    rep = await timed("report", c.post(f"{BASE}/analyses/{aid}/reports",
                                       json={"industry_code": code, "break_even_id": be.json().get("id")}, headers=h))
    if rep.status_code == 201:
        await timed("save", c.post(f"{BASE}/me/reports", json={"report_id": rep.json()["id"]}, headers=h))
        lst = await timed("list", c.get(f"{BASE}/me/reports", headers=h))
        if lst.status_code == 200 and [x["report_id"] for x in lst.json()["items"]] != [rep.json()["id"]]:
            errors.append(f"list: 이 사용자의 저장 목록이 아님 {lst.text[:120]}")


async def main():
    limits = httpx.Limits(max_connections=USERS * 2)
    async with httpx.AsyncClient(timeout=60, limits=limits) as c:
        t = time.perf_counter()
        for _ in range(ROUNDS):
            await asyncio.gather(*(user(c, i + _ * USERS) for i in range(USERS)))
        total = time.perf_counter() - t
    n = sum(len(v) for v in lat.values())
    print(f"동시 {USERS}명 × {ROUNDS}라운드 · 요청 {n}건 · {total:.1f}초 · 오류 {len(errors)}건")
    for k, v in lat.items():
        v = sorted(v)
        print(f"  {k:10s} p50 {statistics.median(v):6.0f}ms  p95 {v[int(len(v) * 0.95) - 1]:6.0f}ms  max {v[-1]:6.0f}ms")
    for e in errors[:10]:
        print("  ✗", e)
    return 1 if errors else 0


sys.exit(asyncio.run(main()))
