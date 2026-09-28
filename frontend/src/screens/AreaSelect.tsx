import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import type { AreaCard, Candidates, CompareOut, MapData, Place } from "../api";
import SeoulMap from "../components/SeoulMap";
import { guardClicks, IconList, IconSearch, Screen, Sheet, Spinner } from "../components/ui";
import { countShort, GRADE_COLOR, josa, pct, radiusLabel, won, won1 } from "../lib/format";
import { pyFixed } from "../api/demo/pyfmt";

/** 화면에 보이는 문자열의 숫자('17.6만원' → 17.6, '1.2억원' → 12000(만원 단위로 맞춤), '27%' → 27) — 표시값끼리 비교용 */
function shown(t: string): number | null {
  const m = t.replace(/,/g, "").match(/^(-?[\d.]+)(억|만)?/);
  if (!m) return null;
  const n = Number(m[1]);
  return m[2] === "억" ? n * 10000 : n;
}
import { useApp } from "../state/app";

const RADII = [300, 500, 1000];
const CITY_HALL = { lat: 37.5663, lng: 126.9779 };
let mapCache: MapData | null = null;

// SB-02 상권 선택
export default function AreaSelect() {
  const { api, draft, setDraft, toast } = useApp();
  const nav = useNavigate();
  const [map, setMap] = useState<MapData | null>(mapCache);
  const [q, setQ] = useState(draft.place?.name && draft.place.name !== "지도에서 고른 위치" ? draft.place.name : "");
  const [results, setResults] = useState<Place[]>([]);
  const [resultsFor, setResultsFor] = useState("");          // 지금 보이는 결과가 어느 검색어의 결과인지
  const [searchErr, setSearchErr] = useState<string | null>(null);   // 검색 요청 자체가 실패(서버 연결·검색어 오류) — '찾지 못했어요'와 구분
  const [active, setActive] = useState(-1);                  // 방향키로 고른 결과(콤보박스 aria-activedescendant)
  const [open, setOpen] = useState(false);
  const pendingEnter = useRef<string | null>(null);          // 결과가 오기 전에 Enter를 누른 검색어
  const [cands, setCands] = useState<Candidates | null>(null);
  const [compare, setCompare] = useState(false);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const debounce = useRef<number>();
  const candSeq = useRef(0), searchSeq = useRef(0);          // 늦게 도착한 이전 요청의 응답은 버린다

  useEffect(() => {
    if (!mapCache) api.areaMap().then((m) => { mapCache = m; setMap(m); }).catch(() => undefined);
  }, [api]);

  useEffect(() => {        // 이전에 고른 위치가 있으면 후보 다시 불러오기
    if (draft.place) loadCandidates(draft.place.lat, draft.place.lng, draft.radius, draft.place.name, draft.area?.area_code);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadCandidates(lat: number, lng: number, radius: number, name: string, keep?: string | null) {
    const my = ++candSeq.current;
    setLoading(true); setErr(null);
    try {
      const c = await api.candidates(lat, lng, radius, name);
      if (my !== candSeq.current) return;
      setCands(c);
      const chosen = c.candidates.find((x) => x.area_code === keep) || c.candidates[0] || null;
      setDraft({ area: chosen, candidateCodes: c.candidates.map((x) => x.area_code) });
    } catch (e: any) {
      if (my !== candSeq.current) return;
      setErr(e.message); setCands(null); setDraft({ area: null, candidateCodes: [] });
    } finally { if (my === candSeq.current) setLoading(false); }
  }

  function search(term: string, delay: number) {
    window.clearTimeout(debounce.current);
    const my = ++searchSeq.current;
    debounce.current = window.setTimeout(() => {
      api.searchPlaces(term).then((r) => {
        if (my !== searchSeq.current) return;
        setResults(r); setResultsFor(term); setActive(-1); setSearchErr(null);
        if (pendingEnter.current === term) {             // Enter를 먼저 눌렀으면 이 검색어의 첫 결과로 바로 선택
          pendingEnter.current = null;
          if (r[0]) choose(r[0], false);                 // 결과가 없으면 아래 '찾지 못했어요' 안내(role=status)가 알려준다
        }
      }).catch((e: any) => {
        if (my !== searchSeq.current) return;
        const st = typeof e?.status === "number" ? e.status : 0;   // 연결 실패(0)·서버 오류(5xx)만 '연결하지 못했어요', 4xx는 서버가 준 이유
        setResults([]); setResultsFor(term); pendingEnter.current = null;
        setSearchErr(st === 0 || st >= 500 ? "검색 서버에 연결하지 못했어요. 잠시 후 다시 시도하거나 지도를 눌러 위치를 골라 주세요."
          : `${e?.message || "검색하지 못했어요"}. 역·구 이름으로 검색하거나 지도를 눌러 위치를 골라 주세요.`);
      });
    }, delay);
  }
  function onType(v: string) {
    setQ(v); setOpen(true); setActive(-1); pendingEnter.current = null;
    if (!v.trim()) { window.clearTimeout(debounce.current); searchSeq.current++; setResults([]); setResultsFor(""); return; }
    search(v.trim(), 220);
  }
  function onEnter() {
    const term = q.trim();
    if (!term) return;
    if (resultsFor === term && results.length && active >= 0) { choose(results[active], false); return; }   // 화살표로 고른 항목
    if ([...term].length < 2) { setOpen(true); if (resultsFor !== term) search(term, 0); return; }   // '역'·'중'처럼 한 글자는 첫 결과를 바로 고르지 않고 목록만
    if (resultsFor === term && results.length) { choose(results[0], false); return; }
    pendingEnter.current = term;                          // 이전 검색어의 결과로 잘못 선택하지 않게 새로 검색
    search(term, 0);
  }
  function choose(p: Place, byPointer = true) {
    if (byPointer) guardClicks();                         // 목록을 눌러 닫을 때: 더블클릭의 두 번째 클릭이 지도를 누르지 않게
    setQ(p.name); setOpen(false); setResults([]); setResultsFor(""); setActive(-1);
    const place = { name: p.name, lat: p.lat, lng: p.lng };
    setDraft({ place });
    loadCandidates(p.lat, p.lng, draft.radius, p.name);
  }
  function setRadius(r: number) {
    setDraft({ radius: r });
    if (draft.place) loadCandidates(draft.place.lat, draft.place.lng, r, draft.place.name, draft.area?.area_code);
  }
  function pickOnMap(lat: number, lng: number) {
    const place = { name: "지도에서 고른 위치", lat, lng };
    setQ(""); setDraft({ place });
    loadCandidates(lat, lng, draft.radius, place.name);
  }
  function selectCard(c: AreaCard) { setDraft({ area: c }); }

  const center = draft.place || CITY_HALL;
  return (
    <Screen title="상권 선택" back="/" step={1}
      right={<button className="icon-btn" onClick={() => nav("/reports")}><IconList />저장 리포트</button>}
      cta={<button className="btn-primary" disabled={!draft.area || loading}
        onClick={() => { if (!draft.area) { toast("상권을 먼저 골라 주세요"); return; } nav("/conditions"); }}>
        {draft.area ? `${josa(draft.area.area_name, "으로/로")} 분석` : "이 상권으로 분석"}</button>}>
      <p className="lead">분석할 지역과 반경을 골라주세요.</p>
      <div className="search">
        <label className="field">
          <IconSearch />
          <input value={q} placeholder="지역·상권 검색 (예: 강남역)" maxLength={50} onChange={(e) => onType(e.target.value)}
            onFocus={() => q && setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)}
            role="combobox" aria-autocomplete="list" aria-expanded={open && results.length > 0} aria-controls="place-list"
            aria-activedescendant={open && active >= 0 ? `place-opt-${active}` : undefined}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown" && results.length) { e.preventDefault(); setOpen(true); setActive((i) => Math.min(i + 1, results.length - 1)); }
              else if (e.key === "ArrowUp" && results.length) { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
              else if (e.key === "Enter") { e.preventDefault(); onEnter(); }
              else if (e.key === "Escape") { setOpen(false); setActive(-1); }
            }}
            aria-label="지역·상권 검색" />
        </label>
        {open && results.length > 0 && (
          <div className="dropdown" role="listbox" id="place-list" aria-label="검색 결과">
            {results.map((p, i) => (
              <div key={`${p.name}-${p.lat}`} id={`place-opt-${i}`} role="option" aria-selected={i === active}
                className={`opt${i === active ? " active" : ""}`} onMouseDown={(e) => e.preventDefault()} onClick={() => choose(p)}>
                <span className="kind">{p.kind === "district" ? "자치구" : p.kind === "station" ? "역" : p.kind === "kakao" ? "장소" : "거리"}</span>
                <span className="grow"><b>{p.name}</b><br /><span className="muted">{p.address || p.area_name}</span></span>
              </div>
            ))}
          </div>
        )}
        {q.trim() && resultsFor === q.trim() && results.length === 0 && (
          <p className="field-hint" role="status">{searchErr
            ? searchErr
            : <>‘{q.trim()}’{particle(q.trim(), "을/를")} 찾지 못했어요. 서울 25개 구와 주요 역·상권 이름으로 찾을 수 있어요 — 가까운 큰 역이나 구 이름으로 검색하거나 지도를 눌러 위치를 골라 주세요.</>}</p>
        )}
        {!open && draft.area && q.trim() && q.trim() !== draft.place?.name && !(resultsFor === q.trim() && results.length === 0) && (
          <p className="field-hint">‘{q.trim()}’{particle(q.trim(), "으로/로")} 바꾸려면 검색 결과에서 장소를 골라 주세요 · 지금 선택: {draft.area.area_name}</p>
        )}
      </div>
      <div style={{ marginTop: 14 }}>
        <SeoulMap data={map} center={center} radius={draft.radius} showPin={!!draft.place} selectedCode={draft.area?.area_code}
          candidateCodes={draft.candidateCodes} onPick={pickOnMap} />
      </div>
      <h2 className="label">분석 반경</h2>
      <div className="chips c3">
        {RADII.map((r) => (
          <button key={r} className={`chip${draft.radius === r ? " on" : ""}`} onClick={() => setRadius(r)} aria-pressed={draft.radius === r}>
            {radiusLabel(r)}</button>
        ))}
      </div>
      <div className="between" style={{ alignItems: "baseline" }}>
        <h2 className="label">후보 지역 (자치구)</h2>
        {!loading && cands && cands.candidates.length >= 2 && (
          <button className="btn-small" onClick={() => setCompare(true)}>
            {cands.candidates.length > 4 ? `후보 ${cands.candidates.length}곳 중 4곳 비교` : `후보 ${cands.candidates.length}곳 비교`}</button>
        )}
        {!loading && cands && cands.candidates.length === 1 && map && (
          <button className="btn-small" onClick={() => setCompare(true)}>다른 구와 비교</button>
        )}
      </div>
      {loading && <div className="center-pad" style={{ padding: 24 }}><Spinner /></div>}
      {!loading && err && <div className="notice warn">{err}</div>}
      {!loading && !err && !cands && <div className="notice">지역을 검색하거나 지도를 눌러 위치를 고르면 반경 안의 후보 상권을 보여드려요.</div>}
      {!loading && cands && (
        <div>
          {cands.candidates.map((c) => {
            const sel = draft.area?.area_code === c.area_code;
            const named = draft.place && c.is_center && !["지도에서 고른 위치", c.area_name].includes(draft.place.name) ? draft.place.name : null;
            return (
              <button key={c.area_code} className={`card${sel ? " sel" : ""}`} style={{ width: "100%", textAlign: "left", display: "block" }}
                onClick={() => selectCard(c)} aria-pressed={sel}>
                <div className="between">
                  <h3>{c.area_name}</h3>
                  {sel ? <span className="badge blue">선택됨</span> : <span className="muted">{c.distance_m ? `경계까지 ${c.distance_m >= 1000 ? `${pyFixed(c.distance_m / 1000, 1)}km` : `${c.distance_m}m`}` : ""}</span>}
                </div>
                <div className="muted">{named ? `${josa(named, "이/가")} 있는 구 · ` : ""}구 전체 합계{c.metrics.quarter_label ? ` · ${c.metrics.quarter_label}` : ""}</div>
                <div className="metric3">
                  <div><b>{countShort(c.metrics.floating_daily)}</b><span>일평균 유동인구</span></div>
                  <div><b>{countShort(c.metrics.store_count)}</b><span>점포 수</span></div>
                  <div><b>{c.metrics.rent_per_3_3m2 == null ? "-" : `₩${won1(c.metrics.rent_per_3_3m2, "")}`}</b><span>3.3㎡당 월 임대료</span></div>
                </div>
              </button>
            );
          })}
          {cands.candidates.length === 1 && cands.candidates[0].distance_m <= draft.radius && (
            // 반경을 넓혀도 한 구만 걸리는 곳이 많아(구 한가운데) '넓히면 비교할 수 있다'고 약속하지 않는다
            <p className="muted" style={{ marginTop: 10 }}>
              {radiusLabel(draft.radius)} 안에는 이 구만 있어요.{map ? " ‘다른 구와 비교’에서 주변 구를 골라 나란히 볼 수 있어요." : ""}
            </p>
          )}
          {cands.notice && <p className="muted" style={{ marginTop: 10 }}>ⓘ {cands.notice}</p>}
        </div>
      )}
      {cands && (
        <CompareSheet open={compare} codes={compareCodes(cands.candidates.map((c) => c.area_code), draft.area?.area_code)} selected={draft.area?.area_code}
          all={(map?.features || []).map((f) => ({ code: f.properties.code, name: f.properties.name,
            km: km(center.lat, center.lng, f.properties.lat, f.properties.lng) }))}
          onClose={() => setCompare(false)}
          onPick={(a) => {
            setCompare(false);
            const c = cands.candidates.find((x) => x.area_code === a.area_code);
            if (c) { selectCard(c); return; }
            // 비교에 추가한 반경 밖의 구: 그 구 중심을 위치로 다시 고른다(검색에서 구 이름을 고른 것과 같게)
            if (a.lat == null || a.lng == null) return;
            setQ(a.area_name);
            setDraft({ place: { name: a.area_name, lat: a.lat, lng: a.lng } });
            loadCandidates(a.lat, a.lng, draft.radius, a.area_name, a.area_code);
          }} />
      )}
    </Screen>
  );
}

/** 두 지점 사이 거리(km, 구 목록 정렬·표시용) */
function km(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const R = 6371, r = Math.PI / 180, dLat = (lat2 - lat1) * r, dLng = (lng2 - lng1) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

/** ‘검색어’ 뒤 조사만(받침에 맞춰): particle('잠실역', '으로/로') → '으로' */
const particle = (w: string, pair: "을/를" | "으로/로") => josa(w, pair).slice(w.length);

/** 비교할 구(최대 4곳, API 제한): 가까운 순서로 고르되 지금 선택한 구는 꼭 넣는다 */
function compareCodes(all: string[], selected?: string | null): string[] {
  const first = all.slice(0, 4);
  if (!selected || first.includes(selected) || !all.includes(selected)) return first;
  return [...all.slice(0, 3), selected];
}

/** UC-02 상권 비교: 후보 구를 같은 기준(최신 분기)으로 나란히. 업종을 고르면 그 업종의 위험·매출도 비교한다. */
function CompareSheet({ open, codes, selected, all, onClose, onPick }: {
  open: boolean; codes: string[]; selected?: string | null; all: { code: string; name: string; km: number }[];
  onClose(): void; onPick(area: AreaCard): void;
}) {
  const { api, industries } = useApp();
  const [ind, setInd] = useState("");
  const [extra, setExtra] = useState<string[]>([]);          // 반경 밖에서 직접 추가한 구
  const [removed, setRemoved] = useState<string[]>([]);      // 기본 후보 중 뺀 구(후보가 5곳 이상일 때 다른 구로 바꿔 보게)
  const [pick, setPick] = useState("");                      // '추가'를 누르기 전 고른 구(방향키로 훑기만 해도 추가되지 않게)
  const [got, setGot] = useState<{ key: string; d: CompareOut } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const seq = useRef(0);
  const base = codes.join(",");
  useEffect(() => { setExtra([]); setRemoved([]); setPick(""); }, [base]);   // 위치가 바뀌면 추가·뺀 구는 비운다
  const shownCodes = [...codes.filter((c) => !removed.includes(c)), ...extra.filter((c) => !codes.includes(c))].slice(0, 4);
  const key = `${shownCodes.join(",")}|${ind}`;
  useEffect(() => {
    if (!open || shownCodes.length < 2) return;
    const my = ++seq.current;
    setErr(null);
    api.compareAreas(shownCodes, ind || null).then((d) => { if (my === seq.current) setGot({ key, d }); })
      .catch((e) => { if (my === seq.current) { setGot(null); setErr(e.message); } });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, key, api]);
  // 지금 고른 구·업종의 결과만 보여준다(새 비교를 불러오는 동안 이전 위치의 구가 잠깐 보이지 않게)
  const data = got && got.key === key ? got.d : null;
  const list = (industries?.industries || []).filter((i) => i.recommendable ?? i.has_sales_data);   // SB-04 목록과 같은 기준
  const areas = data?.areas || [];
  // 4곳 비교(좁은 칸)에서는 금액 끝의 '원'을 빼 '2,090만/원'처럼 단위가 줄바꿈되지 않게(행 이름에 단위 표시)
  const four = areas.length >= 4;
  const short = (t: string) => (four ? t.replace(/원$/, "") : t);
  // 가까운 구부터(고른 위치에서 구 중심까지 거리)
  const addable = all.filter((a) => !shownCodes.includes(a.code)).sort((a, b) => a.km - b.km || a.name.localeCompare(b.name, "ko"));
  const nameOf = (c: string) => all.find((a) => a.code === c)?.name || c;
  const full = shownCodes.length >= 4;
  const tableFocus = useRef(false);                          // 4곳이 차면 새 비교표가 도착했을 때 거기로 포커스
  useEffect(() => {
    if (data && tableFocus.current) { tableFocus.current = false; document.getElementById("cmp-table")?.focus(); }
  }, [data]);
  function add() {
    if (!pick || full) return;
    const willBeFull = shownCodes.length + 1 >= 4;
    if (removed.includes(pick)) setRemoved((x) => x.filter((y) => y !== pick));   // 뺐던 기본 후보를 다시 넣기
    else setExtra((x) => [...x, pick]);
    setPick("");
    // 추가 후 포커스: 더 고를 수 있으면 목록, 4곳이 차면(목록·버튼이 잠김) 비교표 — 불러오는 동안은 시트에 둬서 사라지지 않게
    if (willBeFull) {
      tableFocus.current = true;
      requestAnimationFrame(() => (document.querySelector(".sheet[role=dialog]") as HTMLElement | null)?.focus());
    } else requestAnimationFrame(() => document.getElementById("cmp-add")?.focus());
  }
  // 행마다 가장 유리한 값(낮을수록 좋은 지표는 최소, 높을수록 좋은 지표는 최대)을 굵게
  // val은 '화면에 보이는 값'으로 비교(반올림하면 같은 25명·27%가 한쪽만 굵게 보이지 않게). grade: 그 업종 등급 색을 칠할 행
  type RowDef = { label: string; note?: string; val: (a: any) => number | null | undefined; show: (a: any) => ReactNode;
    better: "low" | "high" | null; grade?: boolean };
  const rows: RowDef[] = [
    { label: "일평균 유동인구", val: (a) => a.metrics.floating_daily, show: (a) => countShort(a.metrics.floating_daily), better: null },
    { label: "주거인구", val: (a) => a.metrics.resident_population, show: (a) => countShort(a.metrics.resident_population), better: null },
    { label: "점포 수(전 업종)", val: (a) => a.metrics.store_count, show: (a) => countShort(a.metrics.store_count), better: null },
    { label: "점포 1곳당 유동인구", note: "높을수록 경쟁이 덜함",
      val: (a) => (a.metrics.floating_daily && a.metrics.store_count ? Math.round(a.metrics.floating_daily / a.metrics.store_count) : null),
      show: (a) => (a.metrics.floating_daily && a.metrics.store_count ? `${Math.round(a.metrics.floating_daily / a.metrics.store_count).toLocaleString()}명` : "-"),
      better: "high" },
    { label: four ? "3.3㎡당 월 임대료(원)" : "3.3㎡당 월 임대료", val: (a) => shown(won1(a.metrics.rent_per_3_3m2)), show: (a) => short(won1(a.metrics.rent_per_3_3m2)), better: "low" },
    { label: "전 업종 평균 폐업 위험", note: "0~100, 낮을수록 안전", val: (a) => a.summary.avg_risk_score,
      show: (a) => (a.summary.avg_risk_score == null ? "-" : pyFixed(a.summary.avg_risk_score, 1)), better: "low" },   // 54.3 · 50.0처럼 자릿수 통일
    { label: "위험 높은 업종 비율", val: (a) => shown(pct(a.summary.high_risk_share, 0)), show: (a) => pct(a.summary.high_risk_share, 0), better: "low" },
  ];
  if (data?.industry_name) {
    rows.push(
      { label: `${data.industry_name} 폐업 위험`, val: (a) => a.industry?.risk_score, grade: true,
        show: (a) => (a.industry ? `${a.industry.risk_score} ${a.industry.risk_grade}` : "점포 없음"), better: "low" },
      { label: "예상 연 폐업률", val: (a) => (a.industry ? shown(pct(a.industry.pred_annual_rate)) : null),
        show: (a) => (a.industry ? pct(a.industry.pred_annual_rate) : "-"), better: "low" },
      { label: "입지 위험", note: "같은 업종끼리 비교", val: (a) => a.industry?.location_risk_pct,
        show: (a) => (a.industry ? `${a.industry.location_risk_pct}` : "-"), better: "low" },
      // 대형 점포가 섞인 듯한 평균(서울 중간값의 3배 이상)은 '가장 유리'로 굵게 표시하지 않고 표시만 한다(SB-05 추천 제외와 같은 기준)
      { label: four ? "점포당 월매출(원)" : "점포당 월매출", note: "카드 매출 기준 추정",
        val: (a) => (a.industry?.sales_ps_m != null && a.industry.sales_outlier == null ? shown(won(a.industry.sales_ps_m)) : null),
        show: (a) => (a.industry?.sales_outlier != null
          ? <>{short(won(a.industry.sales_ps_m))}<br /><span className="muted small">대형 점포 가능</span></>
          : short(won(a.industry?.sales_ps_m))), better: "high" },
      { label: "같은 업종 점포", val: (a) => a.industry?.stores_avg,
        show: (a) => (a.industry ? `${pyFixed(a.industry.stores_avg, 0, true)}개` : "-"), better: null },
    );
  }
  const best = (r: RowDef) => {
    if (!r.better) return null;
    const vs = areas.map((a) => r.val(a)).filter((v): v is number => v != null && isFinite(v));
    if (vs.length < 2) return null;
    const b = r.better === "low" ? Math.min(...vs) : Math.max(...vs);
    return vs.filter((v) => v === b).length === vs.length ? null : b;      // 모두 같으면 굵게 표시하지 않는다
  };
  return (
    <Sheet open={open} onClose={onClose} title="후보 지역 비교">
      <p className="muted">같은 기준(최신 분기 데이터)으로 나란히 봐요. 굵은 값이 이 중 가장 유리한 쪽이에요.</p>
      <label className="label" htmlFor="cmp-ind">업종별로 보기 (선택)</label>
      <select id="cmp-ind" className="select" value={ind} onChange={(e) => setInd(e.target.value)}>
        <option value="">전체 업종 평균만</option>
        {["외식업", "서비스업", "소매업"].map((c) => (
          <optgroup key={c} label={c}>
            {list.filter((i) => i.category === c).map((i) => <option key={i.code} value={i.code}>{i.name}</option>)}
          </optgroup>
        ))}
      </select>
      {addable.length > 0 && (
        <>
          <label className="label" htmlFor="cmp-add">비교할 구 추가{full ? " (최대 4곳)" : ""}</label>
          <div className="row" style={{ gap: 8 }}>
            <select id="cmp-add" className="select grow" value={pick} disabled={full} onChange={(e) => setPick(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && pick) { e.preventDefault(); add(); } }}>
              <option value="">{full ? "4곳까지 비교할 수 있어요" : "가까운 구부터 고르기"}</option>
              {addable.map((a) => <option key={a.code} value={a.code}>{a.name} · 구 중심 {pyFixed(a.km, 1)}km</option>)}
            </select>
            <button className="btn-small" onClick={add} disabled={!pick || full}>추가</button>
          </div>
        </>
      )}
      {/* 지금 고른 구 말고는 뺄 수 있다(기본 후보도 — 후보가 5곳 이상이면 다른 구로 바꿔 보게) */}
      {shownCodes.filter((c) => c !== selected).length > 0 && shownCodes.length > 1 && (
        <div className="tagchips" style={{ marginTop: 10 }}>
          {shownCodes.filter((c) => c !== selected).map((c) => (
            <button key={c} className="tag on" onClick={() => {
              if (extra.includes(c)) setExtra((x) => x.filter((y) => y !== c)); else setRemoved((x) => [...x, c]);
              requestAnimationFrame(() => document.getElementById("cmp-add")?.focus());
            }} aria-label={`${nameOf(c)} 비교에서 빼기`}>{nameOf(c)} ✕</button>
          ))}
        </div>
      )}
      {shownCodes.length < 2 && <p className="muted" style={{ marginTop: 12 }} role="status">비교할 구를 하나 이상 더 골라 주세요.</p>}
      {shownCodes.length >= 2 && err && <div className="notice warn" style={{ marginTop: 12 }}>{err}</div>}
      {shownCodes.length >= 2 && !err && !data && <div className="center-pad" style={{ padding: 24 }}><Spinner /></div>}
      {data && (
        <div id="cmp-table" tabIndex={-1} aria-label="비교표" role="region">
        <table className={`cmp${areas.length >= 4 ? " four" : ""}`}>
          <thead>
            <tr><th scope="col"><span className="sr-only">지표</span></th>
              {areas.map((a) => <th scope="col" key={a.area_code}>{a.area_name}{a.area_code === selected && <span className="muted small"><br />선택됨</span>}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const b = best(r);
              return (
                <tr key={r.label}>
                  <th scope="row">{r.label}{r.note && <span className="muted small"><br />{r.note}</span>}</th>
                  {areas.map((a) => {
                    const v = r.val(a), top = b != null && v === b;
                    const col = r.grade && a.industry ? GRADE_COLOR[a.industry.risk_grade] : undefined;
                    return <td key={a.area_code} className={top ? "best" : ""} style={col ? { color: col } : undefined}>
                      {r.show(a)}{top && <span className="sr-only"> (가장 유리)</span>}</td>;
                  })}
                </tr>
              );
            })}
            <tr>
              <th scope="row"><span className="sr-only">선택</span></th>
              {areas.map((a) => (
                <td key={a.area_code}>
                  <button className="btn-small" onClick={() => onPick(a)} disabled={a.area_code === selected}
                    aria-label={`${a.area_name} 선택`}>{a.area_code === selected ? "선택됨" : "선택"}</button>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
        </div>
      )}
    </Sheet>
  );
}
