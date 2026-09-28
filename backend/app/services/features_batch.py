"""분기 배치: DB 원천 → M-02 특징 → M-04 위험모델 학습(v2) → scoring_model_versions + area_category_features.

API는 이 결과만 읽는다(요청 시 학습·특징 계산 없음). 원천이 갱신되면 이 배치를 다시 돌린다.
학습 구간은 백테스트 최종 모델과 같다: 특징이 완전한 첫 분기(이력 8분기) ~ 정답 4분기가 확정된 마지막 분기.
"""
from __future__ import annotations
import json
import math
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session
from miri_engine import features as F, pipeline as P
from miri_engine.config import MODEL_VERSION, FeatureParams, RISK_FACTORS
from miri_engine.suitability import risk_table
from .. import models as M

# 엔진 컬럼명 → area_category_features 명시 컬럼
EXPLICIT = {
    "exp4": "exposure_4q", "clo4": "closures_4q", "ope4": "openings_4q", "stores_avg4": "stores_avg_4q",
    "rate_eb": "rate_eb", "local_weight": "local_weight", "sales_ps_m": "sales_ps_m", "ticket": "avg_ticket",
    "tx_ps_day": "tx_ps_day", "demand_D": "demand_score", "pred_q_rate": "pred_q_rate",
    "pred_annual_rate": "pred_annual_rate", "risk_score": "risk_score", "risk_grade": "risk_level",
    "risk_pct_in_ind": "location_risk_pct", "confidence": "confidence",
}
# 나머지는 payload_json (API 설명·화면용)
PAYLOAD = (["stores", "stores_nf", "franchise", "openings", "closures", "entry_eb", "eb_k", "mu_ind", "mu_all",
            "mu_ind_entry", "sales_growth", "store_growth", "ind_sales_growth", "ind_store_growth", "floating_pop4",
            "rent4", "closed_months4", "change_code", "has_sales_data", "category",
            "p_sales_decline", "p_store_surge", "p_entry_heat", "p_rent_burden", "p_density", "p_low_sales",
            "p_short_life"]
           + ["x_" + f for f in RISK_FACTORS] + ["eff_" + f for f in RISK_FACTORS])
TIME_KEYS = ["t00", "t06", "t11", "t14", "t17", "t21"]
AGE_KEYS = ["a10", "a20", "a30", "a40", "a50", "a60"]


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def engine_inputs_from_db(db: Session) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """miri_engine.loaders 와 같은 표준 패널 형식(st, sa, ar)을 DB 원천 테이블에서 만든다."""
    A, C = M.CommercialArea, M.BusinessCategory
    S = M.StoreStatistic
    st = pd.DataFrame(db.execute(
        select(A.area_code, A.area_name, C.category_code, C.category_name, S.base_quarter, S.total_store_count,
               S.store_count, S.franchise_count, S.opening_count, S.closure_count)
        .join(A, A.area_id == S.area_id).join(C, C.category_id == S.category_id)
        .where(A.area_level == "district")).all(),
        columns=["area_id", "area_name", "industry_code", "industry_name", "quarter", "stores", "stores_nf",
                 "franchise", "openings", "closures"])
    SM = M.SalesMetric
    sa = pd.DataFrame(db.execute(
        select(A.area_code, C.category_code, SM.base_quarter, SM.quarterly_sales, SM.quarterly_tx_count)
        .join(A, A.area_id == SM.area_id).join(C, C.category_id == SM.category_id)
        .where(A.area_level == "district")).all(),
        columns=["area_id", "industry_code", "quarter", "sales_q", "tx_q"])
    AM, R = M.AreaMetric, M.RentMetric
    ar = pd.DataFrame(db.execute(
        select(A.area_code, AM.base_quarter, AM.floating_population, AM.avg_closed_months, AM.avg_open_months,
               AM.change_indicator)
        .join(A, A.area_id == AM.area_id).where(A.area_level == "district")).all(),
        columns=["area_id", "quarter", "floating_pop", "closed_months", "op_months", "change_code"])
    rent = pd.DataFrame(db.execute(select(A.area_code, R.base_quarter, R.rent_per_3_3m2)
                                   .join(A, A.area_id == R.area_id)).all(), columns=["area_id", "quarter", "rent"])
    ar = ar.merge(rent, on=["area_id", "quarter"], how="left")
    for df in (st, sa, ar):
        df["quarter"] = df["quarter"].astype(int)
        df["area_id"] = df["area_id"].astype(str)
    for c in ["stores", "stores_nf", "franchise", "openings", "closures"]:
        st[c] = st[c].astype(float)
    for c in ["sales_q", "tx_q"]:
        sa[c] = sa[c].astype(float)
    for c in ["floating_pop", "closed_months", "op_months", "rent"]:
        ar[c] = ar[c].astype(float)
    return st, sa, ar


def sales_profiles(db: Session, latest_q: int, n_quarters: int = 4) -> dict[tuple[str, str], dict]:
    """최근 4분기 매출 구성(시간대·주말·성별·연령) 비중. 화면의 '피크 시간대'·체크리스트 근거."""
    qs = []
    y, k = latest_q // 10, latest_q % 10
    for _ in range(n_quarters):
        qs.append(y * 10 + k)
        k -= 1
        if k == 0:
            y, k = y - 1, 4
    A, C, SM = M.CommercialArea, M.BusinessCategory, M.SalesMetric
    rows = db.execute(select(A.area_code, C.category_code, SM.breakdown_json)
                      .join(A, A.area_id == SM.area_id).join(C, C.category_id == SM.category_id)
                      .where(SM.base_quarter.in_(qs))).all()
    acc: dict[tuple[str, str], dict[str, float]] = {}
    for a, c, bj in rows:
        if not bj:
            continue
        d = acc.setdefault((a, c), {})
        for key, v in json.loads(bj).items():
            if v is not None:
                d[key] = d.get(key, 0.0) + float(v)
    out = {}
    for key, d in acc.items():
        tt = sum(d.get(t, 0.0) for t in TIME_KEYS)
        wk = d.get("wd", 0.0) + d.get("we", 0.0)
        ag = sum(d.get(a, 0.0) for a in AGE_KEYS)
        gd = d.get("m", 0.0) + d.get("f", 0.0)
        if tt <= 0:
            continue
        time_share = {t: round(d.get(t, 0.0) / tt, 4) for t in TIME_KEYS}
        age_share = {a: round(d.get(a, 0.0) / ag, 4) for a in AGE_KEYS} if ag > 0 else {}
        out[key] = {
            "time_share": time_share,
            "peak_slot": max(time_share, key=time_share.get),
            "weekend_share": round(d.get("we", 0.0) / wk, 4) if wk > 0 else None,
            "female_share": round(d.get("f", 0.0) / gd, 4) if gd > 0 else None,
            "age_share": age_share,
            "top_age": max(age_share, key=age_share.get) if age_share else None,
        }
    return out


def _clean(v):
    if v is None:
        return None
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    return v


def build_features(db: Session, metrics: dict | None = None, log=print) -> dict:
    t0 = _utcnow()
    st, sa, ar = engine_inputs_from_db(db)
    if st.empty or sa.empty or ar.empty:
        raise RuntimeError("원천 테이블이 비어 있음 — 먼저 적재(ingest)를 실행하세요")
    panel = F.build_panel(st, sa, ar)
    fp = FeatureParams()
    qmin, qmax = int(panel["qidx"].min()), int(panel["qidx"].max())
    first_feat = qmin + fp.window_q + fp.growth_lag_q - 1
    last_feat = qmax - fp.window_q
    if last_feat < first_feat:
        raise RuntimeError("학습에 필요한 분기 수 부족(최소 13분기)")
    fit_q = list(range(first_feat, last_feat + 1))
    model, eb, fe = P.train(panel, fit_q)
    latest_q = int(fe["quarter"].max())
    version = f"{MODEL_VERSION}@{latest_q}"
    rt = risk_table(fe[fe["quarter"] == latest_q], model)
    log(f"  학습 {len(fit_q)}개 분기 · 셀 {model.meta['n_train']:,}개 · 기준 분기 {latest_q} · 행 {len(rt):,}")

    params = json.loads(model.to_json())
    params["eb"] = eb
    db.execute(update(M.ScoringModelVersion).values(is_active=False))
    row = db.get(M.ScoringModelVersion, version) or M.ScoringModelVersion(model_version=version)
    row.model_type = model.meta.get("model_type", "HYBRID")
    row.params_json = json.dumps(params, ensure_ascii=False)
    row.train_quarters_json = json.dumps(model.meta.get("train_quarters", []))
    row.metrics_json = json.dumps(metrics, ensure_ascii=False) if metrics else None
    row.trained_at = _utcnow()
    row.is_active = True
    db.merge(row)
    db.flush()

    amap = {c: i for c, i in db.execute(select(M.CommercialArea.area_code, M.CommercialArea.area_id))}
    cmap = {c: i for c, i in db.execute(select(M.BusinessCategory.category_code, M.BusinessCategory.category_id))}
    prof = sales_profiles(db, latest_q)
    db.execute(delete(M.AreaCategoryFeature).where(M.AreaCategoryFeature.base_quarter == latest_q,
                                                   M.AreaCategoryFeature.model_version == version))
    recs = []
    for r in rt.to_dict("records"):
        rec = {"area_id": amap[r["area_id"]], "category_id": cmap[r["industry_code"]], "base_quarter": latest_q,
               "model_version": version}
        for src, dst in EXPLICIT.items():
            rec[dst] = _clean(r.get(src))
        payload = {k: _clean(r.get(k)) for k in PAYLOAD}
        # 매출 구성(시간대·주말 비중)도 매출 데이터를 믿을 수 있는 셀만 — 월 몇만 원 수준 셀의 '매출 100%' 같은 쏠림 방지
        payload["profile"] = prof.get((r["area_id"], r["industry_code"])) if _clean(r.get("sales_ps_m")) is not None else None
        rec["payload_json"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        recs.append(rec)
    for i in range(0, len(recs), 2000):
        db.execute(insert(M.AreaCategoryFeature), recs[i:i + 2000])
    db.commit()
    secs = (_utcnow() - t0).total_seconds()
    log(f"  모델 {version} 저장 · 특징 {len(recs):,}행 · {secs:.1f}초")
    return {"model_version": version, "base_quarter": latest_q, "rows": len(recs), "beta": model.beta}
