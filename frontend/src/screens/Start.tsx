import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import type { Role } from "../api";
import { guardClicks } from "../components/ui";
import { canPersist } from "../lib/storage";
import { useApp } from "../state/app";

export const ROLES: { role: Role; label: string }[] = [
  { role: "PRE_FOUNDER", label: "예비창업자" }, { role: "OWNER", label: "자영업자" }, { role: "CONSULTANT", label: "컨설턴트" },
];

// SB-01 시작 — 로그인 없이 누구나 바로 시작한다. 사용자 유형은 지원사업을 고르는 데 쓰인다(예비창업자·자영업자 대상 사업).
export default function Start() {
  const { role, setRole, api } = useApp();
  const nav = useNavigate();
  const h1 = useRef<HTMLHeadingElement>(null);
  // 다른 화면과 같은 제목 형식·포커스, 들어온 버튼의 더블클릭 두 번째가 이 화면 버튼을 누르지 않게
  useEffect(() => { guardClicks(400, false); document.title = "시작 · MIRI"; h1.current?.focus({ preventScroll: true }); }, []);
  return (
    <div className="screen">
      <main className="screen-body" style={{ paddingBottom: 40 }}>
        <h1 className="logo" ref={h1} tabIndex={-1}>MIRI</h1>
        <p className="lead" style={{ fontSize: 16 }}>데이터로 찾는 내 가게 자리.<br />감이 아니라 숫자로 시작하세요.</p>
        <span className="label" id="role-label">사용자 유형</span>
        <div className="chips c3" role="group" aria-labelledby="role-label" aria-describedby="role-hint">
          {ROLES.map((r) => (
            <button type="button" key={r.role} className={`chip${role === r.role ? " on" : ""}`}
              onClick={() => setRole(r.role)} aria-pressed={role === r.role}>{r.label}</button>
          ))}
        </div>
        <div className="field-hint" id="role-hint">유형에 맞는 지원사업을 골라 드려요.</div>
        <button className="btn-primary" style={{ width: "100%", marginTop: 24 }} onClick={() => nav("/area")}>분석 시작</button>
        <button className="btn-secondary" style={{ width: "100%", marginTop: 10 }} onClick={() => nav("/reports", { state: { from: "/" } })}>저장 리포트</button>
        <p className="muted" style={{ marginTop: 12, textAlign: "center" }}>
          로그인 없이 모든 기능을 쓸 수 있어요.{canPersist() ? " 저장한 리포트는 이 브라우저에 보관돼요." : ""}
          {api.mode === "demo" && <><br />데모 모드: 데이터는 이 브라우저 안에서만 계산·보관돼요.</>}
        </p>
        {!canPersist() && (
          <div className="notice" role="note" style={{ marginTop: 12 }}>이 브라우저는 저장소를 쓸 수 없어요(사생활 보호 모드 등). 저장한 리포트는 새로고침하거나 창을 닫으면 사라져요.</div>
        )}
      </main>
    </div>
  );
}
