"""M-04 폐업 위험도 v2.

v1: 위험도 = 경쟁포화도 + 업종트렌드 + 임대료부담 + 유동인구효율 (각 요인 척도·가중치 미정의, 폐업 이력 미사용)
v2: '향후 1년 예상 폐업률'을 추정하고, 이를 서울 전체 상권×업종 분포상 백분위로 0~100점 환산.

    log λ = log μ_all(t) + c_t + Σ_k β_k · x_k
      λ      : 점포 1개가 한 분기에 폐업할 기대 확률 (예상 분기 폐업률)
      μ_all  : 서울 전 업종 최근 1년 폐업률 (시장 전체 수준, 오프셋)
      x_k    : 요인 (config.RISK_FACTORS)  — 모두 '클수록 위험' 방향
      β_k ≥ 0: 부호 제약 → '임대료 부담이 클수록 위험이 낮아진다' 같은 설명 불가능한 결과를 원천 차단
      c_t    : 수준 보정 상수 = log ΣE4 − log ΣE4·exp(Σβx)  (분기 t 전체 셀 기준)
               → 점포 가중 평균 λ가 μ_all(t)와 같아짐. 시장 전체 폐업률 수준은 '최근 1년 유지'로 두고
                 모델은 지역·업종 간 상대 차이만 담당 (학습 기간의 시장 추세가 절편에 섞여 들어가는 것 방지)
    적합: 포아송 우도(폐업 수 ~ Poisson(λ × 점포·분기)), L-BFGS-B, 학습 기간 데이터만 사용.
          적합 시에는 공통 절편 β0를 함께 추정(β 편향 방지)하고, 예측에는 c_t를 쓴다.

점수:  score = 100 × F_ref(λ)   (F_ref = 학습 기간 예측값의 경험적 분포, 모델 버전에 고정 저장)
등급:  config.RiskParams 컷오프 (기본 40/70/90)
요인 분해:  effect_k = exp(β_k · x_k) − 1  → "임대료 부담으로 예상 폐업률 +12%"
"""
from __future__ import annotations
import json
import math
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from .config import RiskParams, RISK_FACTORS, RISK_FACTOR_LABELS, MODEL_VERSION, risk_grade

ALL_FACTORS = list(RISK_FACTORS.keys())


class RiskModel:
    def __init__(self, factors: list[str] | None = None, params: RiskParams = RiskParams()):
        self.factors = list(factors or ALL_FACTORS)
        self.params = params
        self.beta0: float | None = None
        self.beta: dict[str, float] = {}
        self.ref_quantiles: list[float] = []   # log λ 의 0~100 백분위 경계(101개)
        self.level_const: dict[int, float] = {}  # 분기 → c_t (수준 보정 상수)
        self.meta: dict = {"model_version": MODEL_VERSION, "model_type": "HYBRID"}

    # ── 학습 ─────────────────────────────────────────────────────────────
    def _X(self, df):
        return df[["x_" + f for f in self.factors]].to_numpy(float)

    def fit(self, df: pd.DataFrame) -> "RiskModel":
        d = df[(df["exp4"] > 0) & (df["fwd_exp4"] > 0) & df["fwd_clo4"].notna()]
        X, y, E, off = self._X(d), d["fwd_clo4"].to_numpy(float), d["fwd_exp4"].to_numpy(float), d["offset"].to_numpy(float)
        n, k = X.shape
        lam_reg = self.params.l2 * len(d)

        def nll(theta):
            eta = off + theta[0] + X @ theta[1:]
            mu = E * np.exp(eta)
            f = mu.sum() - (y * eta).sum() + 0.5 * lam_reg * (theta[1:] ** 2).sum()
            r = mu - y
            g = np.concatenate([[r.sum()], X.T @ r + lam_reg * theta[1:]])
            return f / n, g / n

        bounds = [(None, None)] + [(0.0, self.params.coef_upper_bound)] * k
        res = minimize(nll, np.zeros(k + 1), jac=True, method="L-BFGS-B", bounds=bounds)
        self.beta0 = float(res.x[0])
        self.beta = {f: float(b) for f, b in zip(self.factors, res.x[1:])}
        self.calibrate_levels(df)                      # 학습 분기들의 c_t (각 분기 자기 데이터만 사용)
        self.set_reference(d)
        self.meta.update({"n_train": int(n), "converged": bool(res.success),
                          "train_quarters": sorted(map(int, d["quarter"].unique()))})
        return self

    def set_reference(self, d: pd.DataFrame):
        """점수 환산 기준(학습 기간 예측값 분포의 0~100 백분위 경계) 저장."""
        eta = self.log_rate(d[d["exp4"] > 0])
        self.ref_quantiles = np.quantile(eta, np.linspace(0, 1, 101)).tolist()

    # ── 수준 보정 ─────────────────────────────────────────────────────────
    def _xb(self, df):
        b = np.array([self.beta[f] for f in self.factors])
        return self._X(df) @ b

    def calibrate_levels(self, df: pd.DataFrame) -> dict:
        """분기별 c_t 계산·저장. df는 해당 분기 '전체' 셀(점포 있는 모든 지역×업종)을 포함해야 한다."""
        d = df[df["exp4"] > 0]
        xb = self._xb(d)
        tmp = pd.DataFrame({"q": d["quarter"].to_numpy(), "e": d["exp4"].to_numpy(float), "ex": d["exp4"].to_numpy(float) * np.exp(xb)})
        agg = tmp.groupby("q")[["e", "ex"]].sum()
        for q, r in agg.iterrows():
            self.level_const[int(q)] = float(np.log(r["e"]) - np.log(r["ex"]))
        return self.level_const

    # ── 예측 ─────────────────────────────────────────────────────────────
    def log_rate(self, df: pd.DataFrame) -> np.ndarray:
        qs = df["quarter"].astype(int)
        missing = sorted(set(qs.unique()) - set(self.level_const))
        if missing:   # 일부 행만으로 c_t를 만들면 점수가 틀어지므로 자동 계산하지 않는다
            raise ValueError(f"수준 보정 상수 c_t 없음: 분기 {missing}. 해당 분기 '전체' 셀로 "
                             "calibrate_levels()를 먼저 실행하세요(배치).")
        c = qs.map(self.level_const).to_numpy(float)
        return df["offset"].to_numpy(float) + c + self._xb(df)

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        eta = self.log_rate(df)
        q_rate = np.exp(eta)
        ref = np.asarray(self.ref_quantiles)
        # 단조 보간으로 백분위 → 0~100 (학습 분포 밖은 0/100으로 포화)
        score = np.interp(eta, ref, np.linspace(0, 100, len(ref)))
        out = pd.DataFrame(index=df.index)
        out["pred_q_rate"] = q_rate                              # 예상 분기 폐업률
        out["pred_annual_rate"] = 1 - (1 - np.clip(q_rate, 0, 1)) ** 4   # 예상 연간 폐업률
        out["risk_score"] = np.round(score).astype(int)
        out["risk_grade"] = [risk_grade(s, self.params) for s in out["risk_score"]]
        for f in self.factors:
            out["eff_" + f] = np.exp(self.beta[f] * df["x_" + f].to_numpy(float)) - 1.0
        return out

    def top_factors(self, row: pd.Series, pred: pd.Series, n: int = 3) -> list[dict]:
        """설명용: 위험을 올린 요인 상위 n개 (효과 +%)와 낮춘 요인."""
        items = []
        for f in self.factors:
            eff = float(pred["eff_" + f])
            if abs(eff) < 0.005:
                continue
            up, down = RISK_FACTOR_LABELS[f]
            label = up if eff > 0 else down
            disp = int(math.floor(abs(eff) * 100 + 0.5))          # 표시용 정수 %(사사오입, 반올림 전 값 기준)
            items.append({"factor_code": f, "factor_name": RISK_FACTORS[f], "label": label,
                          "effect_pct": round(eff * 100, 1), "effect_display": disp if eff > 0 else -disp,
                          "x": round(float(row["x_" + f]), 3),
                          "explanation": f"{label}: 예상 폐업률 {'+' if eff > 0 else '−'}{disp}%"})
        items.sort(key=lambda d: -abs(d["effect_pct"]))
        return items[:n]

    # ── 저장/복원 (DB: scoring_model_versions.params_json) ────────────────
    def to_json(self) -> str:
        return json.dumps({"factors": self.factors, "beta0": self.beta0, "beta": self.beta,
                           "ref_quantiles": self.ref_quantiles, "level_const": self.level_const, "meta": self.meta,
                           "grade_cuts": [self.params.cut_normal, self.params.cut_high, self.params.cut_critical]},
                          ensure_ascii=False, indent=1)

    @classmethod
    def from_json(cls, s: str) -> "RiskModel":
        d = json.loads(s)
        cuts = d.get("grade_cuts", [40, 70, 90])
        m = cls(d["factors"], RiskParams(cut_normal=cuts[0], cut_high=cuts[1], cut_critical=cuts[2]))
        m.beta0, m.beta, m.ref_quantiles, m.meta = d["beta0"], d["beta"], d["ref_quantiles"], d["meta"]
        m.level_const = {int(k): float(v) for k, v in d.get("level_const", {}).items()}
        return m
