// 백엔드 app/schemas.py 와 1:1 대응. 금액 단위는 원(KRW).
export type Role = "PRE_FOUNDER" | "OWNER" | "CONSULTANT";
export type Goal = "기본" | "안정형" | "고수익형" | "저비용형";
export type Grade = "낮음" | "보통" | "높음" | "고위험";

export interface Meta {
  data_quarter: number; data_quarter_label: string; model_version: string; trained_at: string;
  analysis_level: "district" | "trade_area"; grade_cuts: number[]; grade_rate_bounds: Record<string, number>;
  goals: Record<string, { D: number; S: number; F: number }>; notices: string[];
}

export interface Place {
  name: string; kind: string; lat: number; lng: number; area_code?: string | null; area_name?: string | null;
  address?: string | null; source: "local" | "kakao";
}
export interface AreaMetrics {
  floating_daily?: number | null; resident_population?: number | null; working_population?: number | null;
  store_count?: number | null; rent_per_3_3m2?: number | null; rent_level?: string | null; change_name?: string | null;
  avg_open_months?: number | null; avg_closed_months?: number | null; quarter_label?: string | null;
}
export interface AreaCard {
  area_code: string; area_name: string; level: string; is_center: boolean; distance_m: number;
  lat?: number | null; lng?: number | null; metrics: AreaMetrics;
}
export interface Candidates {
  lat: number; lng: number; radius_m: number; place_name?: string | null; analysis_level: string;
  notice?: string | null; candidates: AreaCard[];
}
export interface MapData {
  type: "FeatureCollection";
  features: { type: "Feature"; properties: { code: string; name: string; lat: number; lng: number };
    geometry: { type: "Polygon" | "MultiPolygon"; coordinates: any } }[];
  places?: { name: string; kind: string; lat: number; lng: number }[];
}

/** UC-02 상권 비교(POST /areas/compare) */
export interface CompareArea extends AreaCard {
  summary: { avg_risk_score?: number | null; high_risk_share?: number | null };
  industry?: { risk_score: number; risk_grade: Grade; location_risk_pct: number; pred_annual_rate: number;
    sales_ps_m?: number | null; sales_outlier?: number | null; demand_D?: number | null; stores_avg: number } | null;
}
export interface CompareOut { industry_code?: string | null; industry_name?: string | null; data_quarter: number; areas: CompareArea[] }

export interface IndustryGroup { group: string; color: string; codes: string[]; names: string[] }
export interface Industry {
  code: string; name: string; category: string; has_sales_data: boolean; license?: string | null;
  display_group?: string | null;
  recommendable?: boolean;      // 추천 대상이 될 수 있는지(카드 매출이 있는 지역 5곳 이상) — SB-03 자격 칩
}
export interface Industries { groups: IndustryGroup[]; industries: Industry[] }

export interface AnalysisIn {
  area_code: string; place_name?: string | null; lat?: number | null; lng?: number | null; radius_m?: number | null;
  candidate_area_codes?: string[]; user_type?: Role;
  budget: number; monthly_rent_limit: number; labor_cost: number; initial_investment?: number; other_fixed?: number;
  loan_amount?: number; loan_rate_annual?: number; owner_salary?: number; business_goal?: Goal;
  licenses?: string[]; categories?: string[]; excluded_industries?: string[]; interests?: string[];
  cogs_rates?: Record<string, number>;                  // 분야별 원가율(선택, 0~1)
}
export interface PeakFlag { code: string; pill: string; share: number; action: string }
export interface Item {
  industry_code: string; industry_name: string; category: string; display_group?: string | null;
  item_type: "TOP" | "INTEREST" | "CAUTION"; rank?: number | null; suitability?: number | null; score_note?: string | null;
  scores: { D?: number | null; S?: number | null; F?: number | null };
  risk_score: number; risk_grade: Grade; location_risk_pct: number; location_grade: Grade; pred_annual_rate: number;
  sales_ps_m?: number | null; avg_ticket?: number | null; stores_avg?: number | null; confidence: string;
  achievability_ratio?: number | null; eligible: boolean; ineligible_reason?: string | null;
  reason: string; reason_short: string; chips: string[]; caution: string; cautions: string[]; peak: PeakFlag[];
}
export interface Analysis {
  id: string; created_at: string;
  missing_interests?: { industry_code: string; industry_name: string }[];
  area: { area_code: string; area_name: string; level: string; place_name?: string | null; radius_m?: number | null;
    lat?: number | null; lng?: number | null; scope_note?: string | null; candidate_area_codes?: string[] };
  conditions: Record<string, any>; data_quarter: number; data_quarter_label: string; model_version: string;
  business_goal: Goal; weights: { D: number; S: number; F: number }; f_applied: boolean; f_note?: string | null;
  n_candidates: number; n_low_score?: number; empty_reason?: string | null; top: Item[]; interests: Item[]; cautions: Item[]; notices: string[];
}

export interface Factor {
  factor_code: string; factor_name: string; label: string; effect_pct: number; effect_display: number;
  direction: "up" | "down"; explanation: string; detail: string;
}
export interface Reference { key: string; label: string; value?: number | null; display: string; note?: string | null }
export interface Alternative {
  area_code: string; area_name: string; location_risk_pct: number; location_grade: Grade; risk_score: number;
  pred_annual_rate: number; distance_km: number; sales_ps_m?: number | null; affordable?: boolean | null;
  sales_outlier?: number | null;      // 점포당 매출 ÷ 서울 같은 업종 중간값(3배 이상일 때만 — 대형 점포 가능, affordable은 null)
}
export interface Risk {
  analysis_id: string; area_code: string; area_name: string; industry_code: string; industry_name: string;
  category: string; data_quarter: number; data_quarter_label: string; model_version: string; risk_score: number; risk_grade: Grade;
  pred_annual_rate: number; industry_avg_annual_rate?: number | null; seoul_avg_annual_rate?: number | null;
  location_risk_pct: number | null; location_grade: Grade | null; confidence: string; local_data_weight?: number | null;
  grade_cuts: number[]; grade_rate_bounds: Record<string, number>; summary: string; factors: Factor[];
  reference: Reference[]; raw: Record<string, number | null>; alternatives: Alternative[]; recheck: boolean;
  fallback: boolean; notices: string[];
  affordability_basis?: "analysis" | "report";     // 인근 지역 affordable 판단 비용: 분석 조건 / 리포트에 반영한 손익분기
  affordability_cogs_known?: boolean;               // 판단에 원가율을 썼는지(모르면 평균 매출 ≥ 월 고정비만)
  affordability_owner_included?: boolean;           // 판단 비용에 목표 월수입이 들어 있는지
}

export interface BreakEvenIn {
  industry_code: string; monthly_rent?: number; labor_cost?: number; other_fixed?: number; initial_investment?: number;
  loan_amount?: number; loan_rate_annual?: number; owner_salary?: number; cogs_rate?: number;
  other_variable_rate?: number; avg_ticket?: number;
}
export interface BreakEven {
  id: number; analysis_id: string; area_code: string; area_name: string; industry_code: string; industry_name: string; category: string;
  inputs: Record<string, any>; monthly_fixed_cost: number; fixed_breakdown: Record<string, number>;
  variable_cost_rate: number; variable_breakdown: Record<string, number>; contribution_margin_rate: number;
  required_monthly_sales: number; required_daily_sales: number; required_daily_customers: number;
  avg_ticket_used: number; operating_days: number; market_sales_ps_m?: number | null;
  achievability_ratio?: number | null; cost_pressure?: string | null; profit_at_market_avg?: number | null;
  payback_months?: number | null; market_tx_ps_day?: number | null; customers_vs_market?: number | null;
  max_fixed_for_bep?: number | null;
  composition: { fixed_ex_owner: number; variable: number; owner_salary: number; total: number };
  warnings: string[];
  sales_outlier?: number | null;      // 이 지역 평균 매출 ÷ 서울 같은 업종 중간값(3배 이상일 때만 — 배율은 참고용)
}

export interface Action { action_id: number; action_type: string; content: string; priority: number; done: boolean }
export interface Policy {
  policy_id: number; name: string; provider?: string | null; support_type: string; summary?: string | null;
  apply_url?: string | null; target_user: string; target_region: string; checked_at?: string | null;
}
export interface Report {
  id: string; analysis_id: string; created_at: string; area_code: string; area_name: string;
  place_name?: string | null; radius_m?: number | null; industry_code: string; industry_name: string;
  one_line_summary: string; checklist: Action[]; policies: Policy[];
  risk: { risk_score: number; risk_grade: Grade; pred_annual_rate: number; location_risk_pct: number | null;
    location_grade: Grade | null; confidence: string } | null;
  breakeven: { id: number; required_monthly_sales: number; required_daily_customers: number; owner_salary?: number;
    achievability_ratio?: number | null; cost_pressure?: string | null; monthly_fixed_cost: number;
    payback_months?: number | null; changed?: Record<string, number>; entered?: Record<string, number>;
    sales_outlier?: number | null } | null;
  recommendation: { item_type: string; rank?: number | null; suitability?: number | null; business_goal?: string | null;
    caution?: boolean; eligible?: boolean } | null;
  saved_report_id?: number | null; data_quarter_label: string;
}
export interface SavedItem {
  saved_report_id: number; report_id: string; analysis_id: string; created_at: string; area_name: string;
  place_name?: string | null; industry_code: string; industry_name: string; suitability?: number | null;
  risk_score: number; risk_grade: Grade | "-"; memo?: string | null;
  required_monthly_sales?: number | null; monthly_fixed_cost?: number | null; achievability_ratio?: number | null; owner_included?: boolean; edited?: boolean;
  checklist_total?: number; checklist_done?: number;
  business_goal?: string | null; sales_outlier?: number | null;
  item_type?: string | null; rank?: number | null; eligible?: boolean | null; caution?: boolean;
}

export interface ApiErrorBody { code: string; message: string; fields?: { field: string; message: string }[] }
export class ApiError extends Error {
  status: number; code: string; fields: { field: string; message: string }[];
  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.status = status; this.code = body.code; this.fields = body.fields || [];
  }
}

// 화면이 쓰는 API 전체. 실서버(HttpApi)와 데모(DemoApi)가 같은 인터페이스를 구현한다.
export interface Api {
  mode: "server" | "demo";
  meta(): Promise<Meta>;
  industries(): Promise<Industries>;
  searchPlaces(q: string): Promise<Place[]>;
  candidates(lat: number, lng: number, radius_m: number, place_name?: string | null): Promise<Candidates>;
  areaCard(code: string): Promise<AreaCard>;          // 한 지역의 기본 지표(조건 화면 임대료 안내 등)
  areaMap(): Promise<MapData>;
  compareAreas(area_codes: string[], industry_code?: string | null): Promise<CompareOut>;
  createAnalysis(body: AnalysisIn): Promise<Analysis>;
  getAnalysis(id: string): Promise<Analysis>;
  risk(id: string, code: string, be?: number | null): Promise<Risk>;
  breakeven(id: string, body: BreakEvenIn): Promise<BreakEven>;
  getBreakeven(id: string, breakEvenId: number): Promise<BreakEven>;
  createReport(id: string, body: { industry_code: string; break_even_id?: number | null }): Promise<Report>;
  getReport(id: string): Promise<Report>;
  // 저장 리포트: 로그인 대신 이 브라우저로 구분한다(서버는 X-Device-Key 헤더, 데모는 이 브라우저의 저장소)
  saveReport(report_id: string, memo?: string | null): Promise<{ saved_report_id: number; report_id: string }>;
  myReports(): Promise<{ count: number; items: SavedItem[] }>;
  deleteSaved(saved_report_id: number, report_id?: string): Promise<void>;
  deleteAllSaved(): Promise<{ deleted: number }>;      // 이 브라우저의 저장 목록 모두 지우기(공용 컴퓨터 정리)
  updateMemo(saved_report_id: number, report_id: string, memo: string | null): Promise<{ saved_report_id: number; memo: string | null }>;
  setItemDone(report_id: string, action_id: number, done: boolean): Promise<{ action_id: number; done: boolean }>;
}
