"""M-06 근거 문장 템플릿 (규칙 기반). recommendation_items.reason/caution, risk_factors.explanation에 저장."""
from __future__ import annotations
import math


def _won_to_manwon(x):
    return f"{x / 1e4:,.0f}만원"


def _ok(x):
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def recommendation_reason(r: dict, unit_label: str = "지역") -> str:
    parts = []
    if _ok(r.get("D")) and _ok(r.get("sales_ps_m")):
        parts.append(f"점포당 월매출 {_won_to_manwon(r['sales_ps_m'])} "
                     f"(서울 동일 업종 {unit_label} 중 상위 {max(1, round(100 - r['D']))}%)")
    parts.append(f"예상 연간 폐업률 {r['pred_annual_rate']:.1%} · 종합 위험 {r['risk_grade']}({r['risk_score']}점)"
                 f" · 같은 업종 내 입지 위험 {r.get('location_grade', '-')}")
    if _ok(r.get("achievability_ratio")):
        parts.append(f"입력 비용 기준 평균매출이 손익분기의 {r['achievability_ratio']:.2f}배")
    return " / ".join(parts)


def recommendation_caution(r: dict) -> str:
    c = []
    if r.get("risk_grade") in ("높음", "고위험"):
        c.append(f"업종 자체의 폐업률이 높음(종합 위험 {r['risk_grade']})")
    ups = [f for f in r.get("risk_factors", []) if f["effect_pct"] >= 5 and f["factor_code"] != "ind_base"]
    if ups:
        c.append("위험 요인: " + ", ".join(f"{f.get('label', f['factor_name'])}(+{f.get('effect_display', round(f['effect_pct']))}%)"
                                           for f in ups[:2]))
    if r.get("confidence") == "낮음":
        c.append("이 지역 점포 수가 적어 추정 신뢰도 낮음")
    if r.get("cogs_missing"):
        c.append("원가율 입력 시 손익분기 확인 가능")
    if _ok(r.get("achievability_ratio")) and r["achievability_ratio"] < 1.0:
        c.append("평균 매출로는 손익분기 미달")
    return " / ".join(c) if c else "특이 위험 없음"


def risk_factor_explanation(f: dict) -> str:
    if "explanation" in f:
        return f["explanation"]
    sign = "+" if f["effect_pct"] > 0 else "−"
    return f"{f.get('label', f['factor_name'])}: 예상 폐업률 {sign}{abs(f['effect_pct']):.0f}%"
