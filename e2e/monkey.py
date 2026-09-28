"""UI 몽키 테스트: 무작위로 누르고·입력하고·뒤로 가며 화면 오류를 찾는다.
실행: python e2e/monkey.py BASE_URL [단계수] [시드] [OUT_DIR]
BASE_URL 예: http://127.0.0.1:8000/  또는  file:///…/docs/demo/miri-demo.html
찾는 것: 페이지 예외·콘솔 오류, 서버 5xx, 빈 화면, 가로 스크롤, 끝나지 않는 로딩"""
import random
import re
import sys
import time
from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
STEPS = int(sys.argv[2]) if len(sys.argv) > 2 else 200
SEED = int(sys.argv[3]) if len(sys.argv) > 3 else 1
OUT = sys.argv[4] if len(sys.argv) > 4 else "e2e/monkey_out"
rnd = random.Random(SEED)
ROOT = BASE.split("#")[0]
VALUES = ["", "0", "300", "300.5", "0.5", "12,345", "8000", "250", "abc", "-5", "1e5", "강남", "홍대", "성수", "  ", "9999999999999",
          ".", "1.2.3", "가나다", "강남역 2번 출구", "서울 마포구", "x" * 60, "015", "4.5", "100"]
CODES = ["CS100010", "CS100008", "CS200033", "CS200036", "CS300018", "CS200028", "CS999999", "x"]


def main():
    import os
    os.makedirs(OUT, exist_ok=True)
    problems, log = [], []
    ids = {"analysis": set(), "report": set()}
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": rnd.choice([360, 390, 414]), "height": 800})
        page = ctx.new_page()
        ctx.on("page", lambda pg: pg.close())                               # '신청' 새 창은 닫기
        # 외부 네트워크 차단(로컬/파일만)
        ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(("http://127.0.0.1", "http://localhost", "file://", "data:"))
                  else r.abort())
        page.on("dialog", lambda d: d.accept())
        page.on("pageerror", lambda e: problems.append(("페이지 예외", str(e)[:300], list(log[-12:]))))
        # 브라우저가 4xx 응답마다 남기는 'Failed to load resource'는 앱이 처리하는 정상 흐름이라 제외
        page.on("console", lambda m: problems.append(("콘솔 오류", m.text[:300], list(log[-12:])))
                if m.type == "error" and "net::ERR_FAILED" not in m.text and "ERR_ABORTED" not in m.text
                and not re.search(r"status of 4\d\d", m.text) else None)
        page.on("response", lambda r: problems.append(("서버 5xx", f"{r.status} {r.url}", list(log[-12:]))) if r.status >= 500 else None)
        page.goto(BASE)
        for step in range(STEPS):
            m = re.search(r"#/analysis/([0-9a-f-]{36})", page.url)
            if m:
                ids["analysis"].add(m.group(1))
            m = re.search(r"#/report/([0-9a-f-]{36})", page.url)
            if m:
                ids["report"].add(m.group(1))
            act = rnd.choices(["click", "fill", "enter", "back", "goto", "reload"], weights=[62, 22, 5, 5, 5, 1])[0]
            desc = act
            try:
                if act == "click":
                    els = page.locator("button:visible, [role=option]:visible, a[href^='#']:visible, summary:visible, "
                                       "label.switch:visible").all()
                    els = [e for e in els if e.is_enabled()]
                    if els:
                        e = rnd.choice(els)
                        desc = f"click {(e.inner_text() or e.get_attribute('aria-label') or '')[:30]!r}"
                        e.click(timeout=2000)
                elif act == "fill":
                    ins = [i for i in page.locator("input:visible").all() if i.is_enabled() and i.get_attribute("type") != "checkbox"]
                    if ins:
                        i = rnd.choice(ins)
                        v = rnd.choice(VALUES)
                        desc = f"fill {i.get_attribute('id') or i.get_attribute('placeholder') or '?'}={v!r}"
                        i.fill(v, timeout=2000)
                elif act == "enter":
                    page.keyboard.press("Enter")
                elif act == "back":
                    page.go_back(timeout=3000)
                    if page.url.startswith("about:"):          # 기록의 맨 처음을 넘어간 경우(앱 문제 아님)
                        page.goto(BASE)
                elif act == "reload":
                    page.reload()
                else:
                    a = rnd.choice(sorted(ids["analysis"]) or ["00000000-0000-4000-8000-000000000000"])
                    r_ = rnd.choice(sorted(ids["report"]) or ["00000000-0000-4000-8000-000000000000"])
                    route = rnd.choice(["#/", "#/login", "#/area", "#/conditions", "#/interests", "#/reports", f"#/analysis/{a}",
                                        f"#/analysis/{a}/risk/{rnd.choice(CODES)}", f"#/analysis/{a}/breakeven/{rnd.choice(CODES)}",
                                        f"#/analysis/{a}/breakeven/CS100008?be={rnd.choice([1, 999999, 'x'])}", f"#/report/{r_}",
                                        "#/nowhere", f"#/login?next={rnd.choice(['%2Freports', 'https%3A%2F%2Fevil.example', '%2F%2Fevil'])}"])
                    desc = f"goto {route}"
                    page.goto(ROOT + route)
            except Exception as e:  # noqa: BLE001 — 요소가 사라지는 등 경합은 무시
                desc += f" (skip: {type(e).__name__})"
            log.append(f"{step}: {desc}")
            page.wait_for_timeout(120)
            # 로딩이 끝나는지
            t0 = time.time()
            while page.locator(".spinner:visible").count() and time.time() - t0 < 6:
                page.wait_for_timeout(200)
            if page.locator(".spinner:visible").count():
                problems.append(("끝나지 않는 로딩", page.url, list(log[-12:])))
            st = page.evaluate("""() => ({root: document.querySelector('#root')?.children.length || 0,
                text: (document.body.innerText || '').trim().length,
                sw: document.documentElement.scrollWidth, iw: window.innerWidth})""")
            if st["root"] == 0 or st["text"] < 3:
                problems.append(("빈 화면", page.url, list(log[-12:])))
                page.goto(ROOT)
            if st["sw"] > st["iw"] + 1:
                problems.append(("가로 스크롤", f"{page.url} {st['sw']}>{st['iw']}", list(log[-12:])))
                page.screenshot(path=f"{OUT}/hscroll_{SEED}_{step}.png")
            if "evil" in page.url and not page.url.startswith(ROOT):
                problems.append(("외부 이동", page.url, list(log[-12:])))
        b.close()
    uniq = {}
    for kind, msg, ctx_log in problems:
        uniq.setdefault((kind, re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27}", "<id>", msg)), ctx_log)
    print(f"[{BASE.split('/')[-1] or BASE}] 시드 {SEED} · {STEPS}단계 · 문제 {len(problems)}건(고유 {len(uniq)})")
    for (kind, msg), ctx_log in list(uniq.items())[:15]:
        print(f"  ✗ {kind}: {msg}")
        for l in ctx_log[-6:]:
            print(f"      {l}")
    return 1 if uniq else 0


if __name__ == "__main__":
    sys.exit(main())
