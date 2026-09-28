import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Goal } from "../api";
import { MoneyField, Screen } from "../components/ui";
import { fromManwon, isNumberInput, withComma, won, won1 } from "../lib/format";
import { useApp } from "../state/app";

const COGS_CATS: { cat: string; placeholder: string }[] = [
  { cat: "외식업", placeholder: "평균 40.7" }, { cat: "서비스업", placeholder: "예: 15" }, { cat: "소매업", placeholder: "예: 70" },
];
const GOALS: { goal: Goal; label: string; desc: string }[] = [
  { goal: "기본", label: "균형", desc: "매출·안정성·비용을 고르게" },
  { goal: "안정형", label: "안정형", desc: "오래 버티는 게 우선" },
  { goal: "고수익형", label: "고수익형", desc: "매출 잠재력이 우선" },
  { goal: "저비용형", label: "저비용형", desc: "내 비용으로 버틸 수 있는지 우선" },
];

/** 입력한 만원 값을 원 단위로 풀어 보여 준다(원으로 잘못 넣은 '2,000,000' → '= 200억원'을 바로 알아채게) */
function asWon(v: string) {
  const n = fromManwon(v || "");
  if (!(v && Number.isFinite(n) && n > 0)) return null;
  // 1억 미만은 넣은 그대로(234.5 → 234.5만원 — 반올림으로 234만원처럼 보이지 않게), 그 이상은 억 단위로(단위 실수 확인용)
  // 9,999.5만원처럼 1억 바로 밑도 반올림으로 '1억원'이 되지 않게 소수 둘째 자리에서 내림(부동소수 오차만큼은 올려 본다)
  // 1억 이상도 억 단위 소수 둘째 자리에서 내림(19,999.99만원이 '2억원'으로 올라가 보이지 않게)
  const t = n >= 1e8 ? `${withComma(String(Math.floor(n / 1e6 + 1e-6) / 100))}억원`
    : n >= 1e4 ? `${withComma(String(Math.floor(n / 100 + 1e-6) / 100))}만원` : won(n);
  return <b style={{ color: "var(--text-2)" }}>= {t} · </b>;
}
/** 월세가 이 지역 10평 평균의 10배를 넘으면 단위 실수일 수 있다고 알린다 */
function rentWarn(v: string, rent33?: number | null) {
  const n = fromManwon(v || "");
  if (!rent33 || !Number.isFinite(n) || n <= rent33 * 10 * 10) return null;
  return <span style={{ color: "var(--amber-text)" }}>이 지역 10평 평균의 10배가 넘어요 — 만원 단위가 맞는지 확인해 주세요. </span>;
}

// SB-03 창업 조건 입력
export default function Conditions() {
  const { api, draft, setDraft, meta, industries } = useApp();
  const nav = useNavigate();
  const [errs, setErrs] = useState<Record<string, string>>({});
  const rent33 = draft.area?.metrics?.rent_per_3_3m2;
  // '조건 바꿔 다시 분석'으로 복원한 초안에는 지역 지표가 없다 → 임대료 안내(3.3㎡당 평균)를 위해 한 번 불러온다
  const areaCode = draft.area?.area_code;
  const needMetrics = !!draft.area && !(draft.area.metrics && "rent_per_3_3m2" in draft.area.metrics);
  useEffect(() => {
    if (!needMetrics || !areaCode) return;
    let alive = true;
    api.areaCard(areaCode).then((c) => {
      if (alive && draft.area?.area_code === areaCode) setDraft({ area: { ...draft.area, metrics: c.metrics } });
    }).catch(() => undefined);
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [areaCode, needMetrics, api]);
  // 추천 대상이 될 수 있는 업종(카드 매출이 있는 지역 5곳 이상)에 쓰이는 자격만 — 변호사·세무사·공인중개사처럼 눌러도 결과에 영향이 없는 칩은 빼기
  const licenses = useMemo(() => Array.from(new Set((industries?.industries || []).filter((i) => i.recommendable ?? i.has_sales_data).map((i) => i.license).filter(Boolean))) as string[],
    [industries]);
  const w = meta?.goals[draft.goal];
  const upd = (key: keyof typeof draft, errKey: string) => (v: string) => {
    setDraft({ [key]: v } as any);
    if (errs[errKey]) setErrs((e) => { const n = { ...e }; delete n[errKey]; return n; });
  };

  function next() {
    const e: Record<string, string> = {};
    const fields: [keyof typeof draft, string][] = [["budget", "budget"], ["rent", "rent"], ["labor", "labor"],
      ["investment", "investment"], ["otherFixed", "otherFixed"], ["ownerSalary", "ownerSalary"], ["loan", "loan"]];
    for (const [k, ek] of fields) {
      const v = String(draft[k] ?? "");
      if (!isNumberInput(v) || !Number.isFinite(fromManwon(v))) e[ek] = "숫자로 입력해 주세요 (만원 단위, 소수 둘째 자리까지)";
      else if (fromManwon(v) > 1e11) e[ek] = "금액이 너무 커요 (1,000억 원 이하)";
    }
    if (!draft.budget) e.budget = "총 창업 예산을 입력해 주세요";
    if (!draft.rent) e.rent = "월 임대료를 입력해 주세요 (없으면 0)";
    if (!draft.labor) e.labor = "예상 인건비를 입력해 주세요 (혼자 운영하면 0)";
    // 예산 칸 자체가 비었거나 틀렸으면 그 오류 하나만(투자비 오류를 겹쳐 띄우지 않는다)
    if (!e.investment && !e.budget && draft.investment && fromManwon(draft.investment) > fromManwon(draft.budget)) e.investment = "초기 투자비가 총 창업 예산보다 커요";
    const rate = Number((draft.loanRate || "0").trim());
    if (!/^\d*\.?\d*$/.test((draft.loanRate || "").trim()) || !Number.isFinite(rate) || rate < 0 || rate > 30) e.loanRate = "연이율은 0~30 사이 숫자로 입력해 주세요";
    for (const { cat } of COGS_CATS) {
      const v = (draft.cogs?.[cat] || "").trim();
      if (v && (!/^\d*\.?\d*$/.test(v) || !(Number(v) >= 0 && Number(v) <= 95))) e[`cogs-${cat}`] = "0~95 사이의 %로 넣어 주세요";
    }
    setErrs(e);
    if (Object.keys(e).length === 0) { nav("/interests"); return; }
    const cogsErr = COGS_CATS.map(({ cat }) => `cogs-${cat}`).find((k) => e[k]);
    if (e.investment || e.otherFixed || e.ownerSalary || e.loan || e.loanRate || cogsErr) {
      const d = document.querySelector("details.more") as HTMLDetailsElement | null;
      if (d) d.open = true;                              // 선택 입력 칸 오류면 접힌 영역을 펼쳐서 보여주기
    }
    // 첫 오류 칸으로 포커스 → 스크린리더가 연결된 오류 문구(aria-describedby)를 읽는다
    const order: [string, string][] = [["budget", "budget"], ["rent", "rent"], ["labor", "labor"], ["investment", "inv"],
      ["otherFixed", "other"], ["ownerSalary", "owner"], ["loan", "loan"], ["loanRate", "rate"]];
    const first = order.find(([k]) => e[k]) || (cogsErr ? [cogsErr, cogsErr] : undefined);
    if (first) requestAnimationFrame(() => document.getElementById(first[1])?.focus());
  }
  if (!draft.area) {
    return <Screen title="창업 조건 입력" back="/area" step={2}><div className="notice">먼저 상권을 골라 주세요. <button className="btn-text" onClick={() => nav("/area")}>상권 선택으로</button></div></Screen>;
  }
  return (
    <Screen title="창업 조건 입력" back="/area" step={2} cta={<button className="btn-primary" onClick={next}>다음</button>}>
      <p className="lead">창업 비용을 알려주세요. 월 고정비(임대료·인건비 등)는 업종 추천과 손익분기 계산에 바로 쓰여요.</p>
      <label className="label" htmlFor="budget">총 창업 예산</label>
      <MoneyField id="budget" value={draft.budget} onChange={upd("budget", "budget")} placeholder="예: 8,000" error={errs.budget}
        hint={<>{asWon(draft.budget)}초기 투자비를 빼고 운영자금(보통 6개월분, 폐업률이 높은 업종이나 가게 수명이 짧은 지역은 12개월분)이 남는지 리포트에서 점검해요. 추천 순위에는 쓰지 않아요.</>} />
      <label className="label" htmlFor="rent">월 임대료</label>
      <MoneyField id="rent" value={draft.rent} onChange={upd("rent", "rent")} placeholder="예: 300" error={errs.rent}
        hint={<>{asWon(draft.rent)}{rentWarn(draft.rent, rent33)}{`구하려는 점포 월세(아직 모르면 감당할 수 있는 최대치).${rent33 ? ` ${draft.area.area_name} 평균 3.3㎡당 ${won1(rent33)} → 10평(33㎡)이면 약 ${won(rent33 * 10)}` : ""}`}</>} />
      <label className="label" htmlFor="labor">예상 인건비 (월)</label>
      <MoneyField id="labor" value={draft.labor} onChange={upd("labor", "labor")} placeholder="예: 250" error={errs.labor}
        hint={<>{asWon(draft.labor)}직원 급여·4대보험 합계. 대표자 본인 몫(목표 월수입)은 아래 ‘더 정확하게’에서 따로 넣어요.</>} />
      <span className="label" id="goal-label">창업 목표</span>
      {/* 하나만 고르는 선택(다시 눌러도 꺼지지 않음) — 기본값 '균형'도 칩으로 보이게 */}
      <div className="chips c4" role="radiogroup" aria-labelledby="goal-label"
        onKeyDown={(e) => {                              // 라디오 그룹 키보드: 방향키로 옮기며 고르기(탭 정지는 고른 칩 하나)
          const dir = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
          if (!dir) return;
          e.preventDefault();
          const fi = GOALS.findIndex((g) => `goal-${g.goal}` === (e.target as HTMLElement).id);   // 포커스가 있는 칩 기준
          const i = fi >= 0 ? fi : GOALS.findIndex((g) => g.goal === draft.goal);
          const next = GOALS[(i + dir + GOALS.length) % GOALS.length];
          setDraft({ goal: next.goal });
          requestAnimationFrame(() => document.getElementById(`goal-${next.goal}`)?.focus());
        }}>
        {GOALS.map((g) => (
          <button key={g.goal} id={`goal-${g.goal}`} className={`chip${draft.goal === g.goal ? " on" : ""}`} role="radio"
            aria-checked={draft.goal === g.goal} tabIndex={draft.goal === g.goal ? 0 : -1}
            onClick={() => setDraft({ goal: g.goal })}>{g.label}</button>
        ))}
      </div>
      <p className="muted" style={{ marginTop: 8 }}>
        {`${GOALS.find((g) => g.goal === draft.goal)?.desc ?? ""}. `}
        {w && `매출 잠재력 ${Math.round(w.D * 100)} · 생존 안정성 ${Math.round(w.S * 100)} · 비용 적합도 ${Math.round(w.F * 100)}`}
      </p>
      {draft.goal === "저비용형" && !(draft.cogs?.["서비스업"] && draft.cogs?.["소매업"]) && (
        <p className="field-hint" style={{ marginTop: 4 }}>비용 적합도는 원가율을 아는 분야만 계산돼요(외식업은 평균 40.7%). 서비스업·소매업이 후보에 섞이면
          ‘더 정확하게’에서 그 분야 원가율을 넣어야 비용까지 반영해 순위를 매겨요.</p>
      )}
      <div className="bullet">입력은 5분이면 충분해요. 월 고정비를 실제에 가깝게 넣을수록 추천·손익분기가 정확해져요.</div>

      <details className="more">
        <summary>＋ 더 정확하게 (선택)</summary>
        <label className="label" htmlFor="inv">초기 투자비 (인테리어·설비, 보증금 제외)</label>
        <MoneyField id="inv" value={draft.investment} onChange={upd("investment", "investment")} placeholder="0" error={errs.investment}
          hint={<>{asWon(draft.investment)}60개월로 나눠 월 고정비에 넣어요.</>} />
        <label className="label" htmlFor="other">기타 고정비 (관리비·공과금 등, 월)</label>
        <MoneyField id="other" value={draft.otherFixed} onChange={upd("otherFixed", "otherFixed")} placeholder="0" error={errs.otherFixed} />
        <label className="label" htmlFor="owner">목표 월수입 (대표자)</label>
        <MoneyField id="owner" value={draft.ownerSalary} onChange={upd("ownerSalary", "ownerSalary")} placeholder="0" error={errs.ownerSalary}
          hint={<>{asWon(draft.ownerSalary)}넣으면 ‘내 월급까지 버는’ 매출로 손익분기를 계산해요. 비우면 내 월급 0원 기준.</>} />
        <div className="grid2">
          <div>
            <label className="label" htmlFor="loan">대출금</label>
            <MoneyField id="loan" value={draft.loan} onChange={upd("loan", "loan")} placeholder="0" error={errs.loan}
              hint={<>{asWon(draft.loan)}월 이자(대출금 × 연이율 ÷ 12)만 월 고정비에 넣어요.</>} />
          </div>
          <div>
            <label className="label" htmlFor="rate">연이율</label>
            <MoneyField id="rate" value={draft.loanRate} onChange={upd("loanRate", "loanRate")} placeholder="0" prefix="" suffix="%"
              allowDecimal error={errs.loanRate}
              hint={Number(fromManwon(draft.loan || "")) > 0 && !(draft.loanRate || "").trim() ? "비우면 0%로 계산해요." : undefined} />
          </div>
        </div>
        <span className="label" id="cogs-label">분야별 원가율 (매출 대비 재료·상품 원가, %)</span>
        <div className="grid3" role="group" aria-labelledby="cogs-label">
          {COGS_CATS.map(({ cat, placeholder }) => (
            <div key={cat}>
              <label className="label small" htmlFor={`cogs-${cat}`}>{cat}</label>
              <MoneyField id={`cogs-${cat}`} value={draft.cogs?.[cat] || ""} prefix="" suffix="%" allowDecimal placeholder={placeholder}
                error={errs[`cogs-${cat}`]}
                onChange={(v) => {
                  setDraft({ cogs: { ...(draft.cogs || {}), [cat]: v } });
                  if (errs[`cogs-${cat}`]) setErrs((x) => { const n = { ...x }; delete n[`cogs-${cat}`]; return n; });
                }} />
            </div>
          ))}
        </div>
        <p className="field-hint">넣은 분야는 비용 적합도(추천 순위)와 손익분기 기본값에 쓰여요. 모르면 비워 두세요.</p>
        <span className="label" id="lic-label">보유 자격 (자격이 필요한 업종 추천에 사용)</span>
        <div className="tagchips" role="group" aria-labelledby="lic-label">
          {licenses.map((l) => {
            const on = draft.licenses.includes(l);
            return <button key={l} className={`tag${on ? " on" : ""}`} aria-pressed={on}
              onClick={() => setDraft({ licenses: on ? draft.licenses.filter((x) => x !== l) : [...draft.licenses, l] })}>{l}</button>;
          })}
        </div>
      </details>
    </Screen>
  );
}
