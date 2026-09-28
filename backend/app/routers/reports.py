from __future__ import annotations
from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import optional_device, require_device
from ..schemas import MAX_ID, ActionDoneIn, ActionDoneOut, MemoIn, ReportOut, SaveIn, SavedListOut
from ..services import report_svc
from ..services.engine import get_state

router = APIRouter(tags=["리포트 (SB-08·09)"])


@router.get("/reports/{report_id}", response_model=ReportOut, summary="액션 리포트 조회")
def get_report(report_id: str, db: Session = Depends(get_db), device: str | None = Depends(optional_device)):
    rep, req = report_svc.get_report(db, report_id)
    return report_svc.report_out(db, get_state(db), rep, req, device)


@router.patch("/reports/{report_id}/items/{action_id}", response_model=ActionDoneOut, summary="체크리스트 항목 완료 표시")
def set_item_done(body: ActionDoneIn, report_id: str = Path(min_length=1, max_length=36),
                  action_id: int = Path(ge=1, le=MAX_ID), db: Session = Depends(get_db)):
    return report_svc.set_item_done(db, report_id, action_id, body.done)


# 저장 리포트: 로그인 대신 이 브라우저의 저장 키(X-Device-Key)로 구분한다 — 다른 브라우저·기기의 목록은 보이지 않는다
@router.post("/me/reports", status_code=201, summary="리포트 저장 (UC-06, 이 브라우저의 목록에)")
def save_report(body: SaveIn, db: Session = Depends(get_db), device: str = Depends(require_device)):
    sr = report_svc.save_report(db, device, body.report_id, body.memo)
    return {"saved_report_id": sr.saved_report_id, "report_id": body.report_id}


@router.get("/me/reports", response_model=SavedListOut, summary="이 브라우저의 저장 리포트 (SB-09)")
def my_reports(db: Session = Depends(get_db), device: str = Depends(require_device)):
    items = report_svc.list_saved(db, device, get_state(db))
    return {"count": len(items), "items": items}


# 되돌릴 수 없는 전체 삭제는 따로 이름 붙인 주소로만 — 단건 삭제 주소를 잘못 쓴 요청(끝 '/', id 빠짐)이 전체 삭제가 되지 않게
@router.post("/me/reports/clear", summary="이 브라우저의 저장 리포트 모두 삭제(여럿이 쓰는 컴퓨터 정리)")
def clear_reports(db: Session = Depends(get_db), device: str = Depends(require_device)):
    return {"deleted": report_svc.delete_all_saved(db, device)}


@router.delete("/me/reports/{saved_report_id}", status_code=204, summary="저장 리포트 삭제")
def delete_report(saved_report_id: int = Path(ge=1, le=MAX_ID),
                  report_id: str | None = Query(None, min_length=1, max_length=36,
                                                description="이 저장 항목의 리포트 id(주면 일치할 때만 삭제)"),
                  db: Session = Depends(get_db), device: str = Depends(require_device)):
    report_svc.delete_saved(db, device, saved_report_id, report_id)
    return Response(status_code=204)


@router.patch("/me/reports/{saved_report_id}", summary="저장 리포트 메모 수정(없으면 404 — 다시 저장하지 않음)")
def update_memo(body: MemoIn, saved_report_id: int = Path(ge=1, le=MAX_ID), db: Session = Depends(get_db),
                device: str = Depends(require_device)):
    sr = report_svc.update_memo(db, device, saved_report_id, body.report_id, body.memo)
    return {"saved_report_id": sr.saved_report_id, "memo": sr.memo}
