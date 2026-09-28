"""화면 폭별 레이아웃 검사: 320~1280px에서 모든 화면의 가로 넘침·잘림을 찾고 320px 캡처를 남긴다.
실행: (서버 실행 중) python e2e/responsive.py http://127.0.0.1:8000/ [OUT_DIR]
긴 이름(동대문역사문화공원역, 컴퓨터및주변장치판매, 자전거 및 기타운송장비)으로 데이터를 만들어 최악의 경우를 본다."""
import json
import sys
import time
import httpx
from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/") + "/"
OUT = sys.argv[2] if len(sys.argv) > 2 else "e2e/responsive_out"
API = BASE + "api/v1"
WIDTHS = [320, 360, 390, 414, 768, 1280]

c = httpx.Client(timeout=30)
DEVICE = f"responsive-check-{time.time_ns()}-browser-key"           # 화면이 쓰는 브라우저 저장 키와 같게(저장 목록 화면용)
h = {"X-Device-Key": DEVICE}
place = c.get(f"{API}/places/search", params={"q": "동대문역사문화공원역"}).json()[0]
cands = c.get(f"{API}/areas/candidates", params={"lat": place["lat"], "lng": place["lng"], "radius_m": 1000,
                                                  "place_name": place["name"]}).json()
LONG = ["CS300003", "CS300025", "CS100009", "CS200037"]
body = {"area_code": cands["candidates"][0]["area_code"], "place_name": place["name"], "lat": place["lat"], "lng": place["lng"],
        "radius_m": 1000, "budget": 1_234_567_890, "monthly_rent_limit": 12_345_678, "labor_cost": 9_876_543,
        "initial_investment": 123_456_789, "owner_salary": 5_000_000, "business_goal": "고수익형", "interests": LONG,
        "licenses": ["약사"]}
a = c.post(f"{API}/analyses", json=body, headers=h).json()
aid = a["id"]
code = "CS300003"
be = c.post(f"{API}/analyses/{aid}/breakeven", json={"industry_code": code, "cogs_rate": 0.72}, headers=h).json()
rep = c.post(f"{API}/analyses/{aid}/reports", json={"industry_code": code, "break_even_id": be["id"]}, headers=h).json()
c.post(f"{API}/me/reports", json={"report_id": rep["id"], "memo": "메모가 아주 길면 카드가 어떻게 보이는지 확인하기 위한 메모입니다 " * 3}, headers=h)
draft = {"place": {"name": place["name"], "lat": place["lat"], "lng": place["lng"]}, "radius": 1000,
         "area": cands["candidates"][0], "candidateCodes": [x["area_code"] for x in cands["candidates"]],
         "budget": "123,456.78", "rent": "1,234.5", "labor": "987", "investment": "12,345", "otherFixed": "", "ownerSalary": "500",
         "loan": "", "loanRate": "", "goal": "고수익형", "licenses": ["약사"], "interests": LONG, "sameCategoryOnly": False}
ROUTES = ["#/", "#/area", "#/conditions", "#/interests", f"#/analysis/{aid}", f"#/analysis/{aid}/risk/{code}",
          f"#/analysis/{aid}/breakeven/{code}?be={be['id']}", f"#/report/{rep['id']}", "#/reports"]
problems = []
with sync_playwright() as p:
    b = p.chromium.launch()
    for w in WIDTHS:
        ctx = b.new_context(viewport={"width": w, "height": 800}, device_scale_factor=1)
        ctx.add_init_script(f"localStorage.setItem('miri.device', {json.dumps(json.dumps(DEVICE))});"
                            f"localStorage.setItem('miri.role', {json.dumps(json.dumps('OWNER'))});"
                            f"sessionStorage.setItem('miri.draft', {json.dumps(json.dumps(draft))});")
        page = ctx.new_page()
        for r in ROUTES:
            page.goto(BASE + r)
            page.wait_for_timeout(700)
            if r == "#/conditions":
                page.locator("details.more summary").click()
                page.wait_for_timeout(200)
            res = page.evaluate("""() => {
              const iw = window.innerWidth, out = [];
              for (const el of document.querySelectorAll('#root *')) {
                const r = el.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) continue;
                const cs = getComputedStyle(el);
                if (cs.visibility === 'hidden' || cs.display === 'none') continue;
                if (r.right > iw + 1 && !el.closest('.map')) out.push(`${el.tagName.toLowerCase()}.${el.className}: right ${Math.round(r.right)} > ${iw} «${(el.innerText||'').slice(0,30)}»`);
                // 텍스트가 잘리는지(overflow hidden인데 내용이 더 넓음)
                if (cs.overflowX === 'hidden' && el.scrollWidth > el.clientWidth + 2 && el.children.length === 0 && (el.innerText||'').trim())
                  out.push(`잘림 ${el.tagName.toLowerCase()}.${el.className} «${el.innerText.slice(0,30)}»`);
              }
              return {sw: document.documentElement.scrollWidth, iw, out: out.slice(0, 8)};
            }""")
            if res["sw"] > res["iw"] + 1:
                problems.append(f"{w}px {r}: 가로 스크롤 {res['sw']}>{res['iw']}")
            for o in res["out"]:
                problems.append(f"{w}px {r}: {o}")
            if w == 320:
                parts = [x for x in r.strip("#/").split("?")[0].split("/") if len(x) < 30]   # id 제외
                name = "_".join(parts) or "root"
                page.screenshot(path=f"{OUT}/w320_{name}.png", full_page=True)
        ctx.close()
    b.close()
print(f"화면 {len(ROUTES)}개 × 폭 {len(WIDTHS)}개 검사 · 문제 {len(problems)}건")
for x in problems[:40]:
    print("  ✗", x)
sys.exit(1 if problems else 0)
