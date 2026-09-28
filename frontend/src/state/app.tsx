import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { Api, AreaCard, getApi, Goal, Industries, Meta, Role } from "../api";
import { load, remove, removeSessionWhere, save } from "../lib/storage";
import { analysisCache } from "../lib/cache";

// ── 분석 입력 초안 (SB-02~04에서 채우고 분석 시작 시 전송) ────────────────
export interface Draft {
  place: { name: string; lat: number; lng: number } | null;
  radius: number;
  area: AreaCard | null;
  candidateCodes: string[];
  budget: string; rent: string; labor: string;            // 만원 단위 문자열(입력 그대로)
  investment: string; otherFixed: string; ownerSalary: string; loan: string; loanRate: string; // loanRate: %
  goal: Goal;
  licenses: string[];
  interests: string[];                                   // 업종 코드
  sameCategoryOnly: boolean;
  cogs: Record<string, string>;                          // 분야별 원가율(%) 입력 그대로 {"소매업": "70"}
}
export const EMPTY_DRAFT: Draft = {
  place: null, radius: 500, area: null, candidateCodes: [],
  budget: "", rent: "", labor: "", investment: "", otherFixed: "", ownerSalary: "", loan: "", loanRate: "",
  goal: "안정형", licenses: [], interests: [], sameCategoryOnly: true, cogs: {},
};

const ROLE_KEY = "miri.role";
export const LEGACY_NOTICE = "miri.legacyNotice";      // 0.1에 로그인해 있던 브라우저(저장 리포트 화면에서 한 번 안내)
const isRole = (r: unknown): r is Role => r === "PRE_FOUNDER" || r === "OWNER" || r === "CONSULTANT";
/** 시작 화면(SB-01)에서 고른 사용자 유형 — 지원사업 매칭에 쓰인다. 로그인이 있던 0.1이 이 브라우저에 남긴 유형이 있으면 이어서 쓴다 */
function initialRole(): Role {
  const r = load<unknown>(ROLE_KEY, null);
  if (isRole(r)) return r;
  const old = load<{ guestRole?: unknown; user?: { role?: unknown } | null } | null>("miri.session", null);
  const prev = isRole(old?.user?.role) ? old?.user?.role : old?.guestRole;
  return isRole(prev) ? prev : "PRE_FOUNDER";
}

interface Ctx {
  api: Api;
  /** 이 탭에 남은 작업 흔적(입력 초안·분석 결과 캐시·손익분기 수정값)을 지운다 — 여럿이 쓰는 컴퓨터를 정리할 때(로그아웃 대신) */
  forgetThisTab(): void;
  meta: Meta | null;
  industries: Industries | null;
  role: Role;
  setRole(r: Role): void;
  draft: Draft;
  setDraft(patch: Partial<Draft>): void;
  resetDraft(): void;
  toast(msg: string): void;
}

const AppCtx = createContext<Ctx | null>(null);
export const useApp = () => {
  const c = useContext(AppCtx);
  if (!c) throw new Error("AppProvider 밖에서 사용");
  return c;
};

export function AppProvider({ children }: { children: ReactNode }) {
  const [api, setApi] = useState<Api | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [industries, setIndustries] = useState<Industries | null>(null);
  const [role, setRole] = useState<Role>(initialRole);
  const [draft, setDraftState] = useState<Draft>(() => ({ ...EMPTY_DRAFT, ...load<Partial<Draft>>("miri.draft", {}, true) }));
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getApi().then(async (a) => {
      if (!alive) return;
      setApi(a);
      try {
        const [m, i] = await Promise.all([a.meta(), a.industries()]);
        if (alive) { setMeta(m); setIndustries(i); }
      } catch (e: any) {
        if (alive) setBootError(e?.message || "서버에 연결할 수 없어요");
      }
    });
    // 로그인이 있던 0.1이 남긴 값(로그인 정보·비회원 분석 소유 확인 값·로그인 뒤 저장 요청)은 더 쓰지 않는다.
    // 로그인해 있던 사람에게는 저장 리포트 화면에서 '예전 계정의 저장 목록은 여기 없다'고 한 번 알린다
    if (load<{ user?: unknown } | null>("miri.session", null)?.user) save(LEGACY_NOTICE, true);
    remove("miri.session"); remove("miri.claims"); remove("miri.pendingSave", true);
    return () => { alive = false; };
  }, []);

  useEffect(() => { save(ROLE_KEY, role); }, [role]);
  useEffect(() => { save("miri.draft", draft, true); }, [draft]);
  useEffect(() => {
    if (!toastMsg) return;
    const t = setTimeout(() => setToastMsg(null), 2400);
    return () => clearTimeout(t);
  }, [toastMsg]);

  const setDraft = useCallback((patch: Partial<Draft>) => setDraftState((d) => ({ ...d, ...patch })), []);
  const resetDraft = useCallback(() => { setDraftState(EMPTY_DRAFT); remove("miri.draft", true); }, []);

  const value = useMemo<Ctx | null>(() => {
    if (!api) return null;
    const forgetThisTab = () => {
      analysisCache.clear();
      resetDraft();
      removeSessionWhere((k) => k.startsWith("miri.be.") || k.startsWith("miri.refl.") || k.startsWith("miri.req."));
    };
    return { api, meta, industries, role, setRole, draft, setDraft, resetDraft, forgetThisTab, toast: setToastMsg };
  }, [api, meta, industries, role, draft, setDraft, resetDraft]);

  if (bootError) return <div className="boot"><b>MIRI</b><p>{bootError}</p><button className="btn-secondary" onClick={() => location.reload()}>다시 시도</button></div>;
  if (!value) return <div className="boot"><b>MIRI</b><div className="spinner" /></div>;
  return (
    <AppCtx.Provider value={value}>
      {children}
      {toastMsg && <div className="toast" role="status">{toastMsg}</div>}
    </AppCtx.Provider>
  );
}
