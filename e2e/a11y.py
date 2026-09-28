"""접근성 점검(axe-core, WCAG 2.1 AA): SB-01~09 주요 상태마다 axe를 돌려 위반을 모은다.
실행: (백엔드 8000 실행 중, frontend에 npm install 완료) python e2e/a11y.py [BASE_URL]
시트(모달)가 열린 상태는 시트 안만 검사한다(뒤 화면은 가려져 있어 대비 계산이 의미 없음)."""
import json, re, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/"
AXE = (Path(__file__).resolve().parent.parent / "frontend/node_modules/axe-core/axe.min.js").read_text()
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"]
found: dict[str, list] = {}


def audit(page, name, within=None):
    page.wait_for_timeout(200)
    if not page.evaluate("() => !!window.axe"):
        page.add_script_tag(content=AXE)
    ctx = json.dumps(within) if within else "document"
    res = page.evaluate(f"""async () => (await axe.run({ctx}, {{ runOnly: {{ type: 'tag', values: {json.dumps(TAGS)} }} }})).violations
        .map(v => ({{ id: v.id, impact: v.impact, nodes: v.nodes.map(n => n.target.join(' ') + ' | ' + (n.failureSummary || '').split('\\n').slice(1, 2).join('').trim()).slice(0, 4) }}))""")
    found[name] = res
    print(f"{name:22s} 위반 {len(res)}건" + ("" if not res else ": " + ", ".join(f"{v['id']}({v['impact']})" for v in res)))


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_context(viewport={"width": 390, "height": 844}, locale="ko-KR").new_page()
    page.goto(BASE + "#/"); page.get_by_role("button", name="분석 시작").wait_for(); audit(page, "sb01_start")
    page.get_by_role("button", name="분석 시작").click()
    page.get_by_label("지역·상권 검색").fill("강남"); page.get_by_role("option").first.wait_for()
    page.get_by_label("지역·상권 검색").press("ArrowDown"); audit(page, "sb02_search_open")      # 콤보박스 목록이 열린 상태
    page.get_by_label("지역·상권 검색").fill("강남역"); page.get_by_role("option").first.click()
    page.get_by_text("강남역이 있는 구").wait_for(); audit(page, "sb02_area")
    page.get_by_role("button", name=re.compile("후보 \\d곳 (중 \\d곳 )?비교")).click()                       # UC-02 후보 비교 시트
    page.get_by_role("dialog", name="후보 지역 비교").wait_for(); page.locator("table.cmp").wait_for()
    page.get_by_label("업종별로 보기 (선택)").select_option(label="커피-음료"); page.get_by_text("커피-음료 폐업 위험").wait_for()
    audit(page, "sb02_compare_sheet", within=".sheet")
    page.keyboard.press("Escape")
    page.get_by_role("button", name=re.compile("(으로|로) 분석$")).click()
    page.get_by_role("button", name="다음").click(); page.get_by_text("총 창업 예산을 입력해 주세요").wait_for()
    audit(page, "sb03_errors")                                                             # 오류가 칸과 연결됐는지
    assert page.evaluate("() => document.activeElement.id") == "budget", "첫 오류 칸으로 포커스가 가야 함"
    page.locator("#budget").fill("8000"); page.locator("#rent").fill("300"); page.locator("#labor").fill("250")
    page.get_by_role("radio", name="저비용형").click(); audit(page, "sb03_conditions")
    page.get_by_role("button", name="다음").click()
    page.get_by_role("button", name=re.compile("카페·디저트")).click(); audit(page, "sb04_interests")
    page.get_by_role("button", name=re.compile("전체 업종에서 고르기")).click()
    page.get_by_role("dialog").wait_for(); audit(page, "sb04_sheet", within=".sheet")
    page.keyboard.press("Escape")
    page.get_by_role("button", name="분석 시작").click(); page.get_by_text("적합도 점수").first.wait_for(); audit(page, "sb05_results")
    page.get_by_role("button", name="상세 위험도 보기").click(); page.get_by_text("주요 위험 요인").wait_for(); audit(page, "sb06_risk")
    page.get_by_role("button", name="손익분기").click(); page.get_by_text("매달 필요한 매출").wait_for(); audit(page, "sb07_breakeven")
    page.get_by_role("button", name="수정").click(); page.get_by_role("dialog").wait_for(); audit(page, "sb07_edit_sheet", within=".sheet")
    page.keyboard.press("Escape")
    page.get_by_role("button", name="리포트에 반영").click(); page.get_by_text("한줄 결론", exact=True).wait_for(); audit(page, "sb08_report")
    page.get_by_role("button", name="리포트 저장").click(); page.get_by_text("리포트를 저장했어요").wait_for()
    audit(page, "sb08_saved")                                                              # 저장 후(버튼·토스트)
    page.get_by_role("button", name="저장 리포트 보기").click(); page.get_by_text(re.compile("저장한 리포트 \\d+건")).wait_for(); audit(page, "sb09_saved")
    page.get_by_role("button", name=re.compile("리포트.* 메모")).first.click(); page.get_by_role("dialog", name="메모").wait_for()
    audit(page, "sb09_memo_sheet", within=".sheet")
    page.keyboard.press("Escape"); page.wait_for_timeout(400)
    page.get_by_role("button", name=re.compile("리포트.* 삭제")).first.click(); page.get_by_role("dialog", name="리포트 삭제").wait_for()
    audit(page, "sb09_delete_sheet", within=".sheet")
    page.keyboard.press("Escape"); page.wait_for_timeout(400)
    page.get_by_role("button", name="이 브라우저의 저장 목록 모두 지우기").click()
    page.get_by_role("dialog", name="저장 목록 모두 지우기").wait_for(); audit(page, "sb09_wipe_sheet", within=".sheet")
    b.close()

serious = [(k, v["id"]) for k, vs in found.items() for v in vs if v["impact"] in ("serious", "critical")]
for k, vs in found.items():
    for v in vs:
        for n in v["nodes"]:
            print(f"  [{k}] {v['id']}: {n}")
print(f"심각(serious·critical) {len(serious)}건")
sys.exit(1 if serious else 0)
