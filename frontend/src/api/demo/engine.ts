// 데모 엔진: 백엔드(app/services/*, miri_engine/suitability·breakeven·explain)의 '요청 시점 계산'을 그대로 옮긴 것.
// 모델이 필요한 값(위험 점수·요인 효과)은 스냅샷에 미리 계산돼 있다. 백엔드와 결과 동일성은 e2e/parity 테스트로 확인.
import { pyFixed, pyPct, pyRound, pyRoundInt, pySigned } from "./pyfmt";
import { wonFloorBelow, wonValue } from "../../lib/won";

export type Num = number | null;
export interface Snapshot {
  version: number; meta: any; industries: { groups: any[]; industries: any[] };
  areas: Record<string, { name: string; level: string; lat: number; lng: number; geometry: any }>;
  area_cards: Record<string, any>; map: any;
  places: { name: string; aliases: string; kind: string; lat: number; lng: number; area_code: string | null }[];
  policies: any[]; rows: { cols: string[]; data: any[][] }; fallback: Record<string, any>; params: any;
}
export interface Row {
  area_id: string; industry_code: string; category: string; has_sales_data: boolean; stores: Num; exp4: Num; clo4: Num;
  ope4: Num; stores_avg4: number; sales_ps_m: Num; ticket: Num; tx_ps_day: Num; demand_D: Num; risk_score: number;
  risk_grade: string; risk_pct_in_ind: number; pred_annual_rate: number; confidence: string; local_weight: Num;
  rate_eb: Num; sales_growth: Num; store_growth: Num; ind_sales_growth: Num; p_rent_burden: Num; p_density: Num;
  rent4: Num; closed_months4: Num; mu_ind_entry?: Num; factors: [string, number, number][]; ind_avg_rate: Num; seoul_avg_rate: Num;
  profile: Num[] | null;
  sales_rank?: Num; sales_n?: number; sales_med?: Num;            // State가 계산(같은 업종, 매출 있는 지역끼리 1위=최고)
}
export class EngineError extends Error {
  constructor(public status: number, public code: string, message: string, public fields: { field: string; message: string }[] = []) {
    super(message);
  }
}

const ok = (x: any): x is number => x !== null && x !== undefined && typeof x === "number" && isFinite(x);
const okPos = (x: any): x is number => ok(x) && x > 0;

// ════════════════════════ 상태 ════════════════════════
export class State {
  snap: Snapshot; rows: Row[]; index = new Map<string, number>(); byArea = new Map<string, Row[]>();
  byInd = new Map<string, Row[]>(); industries = new Map<string, any>(); areaOrder: string[];
  constructor(snap: Snapshot) {
    this.snap = snap;
    const cols = snap.rows.cols;
    this.rows = snap.rows.data.map((d) => { const o: any = {}; cols.forEach((c, i) => { o[c] = d[i]; }); return o as Row; });
    this.rows.forEach((r, i) => {
      this.index.set(`${r.area_id}|${r.industry_code}`, i);
      if (!this.byArea.has(r.area_id)) this.byArea.set(r.area_id, []);
      this.byArea.get(r.area_id)!.push(r);
      if (!this.byInd.has(r.industry_code)) this.byInd.set(r.industry_code, []);
      this.byInd.get(r.industry_code)!.push(r);
    });
    snap.industries.industries.forEach((i) => this.industries.set(i.code, i));
    this.areaOrder = (snap.meta.area_order as string[] | undefined) || Object.keys(snap.areas);
    // engine.load_state와 같은 점포당 매출 순위: rank(method="min", 내림차순), 표본 수 = 매출 있는 지역 수
    for (const rows of this.byInd.values()) {
      const vals = rows.filter((r) => ok(r.sales_ps_m)).map((r) => r.sales_ps_m as number);
      // 서울 같은 업종 점포당 매출 중간값(pandas median: 짝수 개면 가운데 두 값의 평균) — narrative.sales_outlier
      const sorted = vals.slice().sort((a, b) => a - b), m = sorted.length;
      const med = m ? (m % 2 ? sorted[(m - 1) / 2] : (sorted[m / 2 - 1] + sorted[m / 2]) / 2) : null;
      for (const r of rows) {
        r.sales_n = vals.length;
        r.sales_med = med;
        r.sales_rank = ok(r.sales_ps_m) ? 1 + vals.filter((v) => v > (r.sales_ps_m as number)).length : null;
      }
    }
    if (Array.isArray(snap.params?.risk_cuts)) CUTS = snap.params.risk_cuts;
    if (ok(snap.params?.suitability?.outlier_sales_x)) OUTLIER_X = snap.params.suitability.outlier_sales_x;
  }
  row(area: string, code: string): Row | null { const i = this.index.get(`${area}|${code}`); return i === undefined ? null : this.rows[i]; }
  areaRows(area: string): Row[] { return this.byArea.get(area) || []; }
  get p() { return this.snap.params; }
  profile(r: Row | null): any | null {
    if (!r || !r.profile) return null;
    const pr = r.profile, tk: string[] = this.p.time_keys, ak: string[] = this.p.age_keys;
    const ts: Record<string, number> = {};
    tk.forEach((k, i) => { ts[k] = pr[i] as number; });
    let peak = tk[0];
    tk.forEach((k) => { if (ts[k] > ts[peak]) peak = k; });
    const out: any = { time_share: ts, peak_slot: peak, weekend_share: pr[6], female_share: pr[7], age_share: {}, top_age: null };
    if (pr.length > 8) {
      ak.forEach((k, i) => { out.age_share[k] = pr[8 + i]; });
      let top = ak[0];
      ak.forEach((k) => { if (out.age_share[k] > out.age_share[top]) top = k; });
      out.top_age = top;
    }
    return out;
  }
  /** 압축된 요인 → top_factors() 형식 */
  factors(fs: [string, number, number][], n?: number) {
    const names = this.p.factor_names, labels = this.p.factor_labels;
    return fs.slice(0, n ?? fs.length).map(([code, eff, disp]) => {
      const label = eff > 0 ? labels[code][0] : labels[code][1];
      return { factor_code: code, factor_name: names[code], label, effect_pct: eff, effect_display: disp,
        explanation: `${label}: 예상 폐업률 ${eff > 0 ? "+" : "−"}${Math.abs(disp)}%` };
    });
  }
}

// ════════════════════════ narrative.py ════════════════════════
export function josa(word: string, pair: string): string {
  const [a, b] = pair.split("/");
  const ch = word ? word.charCodeAt(word.length - 1) : 0;
  if (!(ch >= 0xac00 && ch <= 0xd7a3)) return pair !== "으로/로" ? `${word}${a}(${b})` : `${word}(으)로`;
  const jong = (ch - 0xac00) % 28;
  if (pair === "으로/로") return word + (jong === 0 || jong === 8 ? "로" : "으로");
  return word + (jong ? a : b);
}
const stripZeros = (s: string) => s.replace(/0+$/, "").replace(/\.$/, "");
export function won(x: any, unit = "원"): string {
  if (!ok(x)) return "-";
  if (Math.abs(x) >= 99_995_000) return `${stripZeros(pyFixed(x / 1e8, 2, true))}억${unit}`;
  if (Math.abs(x) >= 1e5) return `${pyFixed(x / 1e4, 0, true)}만${unit}`;
  if (Math.abs(x) >= 1e4) return `${stripZeros(pyFixed(x / 1e4, 1))}만${unit}`;
  return `${pyFixed(x, 0, true)}${unit}`;
}
/** narrative.won_value·won_floor_below: 표시값 계산(화면 lib/format과 같은 구현을 쓴다) */
export { wonFloorBelow, wonValue };
/** 작은 금액(3.3㎡당 임대료 등): 1만~100만원은 소수 첫째 자리까지 */
export function won1(x: any): string {
  if (ok(x) && Math.abs(x) >= 1e4 && Math.abs(x) < 1e6) return `${pyFixed(x / 1e4, 1, true)}만원`;
  return won(x);
}
export const pct = (x: any, digits = 1) => (!ok(x) ? "-" : `${pyFixed(x * 100, digits)}%`);
/** narrative.signed_pct: 반올림하면 0이 되는 값은 부호 없이 */
export function signedPct(x: number, digits = 1): string {
  if (Math.abs(x) * 10 ** (digits + 2) < 0.5) return `${pyFixed(0, digits)}%`;
  return `${pySigned(x * 100, digits)}%`.replace(/-/g, "−");
}
const signedPct1 = (x: number) => signedPct(x, 1);
export const times = (r: number) => (r >= 0.005 ? `${pyFixed(r, 2)}배` : "0.01배 미만");
const ra = (t: string) => t + (t.endsWith("미만") ? "이라" : "라");
const yeyo = (t: string) => t + (t.endsWith("미만") ? "이에요" : "예요");
/** narrative.factor_label: 상대 추세 요인의 라벨을 실제 증감 부호와 맞춘다 */
/** narrative.shown_effect: 화면에 보이는 요인 효과 크기(정수 %) — 라벨('약간')·체크리스트·알약 기준을 화면 숫자와 맞춘다 */
export function shownEffect(f: any): number {
  return ok(f.effect_display) ? Math.abs(Math.trunc(f.effect_display)) : Math.floor(Math.abs(f.effect_pct) + 0.5);
}
const SMALL_LABELS: Record<string, [string, string]> = {
  short_life: ["지역 전체 폐업 점포 수명 약간 짧은 편", "지역 전체 폐업 점포 수명 약간 긴 편"],
  low_sales: ["점포당 매출 약간 낮은 편", "점포당 매출 약간 높은 편"],
  ind_base: ["업종 자체 폐업률 약간 높은 편", "업종 자체 폐업률 약간 낮은 편"],
  area_hist: ["이 지역 폐업 이력 약간 많은 편", "이 지역 폐업 이력 약간 적은 편"],
  entry_heat: ["신규 개업 약간 많은 편", "신규 개업 약간 적은 편"] };
export function factorLabel(f: any, x: any = {}): string {
  const c = f.factor_code, up = f.effect_pct > 0;
  if (c === "store_surge" && ok(x.store_growth)) {
    const g = x.store_growth, s = Math.abs(g) < 0.0005 ? 0 : g > 0 ? 1 : -1;
    if (s === 0) return "점포 수 거의 그대로";
    if (up) return s > 0 ? "점포 늘어나는 중" : "점포 감소 폭이 작음";
    return s < 0 ? "점포 줄어드는 중" : "점포 증가 폭이 작음";
  }
  if (c === "sales_decline" && ok(x.sales_growth)) {
    const g = x.sales_growth, s = Math.abs(g) < 0.0005 ? 0 : g > 0 ? 1 : -1;
    if (s === 0) return "매출 거의 그대로";
    if (up) return s < 0 ? "매출 줄어드는 중" : "매출 증가 폭이 작음";
    return s > 0 ? "매출 늘어나는 중" : "매출 감소 폭이 작음";
  }
  if (c === "entry_heat" && entrySmoothed(f, x)) return up ? "개업 비율(보정값) 높은 편" : "개업 비율(보정값) 낮은 편";
  // 효과가 작으면(3% 미만) '짧은 편/낮음' 대신 '약간' — 체크리스트·운영자금 기준(3% 이상만 반영)과 어긋나 보이지 않게
  if (c === "area_hist" && ok(x.rate_eb) && ok(x.ind_avg) && pct(annual(x.rate_eb)) === pct(x.ind_avg)) return "이 지역 폐업 이력 업종 평균 수준";
  if (c === "low_sales" && !up && ok(x.sales_outlier)) return "점포당 매출 높음(대형 점포 가능·참고용)";   // 대형 점포가 섞인 듯한 평균
  if (c in SMALL_LABELS && shownEffect(f) < 3) return SMALL_LABELS[c][up ? 0 : 1];
  return f.label;
}
/** narrative.annual: 분기 폐업률 → 연 폐업률(4분기 복리, 곱셈으로 백엔드와 같은 값) */
export function annual(q: number): number {
  const a = 1.0 - Math.min(Math.max(q, 0.0), 1.0);
  return 1.0 - (a * a) * (a * a);
}
/** narrative.entry_smoothed: 보정 때문에 실제 개업 비율과 반대 방향인지 */
export function entrySmoothed(f: any, x: any): boolean {
  const ope = x.ope4, exp4 = x.exp4, mu = x.mu_ind_entry;
  if (!(ok(ope) && ok(exp4) && exp4 > 0 && ok(mu))) return false;
  const raw = ope / exp4;
  return (f.effect_pct > 0 && raw < mu) || (f.effect_pct < 0 && raw > mu);
}
export function relabel(fs: any[], x: any): any[] {
  return fs.map((f) => {
    const label = factorLabel(f, x);
    const g: any = { ...f, label };
    if ("explanation" in f && "effect_display" in f) g.explanation = `${label}: 예상 폐업률 ${f.effect_pct > 0 ? "+" : "−"}${Math.abs(f.effect_display)}%`;
    return g;
  });
}
const LOC_WORD: Record<string, string> = { 낮음: "낮은 편", 보통: "중간", 높음: "높은 편", 고위험: "매우 높은 편" };
export const OFFER: Record<string, string> = { 외식업: "메뉴", 서비스업: "서비스", 소매업: "상품" };
export const TARGETS: Record<string, string> = { 외식업: "객단가·회전율", 서비스업: "객단가·재방문율", 소매업: "객단가·구매 전환율" };
let CUTS: number[] = [40, 70, 90];                 // State가 스냅샷의 risk_cuts로 바꾼다(miri_engine.config와 같은 값)
const cutGrade = (s: number) => (s >= CUTS[2] ? "고위험" : s >= CUTS[1] ? "높음" : s >= CUTS[0] ? "보통" : "낮음");

const ACADEMY_CODES = ["CS200001", "CS200002", "CS200003", "CS200005"];   // 학원 계열(손님이 학생 — '직장인 대상' 문구 제외)
const LUNCH_BY_CODE: Record<string, string> = { CS200031: "맡기고 찾는 손님이 몰리는 시간대에 인력 배치" };   // 세탁소
export function peakFlags(profile: any, category: string | null = null, industryCode: string | null = null): any[] {
  if (!profile) return [];
  const ts = profile.time_share || {}, out: any[] = [];
  const g = (k: string) => (ts[k] ?? 0) as number;
  const c = category || "";
  const lunch = LUNCH_BY_CODE[industryCode || ""] ?? (industryCode && ACADEMY_CODES.includes(industryCode) ? "점심 시간대 수업·상담 인력 배치"
    : ({ 외식업: "회전율 높이는 메뉴·동선 설계", 소매업: "시간대 진열·계산대 인력 집중",
      서비스업: "예약 시간 조정·인력 배치로 대기 줄이기" } as any)[c] ?? "시간대에 맞춘 인력 배치");
  const weekend = ({ 외식업: "주말 인력·재고 먼저 확보", 소매업: "주말 인력·재고 먼저 확보", 서비스업: "주말 인력·예약 먼저 확보" } as any)[c]
    ?? "주말 인력 먼저 확보";
  const weekday = industryCode && ACADEMY_CODES.includes(industryCode) ? "평일 수업 시간 중심으로 운영 계획"
    : ({ 외식업: "직장인 대상 평일 메뉴·영업시간 구성", 소매업: "직장인 대상 평일 상품·영업시간 구성",
      서비스업: "직장인 대상 평일 영업시간·예약 구성" } as any)[c] ?? "직장인 대상 평일 영업시간 구성";
  if (g("t11") >= 0.3) out.push({ code: "lunch", pill: "점심 피크 집중", share: ts.t11,
    action: `점심 피크(11~14시, 매출 ${pyPct(ts.t11, 0)}) ${lunch}` });
  if (g("t17") >= 0.4) out.push({ code: "dinner", pill: "저녁 피크 집중", share: ts.t17,
    action: `저녁 피크(17~21시, 매출 ${pyPct(ts.t17, 0)})에 인력 집중 배치` });
  const night = g("t21") + g("t00");
  if (night >= 0.4) out.push({ code: "night", pill: "야간 매출 의존", share: night,
    action: `야간(21~06시) 매출 ${pyPct(night, 0)} — 심야 인건비·안전 운영 계획` });
  const we = profile.weekend_share;
  if (ok(we) && we >= 0.4) out.push({ code: "weekend", pill: "주말 매출 의존", share: we, action: `주말 매출 ${pyPct(we, 0)} — ${weekend}` });
  else if (ok(we) && we <= 0.15) out.push({ code: "weekday", pill: "평일 위주 상권", share: 1 - we,
    action: `평일 매출 ${pyPct(1 - we, 0)} — ${weekday}` });
  return out;
}
export function reasonShort(it: any): string {
  const parts: string[] = [];
  const rk = it.sales_rank, n = it.sales_n, D = it.D;
  if (ok(rk) && ok(n) && ok(D)) {
    const unit = it.unit || "구";
    if (n < 5) parts.push(`점포당 매출이 서울 ${Math.trunc(n)}개 ${unit} 중 ${Math.trunc(rk)}위예요.`);   // 참고용이라는 말은 score_note가 한다
    else {
      const share = rk / n;                     // 순위 ÷ 비교 대상 수(narrative.reason_short)
      const lvl = share <= 0.3 ? "높은 편" : share > 0.7 ? "낮은 편" : "중간";
      parts.push(`점포당 매출이 서울 ${Math.trunc(n)}개 ${unit} 중 ${Math.trunc(rk)}위로 ${lvl}이에요.`);
    }
  }
  const g = it.risk_grade, loc = it.risk_pct_in_ind;
  if ((g === "높음" || g === "고위험") && ok(loc) && cutGrade(loc) === "낮음") {
    parts.push(`종합 폐업 위험은 ${g === "고위험" ? "매우 " : ""}높지만 같은 업종끼리 비교하면 이 지역은 입지 위험이 낮은 편이에요(${Math.trunc(loc)}).`);
  } else parts.push(({ 낮음: "폐업 위험은 낮아요.", 보통: "폐업 위험은 보통이에요.", 높음: "폐업 위험이 높은 편이에요.",
    고위험: "폐업 위험이 매우 높아요." } as any)[g] || "");
  return parts.filter(Boolean).join(" ");
}
export function reasonChips(it: any): string[] {
  const c: string[] = [];
  if (ok(it.sales_ps_m)) c.push(`점포당 월매출 ${won(it.sales_ps_m)}`);
  if (ok(it.pred_annual_rate)) c.push(`예상 연 폐업률 ${pct(it.pred_annual_rate)}`);
  if (ok(it.achievability_ratio)) {
    const base = it.owner_included ? "필요 매출(목표 월수입 포함)" : "손익분기";   // 대형 점포가 섞인 듯한 평균이면 배율도 참고용
    c.push(`평균 매출이 ${base}의 ${times(it.achievability_ratio)}` + (ok(it.sales_outlier) ? "(참고용)" : ""));
  } else if (it.cogs_missing) c.push("손익분기 미확인(원가율 미입력)");   // '매출 ≥ 월 고정비'만 봤음 — 순위만 보고 흑자로 읽지 않게
  if (ok(it.stores_avg4)) c.push(`점포 ${pyFixed(it.stores_avg4, 0, true)}개`);
  return c;
}
export function cautionPills(it: any, _profile: any): string[] {
  const pills: string[] = [];
  if (ok(it.achievability_ratio) && it.achievability_ratio < 1) {
    pills.push(it.owner_included ? "평균 매출로 필요 매출(목표 월수입 포함) 미달" : "평균 매출로 손익분기 미달");
  }
  if (ok(it.sales_outlier)) pills.push(OUTLIER_PILL);
  if (it.risk_grade === "고위험") pills.push("폐업 위험 매우 높음");
  else if (it.risk_grade === "높음") pills.push("폐업 위험 높음");
  const ups = (it.risk_factors || []).filter((f: any) => f.effect_pct > 0 && shownEffect(f) >= 5 && f.factor_code !== "ind_base");
  if (ups.length) pills.push(ups[0].label);
  if (it.confidence === "낮음") pills.push("데이터 적음");
  return pills.slice(0, 3);
}
export function riskSummary(areaName: string, r: any, fallback = false): string {
  const score = Math.trunc(r.risk_score), g = r.risk_grade;
  const top = Math.max(1, 100 - score);
  const pos = ({ 낮음: "위험이 낮은 편이에요.", 보통: "중간 수준이에요.", 높음: `위험이 높은 편이에요(상위 ${top}%).`,
    고위험: `위험이 매우 높아요(상위 ${top}%).` } as any)[g] ?? "";
  const s = `${areaName} ${r.industry_name}의 향후 1년 예상 폐업률은 ${pct(r.pred_annual_rate)}로, 서울 전체 지역·업종 조합 중 ${pos}`;
  if (fallback) return s + " 이 지역에는 같은 업종 점포가 없어 입지 비교는 하지 않았어요.";
  const loc = Math.trunc(r.risk_pct_in_ind);
  return s + ` 같은 업종끼리 비교하면 이 지역 입지 위험은 ${LOC_WORD[cutGrade(loc)]}이에요(${loc}).`;
}
export function factorDetail(f: any, x: any = {}): string {
  const c = f.factor_code, same = "같은 업종 다른 지역과 비교";
  if (c === "ind_base") {
    if (ok(x.ind_avg) && ok(x.seoul_avg)) return `업종 전체(서울) 연 폐업률 ${pct(x.ind_avg)} · 서울 전 업종 ${pct(x.seoul_avg)}`;
    return "업종 전체(서울) 폐업률을 전 업종 평균과 비교";
  }
  if (c === "area_hist") {
    if (ok(x.rate_eb) && ok(x.ind_avg)) {
      const local = pct(annual(x.rate_eb)), avg = pct(x.ind_avg), clo = ok(x.clo4) ? `${pyFixed(x.clo4, 0, true)}곳` : null;
      if (ok(x.local_weight) && x.local_weight < 0.8) return (clo ? `이 지역 최근 1년 폐업 ${clo} — ` : "") + `업종 평균(${avg}) 쪽으로 보정한 폐업률 ${local}로 비교`;
      return `이 지역 최근 1년 폐업률 ${local}` + (clo ? `(폐업 ${clo})` : "") + ` · 업종 평균 ${avg}`;
    }
    if (ok(x.clo4) && ok(x.stores_avg4) && x.stores_avg4 > 0) {
      return `이 지역 최근 1년 폐업 ${pyFixed(x.clo4, 0, true)}곳(평균 점포 ${pyFixed(x.stores_avg4, 0, true)}곳) — 점포가 적은 곳은 서울 평균 쪽으로 보정해 비교`;
    }
    return "이 지역·업종의 최근 1년 폐업 이력을 업종 평균과 비교";
  }
  if (c === "sales_decline") return ok(x.sales_growth) ? `이 지역 같은 업종 매출 전년 대비 ${signedPct1(x.sales_growth)} — ${same}` : `이 지역 같은 업종 매출 추세를 ${same}`;
  if (c === "store_surge") return ok(x.store_growth) ? `이 지역 같은 업종 점포 수 전년 대비 ${signedPct1(x.store_growth)} — ${same}` : `이 지역 같은 업종 점포 수 추세를 ${same}`;
  if (c === "entry_heat") {
    if (ok(x.ope4) && entrySmoothed(f, x)) return `최근 1년 같은 업종 개업 ${pyFixed(x.ope4, 0, true)}곳 — 점포가 적어 서울 같은 업종 평균 쪽으로 보정한 개업 비율로 비교`;
    return ok(x.ope4) ? `최근 1년 같은 업종 개업 ${pyFixed(x.ope4, 0, true)}곳 — 점포 대비 개업 비율을 ${same}` : `점포 대비 개업 비율을 ${same}`;
  }
  if (c === "rent_burden") return `임대료 ÷ 점포당 매출을 ${same}`;
  if (c === "density") return `유동인구 대비 점포 수를 ${same}`;
  if (c === "low_sales") return ok(x.sales_ps_m) ? `점포당 월매출 ${won(x.sales_ps_m)} — ${same}` : `점포당 월매출을 ${same}`;
  if (c === "short_life") return ok(x.closed_months4) ? `이 지역 전 업종 폐업 점포 평균 영업 ${pyFixed(x.closed_months4, 0)}개월 — 다른 지역과 비교(업종별 값 아님)` : "이 지역 전 업종 폐업 점포의 평균 영업 기간을 다른 지역과 비교";
  if (c === "ind_trend") return ok(x.ind_sales_growth) ? `업종 전체(서울) 매출 전년 대비 ${signedPct1(x.ind_sales_growth)}` : "업종 전체(서울) 매출 추세";
  return "";
}
/** narrative.months_floor: 운영비 개월 수 소수 첫째 자리 내림(11.96 → 11.9) */
export const monthsFloor = (m: number) => { const s = (Math.floor(m * 10 + 1e-9) / 10).toFixed(1); return s.endsWith(".0") ? s.slice(0, -2) : s; };   // 6.0 → '6
/** suitability.sales_outlier_x / narrative.sales_outlier: 점포당 매출 ÷ 서울 같은 업종 중간값(기준 배수 이상일 때만) — 대형 점포 가능성 */
export const OUTLIER_REASON = "점포당 매출이 서울 중간값";      // 추천 제외 이유 앞부분
let OUTLIER_X = 3.0;                                             // State가 스냅샷 params.suitability.outlier_sales_x로 바꾼다
export function salesOutlierX(row: any, x = OUTLIER_X): number | null {
  if (!row) return null;
  const v = row.sales_ps_m, med = row.sales_med;
  if (!(ok(v) && ok(med)) || med <= 0 || v / med < x) return null;
  return v / med;
}
export const salesOutlier = (row: any) => salesOutlierX(row, OUTLIER_X);
export const OUTLIER_PILL = "매출이 유난히 높음(대형 점포 가능)";
export const BIG_STORE: Record<string, string> = { 소매업: "도매 상가·대형 점포", 외식업: "대형 매장", 서비스업: "대형·기업형 점포" };
/** narrative.data_caveat: 매출 추정이 흔들리는 경우(비교할 구 5곳 미만·대형 점포가 섞인 듯한 매출) */
export function dataCaveat(focus: any): string | null {
  const n = focus.few_sales_areas, x = focus.sales_outlier;
  if (ok(n)) return `매출을 비교할 구가 ${Math.trunc(n)}곳뿐이라 매출 추정은 참고용이에요.`;
  if (ok(x)) return `이 지역 점포당 매출이 서울 같은 업종 중간값의 ${pyFixed(x, 1)}배로 높아 ${josa(BIG_STORE[focus.category] ?? "대형 점포", "이/가")} 섞였을 수 있어요 — 비슷한 규모 점포의 실제 매출을 확인하세요.`;
  return null;
}
/** narrative.risk_is: 낮음·보통 등급 문장 조각 — end '고' / '지만' / '요'(문장 끝) */
export function riskIs(g: string, rate: string, end: "고" | "지만" | "요"): string {
  const stem = ({ 낮음: ["낮고", "낮지만", "낮아요"], 보통: ["보통 수준이고", "보통 수준이지만", "보통 수준이에요"] } as Record<string, string[]>)[g]
    ?? [`${g}이고`, `${g}이지만`, `${g}이에요`];
  const word = stem[{ 고: 0, 지만: 1, 요: 2 }[end]];
  return `폐업 위험이 ${word}(예상 연 폐업률 ${rate})` + (end === "요" ? "." : "");
}
/** narrative.budget_caveat: 예산·운영자금 단서 */
export function budgetCaveat(focus: any): string | null {
  const over = focus.over_budget;
  if (ok(over) && over > 0) return `초기 투자비가 예산보다 ${won(over)} 많아 운영자금이 남지 않아요. 자금 계획부터 다시 세우세요.`;
  const rm = focus.reserve_months, months = Math.trunc(Number(focus.runway_months || 6));   // 체크리스트와 같은 기준(6·12개월)
  if (ok(rm) && rm < months) {
    const inv = Number(focus.investment || 0);
    if (rm <= 0 && inv > 0) return "예산을 초기 투자비로 모두 써서 운영자금이 없어요. 자금 계획부터 다시 세우세요.";
    const lead = inv > 0 ? "예산에서 투자비를 빼면" : "예산으로는";
    const have = rm < 1 ? "1개월분도 안 돼" : `${monthsFloor(rm)}개월분뿐이라`;
    return `${lead} 운영비가 ${have} 운영자금(${months}개월분)부터 마련하세요.`;
  }
  return null;
}
export function oneLiner(area: string, focus: any, alt: any, be: any, areaAlt: any = null): string {
  const name = focus.industry_name, g = focus.risk_grade, rate = pct(focus.pred_annual_rate);
  const subj = `${area} ${josa(name, "은/는")}`;
  const high = g === "높음" || g === "고위험";
  const loc = focus.location_risk_pct;
  const ratio = be ? be.achievability_ratio : null;
  const short = ok(ratio) && ratio < 1;
  const owner = Number(be?.composition?.owner_salary || 0);
  const bep = owner > 0 ? "필요 매출(목표 월수입 포함)" : "손익분기";   // 목표 월수입을 넣었으면 배율의 기준도 그 말로(SB-05·07·08과 같게)
  const altS = alt ? `비슷한 업종인 ${josa(alt.industry_name, "은/는")} 예상 연 폐업률이 ${pct(alt.pred_annual_rate)}(위험 ${alt.risk_grade})예요 — 함께 비교해 보세요.` : null;
  const afford = !areaAlt || areaAlt.cogs_known !== false ? "평균 매출로 지금 비용을 감당할 만한"
    : `평균 매출이 지금 월 고정비${areaAlt.owner_included ? "(목표 월수입 포함)" : ""}보다 큰`;
  const areaS = areaAlt ? `이 업종을 하려면 입지 위험이 더 낮고 ${afford} ${areaAlt.area_name}(입지 위험 ${areaAlt.location_risk_pct}, 예상 연 폐업률 ${pct(areaAlt.pred_annual_rate)})도 비교해 보세요.` : null;
  if (focus.fallback) {
    return `${area}에는 최근 1년 ${name} 점포가 없어 서울 같은 업종 평균으로만 추정했어요(예상 연 폐업률 ${rate}). ` +
      "이 지역 수요는 검증되지 않았으니 주변 상권을 현장에서 먼저 확인하세요.";
  }
  if (focus.license) {
    if (short) {                                   // 자격이 있어도 적자인 구조면 그것도 함께
      return `${subj} ${focus.license} 자격이 있어야 열 수 있어요. 자격이 있어도 평균 매출이 ${bep}의 ${ra(times(ratio))} 지금 비용 구조로는 모자라요(폐업 위험 ${g}, 예상 연 폐업률 ${rate}).`;
    }
    return `${subj} ${focus.license} 자격이 있어야 열 수 있어요. 자격 요건부터 확인하세요(폐업 위험 ${g}, 예상 연 폐업률 ${rate}).`;
  }
  if (high) {
    const crit = g === "고위험", head = `${area}에서 ${josa(name, "은/는")}`;
    const lg = ok(loc) ? cutGrade(Math.trunc(loc)) : null;
    const dc = dataCaveat(focus);
    const good = !short && ok(ratio) && ratio >= 1.15 && (lg === "낮음" || lg === "보통") && !focus.block && !dc;
    let s1: string;
    if (short) {
      s1 = crit ? `${head} 폐업 위험이 매우 높고(예상 연 폐업률 ${rate}) 평균 매출도 ${bep}의 ${ra(times(ratio))} 창업 재검토를 권해요.`
        : `${head} 폐업 위험이 높고(예상 연 폐업률 ${rate}) 평균 매출도 ${bep}의 ${yeyo(times(ratio))}.`;
    } else if (!short && ok(ratio) && ratio < 1.15) {   // 손익분기는 넘지만 여유가 적음(빠듯)
      s1 = crit ? `${head} 폐업 위험이 매우 높고(예상 연 폐업률 ${rate}) 평균 매출도 ${bep}의 ${ra(times(ratio))} 여유가 적어 창업 재검토를 권해요.`
        : `${head} 폐업 위험이 높고(예상 연 폐업률 ${rate}) 평균 매출도 ${bep}의 ${ra(times(ratio))} 여유가 적어요.`;
    } else if (crit) s1 = `${head} 폐업 위험이 매우 높아(예상 연 폐업률 ${rate}) 창업 재검토를 권해요.`;
    else if (good) s1 = `${head} 업종 특성상 폐업 위험이 높아요(예상 연 폐업률 ${rate}).`;
    else s1 = `${head} 폐업 위험이 높아요(예상 연 폐업률 ${rate}).`;
    if (ok(loc) && loc >= 90) s1 += ` 같은 업종끼리 비교해도 이 지역 입지 위험이 매우 높아요(${Math.trunc(loc)}).`;   // 관심 업종이라도 주의 업종이면
    if (focus.block && !short) return `${s1} ${focus.block}`;
    const bc = budgetCaveat(focus);
    const also = [bc, dc].filter((c) => c).map((c) => ` 또 ${c}`).join("");   // 대안을 권해도 운영자금·매출 추정 문제는 빠뜨리지 않는다(둘 다)
    const needBe = !be && !focus.fixed_zero ? " 원가율을 넣어 손익분기도 확인하세요." : "";   // 원가율을 모르는 업종은 위험이 높아도 손익 확인을 권한다
    if (good) {
      if (crit && (altS || areaS)) return `${s1} ${altS || areaS}${also}`;      // 매우 높으면 대안 비교가 먼저
      const facts = `같은 업종끼리 비교한 입지 위험은 ${LOC_WORD[lg as string]}(${Math.trunc(loc)})이고 평균 매출이 ${bep}의 `;
      if (bc) return `${s1} 다만 ${facts}${yeyo(times(ratio))}. 또 ${bc}`;
      const tail = !crit ? "비용을 지키면 검토해 볼 만해요." : "그래도 한다면 비용을 지키고 운영자금부터 확보하세요.";
      return `${s1} 다만 ${facts}${ra(times(ratio))} ${tail}`;
    }
    if (altS || areaS) return `${s1} ${altS || areaS}${also}${needBe}`;
    if (bc || dc) return `${s1} ${bc || dc}` + (bc && dc ? ` 또 ${dc}` : "") + needBe;
    return needBe ? `${s1}${needBe}` : `${s1} 아래 체크리스트부터 점검하세요.`;
  }
  if (short) {
    const profit = be.profit_at_market_avg, maxF = be.max_fixed_for_bep, fixed = be.monthly_fixed_cost;
    const lim = ok(maxF) && ok(fixed) ? wonFloorBelow(maxF, fixed) : maxF;
    let s1: string, s2: string;
    if (owner > 0 && ok(profit) && profit + owner > 0) {
      // 모자란 금액은 체크리스트 '월 X 줄여야 함'과 같은 값(표시 금액끼리의 차이)
      const gap = ok(maxF) && ok(fixed) ? wonValue(fixed) - lim : null;
      const [left, less] = gap !== null && gap > 0 && gap < owner ? [owner - gap, gap] : [profit + owner, -profit];
      s1 = `${subj} 평균 매출이면 가게에 월 ${won(left)}이 남아 목표 월수입 ${won(owner)}보다 월 ${won(less)} 적어요(평균 매출은 필요 매출의 ${times(ratio)}).`;
      // 한도가 목표 월수입보다 작으면 다른 비용을 0원으로 줄여도 목표를 채울 수 없다 — 불가능한 방법을 권하지 않는다
      s2 = ok(maxF) && ok(lim) && lim < owner ? "다른 비용을 모두 줄여도 평균 매출로는 목표 월수입을 채우기 어려워요 — 목표를 낮추거나 매출이 더 나는 업종·입지를 검토하세요."
        : ok(maxF) ? `목표를 채우려면 월 고정비(목표 월수입 포함)를 ${won(lim)} 이하로 낮추거나 목표를 조정하세요.` : "비용이나 목표 월수입을 조정해 보세요.";
    } else {
      s1 = `${subj} 평균 매출이 ${bep}의 ${ra(times(ratio))} 지금 비용 구조로는 적자예요.`;
      s2 = owner > 0 && ok(maxF) && ok(lim) && lim < owner ? "다른 비용을 모두 줄여도 평균 매출로는 목표 월수입을 채우기 어려워요 — 목표를 낮추거나 매출이 더 나는 업종·입지를 검토하세요."
        : ok(maxF) ? `평균 매출로 버티려면 월 고정비${owner > 0 ? "(목표 월수입 포함)" : ""}를 ${won(lim)} 이하로 낮춰야 해요.` : "고정비를 줄일 방법부터 찾아보세요.";
    }
    return `${s1} ${s2}`;
  }
  if (focus.block) return `${subj} ${riskIs(g, rate, "지만")} ${focus.block}`;   // 평균 매출 < 월 고정비·수요 미검증이 입지 비교보다 먼저
  if (ok(loc) && loc >= 90) {
    const dc90 = dataCaveat(focus);
    return `${subj} ${riskIs(g, rate, "지만")}, 같은 업종끼리 비교하면 이 지역 입지 위험이 매우 높아요(${Math.trunc(loc)}). ` +
      (areaS || "같은 업종 폐업이 잦은 이유(상권 이동·경쟁)를 현장에서 먼저 확인하세요.") + (dc90 ? ` 또 ${dc90}` : "") +
      (!be && !focus.fixed_zero ? " 원가율을 넣어 손익분기도 확인하세요." : "");
  }
  const pressure = be ? be.cost_pressure : null;
  const dc = dataCaveat(focus);
  // 매출 추정이 흔들리면(비교할 구가 적음·대형 점포가 섞인 평균) 그 평균으로 '진입을 검토해 볼 만해요'라고 하지 않는다
  const verdict = dc ? "" : " 진입을 검토해 볼 만해요.";
  let s: string;
  if (!be && !focus.fixed_zero) s = `${subj} ${riskIs(g, rate, "요")} 원가율을 넣어 손익분기를 확인한 뒤 결정하세요.`;
  else if (!be || ratio === null || ratio === undefined) {   // 월 고정비 0원: 원가율과 상관없이 손익분기 0원
    s = `${subj} ${riskIs(g, rate, "고")} 입력한 월 고정비가 0원이에요.${verdict}`;
  }
  else if (pressure === "빠듯") {
    s = `${subj} ${riskIs(g, rate, "지만")} 평균 매출이 ${bep}의 ${ra(times(ratio))} 여유가 적어요. 비용을 더 줄일 수 있는지 먼저 점검하세요.`;
  } else s = `${subj} ${riskIs(g, rate, "고")} 평균 매출이 ${bep}의 ${yeyo(times(ratio))}.${verdict}`;
  const caveats: string[] = [];
  const over = focus.over_budget;
  if (pressure !== "빠듯" && be) {
    if (ok(loc) && cutGrade(loc) === "높음") caveats.push(`같은 업종끼리 비교한 입지 위험은 높은 편이에요(${Math.trunc(loc)}).`);
  }
  const bc = budgetCaveat(focus);
  if (bc && ((ok(over) && over > 0) || (pressure !== "빠듯" && be))) caveats.push(bc);
  if (dc) caveats.push(dc);
  if (focus.confidence === "낮음") caveats.push("이 지역 점포가 적어 추정치는 참고용이에요.");
  const first = dc && be && pressure !== "빠듯" ? " 하지만 " : " 다만 ";   // 좋아 보이는 배율 뒤에 바로 단서
  caveats.forEach((c, i) => { s += (i === 0 ? first : " 또 ") + c; });
  return s;
}

// ════════════════════════ miri_engine/breakeven.py ════════════════════════
export interface BEInput {
  monthly_rent: number; labor_cost: number; other_fixed: number; initial_investment: number; loan_amount: number;
  loan_rate_annual: number; owner_salary: number; cogs_rate: number | null; other_variable_rate: number;
  avg_ticket: number | null; operating_days?: number | null;
}
export class ValueErr extends Error {}
function cardFeeRate(st: State, annual: number): number {
  for (const [cap, rate] of st.p.card_fee_tiers) if (annual <= cap) return rate;
  return st.p.card_fee_over_3b;
}
/** breakeven.ratio_floor: 달성배율 표시값 — 소수 둘째 자리 내림(0.9996이 '1.00배'로 보이지 않게) */
export const ratioFloor = (x: number) => Math.floor(x * 100 + 1e-9) / 100;
export function calculate(st: State, inp: BEInput, category: string | null, msales: Num, mticket: Num, mtx: Num,
  ticketLabel = "이 지역 같은 업종 실제 평균"): any {
  const P = st.p.breakeven;
  const warnings: string[] = [];
  const days = inp.operating_days || P.operating_days;
  let cogs = inp.cogs_rate;
  if (cogs === null || cogs === undefined) {
    const d = st.p.default_cogs[category || ""];
    cogs = d === undefined ? null : d;
    if (cogs === null) throw new ValueErr("원가율 입력 필요: 이 업종 대분류에는 공식 근거가 있는 기본 원가율이 없음");
    warnings.push(`원가율을 넣지 않아 ${category} 평균 원가율 ${pyPct(cogs as number)}로 계산했어요`);
  }
  const ticket = okPos(inp.avg_ticket) ? inp.avg_ticket : okPos(mticket) ? mticket : null;
  if (ticket === null) throw new ValueErr("객단가 입력 필요(상권 실데이터 객단가도 없음)");
  for (const k of ["monthly_rent", "labor_cost", "other_fixed", "initial_investment", "loan_amount", "loan_rate_annual", "owner_salary", "other_variable_rate"] as const) {
    if ((inp as any)[k] < 0) throw new ValueErr(`${k}는 0 이상이어야 함`);
  }
  if (!okPos(inp.avg_ticket)) warnings.push(`객단가를 넣지 않아 ${ticketLabel} ${pyFixed(ticket, 0, true)}원으로 계산했어요`);
  const dep = inp.initial_investment / P.depreciation_months;
  const interest = inp.loan_amount * inp.loan_rate_annual / 12;
  const fixed = inp.monthly_rent + inp.labor_cost + inp.other_fixed + dep + interest + inp.owner_salary;
  if (inp.owner_salary === 0) warnings.push("목표 월수입(대표자)을 넣지 않아 '내 월급 0원' 기준 손익분기예요");
  let fee = cardFeeRate(st, 0), v = 0, bep = 0;
  for (let i = 0; i < 5; i++) {
    v = (cogs as number) + fee + inp.other_variable_rate;
    if (v >= 1) throw new ValueErr(`변동비율 ${pyPct(v)} ≥ 100%: 팔수록 손해(원가율·수수료 재확인)`);
    bep = fixed / (1 - v);
    const nf = cardFeeRate(st, bep * 12);
    if (nf === fee) break;
    fee = nf;
  }
  if (bep > P.max_required_sales) throw new ValueErr(`변동비율 ${pyPct(v)}: 매출에서 남는 몫이 거의 없어 필요 매출이 비현실적으로 커요(원가율·수수료 재확인)`);
  const cm = 1 - v;
  const out: any = {
    monthly_fixed_cost: pyRoundInt(fixed),
    fixed_breakdown: { 임대료: inp.monthly_rent, 인건비: inp.labor_cost, 기타고정비: inp.other_fixed, 감가상각: pyRoundInt(dep),
      대출이자: pyRoundInt(interest), 대표자인건비: inp.owner_salary },
    variable_cost_rate: pyRound(v, 4), variable_breakdown: { 원가율: cogs, 카드수수료: fee, 기타: inp.other_variable_rate },
    contribution_margin_rate: pyRound(cm, 4), required_monthly_sales: pyRoundInt(bep), required_daily_sales: pyRoundInt(bep / days),
    required_daily_customers: Math.ceil(bep / ticket / days), avg_ticket_used: pyRoundInt(ticket), operating_days: days,
  };
  if (okPos(msales)) {
    const [lo, mid, hi] = P.pressure_bands;
    let ratio: number | null = null, raw: number | null = null, level = "여유";
    if (bep > 0) {
      raw = msales / bep;
      ratio = ratioFloor(raw);                                     // 배지·문장·추천 제외는 화면에 보이는 내림 값으로
      level = ratio < lo ? "위험" : ratio < mid ? "빠듯" : ratio < hi ? "보통" : "여유";
    } else warnings.push("월 고정비가 0원이라 손익분기 매출도 0원이에요");
    const cashFixed = fixed - dep;
    const mcp = msales * cm - cashFixed;
    let payback: number | null = inp.initial_investment > 0 && mcp > 0 ? Math.ceil(inp.initial_investment / mcp) : null;
    if (payback !== null && payback > P.max_payback_months) payback = null;   // 100년 넘게 걸리면 '회수 기간 없음'과 같게
    Object.assign(out, {
      market_sales_ps_m: pyRoundInt(msales), achievability_ratio: ratio, ratio_for_score: raw === null ? null : pyRound(raw, 3),
      cost_pressure: level,
      profit_at_market_avg: pyRoundInt(msales * cm - fixed),
      payback_months: payback,
    });
    if (okPos(mtx)) {
      const txOp = mtx * P.days_per_month / days;                  // 달력일 → 영업일 기준
      out.market_tx_ps_day = pyRound(txOp, 1);
      out.customers_vs_market = pyRound(bep / ticket / days / txOp, 2);          // 올림 전 필요 결제로 비교
    }
  }
  out.warnings = warnings;
  return out;
}

// ════════════════════════ miri_engine/suitability.py + explain.py ════════════════════════
export interface UserCondition {
  business_goal: string; budget: number; monthly_rent: number; labor_cost: number; other_fixed: number;
  initial_investment: number; loan_amount: number; loan_rate_annual: number; owner_salary: number;
  licenses: string[]; interest_industries: string[]; excluded_industries: string[]; categories: string[];
  cogs_by_category?: Record<string, number> | null;                 // 분석 조건에서 넣은 분야별 원가율
}
export const monthlyFixedTotal = (u: UserCondition) =>
  u.monthly_rent + u.labor_cost + u.other_fixed + u.initial_investment / 60 + u.loan_amount * u.loan_rate_annual / 12 + u.owner_salary;

function riskGrade(st: State, s: number) {
  const [n, h, c] = st.p.risk_cuts;
  return s >= c ? "고위험" : s >= h ? "높음" : s >= n ? "보통" : "낮음";
}
function combine(D: number, S: number, F: number, w: any): number {
  const items = [[w.D, D], [w.S, S], [w.F, F]].filter(([, v]) => ok(v));
  const tw = items.reduce((a, [wt]) => a + wt, 0);
  return tw > 0 ? items.reduce((a, [wt, v]) => a + wt * v, 0) / tw : NaN;
}
function recReason(r: any, unit: string): string {
  const parts: string[] = [];
  if (ok(r.D) && ok(r.sales_ps_m)) parts.push(`점포당 월매출 ${pyFixed(r.sales_ps_m / 1e4, 0, true)}만원 (서울 동일 업종 ${unit} 중 상위 ${Math.max(1, pyRoundInt(100 - r.D))}%)`);
  parts.push(`예상 연간 폐업률 ${pyPct(r.pred_annual_rate)} · 종합 위험 ${r.risk_grade}(${r.risk_score}점) · 같은 업종 내 입지 위험 ${r.location_grade ?? "-"}`);
  if (ok(r.achievability_ratio)) parts.push(`입력 비용 기준 평균매출이 손익분기의 ${pyFixed(r.achievability_ratio, 2)}배`);
  return parts.join(" / ");
}
function recCaution(r: any): string {
  const c: string[] = [];
  if (r.risk_grade === "높음" || r.risk_grade === "고위험") c.push(`업종 자체의 폐업률이 높음(종합 위험 ${r.risk_grade})`);
  const ups = (r.risk_factors || []).filter((f: any) => f.effect_pct >= 5 && f.factor_code !== "ind_base");
  if (ups.length) c.push("위험 요인: " + ups.slice(0, 2).map((f: any) => `${f.label}(+${f.effect_display}%)`).join(", "));
  if (r.confidence === "낮음") c.push("이 지역 점포 수가 적어 추정 신뢰도 낮음");
  if (r.cogs_missing) c.push("원가율 입력 시 손익분기 확인 가능");
  if (ok(r.achievability_ratio) && r.achievability_ratio < 1.0) c.push("평균 매출로는 손익분기 미달");
  return c.length ? c.join(" / ") : "특이 위험 없음";
}
export function recommend(st: State, area: string, u: UserCondition, unit: string) {
  const SP = st.p.suitability, lic: Record<string, string> = st.p.licensed;
  const w = st.snap.meta.goals[u.business_goal];
  const rowsA = st.areaRows(area);
  if (!rowsA.length) throw new ValueErr(`해당 분기에 지역 데이터 없음: ${area}`);
  const fixedTotal = monthlyFixedTotal(u);
  const tab: any[] = [];
  for (const r of rowsA) {
    const code = r.industry_code, L = lic[code];
    let why: string | null = null;
    if (!r.has_sales_data) why = "매출 데이터 없음";
    else if (r.stores_avg4 < SP.min_avg_stores) why = "이 지역 점포 부족(수요 미검증)";
    else if (!ok(r.sales_ps_m)) why = "카드 매출 데이터 부족";
    else if (ok(r.sales_n) && (r.sales_n as number) < SP.min_sales_areas) why = `매출을 비교할 지역이 적음(${Math.trunc(r.sales_n as number)}곳)`;
    else if (L && !u.licenses.includes(L)) why = `${L} 자격 필요`;
    else if (u.excluded_industries.includes(code)) why = "사용자 제외";
    else if (u.categories.length && !u.categories.includes(r.category)) why = "대분류 제한";
    else if (r.sales_ps_m < fixedTotal) why = "평균 매출이 월 고정비보다 적음";
    const D = ok(r.demand_D) ? r.demand_D : NaN;
    const S = 100.0 - r.risk_score;
    let F = NaN, ratio: number | null = null, cogsMissing = false, beError = false;
    const isInterest = u.interest_industries.includes(code);
    if ((why === null || isInterest) && ok(r.sales_ps_m)) {
      const uc = u.cogs_by_category || {};
      const d = r.category in uc ? uc[r.category] : st.p.default_cogs[r.category];
      const cogs = d === undefined ? null : d;
      if (cogs === null) cogsMissing = true;
      else {
        try {
          const be = calculate(st, { monthly_rent: u.monthly_rent, labor_cost: u.labor_cost, other_fixed: u.other_fixed,
            initial_investment: u.initial_investment, loan_amount: u.loan_amount, loan_rate_annual: u.loan_rate_annual,
            owner_salary: u.owner_salary, cogs_rate: cogs, other_variable_rate: 0, avg_ticket: null },
            r.category, r.sales_ps_m, r.ticket, r.tx_ps_day);
          ratio = be.achievability_ratio ?? null;
          const rs = be.ratio_for_score;                            // 점수(F)는 연속값, 표시·제외 판정은 내림 값
          F = ratio !== null ? 100.0 * Math.min(Math.max((rs - SP.f_ratio_zero) / (SP.f_ratio_full - SP.f_ratio_zero), 0.0), 1.0)
            : be.required_monthly_sales === 0 ? 100.0 : NaN;
        } catch (e) {
          if (!(e instanceof ValueErr)) throw e;
          F = NaN;
          if (e.message.includes("변동비율")) why = why ?? "원가·수수료가 매출의 100% 이상";   // 팔수록 손해 → 추천 제외
          else beError = true;
        }
      }
    }
    if (why === null && ratio !== null && ratio < 1.0) why = "평균 매출로 손익분기 미달";
    // 다른 조건은 모두 통과했지만 평균 매출이 대형 점포 때문에 부풀었을 수 있는 업종 → 마지막에 제외(입지 위험 90 이상이면 주의 업종으로)
    const ox = why === null && r.risk_pct_in_ind < SP.exclude_location_pct_ge ? salesOutlierX(r, SP.outlier_sales_x) : null;
    if (ox !== null) why = `${OUTLIER_REASON}의 ${pyFixed(ox, 1)}배(대형 점포 가능)`;
    tab.push({ industry_code: code, industry_name: st.industries.get(code).name, category: r.category, eligible: why === null,
      ineligible_reason: why, is_interest: isInterest, D, S, F, cogs_missing: cogsMissing, be_error: beError,
      risk_score: r.risk_score, risk_grade: r.risk_grade, risk_pct_in_ind: r.risk_pct_in_ind,
      location_grade: riskGrade(st, r.risk_pct_in_ind), pred_annual_rate: r.pred_annual_rate,
      sales_ps_m: ok(r.sales_ps_m) ? r.sales_ps_m : null, ticket: ok(r.ticket) ? r.ticket : null, stores_avg4: r.stores_avg4,
      confidence: r.confidence, achievability_ratio: ratio, risk_factors: st.factors(r.factors, 4),
      sales_outlier: salesOutlierX(r, SP.outlier_sales_x) });   // 대형 점포가 섞인 듯한 평균(설명 문장에서 인용하지 않게)
  }
  const elig = tab.filter((t) => t.eligible);
  // F는 후보 전부에 계산될 때만 적용. 후보가 하나도 없으면 관심 업종(매출 있음)을 기준으로 — 안 그러면 고정비가 너무 커
  // 후보가 0개일 때 F가 빠져 비용이 클수록 관심 업종 점수가 오히려 올라간다(suitability.py와 같게)
  const base = elig.length ? elig : tab.filter((t) => t.is_interest && ok(t.sales_ps_m) && !t.cogs_missing);   // 원가율 모르는 관심 업종은 기준에서 뺀다
  const fApplied = base.length > 0 && base.every((t) => ok(t.F));
  for (const t of tab) t.suitability = pyRound(combine(t.D, t.S, fApplied ? t.F : NaN, w), 2);   // suitability.py와 같게 둘째 자리
  const cand = elig.slice().sort((a, b) => (b.suitability - a.suitability) || (a.risk_score - b.risk_score) || (b.D - a.D));
  // 순위를 채우려고 아주 낮은 점수(min_top_score 미만)까지 넣지 않는다
  const low = (t: any) => Math.floor(t.suitability + 0.5) < SP.min_top_score;     // 화면의 정수 점수 기준(19.67은 '20'이라 통과)
  const top = cand.filter((t) => t.risk_pct_in_ind < SP.exclude_location_pct_ge && !low(t)).slice(0, SP.top_n).map((t) => ({ ...t }));
  const lowRows = cand.filter((t) => t.risk_pct_in_ind < SP.exclude_location_pct_ge && low(t));
  const nLowScore = lowRows.length;
  // 주의 업종은 전부 — 입지 위험이 높은 순(같으면 적합도 순)
  const caution = cand.filter((t) => t.risk_pct_in_ind >= SP.exclude_location_pct_ge).map((t) => ({ ...t }))
    .sort((a, b) => (b.risk_pct_in_ind - a.risk_pct_in_ind) || (b.suitability - a.suitability) || (a.industry_code < b.industry_code ? -1 : a.industry_code > b.industry_code ? 1 : 0));
  // 관심 업종은 사용자가 고른 순서대로(같은 순서면 원래 순서 — 정렬은 안정적)
  const pick = (c: string) => { const i = u.interest_industries.indexOf(c); return i < 0 ? 1 << 30 : i; };
  const interest = tab.filter((t) => t.is_interest).map((t) => ({ ...t })).sort((a, b) => pick(a.industry_code) - pick(b.industry_code));
  for (const g of [top, caution, interest]) for (const t of g) { t.reason = recReason(t, unit); t.caution = recCaution(t); }
  top.forEach((t, i) => { t.rank_order = i + 1; });
  let note: string | null;
  if (fApplied) note = null;
  else if (elig.some((t) => t.cogs_missing)) note = "일부 후보 업종에 원가율 근거가 없어 비용 적합도는 순위에 미반영(표시만)";
  else if (elig.some((t) => t.be_error)) note = "일부 후보 업종의 손익분기 계산 불가(객단가 등 결측)로 비용 적합도는 순위에 미반영";
  else note = "후보 업종 없음";
  return { weights: w, f_applied: fApplied, f_note: note, top, caution_list: caution, interest, n_candidates: cand.length,
    n_low_score: nLowScore, low_list: lowRows.map((t) => [t.industry_name, t.suitability] as [string, number]), table: tab };
}

// ════════════════════════ services/geo.py ════════════════════════
const R_EARTH = 6_371_008.8;
const rad = (d: number) => (d * Math.PI) / 180;
export function haversine(lat1: number, lng1: number, lat2: number, lng2: number) {
  const p1 = rad(lat1), p2 = rad(lat2), dp = p2 - p1, dl = rad(lng2 - lng1);
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * R_EARTH * Math.asin(Math.sqrt(a));
}
const ringsOf = (g: any): number[][][] => (g.type === "Polygon" ? [g.coordinates[0]] : g.coordinates.map((p: any) => p[0]));
function pointInRing(lng: number, lat: number, ring: number[][]) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > lat) !== (yj > lat)) {
      const x = (xj - xi) * (lat - yi) / (yj - yi) + xi;
      if (lng < x) inside = !inside;
    }
  }
  return inside;
}
export const pointInGeometry = (lng: number, lat: number, g: any) => ringsOf(g).some((r) => pointInRing(lng, lat, r));
export function distanceToGeometry(lat: number, lng: number, g: any): number {
  if (pointInGeometry(lng, lat, g)) return 0;
  const kx = Math.cos(rad(lat)) * Math.PI * R_EARTH / 180, ky = Math.PI * R_EARTH / 180;
  let best = Infinity;
  for (const ring of ringsOf(g)) {
    const pts = ring.map(([x, y]) => [(x - lng) * kx, (y - lat) * ky]);
    for (let i = 0; i < pts.length; i++) {
      const [ax, ay] = pts[i], [bx, by] = pts[(i + 1) % pts.length];
      const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy;
      const t = L2 === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / L2));
      best = Math.min(best, Math.hypot(ax + t * dx, ay + t * dy));
    }
  }
  return best;
}

// ════════════════════════ services/areas.py ════════════════════════
export const DISTRICT_NOTICE = "상권 단위 데이터가 아직 없어 자치구(구 전체) 단위로 분석해요. 반경은 후보 구를 고르는 데 쓰여요.";
const norm = (s: string) => (s || "").replace(/\s+/g, "").toLowerCase();

const looksLikeYeok = (ch: string) => ch >= "가" && ch <= "힣" && Math.floor((ch.charCodeAt(0) - 0xac00) / 588) === 11;
const SUFFIX_FALLBACK = ["거리", "시장", "동", "길", "로", "역", "공원", "광장", "호수"];   // areas.search_local과 같음('망원동' → '망원', '신촌역' → '신촌')
/** areas.typo_variants: 흔한 소리 오타(마지막 녁·력·넉 → 역, 능 → 릉) — 원래 검색이 비었을 때만 */
export function typoVariants(nq: string): string[] {
  const cps = Array.from(nq);
  const a = cps.length >= 3 && "녁력넉".includes(cps[cps.length - 1]) ? cps.slice(0, -1).join("") + "역" : nq;
  const b = Array.from(a).length >= 2 ? a.split("능").join("릉") : a;   // 한 글자('능')만으로는 고치지 않는다
  const out: string[] = [];
  for (const v of [a, b]) if (v !== nq && !out.includes(v)) out.push(v);
  return out;
}
const NOISE_TOKENS = new Set(["사거리", "근처", "주변", "앞", "쪽", "출구"]);
// areas.GENERIC_TOKENS: 그것만으로는 장소를 정할 수 없는 흔한 말
const GENERIC_TOKENS = new Set(["카페", "맛집", "학원가", "학원", "시장", "거리", "골목", "역", "상권", "먹자골목", "카페거리", "동네", "입구", "근방",
  "공원", "광장", "한강", "호수"]);
/** areas._split_districts: 띄어 쓰지 않은 구 이름을 떼어 낸다 */
function splitDistricts(t: string, ds: string[]): string[] {
  for (const d of ds) {
    const i = t.indexOf(d);
    if (i >= 0 && t !== d) return [t.slice(0, i), d, t.slice(i + d.length)].filter(Boolean);
  }
  return [t];
}
/** areas.address_tokens: 주소처럼 친 검색어의 낱말(서울·사거리·근처·앞·쪽·출구 번호는 뺌, 붙여 쓴 구 이름은 뗌) */
export function addressTokens(q: string, districts: string[] = []): string[] {
  const ds = [...districts].sort((a, b) => Array.from(b).length - Array.from(a).length);
  const raw = (q || "").trim().split(/\s+/).filter(Boolean).flatMap((t) => (ds.length ? splitDistricts(t, ds) : [t]));
  const out: string[] = [];
  for (let t of raw) {
    const n = Array.from(t).length;
    if (n > 3 && (t.endsWith("사거리") || t.endsWith("근처") || t.endsWith("주변"))) t = t.endsWith("사거리") ? t.slice(0, -3) : t.slice(0, -2);
    else if (n > 2 && (t.endsWith("앞") || t.endsWith("쪽"))) t = t.slice(0, -1);
    const m = /^(.{2,}?)[0-9]+번(출구)?$/.exec(t);          // '강남역2번출구앞' → 앞을 뗀 뒤 출구 번호
    if (m) t = m[1];
    if (!t || NOISE_TOKENS.has(t) || /^(서울특별시|서울시|서울)$/.test(t) || /^[0-9]+번(출구)?$/.test(t)) continue;
    out.push(t);
  }
  return out;
}
function searchWithTypos(st: State, nq: string, limit: number, strict = false) {
  let out = searchOne(st, nq, limit, strict);
  if (!out.length) {
    for (const v of typoVariants(nq)) {
      out = searchOne(st, v, limit, strict);
      if (out.length) break;
    }
  }
  return out;
}
export function searchLocal(st: State, q: string, limit = 8) {
  const nq = norm(q);
  const out = searchWithTypos(st, nq, limit);
  if (out.length) return out;
  // 주소처럼 친 검색어(areas.search_local과 같게): 구 이름이 있으면 그 구 안의 결과만(없으면 그 구 자체),
  // 흔한 말·한 글자는 빼고 남은 낱말을 붙인 말부터, 그다음 오른쪽 낱말부터
  const dnames = Array.from(new Set(Object.values(st.snap.areas).map((a: any) => a.name as string))).sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  const toks = addressTokens(q, dnames);
  if (!toks.length || (toks.length === 1 && norm(toks[0]) === nq)) return [];
  const districts = new Set(dnames);
  let dist = [...toks].reverse().find((t) => districts.has(t)) ?? null;
  let short: string | null = null;                      // '마포 연남동'의 마포처럼 '구'를 뺀 구 이름도 구 제한으로
  if (dist === null) {
    short = [...toks].reverse().find((t) => Array.from(t).length >= 2 && districts.has(t + "구")) ?? null;
    dist = short ? short + "구" : null;
  }
  const words = toks.filter((t) => t !== dist && t !== short && Array.from(t).length >= 2 && !GENERIC_TOKENS.has(t));
  // 붙인 말 → 왼쪽 낱말부터(앞말이 장소 이름). 낱말 검색은 이름·별칭과 같거나 그 말로 시작할 때만(strict)
  const terms = [...(words.length >= 2 ? [words.join("")] : []), ...words].map(norm);
  for (const t of Array.from(new Set(terms))) {
    let res = searchWithTypos(st, t, limit, true);
    if (dist) res = res.filter((r: any) => r.area_name === dist);
    if (res.length) return res;
  }
  if (short) {                                          // 다른 낱말로 못 찾으면 그 말 자체로(강남 카페 → 강남역)
    const own = searchWithTypos(st, norm(short), limit);
    return own.length ? own : searchOne(st, norm(dist as string), limit);
  }
  return dist ? searchOne(st, norm(dist), limit) : [];
}
function searchOne(st: State, nq: string, limit: number, strict = false) {
  let out = searchLocalNorm(st, nq, limit, false, strict);
  if (!out.length) {
    for (const suf of SUFFIX_FALLBACK) {
      if (nq.endsWith(suf) && Array.from(nq).length - suf.length >= 2) {   // 글자 수는 코드 포인트로(파이썬 len과 같게)
        out = searchLocalNorm(st, nq.slice(0, nq.length - suf.length), limit, true);   // 이름이 그 말로 시작하거나 별칭과 같을 때만
        if (out.length) break;
      }
    }
  }
  // '역'을 잘못 친 마지막 글자(첫소리 ㅇ: 강남억 → 강남) — 글자 단위(코드 포인트)로 세고 자른다(이모지 반쪽 방지)
  const cps = Array.from(nq);
  if (!out.length && cps.length >= 3 && looksLikeYeok(cps[cps.length - 1])) out = searchLocalNorm(st, cps.slice(0, -1).join(""), limit, true);
  return out;
}
function searchLocalNorm(st: State, nq: string, limit: number, namesOnly = false, strict = false) {
  if (!nq) return [];
  const scored: [number, number, number, number, any][] = [];
  st.snap.places.forEach((p, idx) => {
    const names = [p.name, ...(p.aliases || "").split(",").filter(Boolean)];
    const nn = names.map(norm);
    if (namesOnly && !(nn[0].startsWith(nq) || nn.slice(1).includes(nq))) return;
    let s: number;
    if (nq === nn[0]) s = 0;
    else if (nn.slice(1).some((n) => n === nq)) s = 1;
    else if (nn.some((n) => n.startsWith(nq))) s = 2;
    else if (!strict && nn.some((n) => n.includes(nq))) s = 3;     // 주소 낱말 검색(strict)은 가운데 일치를 쓰지 않는다
    else return;
    const kr = ({ station: 0, street: 0, district: 1 } as any)[p.kind] ?? 2;
    scored.push([s, kr, p.name.length, idx, p]);
  });
  scored.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2] || a[3] - b[3]);
  return scored.slice(0, limit).map(([, , , , p]) => ({ name: p.name, kind: p.kind, lat: p.lat, lng: p.lng,
    area_code: p.area_code, area_name: p.area_code ? st.snap.areas[p.area_code].name : null, address: null, source: "local" }));
}
export function areaCard(st: State, code: string, isCenter = false, dist = 0) {
  const a = st.snap.areas[code];
  return { area_code: code, area_name: a.name, level: a.level, is_center: isCenter, distance_m: pyRoundInt(dist),
    lat: a.lat, lng: a.lng, metrics: st.snap.area_cards[code] || {} };
}
export function candidates(st: State, lat: number, lng: number, radius: number, place: string | null) {
  const hits: [number, number, number, string][] = [];
  for (const code of st.areaOrder) {
    const a = st.snap.areas[code];
    if (!a.geometry || !st.areaRows(code).length) continue;
    const d = distanceToGeometry(lat, lng, a.geometry);
    if (d <= radius) hits.push([d, pointInGeometry(lng, lat, a.geometry) ? 0 : 1, haversine(lat, lng, a.lat, a.lng), code]);
  }
  let notice = DISTRICT_NOTICE;
  if (!hits.length) {
    let best: string | null = null, bd = Infinity;
    for (const code of st.areaOrder) {
      const a = st.snap.areas[code];
      if (!a.geometry) continue;
      const d = distanceToGeometry(lat, lng, a.geometry);
      if (d < bd) { best = code; bd = d; }
    }
    if (best === null || bd > 3000) throw new EngineError(422, "OUT_OF_COVERAGE", "서울 밖 지역은 아직 분석할 수 없어요. 서울 안에서 골라 주세요");
    hits.push([bd, 1, bd, best]);
    const dist = pyRoundInt(bd) >= 1000 ? `${pyFixed(bd / 1000, 1)}km` : `${pyRoundInt(bd)}m`;      // 반경(300m)보다 먼데 '0.3km'로 보이지 않게
    notice = `반경 안에 서울 자치구가 없어 가장 가까운 ${st.snap.areas[best].name}(경계까지 ${dist}) 기준으로 분석해요.`;
  }
  hits.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2] || (a[3] < b[3] ? -1 : a[3] > b[3] ? 1 : 0));
  return { lat, lng, radius_m: radius, place_name: place, analysis_level: "district", notice,
    candidates: hits.map(([d, , , c], i) => areaCard(st, c, i === 0 && d === 0, d)) };
}

/** areas.compare (UC-02 상권 비교): 같은 기준(최신 분기)으로 지역 지표와 (선택) 업종 위험·매출을 나란히 */
export function compareAreas(st: State, codes0: string[], industry: string | null) {
  const codes = Array.from(new Set(codes0));
  if (codes.length < 2) throw new EngineError(422, "NEED_MORE_AREAS", "비교하려면 상권을 2개 이상 골라 주세요");
  const unknown = codes.filter((c) => !(c in st.snap.areas));
  if (unknown.length) throw new EngineError(404, "UNKNOWN_AREA", `알 수 없는 지역 코드: ${unknown.join(", ")}`);
  if (industry && !st.industries.has(industry)) throw new EngineError(404, "UNKNOWN_INDUSTRY", "알 수 없는 업종이에요");
  const areas = codes.map((c) => {
    const card: any = areaCard(st, c);
    const ar = st.areaRows(c);
    card.summary = {
      avg_risk_score: ar.length ? pyRound(ar.reduce((a, r) => a + r.risk_score, 0) / ar.length, 1) : null,
      high_risk_share: ar.length ? pyRound(ar.filter((r) => r.risk_grade === "높음" || r.risk_grade === "고위험").length / ar.length, 3) : null,
    };
    const r = industry ? st.row(c, industry) : null;
    card.industry = r === null ? null : { risk_score: r.risk_score, risk_grade: r.risk_grade, location_risk_pct: Math.trunc(r.risk_pct_in_ind),
      pred_annual_rate: r.pred_annual_rate, sales_ps_m: ok(r.sales_ps_m) ? r.sales_ps_m : null,
      sales_outlier: salesOutlier(r) === null ? null : pyRound(salesOutlier(r) as number, 1), demand_D: ok(r.demand_D) ? r.demand_D : null,
      stores_avg: r.stores_avg4 };
    return card;
  });
  return { industry_code: industry, industry_name: industry ? st.industries.get(industry).name : null, data_quarter: st.snap.meta.data_quarter, areas };
}

// ════════════════════════ services/risk_svc.py ════════════════════════
export function fallbackRow(st: State, area: string, code: string): any {
  const f = st.snap.fallback[code];
  if (!f) throw new EngineError(404, "NO_INDUSTRY_DATA", "이 업종은 서울 전체에 분석할 데이터가 없어요");
  return { area_id: area, industry_code: code, category: f.category, risk_score: f.risk_score, risk_grade: f.risk_grade,
    pred_annual_rate: f.pred_annual_rate, risk_pct_in_ind: null, confidence: "낮음", local_weight: 0.0, factors: f.factors,
    ind_avg_rate: f.ind_avg_rate, seoul_avg_rate: f.seoul_avg_rate, ind_sales_growth: f.ind_sales_growth,
    stores: 0.0, openings: 0.0, closures: 0.0, exp4: 0.0, clo4: 0.0, ope4: 0.0, stores_avg4: 0.0, sales_ps_m: null, ticket: null,
    tx_ps_day: null, demand_D: null, sales_growth: null, store_growth: null, p_rent_burden: null, p_density: null, rate_eb: null,
    profile: null, closed_months4: null, rent4: null, has_sales_data: true, sales_rank: null };
}
const MAX_ALT_KM = 7.0;
export function alternatives(st: State, area: string, code: string, cur: number | null, extra: string[] = []) {
  const a = st.snap.areas[area];
  if (a.lat === null || a.lat === undefined) return [];
  const all = st.areaOrder.filter((c) => c !== area && st.snap.areas[c].lat !== null && st.snap.areas[c].lat !== undefined)
    .map((c) => [haversine(a.lat, a.lng, st.snap.areas[c].lat, st.snap.areas[c].lng) / 1000, c] as [number, string]);
  const near0 = all.filter(([d]) => d <= MAX_ALT_KM).sort((x, y) => x[0] - y[0]).slice(0, 6);
  // SB-02에서 후보로 보였던 구는 구 중심이 멀어도(7km 넘음) 함께 본다(risk_svc.alternatives extra와 같게)
  const pick = new Set([...near0.map(([, c]) => c), ...extra]);
  const near = all.filter(([, c]) => pick.has(c)).sort((x, y) => x[0] - y[0] || (x[1] < y[1] ? -1 : x[1] > y[1] ? 1 : 0));
  const limit = cur === null ? 40 : cur;
  const out: any[] = [];
  for (const [d, c] of near) {
    const r = st.row(c, code);
    if (!r || r.risk_pct_in_ind >= limit) continue;
    const loc = Math.trunc(r.risk_pct_in_ind);
    out.push({ area_code: c, area_name: st.snap.areas[c].name, location_risk_pct: loc, location_grade: riskGrade(st, loc),
      risk_score: r.risk_score, pred_annual_rate: r.pred_annual_rate, distance_km: pyRound(d, 1) });
  }
  out.sort((x, y) => x.location_risk_pct - y.location_risk_pct);
  if (!out.length && cur === null) {
    // 이 지역에 같은 업종이 없는데(대체 계산) 입지 위험 '낮음'인 곳도 없으면, 이 업종이 있는 가장 가까운 지역이라도(6.1.4 인근 대체)
    for (const [d, c] of near) {
      const r = st.row(c, code);
      if (!r) continue;
      const loc = Math.trunc(r.risk_pct_in_ind);
      out.push({ area_code: c, area_name: st.snap.areas[c].name, location_risk_pct: loc, location_grade: riskGrade(st, loc),
        risk_score: r.risk_score, pred_annual_rate: r.pred_annual_rate, distance_km: pyRound(d, 1) });
    }
  }
  return out.slice(0, 3);
}
export const unitShort = (st: State, area: string) => (st.snap.areas[area]?.level === "district" ? "구" : "상권");
/** risk_svc.industry_n: 업종 전체 매출 추세에 실제로 들어간 지역 수(올해·작년 모두 매출을 믿을 수 있는 지역) */
export const industryN = (st: State, code: string) => (st.byInd.get(code) || []).filter((r) => ok(r.sales_growth)).length;
function reference(r: any, rentLatest: Num, nInd: number, unit: string): any[] {
  const ref: any[] = [];
  const add = (key: string, label: string, value: Num, display: string, note: string | null = null) => ref.push({ key, label, value, display, note });
  if (ok(r.sales_growth)) add("sales_growth", "이 지역 같은 업종 매출 전년 대비", r.sales_growth, signedPct1(r.sales_growth));
  if (ok(r.store_growth)) add("store_growth", "이 지역 같은 업종 점포 수 전년 대비", r.store_growth, signedPct1(r.store_growth));
  if (ok(r.ind_sales_growth) && !(nInd !== null && nInd !== undefined && nInd < 5)) {     // 4개 구 이하 합계는 서울 추세로 보기 어려워 뺀다
    add("ind_sales_growth", "업종 전체(서울) 매출 전년 대비", r.ind_sales_growth, signedPct1(r.ind_sales_growth), nInd ? `서울 ${nInd}개 ${unit} 합계` : null);
  }
  if (ok(r.p_rent_burden)) add("rent_burden", "임대료 부담(같은 업종 중 순위, 0~100)", r.p_rent_burden, pyFixed(r.p_rent_burden, 0), "50이 중간, 높을수록 매출 대비 임대료 부담이 큼");
  if (ok(r.p_density)) add("density", "유동인구 대비 점포 밀도(같은 업종 중 순위, 0~100)", r.p_density, pyFixed(r.p_density, 0), "50이 중간, 높을수록 점포가 빽빽함");
  const v = rentLatest !== null && rentLatest !== undefined ? (ok(rentLatest) ? rentLatest : null) : (ok(r.rent4) ? r.rent4 : null);
  if (v !== null) add("rent", "3.3㎡당 월 임대료(지역 평균)", v, won1(v), "10평이면 약 " + won(v * 10));
  if (ok(r.closed_months4)) add("closed_months", "폐업 점포 평균 영업 기간(이 지역 전 업종)", r.closed_months4, `${pyFixed(r.closed_months4, 0)}개월`);
  const ope = ok(r.ope4) ? r.ope4 : null, clo = ok(r.clo4) ? r.clo4 : null;
  if (ope !== null && clo !== null && (ope || clo)) add("open_close", "최근 1년 같은 업종 개업 / 폐업", null, `${pyFixed(ope, 0, true)}곳 / ${pyFixed(clo, 0, true)}곳`);
  return ref;
}
export function riskDetail(st: State, analysisId: string, area: string, code: string, candidates: string[] = []) {
  const ind = st.industries.get(code);
  if (!ind) throw new EngineError(404, "UNKNOWN_INDUSTRY", "알 수 없는 업종이에요");
  let r: any = st.row(area, code);
  const fallback = r === null;
  const notices: string[] = [];
  const ox = !fallback ? salesOutlier(r) : null;
  if (ox !== null) notices.push(`이 지역 점포당 매출이 서울 같은 업종 중간값의 ${pyFixed(ox, 1)}배예요 — 대형 점포가 섞인 평균일 수 있어 매출 관련 요인·비교는 참고용이에요.`);
  if (fallback) {
    r = fallbackRow(st, area, code);
    notices.push(`${st.snap.areas[area].name}에 최근 1년 ${ind.name} 점포가 없어 서울 같은 업종 평균 조건으로 계산했어요(신뢰도 낮음).`);
  }
  const num = (k: string) => (ok(r[k]) ? r[k] : null);
  const ctx = { ind_avg: r.ind_avg_rate, seoul_avg: r.seoul_avg_rate, clo4: num("clo4"), stores_avg4: num("stores_avg4"),
    sales_growth: num("sales_growth"), store_growth: num("store_growth"), ope4: num("ope4"), exp4: num("exp4"),
    mu_ind_entry: num("mu_ind_entry"), sales_ps_m: num("sales_ps_m"),
    closed_months4: num("closed_months4"), ind_sales_growth: num("ind_sales_growth"), rate_eb: num("rate_eb"), local_weight: num("local_weight"),
    sales_outlier: ox };
  const fx = relabel(st.factors(r.factors), ctx).map((f) => ({ ...f, direction: f.effect_pct > 0 ? "up" : "down", detail: factorDetail(f, ctx) }));
  const loc = fallback ? null : Math.trunc(r.risk_pct_in_ind);
  const exp4 = ok(r.exp4) ? r.exp4 : 0.0, clo4 = ok(r.clo4) ? r.clo4 : 0.0;
  const rr = { ...r, industry_name: ind.name };
  const b = st.snap.meta.grade_rate_bounds;
  const q = st.snap.meta.data_quarter;
  return {
    analysis_id: analysisId, area_code: area, area_name: st.snap.areas[area].name, industry_code: code, industry_name: ind.name,
    category: ind.category, data_quarter: q, data_quarter_label: `${Math.floor(q / 10)}년 ${q % 10}분기`,
    model_version: st.snap.meta.model_version,
    risk_score: r.risk_score, risk_grade: r.risk_grade, pred_annual_rate: r.pred_annual_rate,
    industry_avg_annual_rate: r.ind_avg_rate, seoul_avg_annual_rate: r.seoul_avg_rate,
    location_risk_pct: loc, location_grade: loc === null ? null : riskGrade(st, loc), confidence: r.confidence,
    local_data_weight: ok(r.local_weight) ? r.local_weight : null, grade_cuts: st.snap.meta.grade_cuts, grade_rate_bounds: b,
    summary: riskSummary(st.snap.areas[area].name, rr, fallback), factors: fx,
    reference: reference(r, st.snap.area_cards[area]?.rent_per_3_3m2 ?? null, industryN(st, code), unitShort(st, area)),
    raw: { stores_now: ok(r.stores) ? r.stores : null, stores_avg_1y: ok(r.stores_avg4) ? r.stores_avg4 : null,
      openings_1y: ok(r.ope4) ? r.ope4 : null, closures_1y: clo4,
      raw_closure_rate_q: exp4 > 0 ? pyRound(clo4 / exp4, 4) : null, eb_closure_rate_q: ok(r.rate_eb) ? r.rate_eb : null },
    alternatives: alternatives(st, area, code, loc, candidates), recheck: r.risk_grade === "고위험", fallback,
    notices: [...notices, ...st.snap.meta.notices],
  };
}
export { riskGrade, ok };
