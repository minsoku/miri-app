"""M-02 특징 생성.

입력: 표준 패널(점포/매출/지역지표) → 출력: 상권(지역)×업종×분기 특징 테이블
모든 특징은 '기준 분기 t까지의 데이터'만 사용 (미래 정보 누수 없음).
백테스트용 정답(향후 4분기 폐업률)도 같은 함수에서 fwd_* 컬럼으로 만든다(서비스 운영 시엔 사용 안 함).
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .config import FeatureParams, CATEGORY_BY_PREFIX
from .loaders import quarter_index, index_to_quarter
from .normalize import pct_rank, eb_prior_strength, eb_rate, local_weight

KEY = ["area_id", "industry_code"]


def _roll(df: pd.DataFrame, col: str, w: int) -> pd.Series:
    """(지역, 업종)별 최근 w분기 합. 창이 다 안 차면 NaN."""
    g = df.groupby(KEY, sort=False)[col]
    s = df[col].astype(float).copy()
    for k in range(1, w):
        s = s + g.shift(k)
    return s


def build_panel(stores: pd.DataFrame, sales: pd.DataFrame, area: pd.DataFrame,
                p: FeatureParams = FeatureParams()) -> pd.DataFrame:
    """완전 격자(지역×업종×분기)로 펴고 이동창·증감·전방(정답) 집계를 붙인다."""
    st = stores.copy()
    st["qidx"] = quarter_index(st["quarter"])
    areas = st[["area_id", "area_name"]].drop_duplicates("area_id")
    inds = st[["industry_code", "industry_name"]].drop_duplicates("industry_code")
    qs = np.arange(st["qidx"].min(), st["qidx"].max() + 1)
    grid = (areas.assign(_k=1).merge(inds.assign(_k=1), on="_k")
                 .merge(pd.DataFrame({"qidx": qs, "_k": 1}), on="_k").drop(columns="_k"))
    grid["quarter"] = index_to_quarter(grid["qidx"])
    cnt = ["stores", "stores_nf", "franchise", "openings", "closures"]
    df = grid.merge(st[KEY + ["qidx"] + cnt], on=KEY + ["qidx"], how="left")
    df[cnt] = df[cnt].fillna(0.0)
    sa = sales.copy(); sa["qidx"] = quarter_index(sa["quarter"])
    df = df.merge(sa[KEY + ["qidx", "sales_q", "tx_q"]], on=KEY + ["qidx"], how="left")
    ar = area.copy(); ar["qidx"] = quarter_index(ar["quarter"])
    df = df.merge(ar.drop(columns=["quarter"]), on=["area_id", "qidx"], how="left")
    df = df.sort_values(KEY + ["qidx"]).reset_index(drop=True)
    df["category"] = df["industry_code"].str[:3].map(CATEGORY_BY_PREFIX)
    df["has_sales_data"] = df["industry_code"].isin(sales["industry_code"].unique())

    w = p.window_q
    df["exp4"] = _roll(df, "stores", w)          # 점포·분기 (폐업률 분모)
    df["clo4"] = _roll(df, "closures", w)
    df["ope4"] = _roll(df, "openings", w)
    df["sales4"] = _roll(df, "sales_q", w)       # 증감 계산용: 창 안에 결측 분기가 있으면 NaN
    df["tx4"] = _roll(df, "tx_q", w)
    # 수준(점포당 매출·객단가)용: 4분기 중 매출이 있는 분기만, 분자·분모를 같은 분기로 맞춰 집계
    has_s = df["sales_q"].notna()
    df["_s_avail"] = df["sales_q"].fillna(0.0)
    df["_tx_avail"] = df["tx_q"].fillna(0.0)
    df["_e_avail"] = df["stores"].where(has_s, 0.0)
    df["_n_avail"] = has_s.astype(float)
    s4a, tx4a, e4a, n4a = (_roll(df, c, w) for c in ["_s_avail", "_tx_avail", "_e_avail", "_n_avail"])
    df = df.drop(columns=["_s_avail", "_tx_avail", "_e_avail", "_n_avail"])
    df["stores_avg4"] = df["exp4"] / w
    for c in ["floating_pop", "rent", "closed_months"]:
        df[c + "4"] = _roll(df, c, w) / w         # 지역 지표도 4분기 평균(분기 튐 완화)

    g = df.groupby(KEY, sort=False)
    lag = p.growth_lag_q
    prev_sales = g["sales4"].shift(lag)
    prev_st = g["stores_avg4"].shift(lag)
    df["sales_growth"] = np.where(prev_sales > 0, df["sales4"] / prev_sales - 1.0, np.nan)
    df["store_growth"] = np.where(prev_st > 0, df["stores_avg4"] / prev_st - 1.0, np.nan)

    sps = s4a / e4a.where(e4a > 0) / 3.0
    ok = (n4a >= p.min_sales_quarters) & (e4a >= p.min_exposure_for_sales) & (sps >= p.min_sales_ps_m)
    df["sales_ps_m"] = np.where(ok, sps, np.nan)                                       # 점포당 월매출(원)
    df["ticket"] = np.where(ok & (tx4a > 0), s4a / tx4a.where(tx4a > 0), np.nan)      # 객단가(원/건)
    df["tx_ps_day"] = np.where(ok, tx4a / e4a.where(e4a > 0) / p.days_per_quarter, np.nan)  # 점포당 일 결제건수
    # 매출을 믿을 수 없는 셀(카드 매출이 거의 안 잡힘)은 매출 증감도 잡음 → 쓰지 않는다(전년 셀이 그랬어도 마찬가지)
    df["_ok"] = ok.astype(float)
    ok_prev = df.groupby(KEY, sort=False)["_ok"].shift(lag) == 1.0
    df = df.drop(columns=["_ok"])
    df.loc[~(ok & ok_prev), "sales_growth"] = np.nan

    # 업종 전체(서울) 집계 — 업종 기저 위험과 업종 트렌드
    #   트렌드는 t와 t−4 모두 값이 있는 지역만 합산(결측 지역이 섞여 증감이 왜곡되지 않게)
    both = df["sales4"].notna() & prev_sales.notna() & ok & ok_prev    # 올해·작년 모두 매출을 믿을 수 있는 지역만
    df["_s_now"] = df["sales4"].where(both, 0.0)
    df["_s_prev"] = prev_sales.where(both, 0.0)
    ind = df.groupby(["industry_code", "qidx"]).agg(ind_clo4=("clo4", "sum"), ind_exp4=("exp4", "sum"),
                                                     ind_ope4=("ope4", "sum"), s_now=("_s_now", "sum"),
                                                     s_prev=("_s_prev", "sum"),
                                                     ind_st4=("stores_avg4", "sum")).reset_index()
    df = df.drop(columns=["_s_now", "_s_prev"])
    ind = ind.sort_values(["industry_code", "qidx"])
    gi = ind.groupby("industry_code")
    ind["ind_sales_growth"] = np.where(ind["s_prev"] > 0, ind["s_now"] / ind["s_prev"] - 1.0, np.nan)
    ind["ind_store_growth"] = ind["ind_st4"] / gi["ind_st4"].shift(lag) - 1.0
    ind.loc[ind["ind_exp4"].isna() | (ind["ind_exp4"] <= 0), ["ind_clo4", "ind_exp4"]] = np.nan
    ind["mu_ind"] = ind["ind_clo4"] / ind["ind_exp4"]
    ind["mu_ind_entry"] = ind["ind_ope4"] / ind["ind_exp4"]
    allq = df.groupby("qidx").agg(a_clo=("clo4", "sum"), a_exp=("exp4", "sum")).reset_index()
    allq["mu_all"] = np.where(allq["a_exp"] > 0, allq["a_clo"] / allq["a_exp"], np.nan)
    df = df.merge(ind[["industry_code", "qidx", "mu_ind", "mu_ind_entry", "ind_sales_growth", "ind_store_growth"]],
                  on=["industry_code", "qidx"], how="left")
    df = df.merge(allq[["qidx", "mu_all"]], on="qidx", how="left")

    # 백테스트 정답: 향후 4분기(t+1..t+4) 폐업 수 / 점포·분기
    g = df.groupby(KEY, sort=False)
    df["fwd_clo4"] = g["clo4"].shift(-w)
    df["fwd_exp4"] = g["exp4"].shift(-w)
    df["fwd_rate"] = np.where(df["fwd_exp4"] > 0, df["fwd_clo4"] / df["fwd_exp4"], np.nan)
    df["fwd_sales_ps_m"] = g["sales_ps_m"].shift(-w)
    return df


def estimate_eb(panel: pd.DataFrame, qidx_fit, p: FeatureParams = FeatureParams()) -> dict:
    """학습 기간 분기(qidx_fit)만으로 업종별 EB 사전강도 k 추정 (폐업, 개업 각각)."""
    d = panel[panel["qidx"].isin(qidx_fit) & panel["exp4"].notna()]
    k_clo, cv_clo = eb_prior_strength(d["clo4"], d["exp4"], d["industry_code"], d["qidx"], p.eb_k_min, p.eb_k_max)
    k_ope, cv_ope = eb_prior_strength(d["ope4"], d["exp4"], d["industry_code"], d["qidx"], p.eb_k_min, p.eb_k_max)
    return {"k_close": k_clo.to_dict(), "k_entry": k_ope.to_dict(), "cv_close": cv_clo, "cv_entry": cv_ope,
            "k_close_default": float(k_clo.median()) if len(k_clo) else p.eb_k_max,
            "k_entry_default": float(k_ope.median()) if len(k_ope) else p.eb_k_max}


def add_model_features(panel: pd.DataFrame, eb: dict, p: FeatureParams = FeatureParams()) -> pd.DataFrame:
    """EB 보정 + 업종 내 백분위 + 모델 입력(x_*) + 수요점수 D + 신뢰도."""
    df = panel.copy()
    kc = df["industry_code"].map(eb["k_close"]).fillna(eb["k_close_default"])
    ke = df["industry_code"].map(eb["k_entry"]).fillna(eb["k_entry_default"])
    exp4 = df["exp4"].fillna(0)
    df["eb_k"] = kc
    df["rate_eb"] = eb_rate(df["clo4"].fillna(0), exp4, df["mu_ind"], kc)
    df["entry_eb"] = eb_rate(df["ope4"].fillna(0), exp4, df["mu_ind_entry"], ke)
    df["local_weight"] = local_weight(exp4, kc)

    grp = [df["industry_code"], df["qidx"]]
    valid = df["exp4"] > 0
    def P(v):  # 업종·분기 내 백분위 (점포 있는 셀만)
        return pct_rank(v.where(valid), grp)
    df["p_sales_decline"] = P(-df["sales_growth"])
    df["p_store_surge"] = P(df["store_growth"])
    df["p_entry_heat"] = P(df["entry_eb"])
    df["p_rent_burden"] = P(df["rent4"] / df["sales_ps_m"])
    df["p_density"] = P(df["stores_avg4"] / df["floating_pop4"])
    df["p_low_sales"] = P(-df["sales_ps_m"])
    df["demand_D"] = P(df["sales_ps_m"])           # 적합도 D (높을수록 좋음)
    # 지역 단위 요인: 분기 내 지역 간 백분위 (업종 무관)
    ar = df.drop_duplicates(["area_id", "qidx"])[["area_id", "qidx", "closed_months4"]].copy()
    ar["p_short_life"] = pct_rank(-ar["closed_months4"], ar["qidx"])
    df = df.merge(ar[["area_id", "qidx", "p_short_life"]], on=["area_id", "qidx"], how="left")

    # 모델 입력: 상대 요인은 (P-50)/50 ∈ [-1,1], 결측은 0(=중립)
    for f in ["sales_decline", "store_surge", "entry_heat", "rent_burden", "density", "low_sales", "short_life"]:
        df["x_" + f] = ((df["p_" + f] - 50.0) / 50.0).fillna(0.0)
    df["x_ind_base"] = np.log(df["mu_ind"].clip(lower=1e-6)) - np.log(df["mu_all"].clip(lower=1e-6))
    df["x_area_hist"] = np.log(df["rate_eb"].clip(lower=1e-6)) - np.log(df["mu_ind"].clip(lower=1e-6))
    g_ind = df["ind_sales_growth"].where(df["ind_sales_growth"].notna(), df["ind_store_growth"])   # 매출 추세가 없으면 점포 추세
    df["x_ind_trend"] = (-g_ind.clip(-p.trend_clip, p.trend_clip) / p.trend_clip).fillna(0.0)
    df[["x_ind_base", "x_area_hist"]] = df[["x_ind_base", "x_area_hist"]].fillna(0.0)
    df["offset"] = np.log(df["mu_all"].clip(lower=1e-6))

    e = df["exp4"].fillna(0)
    df["confidence"] = np.select([e >= 40, e >= 12], ["높음", "보통"], default="낮음")
    return df
