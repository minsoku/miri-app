// 데모 엔진 ↔ 백엔드 결과 동일성 검사.  사용: npx esbuild scripts/parity.ts --bundle --platform=node --outfile=/tmp/p.mjs --format=esm && node /tmp/p.mjs cases.json
import { readFileSync } from "fs";
import snapshot from "../src/api/demo/snapshot.json";
import { candidates, compareAreas, EngineError, searchLocal, State } from "../src/api/demo/engine";
import * as S from "../src/api/demo/service";

const st = new State(snapshot as any);
const cases = JSON.parse(readFileSync(process.argv[2], "utf-8"));
const VOLATILE = new Set(["id", "created_at", "analysis_id", "break_even_id", "saved_report_id", "action_id"]);
let n = 0, fails = 0;
const failures: string[] = [];

function cmp(a: any, b: any, path: string): string | null {
  if (typeof a === "number" && typeof b === "number") {
    if (a === b) return null;
    const d = Math.abs(a - b), m = Math.max(Math.abs(a), Math.abs(b));
    return d <= 1e-9 || d / m <= 1e-12 ? null : `${path}: py=${a} js=${b}`;
  }
  if (a === null || b === null || typeof a !== "object" || typeof b !== "object") {
    return a === b || (a === null && b === undefined) ? null : `${path}: py=${JSON.stringify(a)} js=${JSON.stringify(b)}`;
  }
  if (Array.isArray(a) !== Array.isArray(b)) return `${path}: 배열 여부 다름`;
  if (Array.isArray(a)) {
    if (a.length !== b.length) return `${path}: 길이 py=${a.length} js=${b.length} py0=${JSON.stringify(a[0])?.slice(0, 120)}`;
    for (let i = 0; i < a.length; i++) { const r = cmp(a[i], b[i], `${path}[${i}]`); if (r) return r; }
    return null;
  }
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const k of keys) {
    if (VOLATILE.has(k) || k.startsWith("_")) continue;
    if (!(k in a)) return `${path}.${k}: py에 없음 (js=${JSON.stringify(b[k])?.slice(0, 80)})`;
    if (!(k in b)) return `${path}.${k}: js에 없음 (py=${JSON.stringify(a[k])?.slice(0, 80)})`;
    const r = cmp(a[k], b[k], `${path}.${k}`);
    if (r) return r;
  }
  return null;
}
function run(fn: () => any): { status: number; body: any } {
  try { return { status: 200, body: fn() }; }
  catch (e: any) {
    if (e instanceof EngineError) return { status: e.status, body: { error: { code: e.code, message: e.message } } };
    throw e;
  }
}
function check(label: string, py: { status: number; body: any }, js: { status: number; body: any }) {
  n++;
  const pyOk = py.status < 300, jsOk = js.status < 300;
  let r: string | null = null;
  if (pyOk !== jsOk) r = `상태 py=${py.status} js=${js.status} ${JSON.stringify(py.body?.error || js.body?.error)}`;
  else if (!pyOk) r = py.body.error.code === js.body.error.code && py.body.error.message === js.body.error.message ? null
    : `오류 py=${JSON.stringify(py.body.error)} js=${JSON.stringify(js.body.error)}`;
  else r = cmp(py.body, js.body, "");
  if (r) { fails++; if (failures.length < 25) failures.push(`[${label}] ${r}`); }
}

for (const [ci, c] of cases.analyses.entries()) {
  const store = S.emptyStore();
  let req: any = null;
  const js = run(() => { S.validateAnalysisIn(c.input); const { req: q } = S.runAnalysis(st, store, c.input); req = q; return S.analysisOut(st, q); });
  check(`분석#${ci}`, c.analysis, { ...js, status: js.status === 200 ? 201 : js.status });
  if (!req) continue;
  const explicitBe: number[] = [];                 // 명시적 손익분기 단계에서 성공한 id (리포트 생성 중 자동 계산분 제외)
  for (const [si, step] of c.steps.entries()) {
    const label = `분석#${ci}/${step.op}#${si}(${step.code})`;
    if (step.op === "risk") {
      const beId = step.be === "last" ? (explicitBe[explicitBe.length - 1] ?? null) : null;   // 리포트에서 연 위험도(?be=)
      check(label, step.out, run(() => S.riskFor(st, store, req, step.code, beId)));
    } else if (step.op === "breakeven") {
      const out = run(() => { S.validateBreakEvenIn(step.body); return S.computeBreakeven(st, store, req, step.body, true); });
      if (out.status === 200) explicitBe.push(out.body.id);
      check(label, step.out, out);
    } else if (step.op === "report") {
      // 백엔드와 같은 순서의 손익분기 id를 쓰도록: "last"면 이 분석에서 마지막으로 계산한 것
      const beId = step.be === "last" ? (explicitBe[explicitBe.length - 1] ?? null) : null;
      const out = run(() => { const rep = S.createReport(st, store, req, step.code, beId); return S.reportOut(st, store, rep, req); });
      check(label, step.out, { ...out, status: out.status === 200 ? 201 : out.status });
    } else if (step.op === "get") {
      check(label, step.out, run(() => S.analysisOut(st, req)));
    }
  }
}
for (const [i, c] of cases.candidates.entries()) check(`후보#${i}`, c.out, run(() => candidates(st, c.lat, c.lng, c.radius_m, null)));
for (const [i, c] of (cases.compare || []).entries()) check(`비교#${i}`, c.out, run(() => compareAreas(st, c.body.area_codes, c.body.industry_code ?? null)));
for (const c of cases.search) {
  const js = run(() => { const q = c.q.trim(); if (!q) throw new EngineError(422, "EMPTY_QUERY", "검색어를 입력해 주세요"); return searchLocal(st, q, 8); });
  check(`검색:${c.q}`, c.out, js);
}
console.log(`비교 ${n}건 · 불일치 ${fails}건`);
failures.forEach((f) => console.log("  ✗", f));
process.exit(fails ? 1 : 0);
