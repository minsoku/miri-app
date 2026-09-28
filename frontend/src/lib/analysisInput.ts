import type { AnalysisIn, Industries, Role } from "../api";
import type { Draft } from "../state/app";
import { fromManwon } from "./format";

export function categoriesOf(codes: string[], ind: Industries | null): string[] {
  const byCode = new Map((ind?.industries || []).map((i) => [i.code, i.category]));
  return Array.from(new Set(codes.map((c) => byCode.get(c)).filter(Boolean))) as string[];
}

export function buildAnalysisInput(d: Draft, role: Role, ind: Industries | null): AnalysisIn {
  if (!d.area) throw new Error("상권을 먼저 골라 주세요");
  return {
    area_code: d.area.area_code,
    place_name: d.place?.name ?? null,
    lat: d.place?.lat ?? null,
    lng: d.place?.lng ?? null,
    radius_m: d.radius,
    candidate_area_codes: d.candidateCodes,
    user_type: role,
    budget: fromManwon(d.budget),
    monthly_rent_limit: fromManwon(d.rent),
    labor_cost: fromManwon(d.labor),
    initial_investment: fromManwon(d.investment),
    other_fixed: fromManwon(d.otherFixed),
    owner_salary: fromManwon(d.ownerSalary),
    loan_amount: fromManwon(d.loan),
    loan_rate_annual: Math.round(Number(d.loanRate || 0) * 100) / 10000,
    business_goal: d.goal,
    licenses: d.licenses,
    interests: d.interests,
    categories: d.sameCategoryOnly && d.interests.length ? categoriesOf(d.interests, ind) : [],
    cogs_rates: cogsRates(d.cogs),
  };
}

/** 분야별 원가율 입력(%) → 0~1 (빈 칸은 보내지 않음) */
export function cogsRates(c: Record<string, string> | undefined): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(c || {})) {
    const t = (v || "").trim();
    if (!t) continue;
    const n = Number(t);
    if (Number.isFinite(n)) out[k] = Math.round(n * 10) / 1000;           // 소수 첫째 자리 %까지(40.7% → 0.407)
  }
  return out;
}
