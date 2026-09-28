"""운영 정리 작업(선택 실행)."""
from __future__ import annotations
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session
from .. import models as M


def purge_legacy_accounts(db: Session, apply: bool = False) -> dict:
    """0.1(로그인 시절)의 계정 정보를 지운다: users 행(이메일·이름·비밀번호 해시), 그 계정이 만든 분석(딸린 추천·위험도·
    손익분기·리포트까지 — 외래키 CASCADE), 계정이 저장한 목록, 쓸모없어진 비회원 소유 확인 해시.
    0.2부터 로그인이 없어 이 데이터는 주인도 볼 수 없다. apply=False면 개수만 센다(아무것도 지우지 않음)."""
    count = lambda q: db.scalar(select(func.count()).select_from(q.subquery())) or 0  # noqa: E731
    out = {
        "users": count(select(M.User.user_id)),
        "member_analyses": count(select(M.AnalysisRequest.request_id).where(M.AnalysisRequest.user_id.is_not(None))),
        "member_saved": count(select(M.SavedReport.saved_report_id).where(M.SavedReport.user_id.is_not(None))),
        "claim_hashes": count(select(M.AnalysisRequest.request_id).where(M.AnalysisRequest.claim_token_hash.is_not(None))),
    }
    if apply:
        db.execute(delete(M.SavedReport).where(M.SavedReport.user_id.is_not(None)))
        db.execute(delete(M.AnalysisRequest).where(M.AnalysisRequest.user_id.is_not(None)))
        db.execute(delete(M.User))
        db.execute(update(M.AnalysisRequest).where(M.AnalysisRequest.claim_token_hash.is_not(None)).values(claim_token_hash=None))
        db.commit()
    return out
