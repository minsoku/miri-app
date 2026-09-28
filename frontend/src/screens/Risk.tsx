import { useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { Bar, ErrorBox, Loading, Screen, useAsync, useGoBack, useMounted } from "../components/ui";
import { GRADE_BG, GRADE_COLOR, gradeLabel, josa, pct, won, yearTo } from "../lib/format";
import { reflectedBe, requiredOnlyBe } from "../lib/cache";
import { useApp } from "../state/app";

const cutGrade = (score: number, cuts: number[]) => (score >= cuts[2] ? "고위험" : score >= cuts[1] ? "높음" : score >= cuts[0] ? "보통" : "낮음");

// SB-06 폐업 위험도 (v2: 요인 효과 %, 두 축, 참고 지표)
export default function Risk() {
  const { id = "", code = "" } = useParams();
  const { api, toast } = useApp();
  const nav = useNavigate();
  const goBack = useGoBack();
  const location = useLocation();
  const mounted = useMounted();
  const fromState = (location.state as any)?.from as string | undefined;
  const fromReport = fromState && fromState.startsWith("/report/") ? fromState : null;   // 리포트에서 열었는지
  const reportBe = fromReport ? Number((location.state as any)?.be) || null : null;       // 그 리포트에 반영한 손익분기 계산
  // 리포트에서 열지 않았어도 이 탭에서 '리포트에 반영'한 계산이 있으면 그 비용으로(대응 액션 보기가 같은 리포트를 열게)
  // 반영한 계산도 없으면, 손익분기 화면에서 꼭 넣어야 했던 원가율·객단가만 넣은 계산(대응 액션 보기 리포트와 같은 비용)
  const reflected = fromReport ? null : reflectedBe(id, code);
  const reqOnly = fromReport || reflected ? null : requiredOnlyBe(id, code);
  const costBe = reportBe ?? reflected ?? reqOnly;
  const origin = fromReport ? ((location.state as any)?.origin as string | undefined) : undefined;   // 그 리포트를 연 곳(저장 리포트)
  const backToReport = origin ? { from: origin } : undefined;
  const { data: r, error, status, loading, reload } = useAsync(() => api.risk(id, code, costBe), [id, code, costBe]);
  const [busy, setBusy] = useState(false);

  if (loading) return <Screen title="폐업 위험도" back><Loading /></Screen>;
  if (error || !r) {
    return <Screen title="폐업 위험도" back>
      <ErrorBox message={error || "결과가 없어요"} onRetry={status === 404 ? undefined : reload} /></Screen>;
  }

  const color = GRADE_COLOR[r.risk_grade];
  const maxEff = Math.max(...r.factors.map((f) => Math.abs(f.effect_pct)), 1);
  async function toReport() {
    setBusy(true);
    try {
      // 손익분기 화면에서 '리포트에 반영'하지 않은 가정값은 쓰지 않는다(반영한 계산이 있으면 그것, 없으면 서버가 분석 조건으로 계산)
      const rep = await api.createReport(id, { industry_code: code, ...(costBe ? { break_even_id: costBe } : {}) });
      if (mounted.current) nav(`/report/${rep.id}`);           // 기다리는 동안 다른 화면으로 옮겼으면 끌고 가지 않는다
    } catch (e: any) { toast(e.message); } finally { if (mounted.current) setBusy(false); }
  }
  const b = r.grade_rate_bounds;
  const [c1, c2, c3] = r.grade_cuts;
  const segs: [string, number, number][] = [["낮음", 0, c1], ["보통", c1, c2], ["높음", c2, c3], ["고위험", c3, 100]];
  const topPct = Math.max(1, 100 - r.risk_score);
  const loc = r.location_risk_pct;
  const notices = r.fallback ? r.notices.slice(1) : r.notices;      // 대체 계산 안내는 맨 위에 한 번만
  return (
    <Screen title="폐업 위험도" back={fromReport || `/analysis/${id}`} backState={fromReport ? backToReport : undefined}
      cta={<>
        {/* 리포트에서 연 위험도 → 손익분기의 '뒤로'는 이 화면으로(viaRisk: 기록 뒤로) — 리포트로 건너뛰지 않게 */}
        <button className="btn-secondary" onClick={() => nav(`/analysis/${id}/breakeven/${code}${reportBe ? `?be=${reportBe}` : ""}`,
          fromReport ? { state: { from: fromReport, origin, viaRisk: true } } : undefined)}>손익분기</button>
        {fromReport
          // 리포트에서 열었으면 새 리포트(분석 조건 기준)를 또 만들지 않고 보던 리포트로 돌아간다
          ? <button className="btn-primary" onClick={() => goBack(fromReport, backToReport)}>리포트로 돌아가기</button>
          : <button className="btn-primary" onClick={toReport} disabled={busy}>{busy ? "만드는 중…" : "대응 액션 보기"}</button>}
      </>}>
      <p className="sub">{r.area_name} · {r.industry_name} · {yearTo(r.data_quarter_label)} 데이터</p>
      {r.fallback && (
        <div className="notice warn" style={{ marginBottom: 12 }}><b>이 지역 데이터가 없어요</b>{r.notices[0]}</div>
      )}
      <div className="risk-card" style={{ borderColor: color, background: GRADE_BG[r.risk_grade] }}>
        <div className="between">
          <h2 style={{ fontSize: 19, margin: 0, fontWeight: 800 }}>{r.industry_name}</h2>
          <span className="badge" style={{ background: color, color: "#fff" }}>{gradeLabel(r.risk_grade)}</span>
        </div>
        <div className="risk-num" style={{ color }}>{r.risk_score}</div>
        <div className="muted" style={{ textAlign: "center" }}>폐업 위험 점수 (0~100, 높을수록 위험)</div>
        <div className="gradebar" aria-hidden="true">
          <div className="track" />
          <div className="fill" style={{ width: `${r.risk_score}%`, background: color }} />
          {[c1, c2, c3].map((c) => <i key={c} className="tick" style={{ left: `${c}%` }} />)}
          <div className="labels">
            {segs.map(([g, lo, hi]) => (
              <span key={g} className={g === r.risk_grade ? "on" : ""}
                style={{ left: `${(lo + hi) / 2}%`, ...(g === r.risk_grade ? { color } : {}) }}>{g}</span>
            ))}
          </div>
        </div>
        <div className="kv" style={{ marginTop: 10, borderTop: "1px solid rgba(0,0,0,0.06)" }}>
          <span>향후 1년 예상 폐업률</span><b style={{ color }}>{pct(r.pred_annual_rate)}</b>
        </div>
        {/* 점포 수로 가중한 평균이라 지역·업종 조합의 중간값(등급 '보통' 구간)보다 높다 — '평균인데 높음?' 오해를 막게 밝힌다 */}
        <div className="muted">업종 평균 {pct(r.industry_avg_annual_rate)} · 서울 전 업종 평균 {pct(r.seoul_avg_annual_rate)}</div>
        <div className="muted small" style={{ marginTop: 4 }}>이 지역·업종 전체 점포 기준으로 최근 추세가 이어질 때의 추정치예요(내 가게가 문 닫을 확률이 아니에요).</div>
      </div>

      {r.recheck && (
        <div className="notice warn" style={{ marginTop: 12 }}>
          <b>창업 재검토 권장</b>
          서울 전체 지역·업종 중 위험 상위 {topPct}%예요.
          {r.industry_avg_annual_rate != null && r.seoul_avg_annual_rate != null && r.industry_avg_annual_rate > r.seoul_avg_annual_rate * 1.2
            ? ` ${josa(r.industry_name, "은/는")} 서울 어디서나 폐업률이 높은 업종(업종 평균 ${pct(r.industry_avg_annual_rate)} · 서울 전 업종 ${pct(r.seoul_avg_annual_rate)})이라 등급이 높게 나와요.` : ""}
          {" "}{r.alternatives.length > 0 ? "아래 위험 요인과 인근 지역을 먼저 비교하고" : "아래 위험 요인을 먼저 살펴보고"},
          {fromReport ? " 리포트의 실행 체크리스트를 확인해 보세요." : " ‘대응 액션 보기’에서 실행 체크리스트를 확인해 보세요."}
        </div>
      )}

      <div className="axis2">
        <div className="card">
          <div className="muted">종합 위험</div>
          <div className="row" style={{ alignItems: "baseline" }}><b style={{ fontSize: 24, color }}>{r.risk_score}</b><span className="small" style={{ color }}>{r.risk_grade}</span></div>
          <div className="muted small">서울 모든 업종·지역 중</div>
        </div>
        <div className="card">
          <div className="muted">입지 위험</div>
          {loc == null || !r.location_grade ? (
            <>
              <div className="row" style={{ alignItems: "baseline" }}><b style={{ fontSize: 24 }}>-</b></div>
              <div className="muted small">같은 업종 점포가 없어 비교 못 해요</div>
            </>
          ) : (
            <>
              <div className="row" style={{ alignItems: "baseline" }}><b style={{ fontSize: 24, color: GRADE_COLOR[r.location_grade] }}>{loc}</b>
                <span className="small" style={{ color: GRADE_COLOR[r.location_grade] }}>{r.location_grade}</span></div>
              <div className="muted small">같은 업종끼리 비교</div>
            </>
          )}
        </div>
      </div>
      <p className="muted" style={{ marginTop: 10 }}>{r.summary}</p>

      <h2 className="h2">주요 위험 요인</h2>
      <div className="card">
        <p className="muted" style={{ margin: 0 }}>각 요인이 예상 폐업률을 몇 % 올리는지(+)·내리는지(−)예요. 예: +20%면 그 요인 때문에 폐업률이 약 1.2배가 되는 정도예요.</p>
        {r.factors.length === 0 && <p className="muted">두드러진 요인이 없어요.</p>}
        {r.factors.map((f) => (
          <div className="factor" key={f.factor_code}>
            <div className="between">
              <span style={{ fontWeight: 700 }}>{f.label}</span>
              {/* 서버가 반올림 전 값으로 정한 정수 %(−0.5% → −1%, '−0%' 방지) */}
              <span className={`eff ${f.direction}`}>{f.effect_display > 0 ? "+" : "−"}{Math.abs(f.effect_display)}%</span>
            </div>
            <Bar value={Math.abs(f.effect_pct)} max={maxEff} color={f.direction === "up" ? "var(--red)" : "var(--green)"} />
            <div className="muted small" style={{ marginTop: 4 }}>{f.detail}</div>
          </div>
        ))}
      </div>

      {r.alternatives.length > 0 && (
        <>
          <h2 className="h2">{r.fallback || r.location_risk_pct == null ? "이 업종이 있는 인근 지역"
            : `같은 업종, 입지 위험이 이 지역(${r.location_risk_pct})보다 낮은 인근 지역 (입지 위험 낮은 순)`}</h2>
          <div className="card">
            {r.alternatives.map((x) => (
              <div className="kv alt" key={x.area_code}>
                <span>{x.area_name} <span className="muted">· 구 중심 간 {x.distance_km.toFixed(1)}km</span>
                  <br /><span className="muted small">예상 연 폐업률 {pct(x.pred_annual_rate)} · 종합 {gradeLabel(cutGrade(x.risk_score, r.grade_cuts))}</span>
                  {/* 리포트는 평균 매출로 지금 비용을 감당할 수 있는 곳만 권한다 — 여기서도 그 이유가 보이게 */}
                  {x.affordable === false && x.sales_ps_m != null && (
                    <><br /><span className="small" style={{ color: "var(--amber-text)" }}>평균 매출 {won(x.sales_ps_m)} — {r.affordability_basis !== "report"
                      ? "지금 비용(분석 조건)으로는" : fromReport ? "이 리포트의 비용 기준으로는"
                      : reqOnly && costBe === reqOnly ? "손익분기 화면에서 넣은 값 기준으로는" : "리포트에 반영한 비용 기준으로는"}{" "}
                      {r.affordability_cogs_known === false   // 원가율을 모르면 '매출 ≥ 월 고정비'만 봤다(리포트 한줄 결론의 말과 같게)
                        ? `월 고정비${r.affordability_owner_included ? "(목표 월수입 포함)" : ""}보다 적어요`
                        : `${r.affordability_owner_included ? "필요 매출(목표 월수입 포함)" : "손익분기"}에 못 미쳐요`}</span></>
                  )}
                  {x.sales_outlier != null && x.sales_ps_m != null && (
                    <><br /><span className="small" style={{ color: "var(--amber-text)" }}>평균 매출 {won(x.sales_ps_m)} — 서울 같은 업종 중간값의 {x.sales_outlier.toFixed(1)}배라
                      대형 점포가 섞였을 수 있어요</span></>
                  )}</span>
                <b style={{ color: GRADE_COLOR[x.location_grade], whiteSpace: "nowrap" }}>입지 위험 {x.location_risk_pct} · {x.location_grade}</b>
              </div>
            ))}
          </div>
        </>
      )}

      <h2 className="h2">참고 지표</h2>
      <div className="card">
        <p className="muted" style={{ margin: "0 0 4px" }}>이 지역의 실제 수치예요. 일부는 위 요인 계산에도 쓰였어요.</p>
        {r.reference.length === 0 && <p className="muted">이 지역에는 참고할 수치가 없어요.</p>}
        {r.reference.map((x) => (
          <div className="kv" key={x.key}>
            <span>{x.label}{x.note && <><br /><span className="muted small">{x.note}</span></>}</span><b>{x.display}</b>
          </div>
        ))}
      </div>
      <div className="notice" style={{ marginTop: 14 }}>
        <ul>
          <li>등급은 위험 점수(서울 전체 지역·업종 중 순위)로 정해요: 낮음 0~{c1 - 1} · 보통 {c1}~{c2 - 1} · 높음 {c2}~{c3 - 1} · 고위험 {c3}~100.
            예상 연 폐업률로는 보통이 약 {pct(b["보통"])}, 고위험이 약 {pct(b["고위험"])}부터예요(경계 근처는 반올림으로 달라 보일 수 있어요).</li>
          <li>데이터 신뢰도 {r.confidence}{r.local_data_weight != null && ` · 폐업률은 이 지역 기록 ${Math.round(r.local_data_weight * 100)}%와 서울 같은 업종 평균을 섞어 계산(점포가 적거나 업종의 지역 차가 작을수록 서울 평균 비중이 커요)`}</li>
          {notices.map((n) => <li key={n}>{n}</li>)}
        </ul>
      </div>
    </Screen>
  );
}
