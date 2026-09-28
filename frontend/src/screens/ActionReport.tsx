import { useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ErrorBox, IconCheck, Loading, Screen, useAsync } from "../components/ui";
import { analysisCache } from "../lib/cache";
import { canPersist } from "../lib/storage";
import { draftFrom } from "../lib/draftFrom";
import { dateDot, GRADE_COLOR, gradeLabel, manwon, pct, PRESSURE_COLOR, ratioText, withComma, won, yearTo } from "../lib/format";
import { useApp } from "../state/app";

/** 손익분기 입력 항목 → 화면 표시(리포트의 '바꾼 값 기준' 줄) */
const CHANGED_LABEL: Record<string, string> = { monthly_rent: "월 임대료", labor_cost: "월 인건비", other_fixed: "기타 고정비",
  initial_investment: "초기 투자비", loan_amount: "대출금", loan_rate_annual: "연이율", owner_salary: "목표 월수입",
  cogs_rate: "원가율", other_variable_rate: "배달·기타 수수료", avg_ticket: "객단가" };
function changedText(k: string, v: number): string {
  const label = CHANGED_LABEL[k] || k;
  if (k === "avg_ticket") return `${label} ${Math.round(v).toLocaleString()}원`;
  if (k === "loan_rate_annual" || k === "cogs_rate" || k === "other_variable_rate") return `${label} ${pct(v, k === "loan_rate_annual" ? 2 : 1)}`;
  return `${label} ${won(v)}`;
}

const goalLabel = (g?: string | null) => (!g ? "" : g === "기본" ? "균형" : g);
// SB-08 액션 리포트
export default function ActionReport() {
  const { rid = "" } = useParams();
  const { api, toast, resetDraft, setDraft, industries } = useApp();
  const nav = useNavigate();
  const loc = useLocation();
  const { data: rep, error, status, loading, reload, setData } = useAsync(() => api.getReport(rid), [rid]);
  const [reusing, setReusing] = useState(false);
  async function reanalyze() {
    if (!rep) return;
    setReusing(true);
    try {
      const a = analysisCache.get(rep.analysis_id) || await api.getAnalysis(rep.analysis_id);
      // 이 리포트가 쓴 값으로: 손익분기 화면에서 바꾸거나 직접 넣은 값(임대료·인건비·원가율 등)을 분석 조건 위에 덮는다
      const d = draftFrom(a);
      const ch: Record<string, number> = { ...(rep.breakeven?.changed || {}), ...(rep.breakeven?.entered || {}) };
      const mw = (x: number) => withComma(manwon(x));
      const money: [string, "rent" | "labor" | "otherFixed" | "investment" | "loan" | "ownerSalary"][] = [["monthly_rent", "rent"],
        ["labor_cost", "labor"], ["other_fixed", "otherFixed"], ["initial_investment", "investment"], ["loan_amount", "loan"],
        ["owner_salary", "ownerSalary"]];
      for (const [k, f] of money) if (ch[k] != null) (d as any)[f] = mw(ch[k]);
      if (ch.loan_rate_annual != null) d.loanRate = String(Math.round(ch.loan_rate_annual * 10000) / 100);
      const cat = industries?.industries.find((i) => i.code === rep.industry_code)?.category;
      if (ch.cogs_rate != null && cat) d.cogs = { ...(d.cogs || {}), [cat]: String(Math.round(ch.cogs_rate * 1000) / 10) };
      setDraft(d); nav("/conditions");
      // 조건 화면에 없는 값(배달·기타 수수료, 객단가)은 옮길 수 없다 — 사라진 것처럼 보이지 않게 알린다
      if (ch.other_variable_rate != null || ch.avg_ticket != null) toast("배달·기타 수수료와 객단가는 손익분기 화면에서 다시 넣어 주세요");
    } catch (e: any) { toast(e.message); } finally { setReusing(false); }
  }
  const [saving, setSaving] = useState(false);

  /** 로그인 없이 바로 이 브라우저의 저장 목록에 넣는다(서버는 브라우저 저장 키로 구분) */
  async function doSave() {
    if (!rep || saving) return;
    setSaving(true);
    try {
      const r = await api.saveReport(rep.id, null);
      // 응답을 기다리는 사이 다른 리포트로 옮겼으면 그 화면은 건드리지 않는다(지금 보이는 리포트가 이 리포트일 때만)
      setData((cur) => (cur.id !== rep.id ? cur : { ...cur, saved_report_id: r.saved_report_id }));
      toast(canPersist() ? "리포트를 저장했어요" : "저장했어요 — 이 브라우저는 새로고침하면 저장 목록이 사라져요");
    } catch (e: any) { toast(e.message); } finally { setSaving(false); }
  }

  const fromSaved = (loc.state as any)?.from === "/reports";            // 저장 리포트에서 열었으면 뒤로가기도 그쪽으로
  const fromBe = !!(loc.state as any)?.fromBe;                         // 손익분기의 '리포트에 반영'으로 왔으면 뒤로는 손익분기(기록)
  /** 체크리스트 완료 표시: 서버에 저장(다시 열어도 유지). 실패하면 알리고 서버 값으로 되돌린다 */
  async function toggle(actionId: number, next: boolean) {
    if (!rep) return;
    setData((cur) => (cur.id !== rep.id ? cur
      : { ...cur, checklist: cur.checklist.map((x) => (x.action_id === actionId ? { ...x, done: next } : x)) }));
    try { await api.setItemDone(rep.id, actionId, next); } catch (e: any) { toast(e.message); reload(); }
  }
  if (loading) return <Screen title="액션 리포트" back={fromSaved ? "/reports" : true}><Loading /></Screen>;
  if (error || !rep) {
    return (
      <Screen title="액션 리포트" back={fromSaved ? "/reports" : true}>
        <ErrorBox message={error || "리포트가 없어요"} onRetry={status === 404 ? undefined : reload} actions={
          <button className="btn-small" onClick={() => { resetDraft(); nav("/area"); }}>새 분석 시작</button>} />
      </Screen>
    );
  }
  // SB-05 머리말과 같은 모양(장소 → 분석한 구) — 장소 주변에서 다른 구를 골랐을 때 장소가 그 구에 있는 것처럼 읽히지 않게
  const where = rep.place_name && !["지도에서 고른 위치", rep.area_name].includes(rep.place_name) ? `${rep.place_name} 주변 → ` : "";
  const ownerOn = (rep.breakeven?.owner_salary || 0) > 0;
  return (
    <Screen title="액션 리포트" back={fromSaved ? "/reports" : fromBe ? true : `/analysis/${rep.analysis_id}/risk/${rep.industry_code}`}
      cta={rep.saved_report_id
        ? <button className="btn-primary" onClick={() => nav("/reports")}>저장 리포트 보기</button>
        : <button className="btn-primary" onClick={doSave} disabled={saving}>{saving ? "저장 중…" : "리포트 저장"}</button>}>
      <p className="sub">{where}{rep.area_name}(구 전체 기준) · {rep.industry_name}</p>
      {(rep.recommendation || rep.risk?.risk_grade === "고위험") && (
        <p className="muted small" style={{ margin: "-6px 0 10px" }}>
          {rep.recommendation && <>
            {rep.recommendation.item_type === "TOP" ? `추천 ${rep.recommendation.rank}위 업종`
              : rep.recommendation.caution ? `주의 업종(같은 업종 중 입지 위험 상위 10%, 추천 TOP 제외)${rep.recommendation.item_type === "INTEREST" ? " · 내 관심 업종" : ""}`
              : rep.recommendation.eligible === false ? "내 관심 업종(추천 제외)" : "내 관심 업종(추천 TOP 밖)"}
            {rep.recommendation.suitability != null ? ` · 적합도 ${Math.round(rep.recommendation.suitability)}` : ""}
            {rep.recommendation.business_goal && rep.recommendation.suitability != null ? ` (${goalLabel(rep.recommendation.business_goal)} 기준)` : ""}
          </>}
          {rep.risk?.risk_grade === "고위험" ? `${rep.recommendation ? " · " : ""}종합 위험 고위험 — 재검토 권장` : ""}
        </p>
      )}
      {rep.recommendation?.eligible && rep.breakeven?.achievability_ratio != null && rep.breakeven.achievability_ratio < 1 && (
        // 추천 순위는 분석 조건(원가율을 넣지 않은 분야는 '매출 ≥ 월 고정비'만)으로 매겼다 — 아래 '위험 0.68배'와 모순처럼 보이지 않게
        <p className="small" style={{ margin: "-4px 0 10px", color: "var(--amber-text)" }}>
          {rep.recommendation.item_type === "TOP" ? "추천 순위·적합도는" : "적합도는"} 분석할 때의 조건으로 낸 값이에요 — 이 손익분기 계산으로는 평균 매출이 {ownerOn ? "필요 매출(목표 월수입 포함)" : "손익분기"}에 못 미쳐요.</p>
      )}
      <div className="ai-card">
        <span className="badge solid-blue">한줄 결론</span>
        <p>{rep.one_line_summary}</p>
      </div>
      <div className="axis2">
        {rep.risk && (
          <button className="card" style={{ textAlign: "left" }}
            onClick={() => nav(`/analysis/${rep.analysis_id}/risk/${rep.industry_code}`,
              // 위험도 화면의 '손익분기'도 이 리포트에 반영한 계산을 열도록 id를, 돌아올 때를 위해 이 리포트를 연 곳(origin)을 넘긴다
              { state: { from: `/report/${rep.id}`, be: rep.breakeven?.id ?? null, origin: fromSaved ? "/reports" : undefined } })}>
            <div className="muted">폐업 위험</div>
            <b style={{ fontSize: 22, color: GRADE_COLOR[rep.risk.risk_grade] }}>{rep.risk.risk_score}</b>
            <span className="small" style={{ color: GRADE_COLOR[rep.risk.risk_grade] }}> {gradeLabel(rep.risk.risk_grade)}</span>
          </button>
        )}
        <button className="card" style={{ textAlign: "left" }}
          onClick={() => nav(`/analysis/${rep.analysis_id}/breakeven/${rep.industry_code}${rep.breakeven ? `?be=${rep.breakeven.id}` : ""}`,
            { state: { from: `/report/${rep.id}`, origin: fromSaved ? "/reports" : undefined } })}>
          <div className="muted">{ownerOn ? "필요 월매출(목표 월수입 포함)" : "손익분기 월매출"}</div>
          {rep.breakeven ? <b style={{ fontSize: 20 }}>{won(rep.breakeven.required_monthly_sales)}</b> : <span className="btn-text">계산하기 →</span>}
          {rep.breakeven?.cost_pressure && rep.breakeven.achievability_ratio != null && (   // 고정비 0원이면 배율이 없어 SB-07처럼 숨긴다
            <div className="small" style={{ color: PRESSURE_COLOR[rep.breakeven.cost_pressure] }}>
              달성 가능성 {rep.breakeven.cost_pressure}
              {rep.breakeven.achievability_ratio != null && ` · 평균 매출이 ${ownerOn ? "필요 매출(목표 월수입 포함)" : "손익분기"}의 ${ratioText(rep.breakeven.achievability_ratio)}`}
              {rep.breakeven.sales_outlier != null && <span className="muted"> · 대형 점포 가능(참고용)</span>}
            </div>
          )}
        </button>
      </div>

      {rep.breakeven && (Object.keys(rep.breakeven.changed || {}).length > 0 || Object.keys(rep.breakeven.entered || {}).length > 0) && (
        // 손익분기 화면에서 바꾼 값(분석 조건과 다름)·직접 넣은 값(기본값이 없던 원가율·객단가)을 밝힌다 — 추천 결과 화면의 배율과 다른 이유
        <p className="muted small" style={{ margin: "8px 0 0" }}>
          {Object.keys(rep.breakeven.changed || {}).length > 0 ? "손익분기 화면에서 바꾼 값 기준" : "손익분기 화면에서 넣은 값 기준"}:{" "}
          {[...Object.entries(rep.breakeven.changed || {}).map(([k, v]) => changedText(k, Number(v))),
            ...Object.entries(rep.breakeven.entered || {}).map(([k, v]) => `${changedText(k, Number(v))}(직접 입력)`)].join(" · ")}
        </p>
      )}

      <h2 className="h2">실행 체크리스트</h2>
      <div className="card">
        {rep.checklist.length === 0 && <p className="muted" style={{ margin: 0 }}>지금 조건에서 따로 챙길 항목이 없어요.</p>}
        {rep.checklist.map((c) => (
          <button key={c.action_id} className={`check${c.done ? " done" : ""}`} aria-pressed={c.done}
            onClick={() => toggle(c.action_id, !c.done)}>
            <i><IconCheck /></i>
            <span className="grow"><span className="t">{c.action_type}</span><br /><span className="c">{c.content}</span></span>
          </button>
        ))}
      </div>

      <h2 className="h2">연결 가능한 지원사업</h2>
      {rep.policies.length === 0 && <div className="notice">조건에 맞는 지원사업이 없어요. 기업마당(bizinfo.go.kr)에서 최신 공고를 확인해 보세요.</div>}
      {rep.policies.map((p) => (
        <div className="card between" key={p.policy_id}>
          <div className="grow">
            <b>{p.name}</b>
            <div className="muted small">{p.provider} · {p.support_type}{p.target_user && p.target_user !== "전체" ? ` · ${p.target_user} 대상` : ""}</div>
            {p.summary && <div className="small" style={{ color: "var(--text-2)", marginTop: 4 }}>{p.summary}</div>}
            {p.support_type === "재기지원" && (
              <div className="small" style={{ color: "var(--amber-text)", marginTop: 4 }}>지금 운영 중인 가게를 정리하고 업종을 바꿔 다시 시작하려는 경우에 해당해요.</div>
            )}
          </div>
          {p.apply_url && <a className="btn-small" style={{ display: "grid", placeItems: "center" }} href={p.apply_url} target="_blank"
            rel="noopener noreferrer" aria-label={`${p.name} 신청 (새 창)`}>신청</a>}
        </div>
      ))}
      <p className="muted small" style={{ marginTop: 10 }}>
        지원 조건·기간은 신청 전 공고를 꼭 확인하세요{rep.policies[0]?.checked_at ? ` (정보 확인 ${dateDot(rep.policies[0].checked_at)})` : ""}.
        분석 데이터: 서울시 상권분석서비스 {yearTo(rep.data_quarter_label)}(매출은 카드 매출 기준 추정치) · 예상 폐업률은 이 지역·업종 전체 점포 기준으로
        최근 추세가 이어질 때의 추정치예요.
      </p>
      {/* 저장한 시나리오를 조금 바꿔 보고 싶을 때: 이 리포트의 분석 조건을 입력 화면에 되살린다 */}
      <button className="btn-text" style={{ marginTop: 6 }} disabled={reusing} onClick={reanalyze}>
        {reusing ? "조건 불러오는 중…" : "이 조건으로 다시 분석 →"}</button>
    </Screen>
  );
}
