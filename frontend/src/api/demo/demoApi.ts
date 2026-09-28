// 서버 없이 브라우저 안에서 도는 데모 API. 계산 규칙은 백엔드와 같다(scripts/parity.ts로 결과 동일성 검증).
// 로그인 없이(0.2) 분석·저장 리포트가 모두 이 브라우저에만 남는다(localStorage, 막혀 있으면 메모리).
import type { Api, AreaCard, Candidates, Place } from "../types";
import { ApiError } from "../types";
import snapshot from "./snapshot.json";
import { areaCard, candidates, compareAreas, EngineError, searchLocal, State } from "./engine";
import * as S from "./service";

const KEY = "miri.demo.db.v3";            // 저장 구조가 바뀌면 올린다(옛 데이터는 무시) — v3: 체크리스트 항목 id·완료 표시

/** 로그인이 있던 0.1 데모가 남긴 저장소: 서버와 같게 다룬다 — 계정은 버리고, 계정으로 저장했던 목록은 보이지 않으며
 *  (그 계정만 보던 것이므로) 계정이 만든 분석도 열지 않는다(service.getAnalysis). 비회원 분석은 링크로 계속 열린다 */
function fromV01(d: any): S.StoreData {
  const out: S.StoreData = { ...S.emptyStore(), ...d };
  delete (out as any).users;
  out.saved = (Array.isArray(out.saved) ? out.saved : []).filter((x: any) => x && x.user_id == null);
  return out;
}

function loadStore(): S.StoreData {
  try {
    const s = localStorage.getItem(KEY);
    if (s) return fromV01(JSON.parse(s));
  } catch { /* 저장소 막힘 */ }
  return S.emptyStore();
}

/** 저장 리포트와 연결되지 않은 분석은 최근 keep개만 남긴다 */
function prune(store: S.StoreData, keep: number) {
  const savedReq = new Set(store.saved.map((x) => store.reports[x.report_id]?.request_id));
  const ids = Object.values(store.analyses).filter((a: any) => !savedReq.has(a.public_id))
    .sort((a: any, b: any) => (a.created_at < b.created_at ? 1 : -1)).slice(keep).map((a: any) => a.public_id);
  const drop = new Set(ids);
  for (const id of ids) delete store.analyses[id];
  for (const [rid, r] of Object.entries(store.reports)) if (drop.has((r as any).request_id)) delete store.reports[rid];
  store.risks = store.risks.filter((r) => !drop.has(r.request_id));
  store.breakevens = store.breakevens.filter((b) => !drop.has(b.request_id));
}

export async function createDemoApi(): Promise<Api> {
  const st = new State(snapshot as any);
  let store = loadStore();
  let memoryOnly = false;                               // 저장에 실패한 뒤로는 메모리가 최신 → 저장소에서 다시 읽지 않는다
  const persist = () => {
    try { localStorage.setItem(KEY, JSON.stringify(store)); memoryOnly = false; }
    catch {                                             // 용량 초과 등 → 저장하지 않은 오래된 분석부터 지우고 한 번 더
      try { prune(store, 10); localStorage.setItem(KEY, JSON.stringify(store)); memoryOnly = false; } catch { memoryOnly = true; }
    }
  };
  // 다른 탭이 저장한 내용을 덮어쓰지 않게: 요청마다 저장소를 다시 읽고(막혀 있으면 메모리 유지), 바꾸는 요청만 저장한다
  const refresh = () => {
    if (memoryOnly) return;
    try { if (localStorage.getItem(KEY) !== null) store = loadStore(); } catch { /* 저장소 막힘 → 메모리 유지 */ }
  };
  async function wrap<T>(fn: () => T | Promise<T>, mutates = false): Promise<T> {
    await new Promise((r) => setTimeout(r, 60));
    refresh();
    try {
      const out = await fn();
      if (mutates) persist();
      // 서버 응답처럼 복사본(삭제처럼 돌려줄 내용이 없으면 그대로 — JSON.parse(undefined)는 오류)
      return out === undefined ? out : JSON.parse(JSON.stringify(out));
    } catch (e: any) {
      if (e instanceof EngineError) throw new ApiError(e.status, { code: e.code, message: e.message, fields: e.fields });
      if (e instanceof ApiError) throw e;
      throw new ApiError(500, { code: "DEMO_ERROR", message: e?.message || "데모 계산 중 오류" });
    }
  }
  return {
    mode: "demo",
    meta: () => wrap(() => { const m = { ...st.snap.meta }; delete (m as any).area_order; return m; }),
    industries: () => wrap(() => st.snap.industries),
    searchPlaces: (q) => wrap(() => {
      if (!q.trim()) throw new EngineError(422, "EMPTY_QUERY", "검색어를 입력해 주세요");
      if (Array.from(q).length > 50) {   // 서버 Query(max_length=50)과 같게
        throw new EngineError(422, "VALIDATION_ERROR", "검색어가 너무 길어요", [{ field: "q", message: "검색어가 너무 길어요" }]);
      }
      return searchLocal(st, q.trim(), 8) as Place[];
    }),
    candidates: (lat, lng, r, name) => wrap(() => candidates(st, lat, lng, r, name ?? null) as Candidates),
    areaCard: (code) => wrap(() => {
      if (!(code in st.snap.areas)) throw new EngineError(404, "UNKNOWN_AREA", "상권을 찾을 수 없어요");
      return areaCard(st, code) as AreaCard;
    }),
    areaMap: () => wrap(() => st.snap.map),
    compareAreas: (codes, industry) => wrap(() => {
      if (!Array.isArray(codes) || codes.length < 1 || codes.length > 4) {
        throw new EngineError(422, "VALIDATION_ERROR", "비교 상권은 4개까지 고를 수 있어요", [{ field: "area_codes", message: "비교 상권은 4개까지 고를 수 있어요" }]);
      }
      return compareAreas(st, codes, industry ?? null);
    }),
    createAnalysis: (b) => wrap(() => {
      S.validateAnalysisIn(b);
      const { req } = S.runAnalysis(st, store, b);
      return S.analysisOut(st, req);
    }, true),
    getAnalysis: (id) => wrap(() => S.analysisOut(st, S.getAnalysis(store, id))),
    risk: (id, code, be) => wrap(() => {
      if (be !== undefined && be !== null && !(Number.isInteger(be) && be >= 1)) {
        throw new EngineError(422, "VALIDATION_ERROR", "손익분기 결과 값을 확인해 주세요", [{ field: "be", message: "손익분기 결과 값을 확인해 주세요" }]);
      }
      const out = S.riskFor(st, store, S.getAnalysis(store, id), code, be ?? null);
      delete out._risk_id;
      return out;
    }, true),
    breakeven: (id, b) => wrap(() => {
      S.validateBreakEvenIn(b);
      return S.computeBreakeven(st, store, S.getAnalysis(store, id), b, true);
    }, true),
    getBreakeven: (id, beId) => wrap(() => S.getSavedBreakeven(store, S.getAnalysis(store, id), beId)),
    createReport: (id, b) => wrap(() => {
      const req = S.getAnalysis(store, id);
      const rep = S.createReport(st, store, req, b.industry_code, b.break_even_id ?? null);
      return S.reportOut(st, store, rep, req);
    }, true),
    getReport: (id) => wrap(() => {
      const { rep, req } = S.getReport(store, id);
      return S.reportOut(st, store, rep, req);
    }),
    setItemDone: (rid, aid, done) => wrap(() => {
      if (typeof done !== "boolean") throw new EngineError(422, "VALIDATION_ERROR", "완료 여부를 확인해 주세요", [{ field: "done", message: "완료 여부를 확인해 주세요" }]);
      return S.setItemDone(store, rid, aid, done);
    }, true),
    saveReport: (rid, memo) => wrap(() => {
      if (memo !== null && memo !== undefined && [...memo].length > 500) {   // 서버처럼 글자(코드 포인트) 수
        throw new EngineError(422, "VALIDATION_ERROR", "메모가 너무 길어요", [{ field: "memo", message: "메모가 너무 길어요" }]);
      }
      const sr = S.saveReport(store, rid, memo ?? null);
      return { saved_report_id: sr.saved_report_id, report_id: rid };
    }, true),
    myReports: () => wrap(() => { const items = S.listSaved(st, store); return { count: items.length, items }; }),
    // report_svc._my_saved: 리포트 번호를 함께 받으면 그 리포트를 저장한 항목인지도 확인(다른 탭에서 지운 뒤 다시 저장한 항목 보호)
    deleteSaved: (sid, rid) => wrap(() => {
      const i = store.saved.findIndex((x) => x.saved_report_id === sid && (!rid || x.report_id === rid));
      if (i < 0) throw new EngineError(404, "SAVED_NOT_FOUND", "저장한 리포트를 찾을 수 없어요");
      store.saved.splice(i, 1);
    }, true),
    deleteAllSaved: () => wrap(() => { const deleted = store.saved.length; store.saved = []; return { deleted }; }, true),
    updateMemo: (sid, rid, memo) => wrap(() => {
      if (memo !== null && memo !== undefined && [...memo].length > 500) {
        throw new EngineError(422, "VALIDATION_ERROR", "메모가 너무 길어요", [{ field: "memo", message: "메모가 너무 길어요" }]);
      }
      const sr = store.saved.find((x) => x.saved_report_id === sid && (!rid || x.report_id === rid));
      if (!sr) throw new EngineError(404, "SAVED_NOT_FOUND", "저장한 리포트를 찾을 수 없어요");
      sr.memo = memo;
      return { saved_report_id: sr.saved_report_id, memo: sr.memo };
    }, true),
  };
}
