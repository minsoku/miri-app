import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import type { Analysis, Item } from "../api";
import { Bar, ErrorBox, Loading, Screen, useAsync } from "../components/ui";
import { analysisCache } from "../lib/cache";
import { draftFrom } from "../lib/draftFrom";
import { GRADE_COLOR, gradeLabel, won, yearTo } from "../lib/format";
import { useApp } from "../state/app";

function ItemCard({ it, selected, onSelect, expanded, tie = false, owner = false }: { it: Item; selected: boolean; onSelect(): void; expanded: boolean; tie?: boolean; owner?: boolean }) {
  // 순위에 든 업종과 순위 밖 관심 업종이 반올림하면 같은 점수(50 vs 50)면 소수 한 자리까지 — 왜 한쪽만 순위에 들었는지 보이게
  const score = it.suitability == null ? "-" : tie ? (Math.round(it.suitability * 10) / 10).toFixed(1) : Math.round(it.suitability);
  // 머리글(순위·이름·점수)만 버튼 — 펼친 근거 문장·칩은 버튼 밖에 둬서 스크린리더가 따로 읽을 수 있게
  return (
    <div className={`card${selected ? " sel" : ""}`} onClick={onSelect} style={{ cursor: "pointer" }}>
      <button className="card-head" aria-expanded={expanded} onClick={(e) => { e.stopPropagation(); onSelect(); }}>
        <div className="between" style={{ alignItems: "flex-start" }}>
          <div className="grow">
            <div className="row">
              {it.rank ? <span className={`rank${selected ? " on" : ""}`}>{it.rank}위</span> :
                <span className="badge grey">{it.item_type === "INTEREST" ? "관심" : "주의"}</span>}
              {!expanded && <b className="wrap-any" style={{ fontSize: 17 }}>{it.industry_name}</b>}
              {/* 접힌 추천 카드에도 종합 위험 '고위험'은 보이게(펼치거나 위험도 화면에 가야만 알 수 있지 않게) */}
              {!expanded && it.risk_grade === "고위험" && (
                <span className="small" style={{ color: GRADE_COLOR["고위험"], whiteSpace: "nowrap", fontWeight: 700 }}>고위험</span>
              )}
              {/* 접힌 관심 업종 카드에도 순위에 없는 이유를 짧게(펼치면 자세한 이유) */}
              {!expanded && !it.rank && it.item_type === "INTEREST" && (
                <span className="muted small" style={{ whiteSpace: "nowrap" }}>{!it.eligible ? "추천 제외" : it.location_risk_pct >= 90 ? "주의 업종"
                  : it.suitability != null && Math.floor(it.suitability + 0.5) < 20 ? "적합도 20점 미만" : "순위 밖"}</span>
              )}
            </div>
            {expanded && <h3 className="wrap-any" style={{ fontSize: 20, marginTop: 10 }}>{it.industry_name}</h3>}
          </div>
          <div style={{ textAlign: "right", flex: "none" }}>
            <div className={expanded ? "score-big" : "score-mid"} style={{ color: expanded ? undefined : "var(--text)" }}>{score}</div>
            {expanded && <div className="muted">적합도 점수</div>}
            {expanded && !it.eligible && <div className="small" style={{ color: "var(--amber-text)", fontWeight: 700 }}>추천 제외</div>}
          </div>
        </div>
      </button>
      <div style={{ marginTop: 12 }}><Bar value={it.suitability ?? 0} /></div>
      {expanded && (
        <>
          {it.score_note && <p className="score-note">{it.score_note}</p>}
          <p style={{ margin: "12px 0 0", color: "var(--text-2)" }}>{it.reason_short}</p>
          <div className="chiplist">
            <span style={{ color: GRADE_COLOR[it.risk_grade] }}>종합 {gradeLabel(it.risk_grade)} {it.risk_score}점</span>
            <span style={{ color: GRADE_COLOR[it.location_grade] }}>같은 업종 중 입지 위험 {it.location_risk_pct}({it.location_grade})</span>
            {it.chips.map((c) => <span key={c}>{c}</span>)}
          </div>
          {/* 두 가지 '위험'이 무엇을 뜻하는지 카드 안에서 바로(위험도 화면에 가야만 알 수 있지 않게) */}
          <p className="muted small" style={{ margin: "8px 0 0" }}>
            종합 위험은 서울의 모든 업종·지역과 비교한 폐업 위험(점수가 높을수록 위험), 입지 위험은 같은 업종끼리 비교한 이 구의 순위(0~100, 높을수록 위험)예요.</p>
          {it.suitability != null && (
            <p className="muted small" style={{ margin: "8px 0 0" }}>
              점수 구성: 매출 잠재력 {it.scores.D == null ? "-" : Math.round(it.scores.D)} · 생존 안정성 {it.scores.S == null ? "-" : Math.round(it.scores.S)}
              {it.scores.F != null ? ` · 비용 적합도 ${Math.round(it.scores.F)}` : ""}
              {/* '적합도는 어떻게 계산하나요?'에 화면에서 바로 답할 수 있게 */}
              <br />매출 잠재력 = 서울 같은 업종 중 이 구의 점포당 매출 백분위(0~100, 높을수록 좋음) · 생존 안정성 = 100 − 종합 위험 점수
              {it.scores.F != null ? ` · 비용 적합도 = 평균 매출 ÷ ${owner ? "필요 매출(목표 월수입 포함)" : "손익분기"}(0.8배 이하 0점 ~ 1.5배 이상 100점)` : ""}
            </p>
          )}
          {!it.eligible && it.ineligible_reason && <div className="pill" style={{ marginTop: 10 }}>추천 제외 · {it.ineligible_reason}</div>}
          {(it.cautions.length > 0 || it.peak.length > 0) && (
            <div className="tagchips" style={{ marginTop: 10, gap: 6 }}>
              {it.cautions.map((c) => <span key={c} className="pill">유의 · {c}</span>)}
              {it.peak.slice(0, 2).map((p) => <span key={p.code} className="pill info">참고 · {p.pill}</span>)}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** 실제로 순위에 쓴 가중치: 비용 적합도(F)를 못 쓰면 매출·안정성 가중치를 다시 나눠 합이 100이 되게(엔진 combine과 같음) */
function effectiveWeights(a: Analysis) {
  const w = a.weights;
  if (a.f_applied) return w;
  const t = w.D + w.S;
  return { D: w.D / t, S: w.S / t, F: 0 };
}

// SB-05 추천 결과
export default function Results() {
  const { id = "" } = useParams();
  const { api, draft, setDraft } = useApp();
  const nav = useNavigate();
  const { data: a, error, status, loading, reload } = useAsync(async () => analysisCache.get(id) || api.getAnalysis(id), [id]);
  const [sel, setSel] = useState<string | null>(null);
  const [showCaution, setShowCaution] = useState(false);

  if (loading) return <Screen title="추천 결과" back="/interests"><Loading text="분석 결과를 불러오는 중…" /></Screen>;
  if (error || !a) {
    return <Screen title="추천 결과" back="/area">
      <ErrorBox message={error || "결과가 없어요"} onRetry={status === 404 ? undefined : reload} /></Screen>;
  }

  const selected = sel || a.top[0]?.industry_code || a.interests[0]?.industry_code || null;
  const w = effectiveWeights(a);
  const place = a.area.place_name && !["지도에서 고른 위치", a.area.area_name].includes(a.area.place_name) ? a.area.place_name : null;
  const fixedLabel = (a.conditions.owner_salary || 0) > 0 ? "월 고정비(목표 월수입 포함)" : "월 고정비";
  const header = `${place ? `${place} 주변 → ` : ""}${a.area.area_name} · ${fixedLabel} ${won(a.conditions.monthly_fixed_total)}`;
  const interestOnly = a.interests.filter((i) => !a.top.some((t) => t.industry_code === i.industry_code));
  const topShown = new Set(a.top.filter((t) => t.suitability != null).map((t) => Math.round(t.suitability as number)));
  const ties = new Set(interestOnly.filter((i) => i.suitability != null && topShown.has(Math.round(i.suitability)))
    .map((i) => Math.round(i.suitability as number)));
  const isTie = (it: Item) => it.suitability != null && ties.has(Math.round(it.suitability));
  const ranked = a.top.length > 0;                      // 추천 0개면 순위·가중치 안내는 의미가 없어 숨긴다
  // 외식업처럼 업종 자체의 폐업률이 높은 분야는 TOP 전부가 '높음·고위험'일 수 있다 → 순위의 의미(상대 순서)를 먼저 밝힌다
  const allHigh = a.top.length >= 1 && a.top.every((t) => t.risk_grade === "높음" || t.risk_grade === "고위험");
  const notes = [
    ...(a.f_note && ranked
      ? [a.f_note.includes("원가율") ? "‘비용 적합도’는 원가율을 아는 분야만 계산돼요(외식업은 평균값, 다른 분야는 조건 입력에서 넣은 값). 이번 후보에 원가율이 없는 분야가 있어 매출·안정성만으로 순위를 매겼어요." : a.f_note]
      : []),
    ...a.notices,
    ...(ranked ? [((a.n_low_score || 0) > 0
      // 적합도 20점 미만은 순위에 넣지 않으므로 '조건에 맞는 7개 중'이라고만 하면 4개만 보이는 이유가 안 보인다
      ? `조건을 통과한 ${a.n_candidates - a.cautions.length}개 업종${a.cautions.length ? "(주의 업종 제외)" : ""} 중 적합도 20점 이상인 ${a.n_candidates - a.cautions.length - (a.n_low_score || 0)}개의 순위예요.`
      : `조건에 맞는 ${a.n_candidates - a.cautions.length}개 업종 중 순위예요${a.cautions.length ? "(입지 위험 상위 10%인 주의 업종 제외)" : ""}.`)
      + ` 점수는 매출 잠재력·생존 안정성${a.f_applied ? "·비용 적합도" : ""}의 가중 평균이에요.`] : []),
    // 계산로직 §8 표시 단서: 매출은 카드 매출 기준 추정, 폐업률은 지역·업종 전체 점포 기준(내 가게의 확률이 아님)
    `점포당 월매출은 서울시 상권분석서비스의 카드 매출 기준 추정치(${yearTo(a.data_quarter_label)} 평균)이고, 예상 폐업률은 이 지역·업종 전체 점포 기준으로 최근 추세가 이어질 때의 값이에요.`,
  ];
  return (
    <Screen title="추천 결과" back={draft.area ? "/interests" : "/area"}
      cta={a.top.length === 0
        // 추천이 0개면 '조건 바꿔 다시 분석'이 주 버튼(관심 업종이 있으면 그 위험도는 보조 버튼으로)
        ? <>{selected && <button className="btn-secondary" onClick={() => nav(`/analysis/${a.id}/risk/${selected}`)}>위험도 보기</button>}
          <button className="btn-primary" onClick={() => { setDraft(draftFrom(a)); nav("/conditions"); }}>조건 바꿔 다시 분석</button></>
        : <button className="btn-primary" onClick={() => nav(`/analysis/${a.id}/risk/${selected}`)}>상세 위험도 보기</button>}>
      <p className="sub">{header}</p>
      {a.area.scope_note && <p className="scope">ⓘ {a.area.scope_note}</p>}
      <h2 className="h2" style={{ marginTop: 4 }}>
        {a.top.length >= 2 ? `추천 업종 TOP ${a.top.length}` : a.top.length === 1 ? "추천 업종 1개" : "추천할 업종을 찾지 못했어요"}</h2>
      <p className="muted" style={{ margin: "-4px 0 12px" }}>
        {yearTo(a.data_quarter_label)} 데이터 · {(a.conditions.categories || []).length ? `${a.conditions.categories.join("·")} 안에서` : "전체 업종에서"}
        {ranked && <> · {a.business_goal === "기본" ? "균형" : a.business_goal}
          (매출 {Math.round(w.D * 100)}·안정 {Math.round(w.S * 100)}{a.f_applied ? `·비용 ${Math.round(w.F * 100)}` : ""})</>}
        {a.top.length > 0 && <>{" · "}<button className="btn-text" style={{ padding: 0, minHeight: 0 }}
          onClick={() => { setDraft(draftFrom(a)); nav("/conditions"); }}>조건 바꿔 다시 분석</button></>}
      </p>
      {a.top.length === 0 && (
        <div className="notice warn"><b>왜 없을까요?</b>{a.empty_reason || "조건에 맞는 추천 업종이 없어요. 분야 제한이나 비용 조건을 조정해 보세요."}</div>
      )}
      {allHigh && (
        <div className="notice" style={{ marginBottom: 12 }}>
          <b>{a.top.length === 1 ? "추천 업종이 폐업 위험 ‘높음’ 이상이에요" : "추천 업종이 모두 폐업 위험 ‘높음’ 이상이에요"}</b>
          {/* 분야 전체가 위험하다고 말하지 않는다(같은 분야의 관심 업종은 '보통'일 수 있음) — 외식업만 업종 자체 폐업률이 높은 분야 */}
          {a.top.length === 1 ? "추천된 업종은 서울 전체 지역·업종과 비교하면 폐업 위험이 ‘높음’ 이상이에요. "
            : `추천된 ${a.top.length}개 업종이 모두 서울 전체 지역·업종과 비교해 폐업 위험 ‘높음’ 이상이라, 아래 순위는 그 안에서 상대적으로 나은 순서예요. `}
          {(a.conditions.categories || []).join() === "외식업" ? "외식업은 업종 자체 폐업률이 서울 전 업종 평균보다 높아 대부분 여기에 해당해요. " : ""}
          같은 업종끼리 비교한 입지 위험과 손익분기를 함께 보세요.
        </div>
      )}
      {a.top.map((it) => (
        <ItemCard key={it.industry_code} it={it} selected={selected === it.industry_code} expanded={selected === it.industry_code}
          onSelect={() => setSel(it.industry_code)} tie={isTie(it)} owner={(a.conditions.owner_salary || 0) > 0} />
      ))}
      {interestOnly.length > 0 && (
        <>
          <h2 className="h2">내 관심 업종</h2>
          {interestOnly.map((it) => (
            <ItemCard key={it.industry_code} it={it} selected={selected === it.industry_code} expanded={selected === it.industry_code}
              onSelect={() => setSel(it.industry_code)} tie={isTie(it)} owner={(a.conditions.owner_salary || 0) > 0} />
          ))}
        </>
      )}
      {(a.missing_interests || []).length > 0 && (
        <>
          {interestOnly.length === 0 && <h2 className="h2">내 관심 업종</h2>}
          {a.missing_interests!.map((m) => (
            <button key={m.industry_code} className="card" style={{ width: "100%", textAlign: "left", display: "block" }}
              onClick={() => nav(`/analysis/${a.id}/risk/${m.industry_code}`)}>
              <div className="between"><b style={{ fontSize: 17 }}>{m.industry_name}</b><span className="btn-text">위험도 보기 →</span></div>
              <p className="muted" style={{ margin: "6px 0 0" }}>이 지역에 최근 1년 점포가 없어 적합도를 계산하지 않았어요. 위험도는 서울 같은 업종 평균 기준으로 볼 수 있어요.</p>
            </button>
          ))}
        </>
      )}
      {a.cautions.length > 0 && (
        <div className="card" style={{ marginTop: 12 }}>
          <button className="between" style={{ width: "100%" }} onClick={() => setShowCaution((v) => !v)} aria-expanded={showCaution}>
            <b>주의 업종 {a.cautions.length}개</b><span className="btn-text">{showCaution ? "접기" : "보기"}</span>
          </button>
          <p className="muted" style={{ margin: "6px 0 0" }}>같은 업종끼리 비교했을 때 이 지역 입지 위험이 가장 높은 10% 구간이라 TOP에서 뺐어요.</p>
          {showCaution && a.cautions.map((c) => (
            <button key={c.industry_code} className="kv" style={{ width: "100%" }} onClick={() => nav(`/analysis/${a.id}/risk/${c.industry_code}`)}>
              <span>{c.industry_name}</span><b style={{ color: GRADE_COLOR[c.location_grade] }}>입지 위험 {c.location_risk_pct}</b>
            </button>
          ))}
        </div>
      )}
      {notes.length > 0 && (
        <div className="notice" style={{ marginTop: 14 }}>
          <ul>{notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </div>
      )}
    </Screen>
  );
}
