from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ..db import get_db
from ..errors import ApiError
from ..schemas import AreaCardOut, CandidatesOut, CompareIn, CompareOut, PlaceOut
from ..services import areas as S
from ..services.engine import get_state

router = APIRouter(tags=["상권 (SB-02)"])


@router.get("/places/search", response_model=list[PlaceOut], summary="지역·상권 검색 (예: 강남역)")
def search_places(q: str = Query(..., min_length=1, max_length=50), limit: int = Query(8, ge=1, le=20),
                  db: Session = Depends(get_db)):
    return S.search(db, get_state(db), q, limit)


@router.get("/areas/candidates", response_model=CandidatesOut, summary="반경 내 후보 상권")
def area_candidates(lat: float = Query(..., ge=33, le=39), lng: float = Query(..., ge=124, le=132),
                    radius_m: int = Query(500, ge=100, le=5000), place_name: str | None = Query(None, max_length=100),
                    db: Session = Depends(get_db)):
    return S.candidates(get_state(db), lat, lng, radius_m, place_name)


@router.get("/areas/map", summary="지도용 경계(GeoJSON, 단순화)")
def area_map(db: Session = Depends(get_db)):
    return S.simplified_map(get_state(db), db)


@router.post("/areas/compare", response_model=CompareOut, summary="상권 비교 (UC-02) — SB-02 '후보 비교' 시트")
def area_compare(body: CompareIn, db: Session = Depends(get_db)):
    return S.compare(get_state(db), body.area_codes, body.industry_code)


@router.get("/areas/{area_code}", response_model=AreaCardOut, summary="상권 기본 지표")
def area_detail(area_code: str, db: Session = Depends(get_db)):
    st = get_state(db)
    if area_code not in st.areas:
        raise ApiError(404, "UNKNOWN_AREA", "상권을 찾을 수 없어요")
    return S.area_card(st, area_code)
