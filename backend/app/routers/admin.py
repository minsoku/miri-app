from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import require_admin
from .. import models as M
from ..settings import settings
from ..services.engine import reload_state
from ..services.features_batch import build_features
from ..services.ingest import run_ingestion
from ..services import areas as area_svc

# 로그인이 없으므로 서버 환경변수 MIRI_ADMIN_KEY와 같은 값을 X-Admin-Key 헤더로 보내야 쓸 수 있다(지정하지 않으면 꺼짐)
router = APIRouter(prefix="/admin", tags=["관리자 (UC-07)"])


@router.post("/refresh", summary="원천 재적재 + 특징·모델 배치 + 엔진 재로딩")
def refresh(skip_ingest: bool = Query(False), db: Session = Depends(get_db), _: None = Depends(require_admin)):
    logs = [] if skip_ingest else run_ingestion(db, settings.data_dir, log=lambda *_: None)
    out = build_features(db, log=lambda *_: None)
    st = reload_state(db)
    area_svc._map_cache = None
    return {"ingestion": logs, "model_version": out["model_version"], "base_quarter": out["base_quarter"],
            "rows": out["rows"], "notices": st.notices}


@router.get("/ingestion-logs", summary="수집 로그")
def ingestion_logs(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db), _: None = Depends(require_admin)):
    rows = db.execute(select(M.DataIngestionLog, M.DataSource.source_name)
                      .join(M.DataSource, M.DataSource.source_id == M.DataIngestionLog.source_id)
                      .order_by(M.DataIngestionLog.log_id.desc()).limit(limit)).all()
    return [{"log_id": l.log_id, "source": n, "ingested_at": l.ingested_at, "status": l.status, "row_count": l.row_count,
             "max_quarter": l.max_quarter, "error_message": l.error_message} for l, n in rows]
