"""데이터 → 특징 → 모델 학습/저장을 한 번에 (배치: 분기 1회 실행)."""
from __future__ import annotations
import json
import pandas as pd
from . import loaders as L, features as F
from .risk import RiskModel
from .config import FeatureParams, RiskParams


def load_district_data(data_dir: str):
    st = L.load_stores(f"{data_dir}/점포_자치구.csv")
    sa = L.load_sales(f"{data_dir}/매출_자치구.csv")
    ar = L.load_area_metrics(f"{data_dir}/유동인구_자치구.csv", f"{data_dir}/상권변화_자치구.csv",
                             f"{data_dir}/임대료_자치구.csv")
    return st, sa, ar


def train(panel: pd.DataFrame, fit_qidx: list[int], factors=None, fp=FeatureParams(), rp=RiskParams()):
    """학습 분기로 EB k 추정 → 전체 분기 특징 계산 → 학습 분기로 위험 모델 적합."""
    eb = F.estimate_eb(panel, fit_qidx, fp)
    fe = F.add_model_features(panel, eb, fp)
    tr = fe[fe["qidx"].isin(fit_qidx) & (fe["exp4"] > 0) & (fe["fwd_exp4"] > 0)]
    model = RiskModel(factors, rp).fit(tr)
    model.calibrate_levels(fe)          # 모든 분기의 c_t (각 분기 자기 단면만 사용 → 미래 정보 없음)
    model.set_reference(tr)
    model.meta["eb"] = {"cv_close": eb["cv_close"], "cv_entry": eb["cv_entry"],
                        "k_close_default": eb["k_close_default"], "k_entry_default": eb["k_entry_default"]}
    return model, eb, fe


def save_bundle(path: str, model: RiskModel, eb: dict):
    """서비스 배포 묶음: 위험모델 파라미터 + EB 사전강도 (scoring_model_versions에 저장할 JSON)."""
    d = json.loads(model.to_json())
    d["eb"] = eb
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
