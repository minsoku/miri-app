import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import type { BreakEven as BE, BreakEvenIn } from "../api";
import { ApiError } from "../api";
import { ErrorBox, Loading, MoneyField, Screen, Sheet, useMounted } from "../components/ui";
import { fromManwon, man, manwon, pct, PRESSURE_COLOR, ratioText, won, wonFloorBelow, withComma } from "../lib/format";
import { load, remove, save } from "../lib/storage";
import { forgetRequiredOnly, reflectedKey, rememberReflected, rememberRequiredOnly } from "../lib/cache";
import { useApp } from "../state/app";

type Overrides = Omit<BreakEvenIn, "industry_code">;
// API 키 → 화면 용어
const FIXED_LABEL: Record<string, string> = { 기타고정비: "기타 고정비", 감가상각: "초기 투자비 월 상각(60개월)", 대출이자: "대출 이자",
  대표자인건비: "목표 월수입" };
const memoKey = (id: string, code: string) => `miri.be.${id}.${code}`;           // 이 브라우저 탭에서 바꾼 값 기억
type Req = "cogs_rate" | "avg_ticket";                                            // 기본값이 없어 꼭 넣어야 했던 값
interface Memo { o: Overrides; req: Req[] }
const pick = (o: Overrides, keys: Req[]) => Object.fromEntries(keys.filter((k) => o[k] != null).map((k) => [k, o[k]])) as Overrides;

// SB-07 손익분기점 (v2: 26일 영업, 카드수수료, 달성배율)
export default function BreakEven() {
  const { id = "", code = "" } = useParams();
  const { api, toast, industries } = useApp();
  const nav = useNavigate();
  const loc = useLocation();
  const mounted = useMounted();
  const from = (loc.state as any)?.from as string | undefined;        // 리포트에서 열었으면 뒤로가기는 그 리포트로
  const backTo = from && from.startsWith("/report/") ? from : `/analysis/${id}/risk/${code}`;
  const origin = (loc.state as any)?.origin as string | undefined;     // 그 리포트를 연 곳(저장 리포트) — 돌아가면 리포트의 '뒤로'도 그쪽으로
  const backState = backTo === from && origin ? { from: origin } : undefined;
  const viaRisk = !!(loc.state as any)?.viaRisk;
  const indInfo = industries?.industries.find((i) => i.code === code);
  const indName = indInfo?.name, indCat = indInfo?.category;                        // 리포트 → 위험도 → 여기: 뒤로는 위험도 화면(기록)
  const savedId = Number(new URLSearchParams(loc.search).get("be")) || null;   // 리포트에 반영했던 계산을 열 때
  const [be, setBe] = useState<BE | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [over, setOver] = useState<Overrides>({});        // 지금까지 사용자가 바꾼 값(오류가 나도 누적 유지)
  const [required, setRequired] = useState<Req[]>([]);    // 원가율·객단가처럼 기본값이 없어 필수로 넣은 값(되돌려도 유지)
  const [edit, setEdit] = useState(false);
  const [busy, setBusy] = useState(false);
  const [cogsInput, setCogsInput] = useState("");
  const [varInput, setVarInput] = useState("");
  const [ticketInput, setTicketInput] = useState("");
  const last = useRef<{ be: BE | null; o: Overrides; req: Req[] }>({ be: null, o: {}, req: [] });   // 마지막으로 성공한 계산
  const savedKey = useRef<string | null>(null);            // 리포트에 반영했던 계산(?be=)의 입력값 — 지금 계산과 다른지 비교
  const NEEDS_INPUT = ["COGS_REQUIRED", "TICKET_REQUIRED", "VARIABLE_RATE_TOO_HIGH"];

  async function run(o: Overrides, req: Req[] = required) {
    const wasError = !!err;
    setLoading(true); setErr(null); setOver(o); setRequired(req);
    try {
      const b = await api.breakeven(id, { industry_code: code, ...o });
      setBe(b); last.current = { be: b, o, req };
      if (Object.keys(o).length) save(memoKey(id, code), { o, req } as Memo, true); else remove(memoKey(id, code), true);
      // 꼭 넣어야 했던 원가율·객단가만 넣고 분석 조건은 그대로인 계산이면 기억 — 반영하지 않고 돌아가 '대응 액션 보기'를 눌러도
      // 그 값으로. 판단은 서버가 알려 준 inputs(바꾼 값 changed·필수 입력 required)로('바꾼 값 적용 중' 표시와 같은 기준)
      const ch = (b.inputs?.changed || []) as string[], rq = (b.inputs?.required || []) as string[];
      if (b.id && !ch.length && rq.length) rememberRequiredOnly(id, code, b.id); else forgetRequiredOnly(id, code);
      if (wasError) requestAnimationFrame(() => document.querySelector<HTMLElement>(".topbar h1")?.focus());   // 입력 화면에서 돌아오면 제목으로
    } catch (e: any) {
      const ae = e instanceof ApiError ? e : new ApiError(0, { code: "X", message: e.message });
      if (last.current.be && !NEEDS_INPUT.includes(ae.code)) {
        // 값 범위 오류·네트워크 오류: 화면을 오류로 갈아엎지 않고 직전 결과를 유지한 채 알려준다(같은 값 '다시 시도' 막다른 길 방지)
        toast(ae.message); setOver(last.current.o); setRequired(last.current.req);
      } else {
        if (ae.code === "VARIABLE_RATE_TOO_HIGH") {
          // 서버가 계산에 쓴 값(분석 조건에서 넣은 원가율일 수도 있음)으로 칸을 채운다
          const used = (f: string) => (ae.fields.find((x: any) => x.field === f) as any)?.value as number | undefined;
          const cg = o.cogs_rate ?? used("cogs_rate"), ov = o.other_variable_rate ?? used("other_variable_rate");
          setCogsInput(cg != null ? String(Math.round(cg * 1000) / 10) : "");
          setVarInput(ov != null ? String(Math.round(ov * 1000) / 10) : "");
        }
        setErr(ae);
      }
    }
    finally { setLoading(false); }
  }
  useEffect(() => {
    if (!savedId) {                                       // 다시 들어와도 넣었던 원가율·객단가 유지
      const m = load<Memo | null>(memoKey(id, code), null, true);
      run(m?.o || {}, m?.req || []);
      return;
    }
    setLoading(true);
    api.getBreakeven(id, savedId).then((b) => {
      if (!b.inputs) { run({}); return; }             // 입력값이 없는 옛 기록 → 기본값으로 다시 계산
      const o = overridesOf(b);
      // 기본값이 없어 꼭 넣어야 했던 원가율·객단가만 '분석 조건으로'를 눌러도 유지 — 서버가 알려 준 목록(inputs.required),
      // 없는 옛 기록은 직접 넣은 원가율·객단가 모두
      const req = (Array.isArray(b.inputs.required) ? (b.inputs.required as Req[]) : (["cogs_rate", "avg_ticket"] as Req[]))
        .filter((k) => o[k] != null);
      setBe(b); setOver(o); setRequired(req); last.current = { be: b, o, req }; savedKey.current = inputsKey(b.inputs);
      setLoading(false);
    }).catch(() => run({}));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, code, savedId]);

  async function toReport() {
    if (!be || loading) return;                           // 다시 계산하는 중이면 이전 결과로 리포트를 만들지 않는다
    setBusy(true);
    try {
      const rep = await api.createReport(id, { industry_code: code, break_even_id: be.id || null });
      rememberReflected(id, code, be.id, inputsKey(be.inputs));   // 위험도 화면의 '대응 액션 보기'도 이 계산으로
      // 입력값이 같아 보던 리포트가 그대로 돌아오면, 그 리포트를 연 곳(저장 리포트)도 이어서 넘긴다
      // 리포트의 '뒤로'가 이 화면(손익분기)으로 오도록 fromBe를 넘긴다(저장 리포트에서 왔으면 그쪽을 먼저)
      // (?be=로 연 저장된 계산에서 새 값을 반영했으면 뒤로 와도 이 화면은 옛 계산을 다시 불러오므로 fromBe를 넘기지 않는다)
      if (mounted.current) nav(`/report/${rep.id}`, { state: from === `/report/${rep.id}` && origin ? { from: origin } : savedId ? {} : { fromBe: true } });
    } catch (e: any) { toast(e.message); } finally { if (mounted.current) setBusy(false); }
  }

  if (loading && !be) return <Screen title="손익분기점" back><Loading text="계산 중…" /></Screen>;
  if (err && (err.code === "COGS_REQUIRED" || err.code === "TICKET_REQUIRED" || err.code === "VARIABLE_RATE_TOO_HIGH")) {
    const needTicket = err.code === "TICKET_REQUIRED";
    const val = needTicket ? ticketInput : cogsInput;
    const tooHigh = err.code === "VARIABLE_RATE_TOO_HIGH";
    const title = needTicket ? "객단가가 필요해요" : tooHigh ? "원가율·수수료를 확인해 주세요" : "원가율이 필요해요";
    const key: Req = needTicket ? "avg_ticket" : "cogs_rate";
    const nextReq = required.includes(key) || err.code === "VARIABLE_RATE_TOO_HIGH" ? required : [...required, key];
    return (
      <Screen title="손익분기점" back={viaRisk ? true : backTo} backState={viaRisk ? undefined : backState}
        cta={<button className="btn-primary" onClick={() => {
          const v = Number(val.replace(/,/g, ""));
          // 원가율 0%(원가가 없는 서비스)는 다른 입력 화면처럼 받는다. 객단가는 100원 이상
          if (!val.trim() || !Number.isFinite(v) || v < 0 || (needTicket && v === 0)) {
            toast(needTicket ? "객단가를 입력해 주세요" : "원가율을 입력해 주세요"); return;
          }
          if (!needTicket && v >= 100) { toast("원가율은 100% 미만이어야 해요"); return; }
          if (needTicket && v < 100) { toast("객단가는 100원 이상으로 입력해 주세요"); return; }
          if (needTicket && v > 10_000_000) { toast("객단가는 1,000만원 이하로 입력해 주세요"); return; }
          const ov = Number((varInput || "0").replace(/,/g, ""));
          if (tooHigh && (!Number.isFinite(ov) || ov < 0 || ov >= 100)) { toast("배달·기타 수수료는 0~100% 미만으로 넣어 주세요"); return; }
          const r4 = (x: number) => Math.round(x * 100) / 10000;          // % → 비율(부동소수 찌꺼기 없이)
          const o = needTicket ? { ...over, avg_ticket: Math.round(v) }
            : tooHigh ? { ...over, cogs_rate: r4(v), other_variable_rate: r4(ov) } : { ...over, cogs_rate: r4(v) };
          run(o, nextReq);                                 // 앞서 넣은 값은 유지
        }}>계산하기</button>}>
        {indName && <p className="sub">{indName}{indCat ? ` · ${indCat}` : ""}</p>}   {/* 어느 업종의 원가율·객단가인지 */}
        <div className="notice" style={{ marginTop: 8 }} role="alert"><b>{title}</b>{err.message}</div>
        {!needTicket && over.avg_ticket && <p className="muted">객단가 ₩{over.avg_ticket.toLocaleString()} 적용 중</p>}
        {needTicket && over.cogs_rate != null && <p className="muted">원가율 {pct(over.cogs_rate)} 적용 중</p>}
        <label className="label" htmlFor={needTicket ? "ticket" : "cogs"}>{needTicket ? "객단가 (1회 결제 평균)" : "원가율 (매출 대비 재료·상품 원가)"}</label>
        {needTicket
          ? <MoneyField key="ticket" id="ticket" value={ticketInput} onChange={setTicketInput} suffix="원" integer placeholder="예: 15,000" autoFocus />
          : <MoneyField key="cogs" id="cogs" value={cogsInput} onChange={setCogsInput} prefix="" suffix="%" allowDecimal placeholder="예: 30" autoFocus
              hint="예: 미용실 10~20%, 편의점 70~75%처럼 업종마다 크게 달라요. 모르면 거래처 견적으로 추정해 주세요." />}
        {tooHigh && (<>
          <label className="label" htmlFor="var">배달·기타 수수료 (매출 대비)</label>
          <MoneyField id="var" value={varInput} onChange={setVarInput} prefix="" suffix="%" allowDecimal placeholder="0"
            hint="원가율 + 카드수수료 + 배달·기타 수수료가 100% 이상이면 팔수록 손해예요." />
        </>)}
      </Screen>
    );
  }
  if (err || !be) {
    return <Screen title="손익분기점" back>
      <ErrorBox message={err?.message || "계산하지 못했어요"} onRetry={err?.status === 404 ? undefined : () => run(over)} /></Screen>;
  }

  const c = be.composition;
  const ownerOn = c.owner_salary > 0;
  // 막대 숫자(만원)는 합계가 위 필요 매출과 맞게: 변동비 = 합계 − 고정비 − 목표 월수입 (각각 반올림하면 1만원 어긋날 수 있음)
  const totalM = man(c.total), fixedM = man(c.fixed_ex_owner), ownerM = man(c.owner_salary);
  const bars = [{ k: "고정비", v: fixedM, col: "var(--grey-bar)" }, { k: "변동비", v: Math.max(0, totalM - fixedM - ownerM), col: "var(--amber)" },
    ...(ownerOn ? [{ k: "목표 월수입", v: ownerM, col: "var(--blue)" }] : [])];   // 목표 월수입을 넣지 않았으면 0 막대는 그리지 않는다
  const maxBar = Math.max(...bars.map((x) => x.v), 1);
  const fb = be.fixed_breakdown, vb = be.variable_breakdown;
  // 필수로 넣은 원가율·객단가 말고 분석 조건과 다른 값이 있으면 '분석 조건으로' 버튼,
  // 그 값이 아직 리포트에 반영 전이면 '바꾼 값 적용 중'(리포트에 반영했던 계산을 그대로 연 경우는 '리포트에 반영한 값')
  // 서버가 알려 준 '기본값과 실제로 다른 항목'(inputs.changed) 기준 — 같은 값을 다시 넣었으면 바꾼 값이 아니다
  const changedKeys: string[] = Array.isArray(be.inputs.changed) ? be.inputs.changed : Object.keys(over);
  const changed = changedKeys.some((k) => !required.includes(k as Req));
  // 리포트에 반영했던 계산을 연 화면: 지금 값이 그 계산과 다르면(직접 넣은 원가율을 고친 경우 포함) 아직 반영 전이라고 알린다
  const diverged = !!savedId && be.id !== savedId && savedKey.current !== null && inputsKey(be.inputs) !== savedKey.current;
  // ?be= 없이 열었어도 지금 값이 이 탭에서 리포트에 반영한 값과 같으면 '반영 전'이라고 하지 않는다
  const rk = !savedId ? reflectedKey(id, code) : null;
  const reflectedNow = rk !== null && inputsKey(be.inputs) === rk;
  const edited = savedId ? diverged : changed && !reflectedNow;
  // 대형 점포 단서는 달성 가능성 카드 안에 이미 보이므로 아래 안내 목록에서는 뺀다(같은 말 두 번 방지)
  const warnList = be.sales_outlier != null && be.achievability_ratio != null
    ? be.warnings.filter((w) => !w.includes("중간값의")) : be.warnings;
  return (
    <Screen title="손익분기점" back={viaRisk ? true : backTo} backState={viaRisk ? undefined : backState}
      cta={<button className="btn-primary" onClick={toReport} disabled={busy || loading}>{busy ? "반영 중…" : loading ? "계산 중…" : "리포트에 반영"}</button>}>
      <p className="sub">{be.area_name} · {be.industry_name} · 월 {be.operating_days}일 영업 기준</p>
      <div className="hero">
        <div style={{ color: "var(--text-2)", fontWeight: 600 }}>{ownerOn ? "목표 월수입까지 벌려면 매달 필요한 매출" : "손해 보지 않으려면 매달 필요한 매출"}</div>
        <div className="big">{won(be.required_monthly_sales)}</div>
        {ownerOn && <div className="muted">목표 월수입 {won(c.owner_salary)} 포함</div>}
      </div>
      <div className="stat2">
        <div className="card"><b>{be.required_daily_customers.toLocaleString()}건</b><span className="muted">하루 필요 결제</span></div>
        <div className="card"><b>₩{be.avg_ticket_used.toLocaleString()}</b><span className="muted">객단가{ticketNote(be)}</span></div>
      </div>
      {be.achievability_ratio != null && (
        <div className="card" style={{ marginTop: 12 }}>
          <div className="between">
            <h2 className="h2 plain" style={{ fontSize: 16, margin: 0 }}>달성 가능성</h2>
            <span className="badge" style={{ background: PRESSURE_COLOR[be.cost_pressure || "보통"], color: "#fff" }}>
              {be.cost_pressure}{be.sales_outlier != null ? "(참고용)" : ""}</span>
          </div>
          {be.sales_outlier != null && (      // SB-05에서 추천 제외한 이유와 같은 단서를 배율 바로 옆에
            <p className="small" style={{ margin: "6px 0 0", color: "var(--amber-text)" }}>
              이 지역 평균 매출은 서울 같은 업종 중간값의 {be.sales_outlier.toFixed(1)}배라 대형 점포가 섞였을 수 있어요 — 배율·투자 회수는 참고용이에요.</p>
          )}
          <p style={{ margin: "8px 0 0", color: "var(--text-2)" }}>
            이 지역 같은 업종 점포 평균 매출 <b>{won(be.market_sales_ps_m)}</b>은 {ownerOn ? "필요 매출(목표 월수입 포함)" : "손익분기"}의 <b>{ratioText(be.achievability_ratio)}</b>{ratioText(be.achievability_ratio).endsWith("미만") ? "이에요" : "예요"}.
            {be.achievability_ratio < 1 && be.max_fixed_for_bep
              ? (ownerOn && wonFloorBelow(be.max_fixed_for_bep, be.monthly_fixed_cost) < c.owner_salary
                ? " 다른 비용을 모두 줄여도 평균 매출로는 목표 월수입을 채우기 어려워요 — 목표를 낮추거나 매출이 더 나는 업종·입지를 검토하세요."
                : ownerOn ? ` 목표 월수입까지 벌려면 월 고정비(목표 월수입 포함)를 ${won(wonFloorBelow(be.max_fixed_for_bep, be.monthly_fixed_cost))} 이하로 낮춰야 해요.`
                : ` 평균 매출로 버티려면 월 고정비를 ${won(wonFloorBelow(be.max_fixed_for_bep, be.monthly_fixed_cost))} 이하로 낮춰야 해요.`) : ""}
          </p>
          {be.payback_months != null ? <div className="kv"><span>평균 매출일 때 투자 회수</span>
            <b>{be.payback_months > 60 || be.achievability_ratio < 1 ? "5년 안에 회수 어려움" : `약 ${be.payback_months.toLocaleString()}개월`}</b></div>
            : (be.fixed_breakdown?.["감가상각"] ?? 0) > 0 && be.market_sales_ps_m != null && (   // 평균 매출로는 남는 돈이 없거나 100년 넘게 걸림
              <div className="kv"><span>평균 매출일 때 투자 회수</span><b>평균 매출로는 회수 어려움</b></div>)}
          {be.market_tx_ps_day != null && <div className="kv"><span>이 지역 점포당 하루 결제</span><b>{be.market_tx_ps_day.toLocaleString("ko-KR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}건</b></div>}
          {be.customers_vs_market != null && be.customers_vs_market >= 1.2 && be.inputs.ticket_source !== "user" && (
            // 입력 객단가 때문인 경우는 서버가 아래 안내에 같은 내용을 넣으므로 여기서는 지역 평균 객단가일 때만
            <p className="small" style={{ margin: "4px 0 0", color: "var(--amber-text)" }}>
              하루 필요 결제({be.required_daily_customers.toLocaleString()}건)가 이 지역 점포 평균보다 많아요.
            </p>
          )}
          <p className="muted small" style={{ margin: "6px 0 0" }}>평균 매출·결제 건수는 서울시 상권분석서비스의 카드 매출 기준 추정치예요.</p>
        </div>
      )}
      <div className="card" style={{ marginTop: 12 }}>
        <div className="between">
          <h2 className="h2 plain" style={{ fontSize: 16, margin: 0 }}>입력값</h2>
          <div className="row">
            {changed && <button className="btn-small" onClick={() => {
              // 누른 버튼이 사라지므로 포커스를 '수정'으로 옮긴다(키보드 사용자가 화면 맨 위로 튀지 않게)
              run(pick(over, required)).then(() => requestAnimationFrame(() => document.getElementById("be-edit-btn")?.focus()));
            }}>분석 조건으로</button>}
            <button className="btn-small" id="be-edit-btn" onClick={() => setEdit(true)}>수정</button>
          </div>
        </div>
        {edited && <p className="muted small" style={{ margin: "6px 0 0" }}>
          {savedId ? "리포트에 반영한 계산과 다른 값이에요" : "바꾼 값 적용 중"} — 리포트에 반영하기 전에는 이 화면에서만 쓰여요.</p>}
        {(savedId || reflectedNow) && !edited && changed && <p className="muted small" style={{ margin: "6px 0 0" }}>리포트에 반영한 값이에요 — 분석 조건과 다른 값이 들어 있어요.</p>}
        <details style={{ marginTop: 4 }}>
          <summary className="kv" style={{ cursor: "pointer", listStyle: "none" }}>
            <span>{ownerOn ? "월 고정비 + 목표 월수입" : "월 고정비"} ▾</span><b>{won(be.monthly_fixed_cost)}</b></summary>
          {Object.entries(fb).filter(([, v]) => v > 0).map(([k, v]) => (
            <div className="kv small" key={k} style={{ paddingLeft: 12 }}><span>{FIXED_LABEL[k] || k}</span><span>{won(v)}</span></div>
          ))}
        </details>
        <div className="kv"><span>변동비율</span><b>{pct(be.variable_cost_rate)}</b></div>
        <div className="muted small" style={{ marginTop: -4 }}>
          원가율 {pct(vb["원가율"])}{be.inputs.cogs_is_default ? "(업종 평균)" : be.inputs.cogs_source === "analysis" ? "(조건 입력값)" : ""} + 카드수수료 {pct(vb["카드수수료"], 2)}{vb["기타"] ? ` + 기타 ${pct(vb["기타"])}` : ""}
        </div>
        <div className="kv"><span>객단가</span><b>₩{be.avg_ticket_used.toLocaleString()}</b></div>
        {/* '계산식을 보여 주세요'에 화면에서 바로 답할 수 있게 */}
        <p className="muted small" style={{ margin: "6px 0 0" }}>
          필요 월매출 = 월 고정비{ownerOn ? "(목표 월수입 포함)" : ""} {won(be.monthly_fixed_cost)} ÷ (1 − 변동비율 {pct(be.variable_cost_rate)}) ≈ {won(be.required_monthly_sales)}</p>
      </div>
      <div className="card" style={{ marginTop: 12 }}>
        <h2 className="h2 plain" style={{ fontSize: 16, margin: 0 }}>필요 매출 구성 <span className="muted">(단위 만원 · 합계 {won(c.total)})</span></h2>
        <div className="bars3" style={{ gridTemplateColumns: `repeat(${bars.length}, minmax(0, 1fr))` }}>   {/* 목표 월수입 막대가 없으면 빈 칸 없이 */}
          {bars.map((x) => (
            <div className="col" key={x.k}>
              <b>{x.v.toLocaleString()}</b>
              <i style={{ height: `${(x.v / maxBar) * 100}px`, background: x.col }} />
              <span>{x.k}</span>
            </div>
          ))}
        </div>
      </div>
      {warnList.length > 0 && (
        <div className="notice" style={{ marginTop: 12 }}><ul>{warnList.map((w) => <li key={w}>{w}</li>)}</ul></div>
      )}
      <EditSheet open={edit} be={be} over={over} onClose={() => setEdit(false)} onApply={(o) => { setEdit(false); run(o); }} />
    </Screen>
  );
}

/** 원가율·수수료 칸의 오류 표시 대상: 100% 이상이거나 숫자가 아님('.'만 넣은 경우 등) */
const has100 = (s?: string) => { if (!s || s.trim() === "") return false; const n = Number(s.replace(/,/g, "")); return !Number.isFinite(n) || n >= 100; };
/** 계산에 쓴 입력값 비교 키(표시용 항목은 빼고, 소수는 9자리에서 반올림) — 리포트에 반영한 계산과 같은지 */
const KEY_FIELDS = ["monthly_rent", "labor_cost", "other_fixed", "initial_investment", "loan_amount", "loan_rate_annual",
  "owner_salary", "cogs_rate", "other_variable_rate", "avg_ticket", "ticket_source"];
const inputsKey = (i: Record<string, any>) => JSON.stringify(KEY_FIELDS.map((k) => (typeof i[k] === "number" ? Math.round(i[k] * 1e9) / 1e9 : i[k] ?? null)));
/** 객단가 출처 표시 */
const ticketNote = (be: BE) => (be.inputs.ticket_source === "seoul" ? " (서울 업종 평균)" : be.inputs.ticket_is_market ? " (이 지역 평균)" : "");

/** 저장된 계산의 입력값 → 다시 계산할 때 쓸 덮어쓰기 값(그 계산에서 실제로 바꿨던 항목만) */
function overridesOf(b: BE): Overrides {
  const i = b.inputs;
  if (Array.isArray(i.overridden)) {
    return Object.fromEntries((i.overridden as string[]).filter((k) => i[k] != null).map((k) => [k, i[k]])) as Overrides;
  }
  // 'overridden'이 없는 옛 기록: 모든 금액을 덮어쓴 값으로 본다
  const o: Overrides = { monthly_rent: i.monthly_rent, labor_cost: i.labor_cost, other_fixed: i.other_fixed,
    initial_investment: i.initial_investment, loan_amount: i.loan_amount, loan_rate_annual: i.loan_rate_annual,
    owner_salary: i.owner_salary, other_variable_rate: i.other_variable_rate };
  if (!i.cogs_is_default && i.cogs_source !== "analysis") o.cogs_rate = i.cogs_rate;
  if (!i.ticket_is_market && i.avg_ticket) o.avg_ticket = i.avg_ticket;
  return o;
}

function EditSheet({ open, be, over, onClose, onApply }: { open: boolean; be: BE; over: Overrides; onClose(): void; onApply(o: Overrides): void }) {
  const i = be.inputs;
  const fresh = (): Record<string, string> => ({
    rent: withComma(manwon(i.monthly_rent)), labor: withComma(manwon(i.labor_cost)), other: withComma(manwon(i.other_fixed)),
    inv: withComma(manwon(i.initial_investment)), owner: withComma(manwon(i.owner_salary)),
    loan: withComma(manwon(i.loan_amount)), rate: String(Math.round((i.loan_rate_annual || 0) * 10000) / 100),
    cogs: String(Math.round(i.cogs_rate * 1000) / 10), otherVar: String(Math.round((i.other_variable_rate || 0) * 1000) / 10),
    ticket: i.ticket_is_market ? "" : withComma(String(be.avg_ticket_used), false),
  });
  const [f, setF] = useState<Record<string, string>>(fresh);
  const [dirty, setDirty] = useState<Set<string>>(new Set());     // 사용자가 실제로 고친 칸
  const [rateErr, setRateErr] = useState<string | null>(null);
  const [moneyErr, setMoneyErr] = useState<string | null>(null);        // 1,000억 원을 넘는 금액 칸
  const [ticketErr, setTicketErr] = useState<string | null>(null);
  // 열릴 때(또는 열린 채 계산 결과가 바뀔 때) 값을 렌더 중에 바로 채운다 — 효과(useEffect)로 채우면 첫 화면에 빈 칸이 잠깐 보이고
  // 그 사이 입력한 글자가 채운 값 뒤에 붙는다(300 → 300200)
  const [seen, setSeen] = useState<{ open: boolean; be: BE }>({ open, be });
  if (seen.open !== open || (open && seen.be !== be)) {
    setSeen({ open, be });
    if (open) { setF(fresh()); setDirty(new Set()); setRateErr(null); setMoneyErr(null); setTicketErr(null); }
  }
  const set = (k: string) => (v: string) => { setF((s) => ({ ...s, [k]: v })); setDirty((d) => new Set(d).add(k)); };
  const mErr = (k: string) => (moneyErr === k ? (k === "rate" ? "연이율은 0~30 사이로 넣어 주세요" : "금액이 너무 커요 (1,000억 원 이하)") : null);
  function apply() {
    const has = (s?: string) => !!s && s.trim() !== "";
    const num = (s: string) => Number(s.replace(/,/g, ""));
    const bad = (["cogs", "otherVar"] as const).find((k) => has(f[k]) && !Number.isFinite(num(f[k])));
    if (bad) {                                           // '.'만 넣은 칸을 조용히 기본값으로 바꾸지 않는다
      setRateErr("원가율·수수료는 숫자로 넣어 주세요");
      requestAnimationFrame(() => document.getElementById(bad === "cogs" ? "be-cogs" : "be-var")?.focus());
      return;
    }
    if ((has(f.cogs) && num(f.cogs) >= 100) || (has(f.otherVar) && num(f.otherVar) >= 100)) {
      setRateErr("원가율·수수료는 100% 미만으로 넣어 주세요");       // 조용히 99%로 바꾸지 않는다
      requestAnimationFrame(() => document.getElementById(num(f.cogs) >= 100 ? "be-cogs" : "be-var")?.focus());
      return;
    }
    if (has(f.ticket) && (num(f.ticket) < 100 || num(f.ticket) > 10_000_000)) {    // 서버 범위(100원~1,000만원)를 화면에서 먼저
      setTicketErr(num(f.ticket) < 100 ? "객단가는 100원 이상으로 넣어 주세요" : "객단가는 1,000만원 이하로 넣어 주세요");
      requestAnimationFrame(() => document.getElementById("be-ticket")?.focus());
      return;
    }
    // 고친 칸만 새 값으로 보낸다. 손대지 않은 칸은 지금 쓰는 값 그대로(앞서 바꾼 값은 정확한 원 단위로, 아니면 분석 조건) —
    // 화면의 만원 단위 표시값을 다시 보내면 100원 단위가 반올림돼 안 고친 칸 때문에 결과가 바뀌고 '바꾼 값'으로 잡힌다.
    const o: Overrides = { ...over };
    const money: [string, keyof Overrides][] = [["rent", "monthly_rent"], ["labor", "labor_cost"], ["other", "other_fixed"],
      ["inv", "initial_investment"], ["owner", "owner_salary"], ["loan", "loan_amount"]];
    const rateV = has(f.rate) ? num(f.rate) : 0;
    if (!Number.isFinite(rateV) || rateV < 0 || rateV > 30) {
      setRateErr(null); setMoneyErr("rate"); requestAnimationFrame(() => document.getElementById("be-rate")?.focus());
      return;
    }
    for (const [k, key] of money) {                  // 금액 칸을 비우면 0원(되돌리려면 '분석 조건으로' 버튼)
      if (!dirty.has(k)) continue;
      const v = fromManwon(f[k] || "");
      if (Number.isFinite(v) && v > 1e11) {
        setMoneyErr(k); requestAnimationFrame(() => document.getElementById(`be-${k}`)?.focus());
        return;
      }
      if (Number.isFinite(v)) (o as any)[key] = v;
    }
    if (dirty.has("rate")) o.loan_rate_annual = Math.round(rateV * 100) / 10000;
    // 원가율·수수료·객단가는 비우면 기본값(조건 입력값·업종 평균·지역 평균)으로 → 덮어쓴 값을 뺀다
    // % → 비율: 40.7 / 100 = 0.40700000000000003 같은 부동소수 찌꺼기 없이(조건 입력 SB-03과 같게 소수 넷째 자리)
    const toRate = (v: number) => Math.round(v * 100) / 10000;
    const setRate = (k: string, key: "cogs_rate" | "other_variable_rate") => {
      if (!dirty.has(k)) return;
      if (has(f[k]) && Number.isFinite(num(f[k]))) o[key] = toRate(num(f[k])); else delete o[key];
    };
    setRate("cogs", "cogs_rate");
    setRate("otherVar", "other_variable_rate");
    if (dirty.has("ticket")) { if (has(f.ticket) && num(f.ticket) >= 100) o.avg_ticket = Math.round(num(f.ticket)); else delete o.avg_ticket; }
    onApply(o);
  }
  return (
    <Sheet open={open} onClose={onClose} title="입력값 수정">
      <p className="muted">바꾼 값으로 다시 계산해요. 금액 칸을 비우면 0원이고, 원가율·객단가를 비우면 기본값(조건에서 넣은 원가율 또는 업종 평균,
        이 지역 또는 서울 평균 객단가)을 써요.</p>
      <div className="grid2">
        <div><label className="label" htmlFor="be-rent">월 임대료</label><MoneyField id="be-rent" value={f.rent || ""} onChange={set("rent")} error={mErr("rent")} /></div>
        <div><label className="label" htmlFor="be-labor">월 인건비</label><MoneyField id="be-labor" value={f.labor || ""} onChange={set("labor")} error={mErr("labor")} /></div>
        <div><label className="label" htmlFor="be-other">기타 고정비</label><MoneyField id="be-other" value={f.other || ""} onChange={set("other")} error={mErr("other")} /></div>
        <div><label className="label" htmlFor="be-inv">초기 투자비</label><MoneyField id="be-inv" value={f.inv || ""} onChange={set("inv")} error={mErr("inv")} /></div>
      </div>
      <label className="label" htmlFor="be-owner">목표 월수입 (대표자)</label><MoneyField id="be-owner" value={f.owner || ""} onChange={set("owner")} error={mErr("owner")} />
      <div className="grid2">
        <div><label className="label" htmlFor="be-loan">대출금</label><MoneyField id="be-loan" value={f.loan || ""} onChange={set("loan")} error={mErr("loan")} /></div>
        <div><label className="label" htmlFor="be-rate">연이율</label><MoneyField id="be-rate" value={f.rate || ""} onChange={set("rate")} prefix="" suffix="%"
          allowDecimal error={mErr("rate")} /></div>
      </div>
      <div className="grid2">
        <div><label className="label" htmlFor="be-cogs">원가율</label><MoneyField id="be-cogs" value={f.cogs || ""} onChange={set("cogs")} prefix="" suffix="%" allowDecimal
          error={rateErr && has100(f.cogs) ? rateErr : null} /></div>
        <div><label className="label" htmlFor="be-var">배달·기타 수수료</label><MoneyField id="be-var" value={f.otherVar || ""} onChange={set("otherVar")} prefix="" suffix="%" allowDecimal
          error={rateErr && has100(f.otherVar) ? rateErr : null} /></div>
      </div>
      <label className="label" htmlFor="be-ticket">객단가</label>
      <MoneyField id="be-ticket" value={f.ticket || ""} onChange={(v) => { set("ticket")(v); setTicketErr(null); }} suffix="원" integer
        error={ticketErr}
        placeholder={i.ticket_is_market ? `${i.ticket_source === "seoul" ? "서울" : "지역"} 평균 ${be.avg_ticket_used.toLocaleString()}` : "비우면 평균값"} />
      <button className="btn-primary" style={{ width: "100%", marginTop: 20 }} onClick={apply}>다시 계산</button>
    </Sheet>
  );
}
