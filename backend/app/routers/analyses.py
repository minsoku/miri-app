from __future__ import annotations
from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import optional_device
from ..schemas import MAX_ID, AnalysisIn, AnalysisOut, BreakEvenIn, BreakEvenOut, ReportIn, ReportOut, RiskOut
from ..services import analysis as A, breakeven_svc, report_svc, risk_svc
from ..services.engine import get_state

router = APIRouter(prefix="/analyses", tags=["분석 (SB-03~08)"])


@router.post("", response_model=AnalysisOut, status_code=201, summary="분석 실행 → 업종 TOP 5 (UC-01)")
def create_analysis(body: AnalysisIn, db: Session = Depends(get_db)):
    st = get_state(db)
    req = A.run_analysis(db, st, body)
    return A.analysis_out(db, st, req)


@router.get("/{analysis_id}", response_model=AnalysisOut, summary="분석 결과 다시 보기")
def get_analysis(analysis_id: str, db: Session = Depends(get_db)):
    st = get_state(db)
    return A.analysis_out(db, st, A.get_analysis(db, analysis_id))


@router.get("/{analysis_id}/risk/{industry_code}", response_model=RiskOut, summary="폐업 위험도 상세 (UC-03)")
def get_risk(analysis_id: str, industry_code: str, db: Session = Depends(get_db),
             be: int | None = Query(None, ge=1, le=MAX_ID, description="리포트에서 열 때 그 리포트에 반영한 손익분기 id — "
                                    "인근 지역이 비용을 감당하는지(alternatives[].affordable)를 그 비용으로 판단")):
    st = get_state(db)
    out = risk_svc.risk_detail(db, st, A.get_analysis(db, analysis_id), industry_code, be_id=be)
    out.pop("_risk_id", None)
    return out


@router.post("/{analysis_id}/breakeven", response_model=BreakEvenOut, summary="손익분기점 계산 (UC-04)")
def post_breakeven(analysis_id: str, body: BreakEvenIn, db: Session = Depends(get_db)):
    st = get_state(db)
    return breakeven_svc.compute(db, st, A.get_analysis(db, analysis_id), body)


@router.get("/{analysis_id}/breakeven/{break_even_id}", response_model=BreakEvenOut, summary="저장된 손익분기 결과")
def get_breakeven(analysis_id: str, break_even_id: int = Path(ge=1, le=MAX_ID), db: Session = Depends(get_db)):
    return breakeven_svc.get_saved(db, A.get_analysis(db, analysis_id), break_even_id)


@router.post("/{analysis_id}/reports", response_model=ReportOut, status_code=201, summary="액션 리포트 생성 (UC-05)")
def post_report(analysis_id: str, body: ReportIn, db: Session = Depends(get_db),
                device: str | None = Depends(optional_device)):
    st = get_state(db)
    req = A.get_analysis(db, analysis_id)
    rep = report_svc.create_report(db, st, req, body.industry_code, body.break_even_id)
    return report_svc.report_out(db, st, rep, req, device)
