import { load, save } from "./storage";

// 로그인이 없으므로 저장 리포트(SB-09)는 '이 브라우저'로 구분한다. 처음 쓸 때 임의의 키(32바이트)를 만들어 이 브라우저에 두고,
// 리포트·저장 목록 요청에 X-Device-Key 헤더로 보낸다(서버는 해시만 저장). 브라우저 데이터를 지우면 새 키가 생겨 저장 목록도 새로 시작한다.
const KEY = "miri.device";
const OK = /^[A-Za-z0-9_-]{32,128}$/;               // 서버 deps._DEVICE_RE와 같은 형식

function randomKey(): string {
  const b = new Uint8Array(32);
  crypto.getRandomValues(b);
  let s = "";
  for (const x of b) s += String.fromCharCode(x);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");   // base64url 43자
}

/** 이 브라우저의 저장 키. 저장소를 매번 다시 읽는다 — 다른 탭이 먼저 만든 키가 있으면 그것을 같이 쓰게 */
export function deviceKey(): string {
  const k = load<unknown>(KEY, null);
  if (typeof k === "string" && OK.test(k)) return k;
  const fresh = randomKey();
  save(KEY, fresh);                                  // 저장소가 막혀 있으면 이 페이지가 열려 있는 동안만(메모리)
  return fresh;
}
