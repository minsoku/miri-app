// 브라우저 저장소는 사생활 보호 모드·임베드 환경에서 막힐 수 있으므로 모두 try/catch.
// 막힌 환경(아티팩트 미리보기 등)에서는 이 페이지가 열려 있는 동안만 메모리에 둔다 — 입력 초안·브라우저 저장 키 등이
// 저장소가 없다는 이유로 조용히 끊기지 않게
const mem = new Map<string, string>();
const mk = (key: string, session: boolean) => (session ? "s:" : "l:") + key;
export function load<T>(key: string, fallback: T, session = false): T {
  let s: string | null = null;
  try { s = (session ? sessionStorage : localStorage).getItem(key); } catch { /* 저장소 막힘 */ }
  if (s == null) s = mem.get(mk(key, session)) ?? null;
  try { return s ? (JSON.parse(s) as T) : fallback; } catch { return fallback; }
}
export function save(key: string, value: unknown, session = false) {
  const v = JSON.stringify(value);
  try { (session ? sessionStorage : localStorage).setItem(key, v); mem.delete(mk(key, session)); }
  catch { mem.set(mk(key, session), v); }
}
export function remove(key: string, session = false) {
  mem.delete(mk(key, session));
  try { (session ? sessionStorage : localStorage).removeItem(key); } catch { /* 무시 */ }
}
/** 이 탭 저장소(sessionStorage)에서 조건에 맞는 키를 모두 지운다(메모리 대체 저장소 포함) */
export function removeSessionWhere(pred: (key: string) => boolean) {
  for (const k of Array.from(mem.keys())) if (k.startsWith("s:") && pred(k.slice(2))) mem.delete(k);
  try {
    for (let i = sessionStorage.length - 1; i >= 0; i--) {
      const k = sessionStorage.key(i);
      if (k && pred(k)) sessionStorage.removeItem(k);
    }
  } catch { /* 저장소 막힘 */ }
}
let persistOk: boolean | null = null;
/** 이 브라우저가 localStorage에 값을 오래 남길 수 있는지(사생활 보호 모드·저장소를 막은 임베드에서는 false —
 *  그때 브라우저 저장 키·데모 저장소는 메모리에만 있어 새로고침하면 저장 목록이 사라진다) */
export function canPersist(): boolean {
  if (persistOk === null) {
    try { localStorage.setItem("miri.probe", "1"); localStorage.removeItem("miri.probe"); persistOk = true; }
    catch { persistOk = false; }
  }
  return persistOk;
}
