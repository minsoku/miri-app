// 금액 표시값 계산(서버 narrative.won_value·won_floor_below와 같음). 화면(lib/format)과 데모 엔진이 같은 구현을 쓴다.
import { pyFixed, pyRoundInt } from "../api/demo/pyfmt";

/** won()이 화면에 보여 주는 값(정수 원): Number("1.10") * 1e8 = 110000000.00000001 같은 곱셈 오차가 비교를 틀리게 하지 않게 */
export function wonValue(x: number): number {
  if (Math.abs(x) >= 99_995_000) return pyRoundInt(Number(pyFixed(x / 1e8, 2)) * 1e8);
  if (Math.abs(x) >= 1e5) return pyRoundInt(Number(pyFixed(x / 1e4, 0)) * 1e4);
  if (Math.abs(x) >= 1e4) return pyRoundInt(Number(pyFixed(x / 1e4, 1)) * 1e4);
  return pyRoundInt(Number(pyFixed(x, 0)));
}
/** won() 표시 단위(원): 억 단위 소수 둘째 자리=100만원, 만원, 1만~10만은 천원, 그 아래는 1원 */
const wonStep = (x: number) => { const a = Math.abs(x); return a >= 99_995_000 ? 1e6 : a >= 1e5 ? 1e4 : a >= 1e4 ? 1e3 : 1; };
/** '이 금액 이하로 낮추기'의 한도: 표시 단위에서 내림하고, 지금 금액(표시값)과 같아 보이면 한 단위 더 내린다 */
export function wonFloorBelow(limit: number, now: number): number {
  const step = wonStep(limit);
  let t = pyRoundInt(Math.floor(limit / step) * step);
  const shownNow = wonValue(now);
  while (t >= shownNow && t > 0) t -= step;
  return Math.max(t, 0);
}
