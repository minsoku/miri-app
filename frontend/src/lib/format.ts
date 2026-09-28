import type { Grade } from "../api/types";
import { pyFixed } from "../api/demo/pyfmt";

/** '2025년 2분기' → '2025년 2분기까지 최근 1년' (점포당 매출·점포 수·폐업률은 최근 4분기 평균·합계) */
export const yearTo = (label: string) => `${label}까지 최근 1년`;
// 글자·배지에 쓰는 색(흰 바탕 4.5:1 이상). 주황 막대색(--amber)은 글자에 쓰지 않는다.
export const GRADE_COLOR: Record<string, string> = {
  낮음: "var(--green)", 보통: "var(--amber-text)", 높음: "var(--red)", 고위험: "var(--red-deep)",
};
export const GRADE_BG: Record<string, string> = {
  낮음: "var(--green-bg)", 보통: "var(--amber-bg)", 높음: "var(--red-bg)", 고위험: "var(--red-bg)",
};
export const PRESSURE_COLOR: Record<string, string> = {
  여유: "var(--green)", 보통: "var(--blue)", 빠듯: "var(--amber-text)", 위험: "var(--red)",
};
export const gradeLabel = (g: Grade | string) => (g === "고위험" ? "고위험" : `위험 ${g}`);

const stripZeros = (s: string) => s.replace(/0+$/, "").replace(/\.$/, "");
/** 12,345,678 → '1,235만원' · 123,456,789 → '1.23억원' · 15,000 → '1.5만원' · 9,000 → '9,000원'.
 * 서버 문장(app/services/narrative.py won)과 글자 하나까지 같게: 파이썬식 반올림(이진값 기준·동률 짝수)을 쓴다
 * — 화면 머리글 '493만원'과 바로 아래 서버 문장 '492만원'이 어긋나지 않게. */
export function won(x?: number | null, opts: { unit?: string } = {}): string {
  const unit = opts.unit ?? "원";
  if (x === null || x === undefined || !isFinite(x)) return "-";
  const a = Math.abs(x);
  if (a >= 99_995_000) return `${stripZeros(pyFixed(x / 1e8, 2, true))}억${unit}`;   // 만원으로 반올림하면 10,000만원이 되는 값부터 억
  if (a >= 1e5) return `${pyFixed(x / 1e4, 0, true)}만${unit}`;
  if (a >= 1e4) return `${stripZeros(pyFixed(x / 1e4, 1))}만${unit}`;                 // 1만~10만: 12.5만원('13만원'으로 뭉개지 않게)
  return `${pyFixed(x, 0, true)}${unit}`;
}
/** 만원 단위 정수(막대 숫자 등) — won()과 같은 반올림 */
export const man = (x: number) => Number(pyFixed(x / 1e4, 0));
/** 원 → '₩290만' 스타일(SB-02 카드) */
export const wonShort = (x?: number | null) => (x == null ? "-" : `₩${won(x, { unit: "" })}`);
/** 작은 금액(3.3㎡당 임대료 등): 1만~100만원은 소수 첫째 자리까지. 105,600 → '10.6만원' (narrative.won1과 같음) */
export function won1(x?: number | null, unit = "원"): string {
  if (x != null && isFinite(x) && Math.abs(x) >= 1e4 && Math.abs(x) < 1e6) return `${pyFixed(x / 1e4, 1, true)}만${unit}`;
  return won(x, { unit });
}
/** 인원·개수 → '4.2만' */
export function countShort(x?: number | null): string {
  if (x === null || x === undefined || !isFinite(x)) return "-";
  if (x >= 1e8) return `${(x / 1e8).toFixed(1)}억`;
  if (x >= 1e4) return `${(x / 1e4).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}만`;
  return Math.round(x).toLocaleString("ko-KR");
}
/** 0.1925 → '19.2%' — 서버 문장(narrative.pct)과 같은 파이썬식 반올림 */
export const pct = (x?: number | null, d = 1) => (x == null || !isFinite(x) ? "-" : `${pyFixed(x * 100, d)}%`);
/** 달성배율 표시: 소수 둘째 자리 내림(서버 ratio_floor와 같음 — 옛 기록의 0.997도 '1.00배'로 보이지 않게) */
export function ratioText(r: number): string {
  const f = Math.floor(r * 100 + 1e-9) / 100;
  return f < 0.005 ? "0.01배 미만" : `${f.toFixed(2)}배`;
}
/** '이 금액 이하로' 한도 표시(서버 narrative.won_floor_below와 같음 — 데모 엔진과 같은 구현) */
export { wonFloorBelow, wonValue } from "./won";
export const signedPct = (x: number) => `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(Math.round(x))}%`;
export const manwon = (x?: number | null) => (x == null ? "" : String(Math.round(x / 100) / 100));
export const fromManwon = (s: string) => {
  const n = Number(String(s).replace(/,/g, "").trim() || "0");
  return isFinite(n) && n >= 0 ? Math.round(n * 1e4) : NaN;
};
/** 입력 중 표시: 정수부에 쉼표, 소수점은 한 개·소수 둘째 자리까지 그대로 유지(150.5 → 150.5, 12000 → 12,000) */
export const withComma = (s: string, allowDecimal = true) => {
  const clean = s.replace(/[^0-9.]/g, "");
  const [ip, ...rest] = clean.split(".");
  const intPart = ip.replace(/^0+(?=\d)/, "");
  // 문자열로 세 자리마다 쉼표(Number로 바꾸면 16자리 넘는 수가 반올림돼 다른 숫자로 바뀐다)
  const grouped = intPart ? intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",") : (rest.length ? "0" : "");
  if (!allowDecimal || rest.length === 0) return grouped;
  return `${grouped}.${rest[0].slice(0, 2)}`;                 // '1.2.3'을 1.23으로 합치지 않고 첫 소수점만
};
/** 숫자로 읽을 수 있는 입력인지(빈 값은 true) */
export const isNumberInput = (s: string) => !s || /^\d[\d,]*(\.\d*)?$|^\.\d+$/.test(s.trim());
export function dateDot(iso: string, withTime = false): string {
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  if (isNaN(d.getTime())) return iso.slice(0, 10).replace(/-/g, ".");
  const p2 = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}.${p2(d.getMonth() + 1)}.${p2(d.getDate())}` + (withTime ? ` ${p2(d.getHours())}:${p2(d.getMinutes())}` : "");
}
export const radiusLabel = (m?: number | null) => (m == null ? "" : m >= 1000 ? `${m / 1000}km` : `${m}m`);
/** 받침에 맞는 조사 */
export function josa(word: string, pair: "은/는" | "이/가" | "을/를" | "과/와" | "으로/로"): string {
  const [a, b] = pair.split("/");
  const ch = word.charCodeAt(word.length - 1);
  if (ch < 0xac00 || ch > 0xd7a3) return `${word}${a}(${b})`;
  const jong = (ch - 0xac00) % 28;
  if (pair === "으로/로") return word + (jong === 0 || jong === 8 ? "로" : "으로");
  return word + (jong ? a : b);
}
