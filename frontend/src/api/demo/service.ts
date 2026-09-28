// 데모 서비스 계층: app/services/analysis.py · breakeven_svc.py · report_svc.py 를 옮긴 것(저장소는 메모리 객체).
import { pyFixed, pyRound, pyRoundInt, pySigned } from "./pyfmt";
import {
  BIG_STORE, calculate, cautionPills, EngineError, josa, OUTLIER_PILL, OUTLIER_REASON, salesOutlier, shownEffect, monthlyFixedTotal, monthsFloor, OFFER, ok, oneLiner, pct, peakFlags,
  reasonChips, reasonShort, recommend, relabel, riskDetail, State, TARGETS, times, UserCondition, ValueErr, won, won1, wonFloorBelow, wonValue,
} from "./engine";

// 로그인이 없으므로(0.2) 데모 저장소 전체가 '이 브라우저'의 것이다 — 저장 리포트도 이 브라우저의 목록 하나뿐
export interface StoreData {
  seq: number;
  analyses: Record<string, any>;     // public_id → 분석 요청 + 추천 결과
  risks: any[];                      // risk_assessments
  breakevens: any[];                 // break_even_analyses
  reports: Record<string, any>;      // public_id → action_reports
  saved: any[];                      // saved_reports(이 브라우저의 저장 목록)
}
export const emptyStore = (): StoreData => ({ seq: 1, analyses: {}, risks: [], breakevens: [], reports: {}, saved: [] });
const nextId = (s: StoreData) => s.seq++;
const quarterLabel = (q: number) => `${Math.floor(q / 10)}년 ${q % 10}분기`;
const UNIT: Record<string, string> = { district: "자치구", trade_area: "상권" };

function newId(): string {
  const c: any = (globalThis as any).crypto;
  if (c?.randomUUID) return c.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (ch) => {
    const r = (Math.random() * 16) | 0;
    return (ch === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}
const nowIso = () => new Date().toISOString();

export function userCondition(req: any, interests: string[]): UserCondition {
  return { business_goal: req.business_goal, budget: req.budget, monthly_rent: req.monthly_rent_limit, labor_cost: req.labor_cost,
    other_fixed: req.other_fixed, initial_investment: req.initial_investment, loan_amount: req.loan_amount,
    loan_rate_annual: req.loan_rate_annual, owner_salary: req.owner_salary, licenses: req.licenses,
    interest_industries: interests, excluded_industries: req.excluded_industries || [], categories: req.categories,
    cogs_by_category: req.cogs_rates && Object.keys(req.cogs_rates).length ? req.cogs_rates : null };
}

// ── 입력 검증 (app/schemas.py + errors.py 메시지와 동일) ──────────────────
const LABELS: Record<string, string> = { area_code: "상권", budget: "총 창업 예산", monthly_rent_limit: "월 임대료",
  labor_cost: "예상 인건비", initial_investment: "초기 투자비", other_fixed: "기타 고정비", loan_amount: "대출금",
  loan_rate_annual: "대출 금리", owner_salary: "목표 월수입(대표자)", avg_ticket: "객단가", cogs_rate: "원가율",
  other_variable_rate: "배달·기타 수수료", monthly_rent: "월 임대료", interests: "관심 업종", excluded_industries: "제외 업종",
  cogs_rates: "분야별 원가율",
  candidate_area_codes: "후보 상권", licenses: "보유 자격", categories: "업종 대분류" };
const MAX_WON = 100_000_000_000;
function fieldErr(field: string, message: string): never {
  throw new EngineError(422, "VALIDATION_ERROR", message, [{ field, message }]);
}
function checkNum(body: any, k: string, { required = false, ge = 0, le = MAX_WON, lt }: { required?: boolean; ge?: number; le?: number; lt?: number }) {
  const v = body[k], label = LABELS[k] || k;
  if (v === undefined || v === null) { if (required) fieldErr(k, `${josa(label, "을/를")} 입력해 주세요`); return; }
  if (typeof v !== "number" || !Number.isFinite(v)) fieldErr(k, `${josa(label, "은/는")} 숫자로 입력해 주세요`);
  if (v < ge) fieldErr(k, `${josa(label, "은/는")} ${ge} 이상이어야 해요`);
  if ((lt !== undefined && v >= lt) || v > le) fieldErr(k, `${label} 값이 너무 커요`);
}
export function validateAnalysisIn(b: any) {
  if (!b.area_code) fieldErr("area_code", "상권을 입력해 주세요");
  if (b.cogs_rates !== undefined && b.cogs_rates !== null) {
    const cr = b.cogs_rates;
    if (typeof cr !== "object" || Array.isArray(cr)) fieldErr("cogs_rates", "분야별 원가율 값을 확인해 주세요");
    for (const [k, v] of Object.entries(cr)) {
      if (!["외식업", "서비스업", "소매업"].includes(k)) fieldErr("cogs_rates", "분야별 원가율 값을 확인해 주세요");
      if (typeof v !== "number" || !Number.isFinite(v) || v < 0 || v > 0.95) fieldErr("cogs_rates", "원가율은 0~95% 사이로 넣어 주세요");
    }
  }
  for (const k of ["budget", "monthly_rent_limit", "labor_cost"]) checkNum(b, k, { required: true });
  for (const k of ["initial_investment", "other_fixed", "loan_amount", "owner_salary"]) checkNum(b, k, {});
  checkNum(b, "loan_rate_annual", { le: 0.3 });
  // app/schemas.py 목록 개수 제한(중복 제거 전 길이 기준 — pydantic과 같음)
  for (const [k, n] of [["candidate_area_codes", 10], ["licenses", 20], ["excluded_industries", 100], ["interests", 20],
    ["categories", 3]] as [string, number][]) {
    if (Array.isArray(b[k]) && b[k].length > n) fieldErr(k, `${josa(LABELS[k], "은/는")} ${n}개까지 고를 수 있어요`);
    if (Array.isArray(b[k]) && b[k].some((x: any) => typeof x === "string" && x.length > 50)) fieldErr(k, `${josa(LABELS[k], "이/가")} 너무 길어요`);
  }
}
export function validateBreakEvenIn(b: any) {
  for (const k of ["monthly_rent", "labor_cost", "other_fixed", "initial_investment", "loan_amount", "owner_salary"]) checkNum(b, k, {});
  checkNum(b, "loan_rate_annual", { le: 0.3 });
  checkNum(b, "cogs_rate", { lt: 1 });
  checkNum(b, "other_variable_rate", { lt: 1 });
  checkNum(b, "avg_ticket", { ge: 100, le: 10_000_000 });
}

// ── analysis.py ─────────────────────────────────────────────────────────
function item(st: State, area: string, r: any, type: string, fApplied: boolean, ownerIncluded = false, fixedTotal = 1.0) {
  const row = st.row(area, r.industry_code);
  const profile = st.profile(row);
  const ind = st.industries.get(r.industry_code) || {};
  const f = (x: any) => (ok(x) ? x : null);
  const D = f(r.D), F = f(r.F);
  const reason0 = typeof r.ineligible_reason === "string" ? r.ineligible_reason : null;
  const it: any = {
    industry_code: r.industry_code, industry_name: r.industry_name, category: r.category, display_group: ind.display_group ?? null,
    item_type: type, rank: type === "TOP" && ok(r.rank_order) ? Math.trunc(r.rank_order) : null, suitability: f(r.suitability),
    score_note: null,
    scores: { D, S: f(r.S), F: fApplied ? F : null }, risk_score: r.risk_score, risk_grade: r.risk_grade,
    location_risk_pct: r.risk_pct_in_ind, location_grade: r.location_grade, pred_annual_rate: r.pred_annual_rate,
    sales_ps_m: f(r.sales_ps_m), avg_ticket: f(r.ticket), stores_avg: f(r.stores_avg4), confidence: r.confidence,
    achievability_ratio: f(r.achievability_ratio), eligible: !!r.eligible, ineligible_reason: reason0,
    reason: typeof r.reason === "string" ? r.reason : "", caution: typeof r.caution === "string" ? r.caution : "",
  };
  if (ownerIncluded && reason0 !== null && reason0 in OWNER_REASON) it.ineligible_reason = OWNER_REASON[reason0];
  const unit = st.snap.areas[area].level === "district" ? "구" : "상권";
  if ((it.ineligible_reason || "").startsWith(FEW_AREAS)) {        // 화면의 다른 문장(…구가 N곳뿐)과 같은 말로
    it.ineligible_reason = it.ineligible_reason.replace("비교할 지역이", `비교할 ${josa(unit, "이/가")}`);
  }
  if (D === null) { it.suitability = null; it.score_note = "매출 데이터가 없어 적합도를 계산하지 않았어요"; }
  else if (fApplied && F === null) it.score_note = "비용 적합도 없이 낸 점수라 다른 업종과 바로 비교하기 어려워요";
  else if (type === "INTEREST" && it.eligible && it.location_risk_pct >= 90) it.score_note = "같은 업종끼리 비교해 이 지역 입지 위험이 매우 높아(상위 10%) 추천 TOP에서는 뺐어요";
  else if (type === "INTEREST" && it.eligible && it.suitability !== null && Math.floor(it.suitability + 0.5) < st.p.suitability.min_top_score) {
    it.score_note = `적합도가 ${Math.trunc(st.p.suitability.min_top_score)}점 미만이라 추천 순위에 넣지 않았어요`;
  } else if ((reason0 || "").startsWith(FEW_AREAS)) {
    const nAreas = row ? f(row.sales_n) : null;
    it.score_note = nAreas !== null ? `매출을 비교할 구가 ${Math.trunc(nAreas)}곳뿐이라 적합도는 참고용이에요` : "매출을 비교할 구가 적어 적합도는 참고용이에요";
  }
  const nr: any = { ...r, D, achievability_ratio: it.achievability_ratio, unit,
    owner_included: ownerIncluded,
    // '손익분기 미확인' 칩은 답이 정해지지 않았을 때만(월 고정비 0원이거나 평균 매출 < 월 고정비로 이미 빠진 업종 제외)
    cogs_missing: !!r.cogs_missing && fixedTotal > 0 && reason0 !== INELIGIBLE_FIXED && !(ok(r.sales_ps_m) && r.sales_ps_m < fixedTotal) };
  if (row) {
    nr.sales_rank = f(row.sales_rank); nr.sales_n = f(row.sales_n);
    nr.sales_outlier = salesOutlier(row);
    nr.risk_factors = relabel(r.risk_factors || [], { sales_outlier: nr.sales_outlier, store_growth: f(row.store_growth), sales_growth: f(row.sales_growth) });
  }
  it.reason_short = reasonShort(nr);
  it.chips = reasonChips(nr);
  it.cautions = cautionPills(nr, profile);
  if (!it.eligible && (reason0 === INELIGIBLE_BEP || reason0 === INELIGIBLE_FIXED)) {
    it.cautions = it.cautions.filter((c: string) => !c.startsWith("평균 매출로 손익분기") && !c.startsWith("평균 매출로 필요 매출"));     // '추천 제외' 줄과 같은 뜻은 한 번만
  }
  if ((reason0 || "").startsWith(OUTLIER_REASON)) it.cautions = it.cautions.filter((c: string) => c !== OUTLIER_PILL);
  it.peak = peakFlags(profile, r.category, r.industry_code);
  return it;
}

const FEW_AREAS = "매출을 비교할 지역이 적음";
const INELIGIBLE_FIXED = "평균 매출이 월 고정비보다 적음", INELIGIBLE_BEP = "평균 매출로 손익분기 미달";
const OWNER_REASON: Record<string, string> = { [INELIGIBLE_FIXED]: "평균 매출이 월 고정비(목표 월수입 포함)보다 적음",
  [INELIGIBLE_BEP]: "평균 매출로 필요 매출(목표 월수입 포함) 미달" };
/** analysis.fixed_phrase / cut_advice */
export const fixedPhrase = (fixed: number, owner: number) => (owner > 0 ? `목표 월수입을 포함한 월 고정비(${won(fixed)})` : `입력한 월 고정비(${won(fixed)})`);
const cutAdvice = (owner: number) => (owner > 0 ? "임대료·인건비나 목표 월수입을 낮춰" : "임대료·인건비 등 고정비를 낮춰");
const bySalesDesc = (a: any, b: any) => (b.sales_ps_m - a.sales_ps_m) || (a.industry_code < b.industry_code ? -1 : a.industry_code > b.industry_code ? 1 : 0);
function shortfall(rec: any): [number, number | null, string | null, string | null] {
  const hit = rec.table.filter((t: any) => t.ineligible_reason === INELIGIBLE_FIXED || t.ineligible_reason === INELIGIBLE_BEP);
  if (!hit.length) return [0, null, null, null];
  // '가장 높은 업종 월매출'로 대형 점포가 섞인 듯한 평균은 인용하지 않는다(모두 그렇다면 어쩔 수 없이)
  const plain = hit.filter((t: any) => t.sales_outlier === null || t.sales_outlier === undefined);
  const top = (plain.length ? plain : hit).slice().sort(bySalesDesc)[0];
  return [hit.length, top.sales_ps_m, top.ineligible_reason, top.industry_name];
}
/** analysis.covers_fixed: 평균 매출로 월 고정비를(원가율을 알면 원가·카드수수료·기타 수수료까지 빼고) 감당하는지 */
function coversFixed(st: State, sales: any, fixed: number, cogs: number | null | undefined, other = 0): boolean {
  if (!ok(sales) || sales < fixed) return false;
  if (cogs === null || cogs === undefined) return true;
  let fee = st.p.card_fee_over_3b;
  for (const [cap, rate] of st.p.card_fee_tiers) if (sales * 12 <= cap) { fee = rate; break; }
  return sales * (1 - cogs - fee - other) >= fixed;
}
let ST: State | null = null;                        // licensedHint가 카드수수료 표를 쓰도록 runAnalysis가 넣어 둔다
const ST_MIN = () => Number(ST ? ST.p.suitability.min_top_score : 20);   // 추천 TOP 최소 적합도(analysis.MIN_TOP_SCORE)
function licensedHint(rec: any, fixed: number, uc: UserCondition): string {
  const cats = uc.categories || [];
  const cm = uc.cogs_by_category || {};
  const cogsOf = (cat: string) => (cat in cm ? cm[cat] : ST!.p.default_cogs[cat]);
  const lic = rec.table.filter((t: any) => (t.ineligible_reason || "").endsWith("자격 필요") && ok(t.sales_ps_m) && t.sales_ps_m >= fixed
    && (t.sales_outlier === null || t.sales_outlier === undefined)
    && (!cats.length || cats.includes(t.category)) && coversFixed(ST!, t.sales_ps_m, fixed, cogsOf(t.category))).sort(bySalesDesc);
  return lic.length ? ` 자격이 필요한 ${lic[0].industry_name} 등은 보유 자격을 고르면 후보가 될 수 있어요.` : "";
}
/** analysis.outlier_note: 매출이 유난히 높아(서울 중간값의 3배 이상) 추천에서 뺀 업종 중 순위에 들 만했던 것 */
export function outlierNote(st: State, rec: any): string | null {
  // 다른 조건은 다 통과한 업종만 이 이유로 빠진다 → 적합도 하한(화면 정수 20점)도 넘어야 '순위에 들 만했던' 업종
  let hit = rec.table.filter((t: any) => (t.ineligible_reason || "").startsWith(OUTLIER_REASON)
    && Math.floor(t.suitability + 0.5) >= st.p.suitability.min_top_score);
  if (rec.top.length >= st.p.suitability.top_n && hit.length) {
    const cut = Math.min(...rec.top.map((t: any) => t.suitability));
    hit = hit.filter((t: any) => t.suitability > cut);
  }
  if (!hit.length) return null;
  hit = hit.slice().sort((a: any, b: any) => (b.suitability - a.suitability) || (a.industry_code < b.industry_code ? -1 : a.industry_code > b.industry_code ? 1 : 0));
  const names = hit.slice(0, 2).map((t: any) => t.industry_name).join("·") + (hit.length > 2 ? " 등" : "");
  const cats = new Set(hit.map((t: any) => t.category));
  const kind = cats.size === 1 ? (BIG_STORE[hit[0].category] ?? "대형 점포") : "대형 점포";   // 학원에 '도매 상가'라고 하지 않게
  return `점포당 매출이 서울 같은 업종 중간값의 ${st.p.suitability.outlier_sales_x}배 이상인 ${hit.length}개 업종(${names})은 ${josa(kind, "이/가")} 섞인 평균일 수 있어 추천 순위에서 뺐어요.`;
}
/** analysis.low_names: 적합도 하한 미만이라 뺀 업종 이름(점수 높은 순 최대 k개) — '노래방 17점, PC방 5점 등' */
export function lowNames(rec: any, k = 2): string {
  const low: [string, number][] = rec.low_list || [];
  return low.slice(0, k).map(([n, v]) => `${n} ${Math.floor(v + 0.5)}점`).join(", ") + (low.length > k ? " 등" : "");
}
const VAR100 = "원가·수수료가 매출의 100% 이상", CAT_ORDER = ["외식업", "서비스업", "소매업"];
/** analysis._entered_cogs: 원가 때문에 빠진 업종의 분야 중 원가율을 높게(50% 이상) 넣은 분야 — '외식업 95%' */
function enteredCogs(rec: any, uc: UserCondition, reasons: string[]): string {
  const cm: Record<string, number> = uc.cogs_by_category || {};
  const cats = new Set(rec.table.filter((t: any) => reasons.includes(t.ineligible_reason)).map((t: any) => t.category));
  return CAT_ORDER.filter((c) => cats.has(c) && c in cm && cm[c] >= 0.5).map((c) => `${c} ${pct(cm[c]).replace(".0%", "%")}`).join("·");
}
export function emptyReason(rec: any, uc: UserCondition): string {
  const cats = uc.categories || [];
  const scope = cats.length ? ` ${cats.join("·")}` : "";
  const fixed = monthlyFixedTotal(uc), owner = Number(uc.owner_salary || 0);
  const nCaution = rec.caution_list.length;
  const [nCost, best, why, bestName] = shortfall(rec);
  // 비용 때문에 빠진 업종 중 매출이 가장 높은 업종(대형 점포가 섞인 듯한 평균은 빼고)을 예로 든다
  const bestS = why === INELIGIBLE_BEP ? `비용 때문에 빠진 업종 중 매출이 가장 높은 ${bestName}도 월매출 ${won(best)}에서 원가·카드수수료를 빼면 모자라요`
    : `비용 때문에 빠진 업종 중 매출이 가장 높은 ${bestName}도 월매출이 ${josa(won(best), "으로/로")} 월 고정비보다 적어요`;
  const who = (uc.licenses || []).length ? "지금 조건으로 열 수 있는" : "자격 없이 열 수 있는";
  const costS = nCost ? `${fixedPhrase(fixed, owner)}로는 이 지역${scope}에서 ${who} 업종이 평균 매출로 손익분기를 넘기 어려워요. ` +
    `${bestS}. ${cutAdvice(owner)} 다시 분석해 보세요.` : "";
  let hint = nCost ? licensedHint(rec, fixed, uc) : "";
  const ec = nCost ? enteredCogs(rec, uc, [INELIGIBLE_BEP]) : "";      // 높은 원가율이 원인이면 고정비만 탓하지 않는다
  if (ec) hint += ` 입력한 원가율(${ec})이 맞는지도 확인해 보세요 — 원가율이 높으면 고정비를 줄여도 남는 몫이 적어요.`;
  if (nCaution && rec.n_candidates === nCaution) {
    const who = nCaution === 1 ? "조건에 맞는 업종이 1개뿐인데" : `조건에 맞는 업종 ${nCaution}개가 모두`;
    const s = `${who} 같은 업종끼리 비교해 이 지역 입지 위험이 매우 높은 곳이라 추천에서 뺐어요.`;
    if (nCost) return s + ` 나머지 ${nCost}개 업종은 ${fixedPhrase(fixed, owner)}로는 평균 매출로 손익분기를 넘기 어려워요. ${cutAdvice(owner)} 다시 분석해 보세요.` + hint;
    return s + " 아래 주의 업종을 참고하거나 다른 지역과 비교해 보세요.";
  }
  const nLow = Number(rec.n_low_score || 0), MIN = Math.trunc(ST_MIN());
  if (nLow) {        // 후보는 있지만 적합도가 모두 기준 미만 → 순위를 채우려고 넣지 않았다
    const s = nCaution ? `조건에 맞는 업종 중 ${nCaution}개는 같은 업종끼리 비교한 입지 위험이 매우 높아 주의 업종으로 뺐고, 나머지 ${nLow}개(${lowNames(rec)})는 적합도가 ${MIN}점 미만이라 추천하지 않았어요.`
      : `조건에 맞는 ${nLow}개 업종(${lowNames(rec)})의 적합도가 모두 ${MIN}점 미만이라 추천하지 않았어요.`;
    if (nCost) return s + ` 그 밖의 ${nCost}개 업종은 ${fixedPhrase(fixed, owner)}로는 평균 매출로 손익분기를 넘기 어려워요. ${cutAdvice(owner)} 다시 분석해 보세요.` + hint;
    return s + " 분야 제한을 풀거나 다른 지역과 비교해 보세요.";
  }
  if (nCost) return costS + hint;
  const v100 = enteredCogs(rec, uc, [VAR100]);
  if (v100) return `입력한 원가율(${v100})에 카드수수료를 더하면 매출의 100% 이상이라 팔수록 손해예요. 원가율을 확인해 다시 분석해 보세요.`;
  return `이 지역${scope}에는 조건에 맞는 추천 업종이 없어요. 분야 제한이나 비용 조건을 조정해 보세요.`;
}
export const scopeNote = (areaName: string, level: string) => (level !== "district" ? null
  : `상권 단위 데이터가 아직 없어 ${areaName} 전체(자치구) 기준으로 분석했어요. 반경은 후보 구를 고르는 데만 쓰여요.`);

export function runAnalysis(st: State, s: StoreData, body: any) {
  if (!(body.area_code in st.snap.areas)) throw new EngineError(404, "UNKNOWN_AREA", "선택한 상권을 찾을 수 없어요. 상권을 다시 골라 주세요");
  const notices: string[] = [];
  let area = body.area_code;
  if (!st.areaRows(area).length) {
    const a = st.snap.areas[area];
    const near = st.areaOrder.filter((c) => c !== area && st.areaRows(c).length)
      .sort((x, y) => ((st.snap.areas[x].lat - a.lat) ** 2 + (st.snap.areas[x].lng - a.lng) ** 2) - ((st.snap.areas[y].lat - a.lat) ** 2 + (st.snap.areas[y].lng - a.lng) ** 2));
    if (!near.length) throw new EngineError(422, "NO_AREA_DATA", "이 상권은 분석할 데이터가 없어요");
    notices.push(`${a.name}에 데이터가 부족해 인근 ${st.snap.areas[near[0]].name} 기준으로 보정 분석했어요.`);
    area = near[0];
  }
  const interests: string[] = dedupe(body.interests || []), excluded: string[] = dedupe(body.excluded_industries || []);
  const unknown = [...interests, ...excluded].filter((c) => !st.industries.has(c));
  if (unknown.length) throw new EngineError(422, "UNKNOWN_INDUSTRY", `알 수 없는 업종 코드: ${unknown.join(", ")}`, [{ field: "interests", message: "업종을 다시 선택해 주세요" }]);
  const knownLic = new Set(Object.values(st.p.licensed as Record<string, string>));
  if ((body.licenses || []).some((x: string) => !knownLic.has(x))) {
    throw new EngineError(422, "UNKNOWN_LICENSE", "알 수 없는 자격이 있어요. 보유 자격을 다시 선택해 주세요", [{ field: "licenses", message: "보유 자격을 다시 선택해 주세요" }]);
  }
  const candCodes = dedupe(body.candidate_area_codes || []).filter((c) => c in st.snap.areas && c !== area);
  const req: any = {
    public_id: newId(), area_code: area, budget: body.budget,
    monthly_rent_limit: body.monthly_rent_limit, labor_cost: body.labor_cost, initial_investment: body.initial_investment ?? 0,
    business_goal: body.business_goal ?? "기본", user_type: body.user_type ?? "PRE_FOUNDER",
    other_fixed: body.other_fixed ?? 0, loan_amount: body.loan_amount ?? 0, loan_rate_annual: body.loan_rate_annual ?? 0,
    owner_salary: body.owner_salary ?? 0, licenses: dedupe(body.licenses || []), categories: dedupe(body.categories || []),
    place_name: body.place_name ?? null, center_lat: body.lat ?? null, center_lng: body.lng ?? null, radius_meter: body.radius_m ?? null,
    data_quarter: st.snap.meta.data_quarter, model_version: st.snap.meta.model_version, created_at: nowIso(),
    candidate_area_codes: candCodes, interests, cogs_rates: { ...(body.cogs_rates || {}) }, excluded_industries: excluded,
  };
  const uc = userCondition(req, interests);
  if (req.initial_investment > req.budget) {
    throw new EngineError(422, "INVALID_CONDITION", "초기 투자비가 총 창업 예산보다 커요", [{ field: "initial_investment", message: "초기 투자비가 총 창업 예산보다 커요" }]);
  }
  const rec = recommend(st, area, uc, UNIT[st.snap.areas[area].level]);
  ST = st;
  const nTop = rec.top.length;
  const empty = nTop === 0 ? emptyReason(rec, uc) : null;
  if (nTop > 0 && nTop < st.p.suitability.top_n) {
    const [nCost] = shortfall(rec);
    const nLow = Number(rec.n_low_score || 0);
    notices.push(`조건에 맞는 추천 업종이 ${nTop}개예요.` +
      (nCost ? ` ${fixedPhrase(monthlyFixedTotal(uc), Number(uc.owner_salary || 0))}로는 평균 매출로 손익분기를 넘기 어려운 ${nCost}개 업종은 뺐어요.` : "") +
      (nLow ? ` 적합도가 ${Math.trunc(st.p.suitability.min_top_score)}점 미만인 ${nLow}개 업종(${lowNames(rec)})은 순위를 채우려고 넣지 않았어요.` : "") +
      (rec.caution_list.length ? ` 같은 업종끼리 비교한 입지 위험이 매우 높은(상위 10%) ${rec.caution_list.length}개 업종은 ‘주의 업종’ 목록에서 따로 보여 드려요.` : ""));
  }
  const on = outlierNote(st, rec);
  if (on) notices.push(on);
  notices.push(...st.snap.meta.notices);
  req.notices = notices;
  const items: any[] = [];
  for (const [type, arr] of [["TOP", rec.top], ["INTEREST", rec.interest], ["CAUTION", rec.caution_list]] as const) {
    for (const r of arr) items.push(item(st, area, r, type, rec.f_applied, (req.owner_salary || 0) > 0, monthlyFixedTotal(uc)));
  }
  req.result = { weights: rec.weights, f_applied: rec.f_applied, f_note: rec.f_note, n_candidates: rec.n_candidates,
    n_low_score: rec.n_low_score || 0, empty_reason: empty, items };
  s.analyses[req.public_id] = req;
  return { req };
}
const dedupe = (a: string[]) => Array.from(new Set(a));

export function conditionsDict(req: any) {
  return { budget: req.budget, monthly_rent_limit: req.monthly_rent_limit, labor_cost: req.labor_cost,
    initial_investment: req.initial_investment, other_fixed: req.other_fixed, loan_amount: req.loan_amount,
    loan_rate_annual: req.loan_rate_annual, owner_salary: req.owner_salary, business_goal: req.business_goal,
    user_type: req.user_type, licenses: req.licenses, categories: req.categories, cogs_rates: { ...(req.cogs_rates || {}) },
    excluded_industries: [...(req.excluded_industries || [])],
    monthly_fixed_total: pyRoundInt(monthlyFixedTotal(userCondition(req, []))) };
}
export function analysisOut(st: State, req: any) {
  const a = st.snap.areas[req.area_code];
  const buckets: Record<string, any[]> = { TOP: [], INTEREST: [], CAUTION: [] };
  for (const it of req.result.items) buckets[it.item_type].push(it);
  buckets.TOP.sort((x, y) => (x.rank || 99) - (y.rank || 99));
  const notices = [...(req.notices || [])];
  if (req.model_version !== st.snap.meta.model_version) {
    notices.push(req.data_quarter !== st.snap.meta.data_quarter
      ? `이 분석 이후 데이터가 갱신됐어요(${quarterLabel(req.data_quarter)} → ${quarterLabel(st.snap.meta.data_quarter)}). 새로 분석하면 최신 결과를 볼 수 있어요.`
      : "이 분석 이후 계산 방식이 업데이트됐어요. 새로 분석하면 최신 결과를 볼 수 있어요.");
  }
  const got = new Set(buckets.INTEREST.map((i) => i.industry_code));
  const missing = (req.interests || []).filter((c: string) => !got.has(c))
    .map((c: string) => ({ industry_code: c, industry_name: st.industries.get(c).name }));
  return {
    id: req.public_id, created_at: req.created_at,
    area: { area_code: req.area_code, area_name: a.name, level: a.level, place_name: req.place_name, radius_m: req.radius_meter,
      lat: req.center_lat, lng: req.center_lng, scope_note: scopeNote(a.name, a.level), candidate_area_codes: [...(req.candidate_area_codes || [])] },
    conditions: conditionsDict(req), data_quarter: req.data_quarter, data_quarter_label: quarterLabel(req.data_quarter),
    model_version: req.model_version, business_goal: req.business_goal, weights: req.result.weights,
    f_applied: req.result.f_applied, f_note: req.result.f_note, n_candidates: req.result.n_candidates,
    n_low_score: req.result.n_low_score || 0, empty_reason: req.result.empty_reason ?? null,
    top: buckets.TOP, interests: buckets.INTEREST, cautions: buckets.CAUTION, missing_interests: missing, notices,
  };
}
/** 분석 id를 아는 사람이면 누구나(서버 analysis.get_analysis). 0.1 데모에서 계정이 만든 분석(user_id 있음)은 열지 않는다 */
export function getAnalysis(s: StoreData, id: string) {
  const req = s.analyses[id];
  if (!req || req.user_id != null) throw new EngineError(404, "ANALYSIS_NOT_FOUND", "분석 결과를 찾을 수 없어요");
  return req;
}

// ── risk_svc (영속화: 같은 분석·업종·모델 버전은 재사용) ─────────────────
export function riskFor(st: State, s: StoreData, req: any, code: string, beId: number | null = null) {
  const out: any = riskDetail(st, req.public_id, req.area_code, code, req.candidate_area_codes || []);
  // risk_svc._with_affordability: 인근 지역마다 그 지역 평균 매출로 지금 비용을 감당하는지 —
  // 리포트에서 열었으면(be) 그 리포트에 반영한 손익분기(같은 분석·업종일 때만), 아니면 분석 조건 기준
  const beRow = beId ? s.breakevens.find((b) => b.break_even_id === beId && b.request_id === req.public_id && b.industry_code === code && b.inputs) || null : null;
  const cat = st.industries.get(code).category;
  let cg = (req.cogs_rates || {})[cat] ?? st.p.default_cogs[cat] ?? null;
  let fixed = monthlyFixedTotal(userCondition(req, [])), other = 0.0;
  if (beRow) {
    fixed = beRow.result.monthly_fixed_cost;
    other = Number(beRow.inputs.other_variable_rate || 0);
    if (ok(beRow.inputs.cogs_rate)) cg = beRow.inputs.cogs_rate;
  }
  for (const a of out.alternatives) {
    const r2 = st.row(a.area_code, code);
    const sales = r2 && ok(r2.sales_ps_m) ? r2.sales_ps_m : null;
    const x = r2 ? salesOutlier(r2) : null;
    a.sales_ps_m = sales;
    a.sales_outlier = x === null ? null : pyRound(x, 1);
    // 평균 매출이 대형 점포 때문에 부풀었을 수 있으면 감당 여부를 판단하지 않는다(리포트도 권하지 않음)
    a.affordable = sales === null || x !== null ? null : coversFixed(st, sales, fixed, cg, other);
  }
  out.affordability_basis = beRow ? "report" : "analysis";
  out.affordability_cogs_known = cg !== null && cg !== undefined;    // 모르면 '평균 매출 ≥ 월 고정비'만 봄
  out.affordability_owner_included = Number(beRow ? beRow.inputs.owner_salary || 0 : req.owner_salary || 0) > 0;
  const existing = s.risks.filter((r) => r.request_id === req.public_id && r.industry_code === code && r.model_version === st.snap.meta.model_version).pop();
  if (existing) { out._risk_id = existing.risk_id; return out; }
  const ra = { risk_id: nextId(s), request_id: req.public_id, industry_code: code, risk_score: out.risk_score, risk_level: out.risk_grade,
    pred_annual_rate: out.pred_annual_rate, location_risk_pct: out.location_risk_pct, location_risk_level: out.location_grade,
    confidence: out.confidence, model_version: st.snap.meta.model_version };
  s.risks.push(ra);
  out._risk_id = ra.risk_id;
  return out;
}

// ── breakeven_svc.py ─────────────────────────────────────────────────────
const OVERRIDE_KEYS = ["monthly_rent", "labor_cost", "other_fixed", "initial_investment", "loan_amount", "loan_rate_annual",
  "owner_salary", "cogs_rate", "other_variable_rate", "avg_ticket"];
export function computeBreakeven(st: State, s: StoreData, req: any, body: any, persist = true) {
  const code = body.industry_code;
  const ind = st.industries.get(code);
  if (!ind) throw new EngineError(404, "UNKNOWN_INDUSTRY", "알 수 없는 업종이에요");
  const r = st.row(req.area_code, code);
  const pick = (v: any, d: any) => (v === null || v === undefined ? d : v);
  // 원가율 기본값: 이 화면에서 넣은 값 → 분석 조건(SB-03)의 분야별 원가율 → 업종 대분류 평균(외식업만)
  const condCogs = (req.cogs_rates || {})[ind.category];
  const cogsSource = body.cogs_rate != null ? "user" : condCogs !== undefined && condCogs !== null ? "analysis" : "default";
  const inp = { monthly_rent: pick(body.monthly_rent, req.monthly_rent_limit), labor_cost: pick(body.labor_cost, req.labor_cost),
    other_fixed: pick(body.other_fixed, req.other_fixed), initial_investment: pick(body.initial_investment, req.initial_investment),
    loan_amount: pick(body.loan_amount, req.loan_amount), loan_rate_annual: pick(body.loan_rate_annual, req.loan_rate_annual),
    owner_salary: pick(body.owner_salary, req.owner_salary), cogs_rate: pick(body.cogs_rate, condCogs ?? null),
    other_variable_rate: pick(body.other_variable_rate, 0.0), avg_ticket: body.avg_ticket ?? null };
  const m = (k: "sales_ps_m" | "ticket" | "tx_ps_day") => (r === null || !ok(r[k]) ? null : (r[k] as number));
  const mk = { sales_ps_m: m("sales_ps_m"), ticket: m("ticket"), tx_ps_day: m("tx_ps_day") };
  // 객단가 기본값(UC-04 대안 흐름): 입력값 → 이 지역 같은 업종 실제 평균 → 서울 같은 업종 평균
  const ticketSource = body.avg_ticket != null ? "user" : mk.ticket !== null ? "local" : ok(ind.seoul_ticket) ? "seoul" : null;
  const marketTicket = ticketSource === "local" ? mk.ticket : ticketSource === "seoul" ? ind.seoul_ticket : null;
  const label = ticketSource === "seoul" ? "서울 같은 업종 평균(이 지역 데이터 없음)" : "이 지역 같은 업종 실제 평균";
  let res: any;
  try {
    res = calculate(st, inp, ind.category, mk.sales_ps_m, marketTicket, mk.tx_ps_day, label);
  } catch (e: any) {
    if (!(e instanceof ValueErr)) throw e;
    const msg = e.message;
    if (msg.includes("변동비율")) throw new EngineError(422, "VARIABLE_RATE_TOO_HIGH", msg.includes("비현실")
      ? "원가율에 카드수수료와 기타 수수료를 더하면 100%에 너무 가까워 필요 매출이 비현실적으로 커요. 원가율을 확인해 주세요"
      : "원가율에 카드수수료(필요 매출 규모에 따라 0.4~2%)와 기타 수수료를 더하면 100% 이상이라 팔수록 손해예요. 원가율을 확인해 주세요",
      [{ field: "cogs_rate", message: "원가율을 낮춰 주세요", value: inp.cogs_rate ?? st.p.default_cogs[ind.category] ?? null } as any,
        { field: "other_variable_rate", message: "배달·기타 수수료를 확인해 주세요", value: inp.other_variable_rate } as any]);
    if (msg.includes("원가율 입력 필요")) throw new EngineError(422, "COGS_REQUIRED", `${josa(ind.category, "은/는")} 공식 기본 원가율이 없어요. 원가율(매출 대비 재료·상품 원가)을 입력해 주세요`, [{ field: "cogs_rate", message: "원가율을 입력해 주세요" }]);
    if (msg.includes("객단가")) throw new EngineError(422, "TICKET_REQUIRED", "이 지역 실제 객단가 데이터가 없어요. 객단가를 입력해 주세요", [{ field: "avg_ticket", message: "객단가를 입력해 주세요" }]);
    throw new EngineError(422, "INVALID_INPUT", msg);
  }
  const bep = res.required_monthly_sales, owner = inp.owner_salary;
  const fe = pyRoundInt(res.monthly_fixed_cost - owner), ow = pyRoundInt(owner);   // 변동비는 나머지로(구성 합이 원 단위까지 맞게)
  const comp = { fixed_ex_owner: fe, variable: bep - fe - ow, owner_salary: ow, total: bep };
  const maxFixed = mk.sales_ps_m ? pyRoundInt(mk.sales_ps_m * res.contribution_margin_rate) : null;
  const inputs = { monthly_rent: inp.monthly_rent, labor_cost: inp.labor_cost, other_fixed: inp.other_fixed,
    initial_investment: inp.initial_investment, loan_amount: inp.loan_amount, loan_rate_annual: inp.loan_rate_annual,
    owner_salary: inp.owner_salary, cogs_rate: res.variable_breakdown["원가율"], cogs_is_default: cogsSource === "default",
    cogs_source: cogsSource,
    other_variable_rate: inp.other_variable_rate, avg_ticket: body.avg_ticket ?? null, ticket_is_market: body.avg_ticket == null,
    ticket_source: ticketSource,
    // 이 계산에서 덮어쓴 항목(breakeven_svc OVERRIDE_KEYS)
    overridden: OVERRIDE_KEYS.filter((k) => body[k] !== null && body[k] !== undefined),
    // 기본값이 없어 꼭 넣어야 했던 항목(원가율: 조건 입력값·업종 평균 없음 / 객단가: 지역·서울 평균 없음)
    required: ([["cogs_rate", (condCogs === undefined || condCogs === null) && (st.p.default_cogs[ind.category] ?? null) === null],
      ["avg_ticket", mk.ticket === null && !ok(ind.seoul_ticket)]] as [string, boolean][])
      .filter(([k, need]) => need && body[k] !== null && body[k] !== undefined).map(([k]) => k) } as any;
  // 덮어쓴 항목 중 기본값(분석 조건·조건 원가율·업종 평균·지역 평균 객단가)과 실제로 다른 것 — '바꾼 값 적용 중' 표시 기준
  const defaults: Record<string, number | null> = { monthly_rent: req.monthly_rent_limit, labor_cost: req.labor_cost, other_fixed: req.other_fixed,
    initial_investment: req.initial_investment, loan_amount: req.loan_amount, loan_rate_annual: req.loan_rate_annual,
    owner_salary: req.owner_salary,
    cogs_rate: condCogs !== undefined && condCogs !== null ? condCogs : (st.p.default_cogs[ind.category] ?? null),
    other_variable_rate: 0.0, avg_ticket: mk.ticket !== null ? mk.ticket : ok(ind.seoul_ticket) ? ind.seoul_ticket : null };
  const tol: Record<string, number> = { avg_ticket: 1.0 };
  // 기본값이 없어 꼭 넣어야 했던 값(required)은 '바꾼 값'이 아니라 '직접 넣은 값'
  inputs.changed = inputs.overridden.filter((k: string) => !inputs.required.includes(k) && (defaults[k] === null || defaults[k] === undefined
    || Math.abs(Number(body[k]) - Number(defaults[k])) > (tol[k] ?? 1e-6)));
  const out: any = { analysis_id: req.public_id, area_code: req.area_code, area_name: st.snap.areas[req.area_code].name,
    industry_code: code, industry_name: ind.name, category: ind.category, inputs };
  for (const k of ["monthly_fixed_cost", "fixed_breakdown", "variable_cost_rate", "variable_breakdown", "contribution_margin_rate",
    "required_monthly_sales", "required_daily_sales", "required_daily_customers", "avg_ticket_used", "operating_days",
    "market_sales_ps_m", "achievability_ratio", "cost_pressure", "profit_at_market_avg", "payback_months", "market_tx_ps_day",
    "customers_vs_market", "warnings"]) out[k] = res[k] === undefined ? null : res[k];
  out.max_fixed_for_bep = maxFixed;
  out.composition = comp;
  out.warnings = [...(out.warnings || [])];
  if (mk.sales_ps_m === null) out.warnings.push("이 지역 같은 업종의 카드 매출 데이터가 부족해 평균 매출과의 비교(달성 가능성)는 할 수 없어요");
  const bx = r ? salesOutlier(r) : null;
  out.sales_outlier = bx === null ? null : pyRound(bx, 1);
  if (bx !== null) {                                // SB-05에서 추천 제외한 '대형 점포 가능' 평균 — 배율·회수 기간도 참고용
    out.warnings.push(`이 지역 점포당 매출이 서울 같은 업종 중간값의 ${pyFixed(bx, 1)}배예요 — ${josa(BIG_STORE[ind.category] ?? "대형 점포", "이/가")} 섞인 평균일 수 있어 달성 가능성·투자 회수 기간은 참고용이에요`);
  }
  if (req.budget > 0 && inp.initial_investment > req.budget) out.warnings.push(`초기 투자비가 총 창업 예산(${won(req.budget)})보다 커요 — 예산으로는 운영자금을 마련할 수 없어요`);
  const cvm = res.customers_vs_market;
  if (ticketSource === "user" && ok(cvm) && cvm >= 1.2) {
    out.warnings.push(`입력한 객단가(${pyFixed(res.avg_ticket_used, 0, true)}원)로는 하루 ${pyFixed(res.required_daily_customers, 0, true)}건이 필요해 ` +
      `이 지역 점포 평균 결제(${pyFixed(res.market_tx_ps_day, 1, true)}건)의 ${pyFixed(cvm, 1)}배예요 — 매출 기준 달성 가능성보다 어려울 수 있어요`);
  }
  out.fixed_breakdown = Object.fromEntries(Object.entries(out.fixed_breakdown).map(([k, x]) => [k, pyRoundInt(x as number)]));
  if (persist) {
    const result = { ...out };
    delete result.inputs;
    const be = { break_even_id: nextId(s), request_id: req.public_id, industry_code: code, result, inputs };
    s.breakevens.push(be);
    out.id = be.break_even_id;
  } else out.id = 0;
  return out;
}

export function getSavedBreakeven(s: StoreData, req: any, beId: number) {
  const be = s.breakevens.find((b) => b.break_even_id === beId);
  if (!be || be.request_id !== req.public_id || !be.inputs) throw new EngineError(404, "BREAKEVEN_NOT_FOUND", "손익분기 계산 결과를 찾을 수 없어요");
  return { ...be.result, inputs: be.inputs, id: be.break_even_id };
}

// ── report_svc.py ────────────────────────────────────────────────────────
const ROLE_TO_TARGET: Record<string, string> = { PRE_FOUNDER: "예비창업자", OWNER: "자영업자" };
function userCanOpen(st: State, r: any, req: any, fixedTotal: number) {
  if ((req.excluded_industries || []).includes(r.industry_code)) return false;          // 사용자가 뺀 업종
  const lic = st.p.licensed[r.industry_code];
  if (lic && !(req.licenses || []).includes(lic)) return false;
  if (ok(r.sales_n) && r.sales_n < st.p.suitability.min_sales_areas) return false;   // 매출을 비교할 지역 5곳 미만(추천 필터와 같게)
  if (salesOutlier(r) !== null) return false;                                         // 평균 매출이 대형 점포 때문에 부풀었을 수 있으면
  return !!r.has_sales_data && r.stores_avg4 >= 1.0 && ok(r.sales_ps_m) && r.sales_ps_m >= fixedTotal;
}
const GRADE_ORDER: Record<string, number> = { 낮음: 0, 보통: 1, 높음: 2, 고위험: 3 };
/** report_svc._can_cover: 평균 매출로 월 고정비(원가율을 아는 업종은 원가·카드수수료까지 빼고)를 감당하는지 */
function canCover(st: State, r: any, fixedTotal: number, cogsMap: Record<string, number> | null = null, otherRate = 0): boolean {
  const cm = cogsMap || {};
  const cogs = r.category in cm ? cm[r.category] : st.p.default_cogs[r.category];
  return coversFixed(st, r.sales_ps_m, fixedTotal, cogs, otherRate);
}
function pickAlternative(st: State, area: string, focus: any, tops: any[], req?: any, fixedTotal?: number) {
  const fam = st.industries.get(focus.industry_code)?.family;
  if (!fam) return null;
  const lim = focus.pred_annual_rate * 0.85, g0 = GRADE_ORDER[focus.risk_grade] ?? 0;
  const excl: string[] = req ? req.excluded_industries || [] : [];                   // 사용자가 뺀 업종은 대안으로도 권하지 않는다
  const sameFamily = (code: string) => code !== focus.industry_code && !excl.includes(code) && st.industries.get(code)?.family === fam;
  const lower = (g: string) => (GRADE_ORDER[g] ?? 9) < g0;
  const ft = fixedTotal !== undefined ? fixedTotal : req ? monthlyFixedTotal(userCondition(req, [])) : 0;
  const cm = req ? req.cogs_rates || {} : {};
  const affordable = (code: string) => { const r = st.row(area, code); return !!r && canCover(st, r, ft, cm); };
  const alts = tops.filter((t) => sameFamily(t.industry_code) && t.pred_annual_rate <= lim && lower(t.risk_grade) && affordable(t.industry_code));
  if (alts.length) {
    const b = alts.reduce((best, t) => ((t.suitability || 0) > (best.suitability || 0) ? t : best), alts[0]);
    return { industry_code: b.industry_code, industry_name: b.industry_name, category: b.category, pred_annual_rate: b.pred_annual_rate,
      risk_grade: b.risk_grade };
  }
  const rows = st.areaRows(area).filter((r) => sameFamily(r.industry_code) && r.pred_annual_rate <= lim && ok(r.demand_D)
    && (r.demand_D as number) >= 50 && r.has_sales_data && r.risk_pct_in_ind < 90 && lower(r.risk_grade)
    && (!req || (userCanOpen(st, r, req, ft) && canCover(st, r, ft, cm))));
  if (!rows.length) return null;
  const r = rows.slice().sort((a, b) => ((b.demand_D as number) - (a.demand_D as number)) || (a.industry_code < b.industry_code ? -1 : 1))[0];
  return { industry_code: r.industry_code, industry_name: st.industries.get(r.industry_code).name, category: r.category,
    pred_annual_rate: r.pred_annual_rate, risk_grade: r.risk_grade };
}
export function matchPolicies(st: State, userType: string, category: string, grade: string, deficit: boolean, lendOk = true, k = 3) {
  const target = ROLE_TO_TARGET[userType];
  const scored: [number, any][] = [];
  for (const p of st.snap.policies) {
    if (!["서울", "전국"].includes(p.target_region) || !["전체", category].includes(p.target_category)) continue;
    if (target && !["전체", target].includes(p.target_user)) continue;
    let sc = 0.0;
    const bad = deficit;
    if (p.support_type === "교육" && userType === "PRE_FOUNDER") sc += 2;
    if (p.support_type === "컨설팅") sc += grade === "높음" || grade === "고위험" || bad ? 2 : 1;
    if (p.support_type === "자금") sc += lendOk && !bad ? 1 : -3;
    if (p.support_type === "재기지원") sc += userType === "OWNER" && grade === "고위험" ? 2 : -5;
    if (p.support_type === "정보") sc += 0.5;
    if (p.target_region === "서울") sc += 0.3;
    if (sc > 0) scored.push([sc, p]);
  }
  scored.sort((a, b) => b[0] - a[0]);
  return scored.slice(0, k).map(([, p]) => p);
}
const rowF = (row: any, k: string): number | null => (row && ok(row[k]) ? row[k] : null);
export function entryBlock(st: State, req: any, row: any, code: string, fixedTotal: number, owner = 0): string | null {
  const lic = st.p.licensed[code];
  if (lic && !(req.licenses || []).includes(lic)) return `${lic} 자격이 있어야 열 수 있어요. 자격 요건부터 확인하세요.`;
  if (!row) return null;
  const sales = rowF(row, "sales_ps_m");
  if (row.stores_avg4 < st.p.suitability.min_avg_stores) return "이 지역 점포가 적어 수요가 충분히 검증되지 않았어요. 현장 수요를 먼저 확인하세요.";
  if (!row.has_sales_data || sales === null) {
    return "이 지역 카드 매출 데이터가 부족해 매출로는 판단할 수 없어요. 비슷한 점포의 실제 매출을 먼저 확인하세요.";
  }
  if (sales < fixedTotal) {
    return `점포당 평균 월매출(${won(sales)})이 ${fixedPhrase(fixedTotal, owner)}보다 적어요. ` +
      (owner > 0 ? "비용 조건이나 목표 월수입부터 다시 보세요." : "비용 조건부터 다시 보세요.");
  }
  return null;
}
/** report_svc._area_alt: 같은 업종 입지 위험이 한 등급 이상 낮고 그 지역 평균 매출로 지금 비용을 감당할 수 있는 인근 지역 */
function areaAltOf(st: State, focusRisk: any, code: string, fixedTotal: number, cogsMap: Record<string, number> | null = null, otherRate = 0): any | null {
  const lg = focusRisk.location_grade ? GRADE_ORDER[focusRisk.location_grade] : null;
  // 종합 위험이 높음·고위험이면 입지 등급이 같아도 예상 연 폐업률이 10% 이상 낮은 곳까지(SB-06의 인근 지역 대안을 리포트에서도)
  const high = focusRisk.risk_grade === "높음" || focusRisk.risk_grade === "고위험", rate0 = focusRisk.pred_annual_rate;
  for (const a of focusRisk.alternatives) {
    if (lg !== null && lg !== undefined && GRADE_ORDER[a.location_grade] >= lg && !(high && ok(rate0) && a.pred_annual_rate <= rate0 * 0.9)) continue;
    if ((lg === null || lg === undefined) && a.location_grade !== "낮음") continue;   // 이 지역에 같은 업종이 없으면 '낮음'인 곳만(가까운 곳 대체 목록 제외)
    const r = st.row(a.area_code, code);
    if (r && salesOutlier(r) === null && canCover(st, r, fixedTotal, cogsMap, otherRate)) {   // 대형 점포가 섞인 듯한 평균이면 권하지 않음
      const cm = cogsMap || {};
      const cogs = r.category in cm ? cm[r.category] : st.p.default_cogs[r.category];
      return { ...a, cogs_known: cogs !== null && cogs !== undefined };   // 원가율을 모르면 '매출 ≥ 월 고정비'만 본 것
    }
  }
  return null;
}
/** report_svc.cash_monthly: 가게에서 실제로 나가는 월 비용(임대료+인건비+기타+대출 이자), 1만원 미만은 0 */
export function cashMonthly(inp: any, req: any): number {
  const i = inp || {};
  const g = (k: string, d: any) => Number((i[k] ?? d) || 0);
  const v = g("monthly_rent", req.monthly_rent_limit) + g("labor_cost", req.labor_cost) + g("other_fixed", req.other_fixed)
    + g("loan_amount", req.loan_amount) * g("loan_rate_annual", req.loan_rate_annual) / 12;
  return v >= 10_000 ? v : 0;
}
/** report_svc._cash_items: 0원이 아닌 현금 고정비 이름 */
function cashItems(inp: any, req: any): string {
  const g = (k: string, d: any) => Number((inp[k] ?? d) || 0);
  const interest = g("loan_amount", req.loan_amount) * g("loan_rate_annual", req.loan_rate_annual) / 12;
  const names = ([["임대료", g("monthly_rent", req.monthly_rent_limit)], ["인건비", g("labor_cost", req.labor_cost)],
    ["기타 고정비", g("other_fixed", req.other_fixed)], ["대출 이자", interest]] as [string, number][]).filter(([, v]) => v > 0).map(([k]) => k);
  return names.slice(0, 2).join("·") + (names.length > 2 ? " 등" : "");
}
export function buildChecklist(req: any, focusRisk: any, row: any, be: any, alt: any, profile: any, rentLatest: any, beInputs: any = null,
  licensed: Record<string, string> = {}, registration: Record<string, string> = {}, betterArea: any = null, outMeta: any = null, keepArea = false,
  keepAlt = false) {
  const items: any[] = [];
  const add = (t: string, content: string, pr: number) => items.push({ action_type: t, content, priority: pr });
  const cat = focusRisk.category;
  const offer = OFFER[cat] ?? "상품·서비스";
  const lic = licensed[focusRisk.industry_code];
  if (lic && !(req.licenses || []).includes(lic)) {
    add("자격확인", `${lic} 자격이 있어야 열 수 있어요 — 자격 요건·취득 기간부터 확인`, 1);
    betterArea = null; keepArea = false;          // 자격이 없으면 다른 구 비교 대신(폐업 이력 요인은 현장 확인 항목으로)
  }
  const reg = registration[focusRisk.industry_code];
  if (reg) add("인허가", reg, 2);
  const inp = beInputs || {};
  const rent = Number((inp.monthly_rent ?? req.monthly_rent_limit) || 0);
  const owner = Number((inp.owner_salary ?? req.owner_salary) || 0);
  const inv = Number((inp.initial_investment ?? req.initial_investment) || 0);
  const ratio = be ? be.achievability_ratio : null, maxF = be ? be.max_fixed_for_bep : null;
  const short = ok(ratio) && ratio < 1 && ok(maxF);
  const target = short ? wonFloorBelow(maxF, be.monthly_fixed_cost) : 0;             // 한도는 표시 단위에서 내림
  const gap = short ? wonValue(be.monthly_fixed_cost) - target : 0;                    // 화면에 보이는 두 금액의 차이
  const fixedTotal = be ? be.monthly_fixed_cost : monthlyFixedTotal(userCondition(req, []));
  const sales = rowF(row, "sales_ps_m");
  const noBeDeficit = !be && sales !== null && sales < fixedTotal;
  const what = owner > 0 ? "월 고정비(목표 월수입 포함)" : "월 고정비";
  if (noBeDeficit) add("비용절감", `${what}를 이 지역 점포당 평균 월매출(${won(sales)})보다 충분히 낮추기 (지금 ${won(fixedTotal)}) — 원가율을 넣으면 정확한 한도를 계산해요`, 1);
  const vr = be ? be.variable_cost_rate : null;
  if (ok(vr) && vr >= 0.7) {
    const otherV = Number((be.variable_breakdown || {})["기타"] || 0);
    add("비용절감", `원가율·수수료가 매출의 ${pct(vr, 0)}라 팔아도 남는 몫이 ${pct(1 - vr, 0)}뿐 — ` +
      (otherV > 0 ? "원가·배달 수수료부터 점검" : "원가(재료·상품 매입가)부터 점검"), 1);
  }
  if (short && owner > 0 && target < owner) {                // 한도가 목표 월수입보다 작으면 비용만 줄여서는 안 된다
    add("비용절감", `${what}를 ${won(target)} 이하로 낮춰야 하는데 목표 월수입(${won(owner)})만으로도 넘어요 — 목표 월수입을 낮추거나 업종·입지부터 다시 검토`, 1);
  } else if (short) add("비용절감", `${what}를 ${won(target)} 이하로 낮추기 (지금 ${won(be.monthly_fixed_cost)}, 월 ${won(gap)} 줄여야 함)`, 1);
  if (be && ok(ratio) && ratio >= 1 && ratio < 1.15) {        // 손익분기는 넘지만 빠듯 — 한줄 결론의 '여유가 적어요'를 실행 항목으로
    add("비용절감", `평균 매출이 ${owner > 0 ? "필요 매출(목표 월수입 포함)" : "손익분기"}의 ${times(ratio)}로 여유가 적어요 — 월 고정비를 더 줄일 수 있는지 먼저 점검`, 3);
  }
  const rent33 = rentLatest !== null && rentLatest !== undefined ? rentLatest : rowF(row, "rent4");
  const areaRent = ok(rent33) ? ` · 이 지역 3.3㎡당 평균 ${won1(rent33)}(10평 약 ${won(rent33 * 10)})` : "";
  // 임대료만 줄여 맞추라는 제안이 현실적인지: 남는 임대료가 10만원 미만이거나 이 지역 10평 평균의 절반보다 낮으면 비현실적
  const floorRent = Math.max(100_000, ok(rent33) ? Math.min(0.5 * rent33 * 10, 0.5 * rent) : 0);
  if (rent > 0 && !noBeDeficit) {
    if (short && (gap >= rent || rent - gap < floorRent)) {
      const others = ([["인건비", inp.labor_cost ?? req.labor_cost], ["기타 고정비", inp.other_fixed ?? req.other_fixed], ["목표 월수입", owner],
        ["초기 투자비", inv]] as [string, number][]).filter(([, x]) => (x || 0) > 0).map(([k]) => k);
      add("비용절감", "임대료만 줄여서는 어려워요 — " + (others.length ? others.join("·") + "도 함께 조정" : "업종·입지부터 다시 검토"), 2);
    }
    else if (short) add("비용절감", `임대료만 줄인다면 월 ${won(rent - gap)} 이하 매물 찾기 (지금 ${won(rent)})${areaRent}`, 2);
    else add("비용절감", `월 임대료 ${won(rent)} 이하 매물 우선 검토${areaRent}`, 2);
  }
  const cashFixed = cashMonthly(inp, req);                 // 가게에서 실제로 나가는 월 비용(대표자 월수입·감가상각 제외)
  let longDone = false;                                     // '오래 버티기' 항목(업종 자체 폐업률·지역 수명)은 하나만
  /** report_svc.long_tail: 나가는 돈이 없으면 현장 확인, 예산이 12개월분에 못 미치면 되풀이하지 않고, 아니면 12개월분 금액 */
  const longTail = (kind: string) => {
    if (cashFixed <= 0) return kind === "ind" ? "현장 수요부터 확인" : "상권이 오래가는지 현장에서 먼저 확인";
    if (req.budget > 0 && req.budget - inv < 12 * cashFixed) return kind === "ind" ? "비슷한 업종의 실제 매출·폐업 사례부터 확인" : "상권이 오래가는지 현장에서 먼저 확인";
    return `운영자금은 최소 12개월분(${won(12 * cashFixed)})으로 계획`;
  };
  const ups = focusRisk.factors.filter((f: any) => f.direction === "up" && shownEffect(f) >= 3);   // 화면 숫자(+3%) 기준
  // 운영자금 12개월 기준은 요인 자체로 정한다(비슷한 업종 비교 항목이 대신 들어가도 기준은 같게)
  let twelve = cashFixed > 0 && ups.some((f: any) => f.factor_code === "ind_base" && shownEffect(f) >= 10);
  let added = 0;
  for (const f of ups) {
    if (added >= 2) break;
    const n0 = items.length, c = f.factor_code;
    if (c === "ind_base" && alt) add("업종변경", `폐업률이 낮은 비슷한 업종 ${josa(alt.industry_name, "과/와")} 비교 후 결정 (예상 연 폐업률 ${pct(alt.pred_annual_rate)}, 위험 ${alt.risk_grade})`, 3);
    else if (c === "ind_base" && shownEffect(f) >= 10) {
      add("운영", "업종 자체 폐업률이 높은 업종 — " + (inv > 0 ? "초기 투자비를 줄이고 " : "") + longTail("ind"), 3);
      longDone = true;
    }
    else if (c === "area_hist" && betterArea) {
      const a = betterArea;
      add("입지변경", `같은 업종 입지 위험이 더 낮은 ${a.area_name}(입지 위험 ${a.location_risk_pct}·${a.location_grade}, 예상 연 폐업률 ${pct(a.pred_annual_rate)})도 비교`, 3);
    } else if (c === "area_hist") add("현장확인", `이 지역 같은 업종 최근 1년 폐업 ${pyFixed(focusRisk.raw.closures_1y, 0, true)}곳 — 폐업 원인(상권 이동·경쟁) 현장 확인`, 3);
    else if (c === "store_surge") {
      const g = rowF(row, "store_growth");
      if (g !== null && g > 0 && pySigned(g * 100, 0) !== "+0") add("운영", `점포 수가 전년보다 ${pySigned(g * 100, 0)}% 늘어 경쟁이 세지는 중 — 차별화 ${offer}·콘셉트 먼저 준비`, 4);
    } else if (c === "sales_decline") {
      const g = rowF(row, "sales_growth");
      if (g !== null && g < 0 && pySigned(g * 100, 0) !== "-0") add("운영", `이 지역 같은 업종 매출이 전년보다 ${pySigned(g * 100, 0)}% 줄어드는 중 — 매출 목표를 보수적으로 잡고 비용 계획`, 4);
    } else if (c === "entry_heat") add("운영", "신규 개업이 몰리는 곳 — 오픈 초기 3개월 고객 확보(마케팅) 계획", 4);
    else if (c === "short_life" && !longDone) {           // 같은 취지(오래 버티기) 항목은 하나만
      const m = rowF(row, "closed_months4");
      add("운영", (m !== null ? `이 지역은 폐업한 가게(전 업종)의 평균 영업 기간이 ${pyFixed(m, 0)}개월로 서울에서 짧은 편 — ` : "이 지역은 폐업한 가게의 영업 기간이 서울에서 짧은 편 — ") + longTail("life"), 4);
      twelve = twelve || cashFixed > 0; longDone = true;
    } else if (c === "low_sales") add("운영", `점포당 매출이 같은 업종 다른 지역보다 낮은 편 — ${TARGETS[cat] ?? "객단가"} 목표 먼저 설정`, 4);
    else if (c === "rent_burden") add("비용절감", "매출 대비 임대료 부담이 큰 지역 — 임대료 협상·면적 줄이기 검토", 4);
    else if (c === "density") add("현장확인", "유동인구 대비 점포가 많은 곳 — 점포 앞 동선·경쟁점 위치 현장 확인", 4);
    if (items.length > n0) added += 1;
  }
  if (betterArea && !items.some((it) => it.action_type === "입지변경" && it.content.includes(betterArea.area_name))) {
    const a = betterArea;         // 입지 요인이 상위가 아니어도 비용을 감당할 인근 구가 있으면 알려 준다
    add("입지변경", `같은 업종 입지 위험이 더 낮은 ${a.area_name}(입지 위험 ${a.location_risk_pct}·${a.location_grade}, 예상 연 폐업률 ${pct(a.pred_annual_rate)})도 비교`, 4);
  }
  const ox = row ? salesOutlier(row) : null;
  if (ox !== null) add("현장확인", `비슷한 규모 점포의 실제 매출부터 확인 — 이 지역 평균은 서울 같은 업종 중간값의 ${pyFixed(ox, 1)}배라 대형 점포가 섞였을 수 있어요`, 2);
  const flags = peakFlags(profile, cat, focusRisk.industry_code);
  if (flags.length) add("운영", flags[0].action, 5);
  if (cashFixed > 0) {
    const months = twelve ? 12 : 6;
    const need = months * cashFixed, reserve = req.budget - inv;
    if (req.budget > 0 && reserve < 0) {
      add("운영자금", `초기 투자비가 예산보다 ${won(-reserve)} 많아요 — 투자비를 줄이거나 자금을 더 마련하고, 초기 ${months}개월 운영자금(${won(need)})도 따로 확보`, 2);
    } else if (req.budget > 0 && reserve === 0) {
      add("운영자금", `예산을 초기 투자비로 모두 써서 운영자금이 없어요 — 초기 ${months}개월 운영자금(${won(need)}) 따로 마련`, 2);
    } else if (req.budget > 0 && reserve < need) {
      const have = reserve / cashFixed < 1 ? "1개월분도 안 됨" : `${monthsFloor(reserve / cashFixed)}개월분`;
      add("운영자금", `${inv > 0 ? "예산에서 투자비를 빼면" : "예산으로는"} 운영비 ${have} — 초기 ${months}개월 운영자금(${won(need)}) 확보`, 2);
    } else if (!longDone) {                      // '오래 버티기' 항목이 이미 기간·금액을 말하면 생략
      add("운영자금", `초기 ${months}개월 운영자금(${won(need)}: ${cashItems(inp, req)} ${months}개월분) 별도 확보`, 6);
    }
  }
  if (outMeta) outMeta.runway_months = twelve ? 12 : 6;
  if (keepAlt && alt && !items.some((it) => it.action_type === "업종변경")) {
    // 한줄 결론이 권한 비슷한 업종은 업종 자체 폐업률 요인이 없어도 체크리스트에 남긴다
    add("업종변경", `폐업률이 낮은 비슷한 업종 ${josa(alt.industry_name, "과/와")} 비교 후 결정 (예상 연 폐업률 ${pct(alt.pred_annual_rate)}, 위험 ${alt.risk_grade})`, 3);
  }
  if (!items.length) add("현장확인", "계약 전 평일·주말 점포 앞 유동인구와 가까운 경쟁점을 직접 확인", 1);
  items.sort((a, b) => a.priority - b.priority);
  const seen = new Set<string>(), out: any[] = [];
  for (const it of items) if (!seen.has(it.content)) { seen.add(it.content); out.push(it); }
  let res = out.slice(0, 5);
  // 한줄 결론이 권한 인근 구·비슷한 업종은 체크리스트에도: 3순위 이하 항목 중 마지막 것과 바꾼다(1·2순위와 대안 업종 항목은 건드리지 않음)
  const keep: any[] = [];
  if (keepArea && betterArea) keep.push(out.find((it) => it.action_type === "입지변경" && it.content.includes(betterArea.area_name)));
  if (keepAlt && alt) keep.push(out.find((it) => it.action_type === "업종변경"));
  for (const k of keep.filter(Boolean)) {
    if (res.includes(k)) continue;
    let victims = res.map((it, i) => (it.priority > 2 && it.action_type !== "업종변경" && !keep.includes(it) ? i : -1)).filter((i) => i >= 0);
    if (!victims.length)   // 1·2순위만 남았으면 임대료 매물 항목과 바꾼다
      victims = res.map((it, i) => (it.action_type === "비용절감" && it.priority === 2 && (it.content.includes("매물") || it.content.includes("임대료만"))
        && !keep.includes(it) ? i : -1)).filter((i) => i >= 0);
    if (!victims.length)   // 그것도 없으면 2순위 항목 중 마지막(자격·대안 업종 항목은 두고)
      victims = res.map((it, i) => (it.priority === 2 && it.action_type !== "업종변경" && it.action_type !== "자격확인" && !keep.includes(it) ? i : -1))
        .filter((i) => i >= 0);
    if (!victims.length) break;
    const v = victims[victims.length - 1];
    res = [...res.slice(0, v), ...res.slice(v + 1), k].sort((a, b) => a.priority - b.priority);
  }
  res.forEach((it, i) => { it.priority = i + 1; });
  return res;
}
/** report_svc.input_key: 손익분기 입력값 비교 키(계산에 쓴 값만 — 어느 칸을 직접 넣었는지 같은 표시용 항목은 뺀다) */
const KEY_SKIP = new Set(["overridden", "required", "changed", "cogs_is_default", "cogs_source", "ticket_is_market"]);
export function inputKey(inputs: any): string | null {
  if (!inputs) return null;
  const n = (v: any) => (typeof v === "number" && !Number.isInteger(v) ? Math.round(v * 1e9) / 1e9 : v);   // 40.7% → 0.40700000000000003도 같은 입력
  return JSON.stringify(Object.keys(inputs).sort().filter((k) => !KEY_SKIP.has(k)).map((k) => [k, n(inputs[k])]));
}
export function createReport(st: State, s: StoreData, req: any, code: string, beId: number | null) {
  const ind = st.industries.get(code);
  if (!ind) throw new EngineError(404, "UNKNOWN_INDUSTRY", "알 수 없는 업종이에요");
  const focus = riskFor(st, s, req, code);
  const row = st.row(req.area_code, code);
  const profile = st.profile(row);
  let beRow: any = null;
  // report_svc._existing_report: 같은 분석·업종·손익분기 입력으로 이미 만든 리포트(지금 모델)면 그대로 돌려준다.
  // 저장한 리포트가 있으면 그것을, 없으면 가장 최근 것을(저장 목록 중복 방지)
  const existing = (match: (r: any) => boolean) => {
    const ms = Object.values(s.reports).filter((r: any) => r.request_id === req.public_id && r.industry_code === code)
      .sort((a: any, b: any) => b.seq - a.seq).filter((r: any) => {
        const risk = s.risks.find((x) => x.risk_id === r.risk_id);
        return risk && risk.model_version === st.snap.meta.model_version && match(r);
      });
    return ms.find((r: any) => s.saved.some((x) => x.report_id === r.public_id)) ?? ms[0] ?? null;
  };
  const beKey = (id: number | null) => { const b = id === null ? null : s.breakevens.find((x) => x.break_even_id === id); return b ? inputKey(b.inputs) : null; };
  if (beId !== null && beId !== undefined) {
    beRow = s.breakevens.find((b) => b.break_even_id === beId);
    if (!beRow || beRow.request_id !== req.public_id || beRow.industry_code !== code) throw new EngineError(404, "BREAKEVEN_NOT_FOUND", "손익분기 계산 결과를 찾을 수 없어요");
    const key = beKey(beId);           // 손익분기 화면은 열 때마다 계산을 새로 저장 → id가 달라도 입력값이 같으면 같은 리포트
    const same = existing((r) => r.break_even_id === beId || (r.break_even_id !== null && key !== null && beKey(r.break_even_id) === key));
    if (same) return same;
  } else {
    // 위험도 화면에서 바로 만든 리포트: '리포트에 반영'하지 않은 손익분기 가정값은 쓰지 않고 분석 조건으로 계산
    let preview: any = null;
    try { preview = computeBreakeven(st, s, req, { industry_code: code }, false); } catch (e) { if (!(e instanceof EngineError)) throw e; }
    const key = preview ? inputKey(preview.inputs) : null;
    const same = existing((r) => (r.break_even_id === null && key === null) || (r.break_even_id !== null && key !== null && beKey(r.break_even_id) === key));
    if (same) return same;
    if (preview) {
      const res = computeBreakeven(st, s, req, { industry_code: code }, true);
      beRow = s.breakevens.find((b) => b.break_even_id === res.id) || null;
    }
  }
  const be = beRow ? { ...beRow.result, id: beRow.break_even_id } : null;
  const beInputs = beRow ? beRow.inputs : null;
  const tops = req.result.items.filter((i: any) => i.item_type === "TOP");
  const fixedTotal = be ? be.monthly_fixed_cost : monthlyFixedTotal(userCondition(req, []));   // 반영한 손익분기 비용 우선
  const inv = Number(((beInputs || {}).initial_investment ?? req.initial_investment) || 0);
  const ownerAmt = Number(((beInputs || {}).owner_salary ?? req.owner_salary) || 0);
  const cashFixed = cashMonthly(beInputs, req);
  const reserveMonths = cashFixed > 0 && req.budget > 0 ? Math.max(req.budget - inv, 0) / cashFixed : null;
  const overBudget = req.budget > 0 && inv > req.budget ? inv - req.budget : null;
  const focusItem = { industry_code: code, industry_name: ind.name, risk_grade: focus.risk_grade, pred_annual_rate: focus.pred_annual_rate,
    fixed_zero: fixedTotal <= 0,   // 월 고정비 0원이면 원가율과 상관없이 손익분기 0원
    category: ind.category, location_risk_pct: focus.location_risk_pct, fallback: focus.fallback, confidence: focus.confidence,
    block: entryBlock(st, req, row, code, fixedTotal, ownerAmt), reserve_months: reserveMonths, over_budget: overBudget, investment: inv,
    // 매출 추정이 흔들리는 경우(비교할 구 5곳 미만·대형 점포가 섞인 듯한 매출) — 한줄 결론의 단서
    few_sales_areas: row && ok(row.sales_n) && (row.sales_n as number) < st.p.suitability.min_sales_areas ? row.sales_n : null,
    sales_outlier: salesOutlier(row) };
  const alt = pickAlternative(st, req.area_code, focusItem, tops, req, fixedTotal);
  // 같은 업종의 다른 구: 리포트에 반영한 손익분기의 원가율·기타 수수료로 판단(없으면 분석 조건의 분야별 원가율)
  let altCogs: Record<string, number> = { ...(req.cogs_rates || {}) }, altOther = 0;
  if (beInputs) {
    if (ok(beInputs.cogs_rate)) altCogs = { ...altCogs, [ind.category]: beInputs.cogs_rate };
    altOther = Number(beInputs.other_variable_rate || 0);
  }
  const areaAlt = areaAltOf(st, focus, code, fixedTotal, altCogs, altOther);
  if (areaAlt) areaAlt.owner_included = ownerAmt > 0;       // '월 고정비(목표 월수입 포함)보다 큰' — SB-06 문구와 같게
  const meta: any = {};
  let checklist = buildChecklist(req, focus, row, be, alt, profile, st.snap.area_cards[req.area_code]?.rent_per_3_3m2 ?? null, beInputs,
    st.p.licensed, st.p.registration_notes || {}, areaAlt, meta);
  // 한줄 결론도 체크리스트와 같은 운영자금 기준(6·12개월)과 자격 조건을 쓴다
  (focusItem as any).runway_months = meta.runway_months ?? 6;
  const licNeed = st.p.licensed[code];
  (focusItem as any).license = licNeed && !(req.licenses || []).includes(licNeed) ? licNeed : null;
  const one = oneLiner(focus.area_name, focusItem, alt, be, areaAlt);
  const citeArea = !!areaAlt && one.includes(areaAlt.area_name);
  const citeAlt = !!alt && one.includes(`비슷한 업종인 ${alt.industry_name}`);
  if ((citeArea && !checklist.some((c: any) => c.content.includes(areaAlt.area_name)))
    || (citeAlt && !checklist.some((c: any) => c.action_type === "업종변경"))) {
    // 한줄 결론이 권한 인근 구·비슷한 업종이 체크리스트에 없으면 그 항목을 남겨 다시 만든다
    checklist = buildChecklist(req, focus, row, be, alt, profile, st.snap.area_cards[req.area_code]?.rent_per_3_3m2 ?? null, beInputs,
      st.p.licensed, st.p.registration_notes || {}, areaAlt, null, citeArea, citeAlt);
  }
  const ratio = be ? be.achievability_ratio : null, sales = rowF(row, "sales_ps_m");
  const deficit = (ok(ratio) && ratio < 1) || (!be && sales !== null && sales < fixedTotal);
  const licReq = st.p.licensed[code];
  const lendOk = !((licReq && !(req.licenses || []).includes(licReq)) || focus.fallback || sales === null || focus.risk_grade === "고위험" || !be
    || focusItem.sales_outlier !== null || focusItem.few_sales_areas !== null   // 매출 추정이 흔들리면 대출을 권하지 않는다
    || (ok(focus.location_risk_pct) && focus.location_risk_pct >= 90));         // 주의 업종(입지 위험 상위 10%)
  const policies = matchPolicies(st, req.user_type, ind.category, focus.risk_grade, deficit, lendOk);
  const rep = { public_id: newId(), seq: nextId(s), request_id: req.public_id, industry_code: code, risk_id: focus._risk_id,
    break_even_id: beRow ? beRow.break_even_id : null, one_line_summary: one,
    checklist: checklist.map((it: any) => ({ action_id: nextId(s), ...it, done: false })),     // action_items(완료 표시 포함)
    policy_ids: policies.map((p: any) => p.policy_id), created_at: nowIso(),
    // 지원사업을 고른 근거(report_svc policy_ctx_json과 같은 기록)
    policy_ctx: { category: ind.category, risk_grade: focus.risk_grade, deficit: !!deficit, lend_ok: !!lendOk } };
  s.reports[rep.public_id] = rep;
  return rep;
}
export function getReport(s: StoreData, id: string) {
  const rep = s.reports[id];
  const req = rep ? s.analyses[rep.request_id] : null;
  if (!rep || !req || req.user_id != null) throw new EngineError(404, "REPORT_NOT_FOUND", "리포트를 찾을 수 없어요");
  return { rep, req };
}
/** report_svc._changed_values: 손익분기 입력 중 목록(changed·required)에 든 항목의 값.
 * 10차 이전 기록은 changed에 required가 섞여 있어 '바꾼 값'에서는 required를 뺀다(같은 값이 두 번 나오지 않게) */
const pickInputs = (inp: any, key: string) => {
  const skip = new Set<string>(key === "changed" ? ((inp && inp.required) || []) : []);
  return Object.fromEntries(((inp && inp[key]) || [])
    .filter((k: string) => inp[k] !== null && inp[k] !== undefined && !skip.has(k)).map((k: string) => [k, inp[k]]));
};
/** report_svc._outlier_of: 이 지역·업종 평균 매출이 서울 중간값의 몇 배인지(3배 이상일 때만, 소수 첫째 자리) */
function outlierOf(st: State, area: string, code: string): number | null {
  const r = st.row(area, code);
  const x = r ? salesOutlier(r) : null;
  return x === null ? null : pyRound(x, 1);
}
export function reportOut(st: State, s: StoreData, rep: any, req: any) {
  const ind = st.industries.get(rep.industry_code);
  const risk = s.risks.find((r) => r.risk_id === rep.risk_id) || null;
  const be = rep.break_even_id ? s.breakevens.find((b) => b.break_even_id === rep.break_even_id) : null;
  let rec: any = null;
  const order: Record<string, number> = { TOP: 0, INTEREST: 1, CAUTION: 2 };   // 같은 업종이 여러 목록에 있으면 TOP → 관심 → 주의 순
  for (const d of req.result.items) {
    if (d.industry_code === rep.industry_code && d.item_type in order) {
      if (rec === null || order[d.item_type] < order[rec.item_type]) {
        rec = { item_type: d.item_type, rank: d.rank, suitability: d.suitability, business_goal: req.business_goal,
          eligible: !!d.eligible,
          caution: d.item_type === "CAUTION" || (!!d.eligible && (d.location_risk_pct || 0) >= 90) };   // 관심 업종이어도 주의 업종이면
      }
    }
  }
  const saved = s.saved.find((x) => x.report_id === rep.public_id);          // 이 브라우저가 저장했는지
  const policies = rep.policy_ids.map((pid: number) => st.snap.policies.find((p: any) => p.policy_id === pid)).filter(Boolean)
    .map((p: any) => ({ policy_id: p.policy_id, name: p.name, provider: p.provider, support_type: p.support_type, summary: p.summary,
      apply_url: p.apply_url, target_user: p.target_user, target_region: p.target_region, checked_at: p.checked_at }));
  return {
    id: rep.public_id, analysis_id: req.public_id, created_at: rep.created_at, area_code: req.area_code,
    area_name: st.snap.areas[req.area_code].name, place_name: req.place_name, radius_m: req.radius_meter,
    industry_code: rep.industry_code, industry_name: ind.name, one_line_summary: rep.one_line_summary,
    checklist: rep.checklist.map((it: any) => ({ action_id: it.action_id, action_type: it.action_type, content: it.content,
      priority: it.priority, done: !!it.done })), policies,
    risk: risk ? { risk_score: risk.risk_score, risk_grade: risk.risk_level, pred_annual_rate: risk.pred_annual_rate,
      location_risk_pct: risk.location_risk_pct, location_grade: risk.location_risk_level, confidence: risk.confidence } : null,
    breakeven: be ? { id: be.break_even_id, required_monthly_sales: be.result.required_monthly_sales,
      owner_salary: (be.inputs && be.inputs.owner_salary) || 0,
      required_daily_customers: be.result.required_daily_customers, achievability_ratio: be.result.achievability_ratio,
      cost_pressure: be.result.cost_pressure, monthly_fixed_cost: be.result.monthly_fixed_cost, payback_months: be.result.payback_months,
      sales_outlier: outlierOf(st, req.area_code, rep.industry_code),
      changed: pickInputs(be.inputs, "changed"), entered: pickInputs(be.inputs, "required") } : null,
    recommendation: rec, saved_report_id: saved ? saved.saved_report_id : null, data_quarter_label: quarterLabel(req.data_quarter),
  };
}
export function saveReport(s: StoreData, reportId: string, memo: string | null) {
  getReport(s, reportId);
  const ex = s.saved.find((x) => x.report_id === reportId);
  if (ex) { if (memo !== null && memo !== undefined) ex.memo = memo; return ex; }
  const sr = { saved_report_id: nextId(s), report_id: reportId, memo: memo ?? null, created_at: nowIso() };
  s.saved.push(sr);
  return sr;
}
export function listSaved(st: State, s: StoreData) {
  return s.saved.filter((x) => { const r = s.reports[x.report_id], q = r && s.analyses[r.request_id]; return q && q.user_id == null; })
    .sort((a, b) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : b.saved_report_id - a.saved_report_id))
    .map((sr) => {
      const rep = s.reports[sr.report_id], req = s.analyses[rep.request_id];
      const risk = s.risks.find((r) => r.risk_id === rep.risk_id);
      const be = rep.break_even_id ? s.breakevens.find((b) => b.break_even_id === rep.break_even_id) : null;
      let rc: any = null;
      const order: Record<string, number> = { TOP: 0, INTEREST: 1, CAUTION: 2 };   // report_out과 같은 순서
      for (const it of req.result.items) {
        if (it.industry_code === rep.industry_code && it.item_type in order && (rc === null || order[it.item_type] < order[rc.item_type])) rc = it;
      }
      const suit: number | null = rc ? rc.suitability ?? null : null;
      return { saved_report_id: sr.saved_report_id, report_id: rep.public_id, analysis_id: req.public_id, created_at: sr.created_at,
        area_name: st.snap.areas[req.area_code].name, place_name: req.place_name, industry_code: rep.industry_code,
        industry_name: st.industries.get(rep.industry_code).name, suitability: suit, risk_score: risk ? risk.risk_score : 0,
        risk_grade: risk ? risk.risk_level : "-", memo: sr.memo,
        // 반영한 손익분기 요약 + 체크리스트 진행(같은 지역·업종 카드끼리 구분)
        required_monthly_sales: be ? be.result.required_monthly_sales : null,
        monthly_fixed_cost: be ? be.result.monthly_fixed_cost : monthlyFixedTotal(userCondition(req, [])),
        achievability_ratio: be && be.result.achievability_ratio !== null && be.result.achievability_ratio !== undefined ? be.result.achievability_ratio : null,
        owner_included: be ? Number((be.inputs && be.inputs.owner_salary) || 0) > 0 : Number(req.owner_salary || 0) > 0,
        edited: !!be && ((be.inputs && be.inputs.changed) || []).some((k: string) => !((be.inputs && be.inputs.required) || []).includes(k)),
        business_goal: req.business_goal,
        item_type: rc ? rc.item_type : null, rank: rc ? rc.rank ?? null : null, eligible: rc ? !!rc.eligible : null,
        caution: !!rc && (rc.item_type === "CAUTION" || (!!rc.eligible && (rc.location_risk_pct || 0) >= 90)),
        sales_outlier: be ? outlierOf(st, req.area_code, rep.industry_code) : null,
        checklist_total: rep.checklist.length, checklist_done: rep.checklist.filter((it: any) => it.done).length };
    });
}
/** report_svc.set_item_done: 체크리스트 항목 완료 표시(리포트를 볼 수 있는 사람 = 리포트 주소를 아는 사람) */
export function setItemDone(s: StoreData, reportId: string, actionId: number, done: boolean) {
  const { rep } = getReport(s, reportId);
  const it = rep.checklist.find((x: any) => x.action_id === actionId);
  if (!it) throw new EngineError(404, "ACTION_NOT_FOUND", "체크리스트 항목을 찾을 수 없어요");
  it.done = !!done;
  return { action_id: actionId, done: it.done };
}
export { pyRound };
