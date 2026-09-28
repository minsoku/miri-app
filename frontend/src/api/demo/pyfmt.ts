// 파이썬과 같은 결과를 내는 반올림·숫자 포맷 (데모 엔진이 백엔드와 글자 하나까지 같게 나오도록).
// 파이썬 round()/format()은 '이진 부동소수의 정확한 값'을 기준으로 반올림하고 동률이면 짝수로 간다(banker's).
// JS toFixed/Math.round는 동률을 올림하므로 0.125, 2.5 같은 값에서 결과가 달라진다 → BigInt로 정확한 값을 계산.

const buf = new DataView(new ArrayBuffer(8));

/** x = sign × N × 10^(−k)  (N: BigInt, k ≥ 0) 로 정확히 분해 */
function exact(x: number): { neg: boolean; N: bigint; k: number } {
  buf.setFloat64(0, x);
  const hi = buf.getUint32(0), lo = buf.getUint32(4);
  const neg = (hi >>> 31) === 1;
  const expBits = (hi >>> 20) & 0x7ff;
  const fracHi = hi & 0xfffff;
  let m = (BigInt(fracHi) << 32n) | BigInt(lo);
  let e: number;
  if (expBits === 0) { e = -1074; } else { m |= 1n << 52n; e = expBits - 1075; }
  if (m === 0n) return { neg, N: 0n, k: 0 };
  if (e >= 0) return { neg, N: m << BigInt(e), k: 0 };
  const k = -e;
  return { neg, N: m * 5n ** BigInt(k), k };
}

/** 소수 n자리로 반올림(동률 짝수)한 정수 q (값 = q × 10^−n) */
function roundedInt(x: number, n: number): { neg: boolean; q: bigint } {
  const { neg, N, k } = exact(x);
  if (n >= k) return { neg, q: N * 10n ** BigInt(n - k) };
  const div = 10n ** BigInt(k - n);
  let q = N / div;
  const r = N % div;
  const twice = r * 2n;
  if (twice > div || (twice === div && q % 2n === 1n)) q += 1n;
  return { neg, q };
}

function toStr(neg: boolean, q: bigint, n: number, comma: boolean): string {
  let s = q.toString();
  if (n > 0) {
    s = s.padStart(n + 1, "0");
    const ip = s.slice(0, s.length - n), fp = s.slice(s.length - n);
    s = (comma ? group(ip) : ip) + "." + fp;
  } else if (comma) s = group(s);
  return (neg ? "-" : "") + s;
}
const group = (ip: string) => ip.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

/** 파이썬 format(x, f".{n}f") / format(x, f",.{n}f") */
export function pyFixed(x: number, n: number, comma = false): string {
  if (!isFinite(x)) return isNaN(x) ? "nan" : x > 0 ? "inf" : "-inf";
  const { neg, q } = roundedInt(x, n);
  return toStr(neg, q, n, comma);
}
/** 파이썬 format(x, f"+.{n}f") — 0 이상은 '+' */
export function pySigned(x: number, n: number): string {
  const s = pyFixed(x, n);
  return s.startsWith("-") ? s : "+" + s;
}
/** 파이썬 round(x, n) → float */
export function pyRound(x: number, n = 0): number {
  if (!isFinite(x)) return x;
  const { neg, q } = roundedInt(x, n);
  const v = Number(toStr(false, q, n, false));
  return neg ? -v : v;
}
/** 파이썬 int(round(x)) */
export const pyRoundInt = (x: number) => pyRound(x, 0) + 0;   // -0 → 0
/** 파이썬 f"{x:.1%}" */
export const pyPct = (x: number, n = 1) => pyFixed(x * 100, n) + "%";
