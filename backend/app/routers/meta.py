from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from miri_engine.config import GOAL_WEIGHTS
from ..db import get_db
from ..schemas import MetaOut
from ..services.catalog import quarter_label, DISPLAY_GROUPS
from ..services.engine import get_state

router = APIRouter(tags=["메타"])


@router.get("/health", summary="헬스 체크")
def health():
    return {"status": "ok"}


@router.get("/meta", response_model=MetaOut, summary="데이터 기준 분기·모델 버전·등급 기준")
def meta(db: Session = Depends(get_db)):
    st = get_state(db)
    levels = {a["level"] for a in st.areas.values()}
    p = st.model.params
    return {"data_quarter": st.quarter, "data_quarter_label": quarter_label(st.quarter),
            "model_version": st.model_version, "trained_at": st.trained_at,
            "analysis_level": "trade_area" if "trade_area" in levels else "district",
            "grade_cuts": [p.cut_normal, p.cut_high, p.cut_critical], "grade_rate_bounds": st.grade_rate_bounds(),
            "goals": GOAL_WEIGHTS, "notices": st.notices}


@router.get("/industries", summary="업종 목록 + 관심 업종 칩(SB-04)", tags=["업종"])
def industries(db: Session = Depends(get_db)):
    st = get_state(db)
    inds = sorted(st.industries.values(), key=lambda d: d["code"])
    names = {d["code"]: d["name"] for d in inds}
    return {
        "groups": [{**g, "names": [names.get(c, c) for c in g["codes"]]} for g in DISPLAY_GROUPS],
        "industries": [{"code": d["code"], "name": d["name"], "category": d["category"],
                        "has_sales_data": d["has_sales_data"], "recommendable": d["recommendable"],
                        "license": d["license"], "display_group": d["display_group"]} for d in inds],
    }
