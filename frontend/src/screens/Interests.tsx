import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { IconCheck, IconSearch, Screen, Sheet, useMounted } from "../components/ui";
import { buildAnalysisInput, categoriesOf } from "../lib/analysisInput";
import { analysisCache } from "../lib/cache";
import { josa } from "../lib/format";
import { useApp } from "../state/app";

/** 일상에서 쓰는 이름 → 데이터 업종명(서울시 상권분석서비스 분류). '약국'으로 찾으면 '의약품'이 나오게 */
const ALIASES: Record<string, string> = {
  CS100001: "한식 백반 식당 밥집 고기 고깃집 삼겹살 국밥 돼지국밥 순대국밥 족발 보쌈 곱창 냉면 국수 칼국수 순대 순대국 순댓국 도시락", CS100002: "중국집 짜장 짜장면 짬뽕 중식 마라탕", CS100003: "초밥 스시 돈카츠 돈가스 돈까스 라멘 우동 일식 횟집", CS100004: "파스타 레스토랑 피자 양식 샐러드 브런치 쌀국수",
  CS100005: "빵집 베이커리 케이크 디저트 떡집 떡 도넛", CS100006: "햄버거 버거 패스트푸드", CS100007: "치킨 통닭", CS100008: "떡볶이 김밥 분식",
  CS100009: "술집 호프 주점 포차 포장마차 이자카야 맥주 와인바 수제맥주 막걸리 펍", CS100010: "카페 커피 음료 디저트카페 찻집 버블티 주스 스무디 아이스크림",
  CS200001: "학원 보습 입시 공부방 수학 국어 과학 코딩", CS200002: "영어학원 어학원", CS200003: "미술학원 음악학원 피아노", CS200005: "태권도 체육관 수영",
  CS200006: "병원 의원 내과 소아과", CS200007: "치과", CS200008: "한의원", CS200024: "헬스 헬스장 헬스클럽 피트니스 필라테스 요가 짐 크로스핏 스포츠",
  CS200025: "카센터 정비 자동차정비", CS200026: "세차 광택", CS200028: "헤어 미용 헤어샵 미장원 머리방 이발소 이발 바버샵 바버", CS200029: "네일 네일아트", CS200030: "피부 피부관리 에스테틱 뷰티",
  CS200016: "당구 포켓볼", CS200017: "골프 스크린골프", CS200019: "피시방 피씨방 게임방", CS200037: "코인노래방 노래연습장",
  CS200032: "가전수리 수리점", CS300003: "컴퓨터 노트북", CS300006: "쌀집 쌀", CS300010: "반찬", CS300019: "의료기",
  CS300027: "침구 이불 원단", CS300031: "가구점", CS300032: "가전 전자제품", CS300036: "조명", CS200031: "빨래방 코인세탁 코인빨래방 셀프빨래방", CS200033: "부동산 공인중개 공인중개사", CS200034: "모텔 숙박 여관", CS200036: "원룸 고시텔",
  CS300001: "마트 식료품 동네마트 구멍가게", CS300002: "편의점", CS300004: "휴대폰 핸드폰 통신 폰", CS300007: "정육점", CS300008: "생선가게 수산",
  CS300009: "과일가게 채소", CS300011: "옷가게 의류 옷집 속옷", CS300014: "신발가게", CS300016: "안경점 렌즈 콘택트렌즈", CS300017: "금은방 귀금속 시계 주얼리 액세서리",
  CS300018: "약국 약", CS300020: "서점 책방", CS300021: "문구점 문방구 팬시", CS300022: "화장품가게 코스메틱", CS300024: "스포츠용품 골프용품 낚시 캠핑 등산",
  CS300025: "자전거", CS300026: "장난감", CS300028: "꽃집 꽃가게 화원 식물", CS300029: "펫샵 애견 반려동물 애완 애견미용 펫미용", CS300033: "철물 공구",
  CS300043: "온라인 온라인쇼핑몰 쇼핑몰 스마트스토어 인터넷",
};
const norm = (s: string) => s.replace(/[\s\-/·・]+/g, "").toLowerCase();   // '커피음료'·'커피 음료'도 '커피-음료'로
// 이름·별칭 뒤에 붙는 말(커피숍 = 커피 + 숍, 치킨집 = 치킨 + 집, 안경점 = 안경 + 점) — '동물병원'이 '병원', '피부과'가 '피부'로
// 잘못 걸리지 않게 이것만 허용. '학원'은 학원 업종에만(컴퓨터학원이 컴퓨터 판매로 가지 않게)
const TAILS = ["숍", "샵", "집", "점", "가게", "방", "실", "장", "전문점", "당", "센터", "매장", "몰"];
const ACADEMY = new Set(["CS200001", "CS200002", "CS200003", "CS200005", "CS200024"]);
const tailsOf = (code: string) => (ACADEMY.has(code) ? [...TAILS, "학원"] : TAILS);
const withTail = (q: string, w: string, code: string) => q.startsWith(w) && tailsOf(code).includes(q.slice(w.length));
/** 검색어에 맞는 별칭(없으면 null): 별칭이 검색어로 시작하거나, 검색어가 '별칭 + 흔한 꼬리말'일 때(부분 문자열로는 맞추지 않는다) */
const aliasHit = (code: string, q: string) => (ALIASES[code] || "").split(" ").filter(Boolean)
  .find((a) => a.startsWith(q) || withTail(q, a, code)) || null;
const matches = (i: { code: string; name: string }, f: string) => {
  const q = norm(f), n = norm(i.name);
  return !q || n.includes(q) || withTail(q, n, i.code) || aliasHit(i.code, q) !== null;
};

// SB-04 관심 업종 선택
export default function Interests() {
  const { api, draft, setDraft, industries, role, toast, meta } = useApp();
  const nav = useNavigate();
  const mounted = useMounted();
  const [busy, setBusy] = useState(false);
  const [sheet, setSheet] = useState(false);
  const [filter, setFilter] = useState("");
  const groups = industries?.groups || [];
  const nameOf = useMemo(() => new Map((industries?.industries || []).map((i) => [i.code, i.name])), [industries]);
  // 묶음 칩이 켜진(묶음 전체를 고른) 업종 말고는 따로 태그로 보여준다 — 치킨·호프에서 호프만 빼면 치킨이 태그로 남는다
  const fullGroupCodes = new Set(groups.filter((g) => g.codes.every((c) => draft.interests.includes(c))).flatMap((g) => g.codes));
  const extra = draft.interests.filter((c) => !fullGroupCodes.has(c));
  const cats = categoriesOf(draft.interests, industries);

  const MAX = 20;                                   // 서버 제한(app/schemas.py AnalysisIn.interests)과 같게
  function toggleGroup(codes: string[]) {
    const on = codes.every((c) => draft.interests.includes(c));
    const next = on ? draft.interests.filter((c) => !codes.includes(c)) : Array.from(new Set([...draft.interests, ...codes]));
    if (!on && next.length > MAX) { toast(`관심 업종은 ${MAX}개까지 고를 수 있어요`); return; }
    setDraft({ interests: next });
  }
  function toggleCode(code: string) {
    if (!draft.interests.includes(code) && draft.interests.length >= MAX) { toast(`관심 업종은 ${MAX}개까지 고를 수 있어요`); return; }
    setDraft({ interests: draft.interests.includes(code) ? draft.interests.filter((c) => c !== code) : [...draft.interests, code] });
  }
  async function start() {
    if (!draft.area) { toast("먼저 상권을 골라 주세요"); nav("/area"); return; }
    // 주소로 바로 들어오거나 조건 칸을 비운 채 돌아와도 필수 조건 없이 분석하지 않는다(6.1.4 필수 입력값)
    if (!draft.budget || !draft.rent || !draft.labor) { toast("창업 조건을 먼저 입력해 주세요"); nav("/conditions"); return; }
    setBusy(true);
    try {
      const a = await api.createAnalysis(buildAnalysisInput(draft, role, industries));
      analysisCache.set(a.id, a);
      if (mounted.current) nav(`/analysis/${a.id}`);          // 기다리는 동안 다른 화면으로 옮겼으면 끌고 가지 않는다
    } catch (e: any) {
      toast(e.message);
      const condFields = ["budget", "monthly_rent_limit", "labor_cost", "initial_investment", "other_fixed", "owner_salary",
        "loan_amount", "loan_rate_annual", "licenses", "cogs_rates"];
      if (mounted.current && e.fields?.some((f: any) => condFields.includes(f.field))) nav("/conditions");
    } finally { if (mounted.current) setBusy(false); }
  }
  // 추천 대상이 될 수 있는 업종만(카드 매출이 있는 구 5곳 이상) — 부동산중개업·고시원처럼 늘 '추천 제외'가 되는 업종은 빼기
  const pickable = (industries?.industries || []).filter((i) => i.recommendable ?? i.has_sales_data);
  const list = pickable.filter((i) => matches(i, filter));
  // 목록에는 없지만 이름으로는 맞는 업종(부동산중개업·고시원·동물병원처럼 카드 매출이 부족한 업종) — '다른 이름으로 찾아보세요'가 아니라 이유를
  const unlisted = !filter.trim() ? [] : (industries?.industries || []).filter((i) => !pickable.includes(i) && matches(i, filter));
  const unlistedMsg = unlisted.length ? `${josa(unlisted.slice(0, 2).map((i) => i.name).join("·") + (unlisted.length > 2 ? " 등" : ""), "은/는")} 서울 여러 구의 카드 매출 데이터가 부족해 추천·비교 대상에서 뺐어요.` : "";
  const byCat = ["외식업", "서비스업", "소매업"].map((c) => ({ cat: c, items: list.filter((i) => i.category === c) }));

  return (
    <Screen title="관심 업종 선택" back="/conditions" step={3}
      cta={<button className="btn-primary" onClick={start} disabled={busy || !industries}>{busy ? "분석 중…" : draft.interests.length ? "분석 시작" : "건너뛰고 자동 추천"}</button>}>
      <p className="lead">관심 업종을 고르거나, 건너뛰면 자동 추천해드려요.</p>
      <div className="chips c2">
        {groups.map((g) => {
          const on = g.codes.every((c) => draft.interests.includes(c));
          return (
            <button key={g.group} className={`chip ind-chip${on ? " on" : ""}`} aria-pressed={on} onClick={() => toggleGroup(g.codes)}>
              <span className="dot" style={{ background: g.color + "22" }}><i style={{ background: g.color }} /></span>
              <span className="nm">{g.group}</span>
              {on && <span className="check-mark"><IconCheck /></span>}
            </button>
          );
        })}
      </div>
      {extra.length > 0 && (
        <div className="tagchips" style={{ marginTop: 12 }}>
          {extra.map((c) => <button key={c} className="tag on" onClick={() => toggleCode(c)} aria-label={`${nameOf.get(c)} 선택 해제`}>{nameOf.get(c)} ✕</button>)}
        </div>
      )}
      <button className="btn-text" style={{ marginTop: 14 }} onClick={() => setSheet(true)}>＋ 전체 업종에서 고르기 ({pickable.length}개)</button>
      {draft.interests.length > 0 && (
        <label className="switch" style={{ marginTop: 14 }}>
          <span><b style={{ fontSize: 14 }}>같은 분야에서만 추천</b><br /><span className="muted">{cats.join("·")} 안에서 TOP 5를 골라요</span></span>
          <input type="checkbox" checked={draft.sameCategoryOnly} onChange={(e) => setDraft({ sameCategoryOnly: e.target.checked })} />
        </label>
      )}
      <div className="notice" style={{ marginTop: 16 }}>
        <b>추천은 이렇게 동작해요</b>
        <ul>
          <li>관심 업종을 직접 골라도 돼요 — 추천에서 빠져도 점수와 이유를 보여드려요</li>
          <li>건너뛰면 이 지역 매출·폐업 데이터와 내 월 고정비로 전체 업종에서 자동 추천</li>
          <li>최종적으로 적합 업종 TOP 5를 제안</li>
          {(meta?.goals[draft.goal]?.F ?? 0) >= 0.4 && (
            <li>‘비용 적합도’는 원가율을 아는 분야만 계산돼요(외식업 평균 또는 조건 입력에서 넣은 분야) — 원가율 없는 분야가 후보에 섞이면 매출·안정성만으로 순위를 매겨요</li>
          )}
        </ul>
      </div>
      <Sheet open={sheet} onClose={() => setSheet(false)} title="전체 업종">
        <p className="muted">매출 데이터로 비교할 수 있는 {pickable.length}개 업종이에요(최대 20개 선택). 자격이 필요한 업종은 표시했어요.</p>
        <label className="field" style={{ margin: "12px 0" }}>
          <IconSearch /><input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="업종 검색 (예: 카페, 약국)" aria-label="업종 이름 검색" />
        </label>
        {list.length === 0 && <p className="muted wrap-any" role="status">{unlistedMsg
          || <>‘{filter.trim()}’에 맞는 업종이 없어요. 다른 이름(예: 카페 → 커피-음료)으로 찾아보세요.</>}</p>}
        {list.length > 0 && unlistedMsg && <p className="muted small wrap-any">{unlistedMsg}</p>}
        {byCat.map(({ cat, items }) => items.length > 0 && (
          <div key={cat}>
            <h3 className="label">{cat}</h3>
            <div className="tagchips">
              {items.map((i) => {
                const on = draft.interests.includes(i.code);
                const fq = norm(filter);
                const hint = fq && !norm(i.name).includes(fq) ? aliasHit(i.code, fq) : null;
                return <button key={i.code} className={`tag${on ? " on" : ""}`} aria-pressed={on} onClick={() => toggleCode(i.code)}>
                  {i.name}{hint ? `(${hint})` : ""}{i.license ? ` · ${i.license}` : ""}</button>;
              })}
            </div>
          </div>
        ))}
        <button className="btn-primary" style={{ width: "100%", marginTop: 20 }} onClick={() => setSheet(false)}>
          {draft.interests.length}개 선택 완료</button>
      </Sheet>
    </Screen>
  );
}
