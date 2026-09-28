"""정규화와 소표본 보정.

1) 백분위 정규화 (v1의 '정규화'는 방식이 정의돼 있지 않았음)
   P = 100 × (순위 − 0.5) / n   (동점은 평균 순위, 같은 업종·같은 분기 안에서만 비교)
   - 이상치에 강하고(최소-최대 정규화와 달리 극단값 1개가 전체 척도를 망치지 않음)
   - '서울 전체 동일 업종 중 상위 x%'로 바로 설명 가능
   - 분기마다 다시 계산하므로 물가·코로나·카드데이터 추정방식 변경 같은 공통 충격이 상쇄됨

2) 경험적 베이즈(EB) 폐업률 보정 (v1의 '데이터 부족 시 인근 상권 대체'를 수식화)
   보정 폐업률 = (폐업 수 + k × 상위지역 폐업률) / (점포·분기 수 + k)
   - 점포가 적은 셀일수록 상위지역(업종 평균) 쪽으로 당겨짐, 많을수록 자기 데이터 유지
   - k(사전강도)는 베타-이항 적률법:  k = μ(1−μ)/τ² − 1
     τ² = (관측 분산) − (표본 크기로 인한 이항 분산) = 지역 간 '진짜' 폐업률 차이의 분산
     τ = CV × μ 로 두고 CV를 전 업종 공통 1개 모수로 추정 (지역 수가 적은 업종도 안정적)
     τ² 는 DerSimonian–Laird 불편 적률 추정
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def pct_rank(values: pd.Series, groups: list[pd.Series] | pd.Series | None = None) -> pd.Series:
    """그룹 내 중간순위 백분위(0~100). 결측은 결측 유지."""
    v = pd.Series(values, copy=False)
    if groups is None:
        r = v.rank(method="average")
        n = v.notna().sum()
        return 100.0 * (r - 0.5) / n
    g = v.groupby(groups)
    r = g.rank(method="average")
    n = g.transform("count")
    return 100.0 * (r - 0.5) / n


def eb_prior_strength(events: pd.Series, exposure: pd.Series, by: pd.Series,
                      time: pd.Series, k_min: float, k_max: float) -> tuple[pd.Series, float]:
    """업종(by)별 EB 사전강도 k (합동 변동계수 방식, DerSimonian–Laird 적률 추정).

    분기(time)·업종별로 지역 간 '진짜' 폐업률 분산 τ² 를 불편 추정하고
        Q  = Σ e_a (r_a − μ̂)²,   μ̂ = Σ y / Σ e
        τ² = [Q − (n − 1)·μ̂(1 − μ̂)] / [E − Σ e_a² / E]
    상대분산 τ²/μ² 를 전 업종·분기에서 평균해 CV(지역 간 폐업률 변동계수)를 1개 모수로 추정한다.
        k_i = (1 − μ_i) / (CV² · μ_i) − 1
    반환: (업종별 k, CV)
    """
    df = pd.DataFrame({"y": events, "e": exposure, "by": by, "t": time})
    df = df[df["e"] > 0]
    rows = []
    for (b, t), d in df.groupby(["by", "t"]):
        E = d["e"].sum()
        n = len(d)
        if n < 3 or E <= 0:
            continue
        mu = d["y"].sum() / E
        if not (0 < mu < 1):
            continue
        r = d["y"] / d["e"]
        Q = (d["e"] * (r - mu) ** 2).sum()
        denom = E - (d["e"] ** 2).sum() / E
        if denom <= 0:
            continue
        tau2 = (Q - (n - 1) * mu * (1 - mu)) / denom
        rows.append((b, mu, tau2 / mu ** 2))
    if not rows:
        return pd.Series(dtype=float, name="eb_k"), float("nan")
    R = pd.DataFrame(rows, columns=["by", "mu", "rel_tau2"])
    cv2 = max(float(R["rel_tau2"].mean()), 1e-6)
    mu_i = R.groupby("by")["mu"].mean()
    k = ((1 - mu_i) / (cv2 * mu_i) - 1.0).clip(k_min, k_max)
    return k.rename("eb_k"), float(np.sqrt(cv2))


def eb_rate(events, exposure, prior_rate, k):
    """EB 보정 비율. exposure=0이면 prior_rate 그대로."""
    return (np.asarray(events, float) + np.asarray(k, float) * np.asarray(prior_rate, float)) / \
           (np.asarray(exposure, float) + np.asarray(k, float))


def local_weight(exposure, k):
    """보정 폐업률에서 '이 지역 자체 데이터'가 차지하는 비중 (0~1) → 신뢰도 표시에 사용."""
    e = np.asarray(exposure, float)
    return e / (e + np.asarray(k, float))
