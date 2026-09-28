import type { Analysis } from "../api";
import type { Draft } from "../state/app";
import { manwon, withComma } from "./format";

/** 이 분석의 조건으로 입력 초안을 되살린다(새 탭·저장 리포트에서 열어 초안이 비었을 때 '조건 바꿔 다시 분석'용) */
export function draftFrom(a: Analysis): Partial<Draft> {
  // 입력칸과 같은 모양(천 단위 쉼표)으로 되살린다 — 직접 넣은 값은 '10,000'인데 복원한 값만 '15000'으로 보이지 않게
  const c = a.conditions || {}, m = (x: any) => (x ? withComma(manwon(x)) : "");
  const hasPt = a.area.lat != null && a.area.lng != null;
  return {
    place: hasPt ? { name: a.area.place_name || a.area.area_name, lat: a.area.lat as number, lng: a.area.lng as number } : null,
    radius: a.area.radius_m || 500,
    area: { area_code: a.area.area_code, area_name: a.area.area_name, level: a.area.level, is_center: true, distance_m: 0,
      lat: a.area.lat ?? null, lng: a.area.lng ?? null, metrics: {} as any },
    // SB-02에서 후보로 보였던 구도 되살린다(다시 분석해도 인근 지역 대안이 같게)
    candidateCodes: [a.area.area_code, ...(a.area.candidate_area_codes || []).filter((c) => c !== a.area.area_code)],
    budget: withComma(manwon(c.budget ?? 0)), rent: withComma(manwon(c.monthly_rent_limit ?? 0)), labor: withComma(manwon(c.labor_cost ?? 0)),
    investment: m(c.initial_investment), otherFixed: m(c.other_fixed), ownerSalary: m(c.owner_salary), loan: m(c.loan_amount),
    loanRate: c.loan_rate_annual ? String(Math.round(c.loan_rate_annual * 10000) / 100) : "",
    goal: a.business_goal, licenses: c.licenses || [],
    interests: [...a.interests.map((i) => i.industry_code), ...(a.missing_interests || []).map((i) => i.industry_code)],
    // 자동 추천(관심 업종 없음)으로 만든 분석이면 새로 시작할 때처럼 켠 채로(관심 업종을 고르면 그 분야 안에서)
    sameCategoryOnly: (c.categories || []).length > 0 || a.interests.length + (a.missing_interests || []).length === 0,
    cogs: Object.fromEntries(Object.entries(c.cogs_rates || {}).map(([k, v]) => [k, String(Math.round(Number(v) * 1000) / 10)])),
  };
}
