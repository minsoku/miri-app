import type { Analysis } from "../api";
// 방금 만든 분석 결과를 다시 요청하지 않도록 메모리에 잠깐 보관
export const analysisCache = new Map<string, Analysis>();

import { load, remove, save } from "./storage";

// 이 탭에서 '리포트에 반영'한 손익분기 계산(분석·업종별) — 위험도 화면의 '대응 액션 보기'가 같은 비용으로 리포트를 열게
const reflKey = (id: string, code: string) => `miri.refl.${id}.${code}`;
export function rememberReflected(id: string, code: string, beId?: number | null, inputsKey?: string | null) {
  if (beId) save(reflKey(id, code), { id: beId, key: inputsKey ?? null }, true);
}
type Refl = { id: number; key: string | null } | number | null;
export const reflectedBe = (id: string, code: string): number | null => {
  const v = load<Refl>(reflKey(id, code), null, true);
  return v == null ? null : typeof v === "number" ? v : v.id;
};
/** 반영한 계산의 입력값 키 — 손익분기 화면이 '지금 값이 이미 리포트에 반영됐는지' 알 수 있게 */
export const reflectedKey = (id: string, code: string): string | null => {
  const v = load<Refl>(reflKey(id, code), null, true);
  return v && typeof v === "object" ? v.key : null;
};

// 기본값이 없어 손익분기 화면에서 꼭 넣어야 했던 값(원가율·객단가)만 넣은 계산 — '리포트에 반영'을 누르지 않고 위험도 화면으로
// 돌아가 '대응 액션 보기'를 눌러도 넣은 원가율이 리포트에 쓰이게(분석 조건을 바꾼 계산은 반영해야만 쓰인다)
const reqKey = (id: string, code: string) => `miri.req.${id}.${code}`;
export function rememberRequiredOnly(id: string, code: string, beId?: number | null) {
  if (beId) save(reqKey(id, code), beId, true);
}
export const requiredOnlyBe = (id: string, code: string): number | null => load<number | null>(reqKey(id, code), null, true);
export const forgetRequiredOnly = (id: string, code: string) => remove(reqKey(id, code), true);
