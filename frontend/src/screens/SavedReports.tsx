import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { SavedItem } from "../api";
import { ErrorBox, Loading, Screen, Sheet, useAsync } from "../components/ui";
import { dateDot, GRADE_COLOR, gradeLabel, ratioText, won } from "../lib/format";
import { canPersist, load, remove } from "../lib/storage";
import { LEGACY_NOTICE, useApp } from "../state/app";

// SB-09 저장 리포트 — 로그인 없이 이 브라우저에 저장한 리포트(서버는 브라우저 저장 키로 구분)
export default function SavedReports() {
  const { api, resetDraft, forgetThisTab, toast } = useApp();
  const nav = useNavigate();
  const loc = useLocation();
  const fromStart = (loc.state as any)?.from === "/";                  // 시작 화면에서 열었으면 뒤로가기도 그쪽으로
  const { data, error, loading, reload } = useAsync(() => api.myReports(), []);
  const [memoFor, setMemoFor] = useState<SavedItem | null>(null);
  const [delFor, setDelFor] = useState<SavedItem | null>(null);
  const [delBusy, setDelBusy] = useState(false);
  const [legacy, setLegacy] = useState(() => load<boolean>(LEGACY_NOTICE, false) === true);
  const [wipeOpen, setWipeOpen] = useState(false);
  const [wipeBusy, setWipeBusy] = useState(false);
  // 되돌릴 수 없는 삭제 확인은 '취소'에 먼저 포커스(Enter 한 번에 지워지지 않게)
  useEffect(() => { if (delFor) requestAnimationFrame(() => document.getElementById("del-cancel")?.focus()); }, [delFor]);
  useEffect(() => { if (wipeOpen) requestAnimationFrame(() => document.getElementById("wipe-cancel")?.focus()); }, [wipeOpen]);
  const [memo, setMemo] = useState("");
  const [memoBusy, setMemoBusy] = useState(false);
  const cta = <button className="btn-primary" onClick={() => { resetDraft(); nav("/area"); }}>새 분석 시작</button>;

  // 확인은 브라우저 confirm() 대신 시트로 — 샌드박스(iframe) 안에서는 confirm()이 무시돼 삭제가 되지 않는다
  async function del() {
    if (!delFor) return;
    setDelBusy(true);
    try {
      await api.deleteSaved(delFor.saved_report_id, delFor.report_id); setDelFor(null); toast("삭제했어요"); reload();
      requestAnimationFrame(() => document.querySelector<HTMLElement>(".topbar h1")?.focus());   // 지운 카드 대신 화면 제목으로
    } catch (e: any) {
      toast(e.message);
      if (e?.status === 404) {                                     // 다른 탭에서 이미 지웠으면 목록을 새로 불러온다
        setDelFor(null); reload(); requestAnimationFrame(() => document.querySelector<HTMLElement>(".topbar h1")?.focus());
      }
    } finally { setDelBusy(false); }
  }
  /** 이 브라우저의 저장 목록을 모두 지운다 — 로그인이 없으니 공용 컴퓨터를 다 쓴 뒤 로그아웃 대신 */
  async function wipe() {
    setWipeBusy(true);
    try {
      const r = await api.deleteAllSaved();
      forgetThisTab();                                   // 다음 사람이 이 탭의 입력값·결과를 이어 보지 않게(로그아웃이 하던 정리)
      setWipeOpen(false); toast(r.deleted ? "저장 목록을 모두 지웠어요" : "지울 리포트가 없어요"); reload();
      requestAnimationFrame(() => document.querySelector<HTMLElement>(".topbar h1")?.focus());
    } catch (e: any) { toast(e.message); } finally { setWipeBusy(false); }
  }
  async function saveMemo() {
    if (!memoFor) return;
    setMemoBusy(true);
    try {
      // 메모만 고친다 — 다른 탭에서 이미 지운 항목이면 다시 저장하지 않고 404(목록을 새로 불러온다)
      await api.updateMemo(memoFor.saved_report_id, memoFor.report_id, memo.trim() || null);
      setMemoFor(null); toast("메모를 저장했어요"); reload();
    } catch (e: any) {
      toast(e.message);
      if (e?.status === 404) { setMemoFor(null); reload(); }
    } finally { setMemoBusy(false); }
  }
  return (
    <Screen title="저장 리포트" back={fromStart ? "/" : "/area"} cta={cta}>
      {loading && <Loading />}
      {error && <ErrorBox message={error} onRetry={reload} />}
      {data && (
        <>
          <p className="sub wrap-any"><b style={{ color: "var(--text)" }}>이 브라우저에 저장한 리포트 {data.count}건</b>
            <br /><span className="small">이 브라우저에만 보관돼요. 다른 기기에서는 보이지 않고, 브라우저 데이터를 지우면 사라져요.</span></p>
          {!canPersist() && (
            <div className="notice" role="note">이 브라우저는 저장소를 쓸 수 없어요(사생활 보호 모드 등). 새로고침하거나 창을 닫으면 이 목록이 사라져요.</div>
          )}
          {legacy && (
            <div className="notice" role="note" style={{ marginTop: 8 }}>
              로그인 기능이 없어졌어요. 예전에 계정으로 저장한 리포트는 이 목록에 나오지 않아요 — 필요하면 다시 분석해 저장해 주세요.
              <div style={{ marginTop: 6 }}><button className="btn-text" onClick={() => {
                remove(LEGACY_NOTICE); setLegacy(false);
                requestAnimationFrame(() => document.querySelector<HTMLElement>(".topbar h1")?.focus());   // 사라진 버튼 대신 화면 제목으로
              }}>알겠어요</button></div>
            </div>
          )}
          {data.count === 0 && <div className="empty">아직 저장한 리포트가 없어요.<br />분석 후 액션 리포트에서 저장해 보세요.</div>}
          {data.items.map((it) => (
            <div key={it.saved_report_id} className="card saved-card">
              <button className="grow" style={{ textAlign: "left" }} onClick={() => nav(`/report/${it.report_id}`, { state: { from: "/reports" } })}>
                <b className="wrap-any" style={{ fontSize: 17 }}>{it.area_name} · {it.industry_name}</b>
                <div className="muted wrap-any">
                  {it.place_name && !["지도에서 고른 위치", it.area_name].includes(it.place_name) ? `${it.place_name}에서 고른 구 · ` : ""}
                  {dateDot(it.created_at, true)}
                  {/* 추천 상태를 함께 — 적합도만 보면 추천에서 빠진(대형 점포·주의) 업종이 가장 좋아 보이지 않게 */}
                  {it.item_type === "TOP" && it.rank ? ` · 추천\u00a0${it.rank}위`
                    : it.item_type === "INTEREST" && !it.eligible ? " · 관심\u2060(추천\u00a0제외)"
                    : it.caution ? " · 주의\u00a0업종" : it.item_type === "INTEREST" ? " · 관심\u00a0업종" : ""}
                  {it.suitability != null ? ` · 적합도\u00a0${Math.round(it.suitability)}` : ""}
                  {it.business_goal ? ` · ${it.business_goal === "기본" ? "균형" : it.business_goal}` : ""}</div>
                {/* 같은 지역·업종을 조건만 바꿔 저장해도 구분되게: 반영한 손익분기 요약과 체크리스트 진행 */}
                {(it.required_monthly_sales != null || (it.checklist_total || 0) > 0) && (
                  <div className="small muted">
                    {it.monthly_fixed_cost != null ? `월 고정비${it.owner_included ? "(목표 월수입 포함)" : ""} ${won(it.monthly_fixed_cost)} · ` : ""}
                    {it.required_monthly_sales != null
                      ? `${it.owner_included ? "필요 월매출(목표 월수입 포함)" : "손익분기 월매출"} ${won(it.required_monthly_sales)}`
                        + (it.achievability_ratio != null ? ` · 평균 매출 ${ratioText(it.achievability_ratio)}` : "")
                        + (it.sales_outlier != null ? "(대형 점포 가능·참고용)" : "")
                        + (it.edited ? " · 바꾼 값 기준" : "")
                        // 추천 순위는 분석 조건으로 매겼다(원가율을 넣지 않은 분야는 '매출 ≥ 월 고정비'만) — '추천 3위'와 '0.68배'가 모순처럼 보이지 않게
                        + (it.item_type === "TOP" && it.achievability_ratio != null && it.achievability_ratio < 1 ? " · 순위는 분석 조건 기준" : "") : ""}
                    {it.required_monthly_sales != null && (it.checklist_total || 0) > 0 ? " · " : ""}
                    {(it.checklist_total || 0) > 0 ? `체크리스트 ${it.checklist_done || 0}/${it.checklist_total}` : ""}
                  </div>
                )}
                {/* 긴 메모는 카드에서 세 줄까지(전체는 '메모 수정'에서) */}
                {it.memo && <div className="small wrap-any memo-clamp" style={{ color: "var(--text-2)", whiteSpace: "pre-line" }}>메모: {it.memo}</div>}
              </button>
              <div className="score">
                <b style={{ color: GRADE_COLOR[it.risk_grade] || "var(--text)" }}>{it.risk_score}</b>
                <span className="muted small">{it.risk_grade === "-" ? "" : gradeLabel(it.risk_grade)}</span>
                <div className="card-actions">
                  <button className="mini" onClick={() => { setMemo(it.memo || ""); setMemoFor(it); }}
                    aria-label={`${it.area_name} ${it.industry_name} 리포트(${dateDot(it.created_at, true)} 저장) ${it.memo ? "메모 수정" : "메모 쓰기"}`}>{it.memo ? "메모 수정" : "메모 쓰기"}</button>
                  <button className="mini danger" onClick={() => setDelFor(it)} aria-label={`${it.area_name} ${it.industry_name} 리포트(${dateDot(it.created_at, true)} 저장) 삭제`}>삭제</button>
                </div>
              </div>
            </div>
          ))}
          {data.count > 0 && (
            <div className="link-row"><button className="btn-text" onClick={() => setWipeOpen(true)}>이 브라우저의 저장 목록 모두 지우기</button></div>
          )}
        </>
      )}
      <Sheet open={!!memoFor} onClose={() => setMemoFor(null)} title="메모">
        <p className="muted">{memoFor ? `${memoFor.area_name} · ${memoFor.industry_name}` : ""} — 현장 확인 내용이나 결정 이유를 남겨 두세요.</p>
        <label className="field area" style={{ marginTop: 10 }} htmlFor="memo">
          <textarea id="memo" value={memo} rows={4} aria-describedby="memo-hint"
            onChange={(e) => setMemo([...e.target.value].slice(0, 500).join(""))}   /* 서버처럼 글자(코드 포인트) 수로 500자 */
            aria-label="메모 내용"
            placeholder="예: 평일 점심 유동인구 많음, 임대료 협상 가능" />
        </label>
        <div className="field-hint" id="memo-hint">{[...memo].length}/500자</div>
        <button className="btn-primary" style={{ width: "100%", marginTop: 14 }} onClick={saveMemo} disabled={memoBusy}>
          {memoBusy ? "저장 중…" : "메모 저장"}</button>
      </Sheet>
      <Sheet open={!!delFor} onClose={() => setDelFor(null)} title="리포트 삭제">
        <p>{delFor ? `‘${delFor.area_name} · ${delFor.industry_name}’ 리포트(${dateDot(delFor.created_at, true)} 저장)를 목록에서 지울까요?` : ""}</p>
        <p className="muted small">{delFor?.memo ? "적어 둔 메모도 함께 지워져요. " : ""}지운 뒤에는 되돌릴 수 없어요.</p>
        <div className="grid2" style={{ marginTop: 14 }}>
          <button className="btn-secondary grow" id="del-cancel" onClick={() => setDelFor(null)}>취소</button>
          <button className="btn-primary danger" onClick={del} disabled={delBusy}>{delBusy ? "지우는 중…" : "삭제"}</button>
        </div>
      </Sheet>
      <Sheet open={wipeOpen} onClose={() => setWipeOpen(false)} title="저장 목록 모두 지우기">
        <p>{`이 브라우저에 저장한 리포트 ${data?.count ?? 0}건과 메모를 모두 지울까요?`}</p>
        <p className="muted small">여럿이 함께 쓰는 컴퓨터라면 다 쓴 뒤 지워 두세요 — 이 탭의 입력값도 함께 지워요. 지운 뒤에는 되돌릴 수 없어요(리포트 링크는 그대로 열려요).</p>
        <div className="grid2" style={{ marginTop: 14 }}>
          <button className="btn-secondary grow" id="wipe-cancel" onClick={() => setWipeOpen(false)}>취소</button>
          <button className="btn-primary danger" onClick={wipe} disabled={wipeBusy}>{wipeBusy ? "지우는 중…" : "모두 지우기"}</button>
        </div>
      </Sheet>
    </Screen>
  );
}
