import { ReactNode, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useNavigationType } from "react-router-dom";
import { withComma } from "../lib/format";

export const IconBack = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M15 5l-7 7 7 7" /></svg>
);
export const IconSearch = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></svg>
);
export const IconCheck = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
);
export const IconList = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" /></svg>
);

/** 앱 안의 이동 기록(주소·키). 화면 왼쪽 위 '뒤로'가 정해진 화면으로 갈 때, 바로 앞 기록이 그 화면이면 브라우저 뒤로(-1)로 가고
 *  아니면 지금 기록을 그 화면으로 바꾼다 — 화살표를 누를 때마다 기록이 쌓여 휴대폰 '뒤로'가 앞으로 되돌아가지 않게 */
const trail: { key: string; path: string }[] = [];
let trailIdx = -1;
// 새로고침해도 이 탭의 이동 기록을 이어 쓴다(React Router가 기록마다 key를 history.state에 남기므로 key로 다시 찾을 수 있다).
// 저장소를 못 쓰는 환경(사생활 보호 모드·미리보기)에서는 예전처럼 새로 연 것으로 본다
const TRAIL_KEY = "miri.trail";
try {
  const o = JSON.parse(sessionStorage.getItem(TRAIL_KEY) || "null");
  if (o && Array.isArray(o.t) && o.t.every((x: any) => x && typeof x.key === "string" && typeof x.path === "string")) {
    trail.push(...o.t);
    trailIdx = Math.min(Math.max(-1, Number(o.i) | 0), trail.length - 1);
  }
} catch { /* 저장소 없음 */ }
function saveTrail() {
  if (trail.length > 100) { const d = trail.length - 100; trail.splice(0, d); trailIdx = Math.max(0, trailIdx - d); }
  try { sessionStorage.setItem(TRAIL_KEY, JSON.stringify({ t: trail, i: trailIdx })); } catch { /* 저장소 없음 */ }
}
export function HistoryTracker() {
  const loc = useLocation();
  const type = useNavigationType();
  useEffect(() => {
    const cur = { key: loc.key, path: loc.pathname };
    if (trailIdx >= 0 && trail[trailIdx].key === loc.key) { trail[trailIdx] = cur; saveTrail(); return; }   // 같은 기록(효과가 두 번 돈 경우)
    if (type === "POP") {
      const i = loc.key === "default" ? -1 : trail.findIndex((t) => t.key === loc.key);   // 'default' = 주소를 직접 연 기록(구별 불가)
      if (i >= 0) trailIdx = i;
      else { trail.length = 0; trail.push(cur); trailIdx = 0; }         // 새로 열거나 새로고침: 앱 밖 기록은 모른다
    } else if (type === "REPLACE" && trailIdx >= 0) {
      trail[trailIdx] = cur;
    } else {
      trail.splice(trailIdx + 1); trail.push(cur); trailIdx = trail.length - 1;
    }
    saveTrail();
  }, [loc.key, loc.pathname, type]);
  return null;
}
/** 바로 앞 기록의 화면 주소(앱 안에서 모르면 null) */
export const prevPath = (): string | null => (trailIdx > 0 ? trail[trailIdx - 1].path : null);
/** 정해진 화면으로 돌아가기(뒤로 화살표·'리포트로 돌아가기'): 바로 앞 기록이 그 화면이면 기록을 되감고(그 화면의 상태도 그대로),
 *  아니면 지금 기록을 그 화면으로 바꾼다. target이 없으면(브라우저 뒤로) 앱 안의 앞 기록이 없을 때 지역 선택 화면으로 */
export function useGoBack() {
  const nav = useNavigate();
  return (target?: string, state?: unknown) => {
    if (!target) {
      // 앱 안의 앞 기록을 모르면(새로고침·직접 연 주소) 브라우저 기록이 남아 있을 때만 뒤로, 아예 없으면 지역 선택 화면으로
      const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0;
      if (prevPath() === null && idx <= 0) nav("/area", { replace: true }); else nav(-1);
      return;
    }
    if (prevPath() === target.split("?")[0]) nav(-1);
    else nav(target, { replace: true, ...(state ? { state } : {}) });
  };
}

export function Screen(props: {
  title?: string; back?: boolean | string; step?: number; right?: ReactNode; children: ReactNode; cta?: ReactNode;
  /** 뒤로 간 화면에 넘길 상태(예: 저장 리포트에서 연 리포트로 돌아갈 때 그 리포트의 '뒤로'도 저장 리포트로) */
  backState?: unknown;
}) {
  const goBack = useGoBack();
  const loc = useLocation();
  const h1 = useRef<HTMLHeadingElement>(null);
  useEffect(() => { if (props.title) document.title = `${props.title} · MIRI`; }, [props.title]);
  // 화면이 바뀌면 제목으로 포커스를 옮겨 스크린리더가 새 화면을 읽게 한다(포커스가 body로 떨어지지 않게)
  // 화면이 바뀐 직후 400ms는 더블클릭의 두 번째 클릭(같은 자리의 다음 화면 버튼·뒤로 화살표)을 버린다 —
  // '다음'을 두 번 눌러 SB-04를 건너뛰거나 '리포트에 반영'이 저장까지 눌리지 않게. 새 자리를 한 번 누르는 클릭은 통과
  useEffect(() => { guardClicks(400, false); h1.current?.focus({ preventScroll: true }); }, [loc.pathname]);
  return (
    <div className="screen">
      {(props.title || props.back || props.step !== undefined) && (
        <header>
          {(props.title || props.back) && (
            <div className="topbar">
              {props.back && (
                <button className="back" aria-label="뒤로"
                  onClick={() => goBack(typeof props.back === "string" ? props.back : undefined, props.backState)}><IconBack /></button>
              )}
              <h1 ref={h1} tabIndex={-1}>{props.title}</h1>
              {props.right}
            </div>
          )}
          {props.step !== undefined && (
            <div className="steps" role="img" aria-label={`3단계 중 ${props.step}단계`}>
              {[1, 2, 3].map((i) => <span key={i} className={i <= props.step! ? "on" : ""} />)}
            </div>
          )}
        </header>
      )}
      {/* 하단 버튼 줄은 화면에 고정(position: fixed)이라 main 안에 둬도 위치는 같고, 랜드마크 밖 콘텐츠가 생기지 않는다 */}
      <main className="screen-body">
        {props.children}
        {props.cta && <div className="cta-bar">{props.cta}</div>}
      </main>
    </div>
  );
}

/** 오류·안내 문구를 입력칸과 연결(aria-describedby)하고, 오류면 aria-invalid */
function describe(id: string | undefined, error?: string | null, hint?: ReactNode) {
  if (!id) return {};
  return { "aria-invalid": error ? true : undefined,
    "aria-describedby": error ? `${id}-err` : hint ? `${id}-hint` : undefined } as const;
}

export function MoneyField(props: {
  value: string; onChange(v: string): void; placeholder?: string; suffix?: string; error?: string | null;
  hint?: ReactNode; id?: string; prefix?: string; allowDecimal?: boolean; integer?: boolean; autoFocus?: boolean;
}) {
  // 쉼표를 넣고 빼도 커서가 끝으로 튀지 않게: 커서 왼쪽 숫자 개수를 세어 서식을 입힌 값에서 같은 자리로 되돌린다
  const ref = useRef<HTMLInputElement>(null);
  const caret = useRef<number | null>(null);
  useLayoutEffect(() => {
    const el = ref.current, pos = caret.current;
    caret.current = null;
    if (el && pos !== null && document.activeElement === el) el.setSelectionRange(pos, pos);
  }, [props.value]);
  const oneDot = (x: string) => { const [a, ...r] = x.split("."); return r.length ? `${a}.${r.join("")}` : a; };   // 소수점은 하나만
  const fmt = (raw: string) => (props.allowDecimal ? oneDot(raw.replace(/[^0-9.]/g, ""))
    : props.integer ? withComma(raw.split(".")[0], false) : withComma(raw));
  function change(el: HTMLInputElement, inputType?: string) {
    let raw = el.value, pos = el.selectionStart ?? raw.length;
    // 쉼표만 지웠으면(숫자는 그대로) — Backspace는 그 앞 숫자를, Delete는 그 뒤 숫자를 지운다(아무 일도 안 하는 것처럼 보이지 않게).
    // 붙여넣기·입력은 건드리지 않는다
    const onlyComma = raw.length < props.value.length && raw.replace(/,/g, "") === props.value.replace(/,/g, "");
    if (onlyComma && inputType === "deleteContentBackward" && pos > 0) {
      raw = raw.slice(0, pos - 1) + raw.slice(pos); pos -= 1;
    } else if (onlyComma && inputType === "deleteContentForward" && pos < raw.length) {
      raw = raw.slice(0, pos) + raw.slice(pos + 1);
    }
    const sig = raw.slice(0, pos).replace(/[^0-9.]/g, "").length;
    const next = fmt(raw);
    let i = 0, n = 0;
    while (i < next.length && n < sig) { if (/[0-9.]/.test(next[i])) n++; i++; }
    if (next === props.value) {
      // 값이 그대로면(글자·한글 입력 등 버린 입력) React가 칸을 되돌리며 커서를 끝으로 보내므로 직접 제자리로
      requestAnimationFrame(() => { if (document.activeElement === el) el.setSelectionRange(i, i); });
    } else caret.current = i;
    props.onChange(next);
  }
  return (
    <div>
      <label className={`field money${props.error ? " error" : ""}`} htmlFor={props.id}>
        {props.prefix !== "" && <span className="prefix" aria-hidden="true">{props.prefix ?? "₩"}</span>}
        <input id={props.id} ref={ref} inputMode={props.allowDecimal ? "decimal" : "numeric"} autoComplete="off" value={props.value}
          placeholder={props.placeholder ?? "0"} autoFocus={props.autoFocus} {...describe(props.id, props.error, props.hint)}
          onChange={(e) => change(e.target, (e.nativeEvent as InputEvent).inputType)} />
        <span className="suffix">{props.suffix ?? "만원"}</span>
      </label>
      {props.error ? <div className="field-error" id={props.id && `${props.id}-err`}>{props.error}</div>
        : props.hint ? <div className="field-hint" id={props.id && `${props.id}-hint`}>{props.hint}</div> : null}
    </div>
  );
}

export function TextField(props: {
  value: string; onChange(v: string): void; type?: string; placeholder?: string; id?: string; error?: string | null;
  autoComplete?: string; describedBy?: string;                     // 폼 전체 오류 문구와 연결할 때
}) {
  return (
    <div>
      <label className={`field${props.error ? " error" : ""}`} htmlFor={props.id}>
        <input id={props.id} type={props.type || "text"} value={props.value} placeholder={props.placeholder}
          autoComplete={props.autoComplete} onChange={(e) => props.onChange(e.target.value)} {...describe(props.id, props.error)}
          {...(props.describedBy ? { "aria-describedby": props.describedBy, "aria-invalid": true } : {})} />
      </label>
      {props.error && <div className="field-error" id={props.id && `${props.id}-err`}>{props.error}</div>}
    </div>
  );
}

export const Bar = ({ value, max = 100, color }: { value: number; max?: number; color?: string }) => (
  <div className="bar"><i style={{ width: `${Math.max(0, Math.min(100, (value / max) * 100))}%`, background: color }} /></div>
);

export const Spinner = () => <div className="spinner" aria-label="불러오는 중" />;

export function Loading({ text = "불러오는 중…" }: { text?: string }) {
  return <div className="center-pad"><Spinner /><span>{text}</span></div>;
}

export function ErrorBox({ message, onRetry, actions }: { message: string; onRetry?: () => void; actions?: ReactNode }) {
  return (
    <div className="center-pad" role="alert">
      <span>{message}</span>
      <div className="row" style={{ flexWrap: "wrap", justifyContent: "center" }}>
        {onRetry && <button className="btn-small" onClick={onRetry}>다시 시도</button>}
        {actions}
      </div>
    </div>
  );
}

/** 겹친 버튼 오작동 방지: 시트·목록이 열리고 닫히는 순간의 더블클릭(더블탭) 두 번째 클릭이 그 아래 버튼
 * (리포트에 반영·분석 시작·지도)을 누르지 않게 캡처 단계에서 버린다.
 *  · 500ms 안의 '두 번째 클릭'(detail ≥ 2)과 dblclick
 *  · 포인터로 닫았다면 250ms 안에 '같은 자리'를 바로 다음에 누른 클릭(detail을 세지 않는 터치 기기의 더블탭) —
 *    그 사이에 다른 곳을 한 번이라도 눌렀다면(입력칸·다른 버튼) 더블탭이 아니므로 막지 않는다
 * 다른 자리를 새로 누르는 클릭은 그대로 통과한다. */
let guardUntil = 0, guardSameUntil = 0, guardPos = { x: -1e9, y: -1e9 }, guardSameDown = -1, downCount = 0;
let lastDown = { x: -1e9, y: -1e9, t: 0 }, guardInstalled = false;
function swallow(e: MouseEvent) {
  const now = Date.now();
  const same = Math.abs(e.clientX - guardPos.x) < 24 && Math.abs(e.clientY - guardPos.y) < 24;
  const nextTap = downCount <= guardSameDown + 1;          // 가드를 건 뒤 첫 번째 누름(키보드 클릭은 누름이 없어 그대로)
  if ((now < guardUntil && (e.type === "dblclick" || e.detail >= 2)) || (now < guardSameUntil && same && nextTap)) {
    e.stopPropagation(); e.preventDefault();
  }
}
function installGuard() {
  if (guardInstalled || typeof window === "undefined") return;
  window.addEventListener("pointerdown", (e) => { downCount++; lastDown = { x: e.clientX, y: e.clientY, t: Date.now() }; }, true);
  window.addEventListener("click", swallow, true);
  window.addEventListener("dblclick", swallow, true);
  guardInstalled = true;
}
if (typeof window !== "undefined") installGuard();
/** 더블클릭·연속 탭의 두 번째 입력을 잠깐 막는다. 기한은 늘리기만 한다 — 시트가 닫히며 건 '같은 자리' 가드(터치 브라우저는
 *  탭마다 detail=1)를 바로 이어지는 화면 전환의 가드가 지우지 않게 */
export function guardClicks(ms = 500, samePlace = true) {
  installGuard();
  const now = Date.now();
  guardUntil = Math.max(guardUntil, now + ms);
  const byPointer = now - lastDown.t < 600;               // 방금 누른 포인터로 닫힌 경우(키보드 Esc면 막을 게 없음)
  if (samePlace && byPointer) {
    guardSameUntil = Math.max(guardSameUntil, now + 250);
    guardPos = { x: lastDown.x, y: lastDown.y };
    guardSameDown = downCount;                            // 이 누름 다음의 첫 누름만 더블탭으로 본다
  }
}
/** 비동기 작업이 끝났을 때 화면이 아직 떠 있는지(다른 화면으로 옮긴 뒤 늦게 온 응답이 화면을 끌고 가지 않게) */
export function useMounted() {
  const m = useRef(true);
  useEffect(() => { m.current = true; return () => { m.current = false; }; }, []);
  return m;
}

/** 아래에서 올라오는 시트(모달). 열리면 시트로 포커스를 옮기고, Tab은 시트 안에서만 돌며, 닫히면 연 버튼으로 돌려준다. */
export function Sheet({ open, onClose, title, children }: { open: boolean; onClose(): void; title: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;                         // 부모가 매번 새 함수를 넘겨도 포커스 효과가 다시 돌지 않게
  const id = useId();
  useEffect(() => {
    if (!open) return;
    guardClicks(500, false);                          // 여는 버튼을 더블클릭해도 두 번째 클릭이 바깥(닫기)을 누르지 않게
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") { closeRef.current(); return; }
      if (e.key !== "Tab" || !ref.current) return;
      const list = Array.from(ref.current.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, summary, [tabindex]:not([tabindex="-1"])')).filter((el) => !el.hasAttribute("disabled"));
      if (!list.length) return;
      const first = list[0], last = list[list.length - 1], cur = document.activeElement;
      if (e.shiftKey && (cur === first || cur === ref.current)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && cur === last) { e.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", h);
    return () => {
      window.removeEventListener("keydown", h);
      guardClicks();                                  // 닫힐 때: 시트 버튼 더블클릭의 두 번째 클릭이 아래 버튼을 누르지 않게
      if (prev && document.contains(prev)) prev.focus();
    };
  }, [open]);
  if (!open) return null;
  return (
    <div className="overlay" onClick={onClose}>
      <div className="sheet" role="dialog" aria-modal="true" aria-labelledby={id} tabIndex={-1} ref={ref}
        onClick={(e) => e.stopPropagation()}>
        <h2 id={id}>{title}</h2>
        <button type="button" className="sheet-close" aria-label="닫기" onClick={onClose}>×</button>
        {children}
      </div>
    </div>
  );
}

/** 비동기 데이터 로딩 훅. status: 실패한 요청의 HTTP 상태(404면 '다시 시도'를 보이지 않는다).
 *  setData(값)은 그 값으로 바꾸고(불러오기 끝), setData(함수)는 지금 가진 데이터가 있을 때만 그것을 고친다 —
 *  응답을 기다리는 사이 다른 주소로 옮겨 불러오는 중이거나 오류가 난 화면에 이전 데이터를 되살리지 않게 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<{ data: T | null; error: string | null; status: number | null; code?: string | null; loading: boolean }>(
    { data: null, error: null, status: null, code: null, loading: true });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: null, status: null, code: null }));
    fn().then((data) => alive && setState({ data, error: null, status: null, code: null, loading: false }))
      .catch((e) => alive && setState({ data: null, error: e?.message || "문제가 생겼어요", status: e?.status ?? null, code: e?.code ?? null, loading: false }));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const setData = (d: T | ((prev: T) => T)) =>
    setState((s) => (typeof d !== "function" ? { data: d, error: null, status: null, code: null, loading: false }
      : s.data === null ? s : { ...s, data: (d as (prev: T) => T)(s.data) }));
  return { ...state, reload: () => setTick((t) => t + 1), setData };
}
