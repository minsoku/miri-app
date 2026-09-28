"""서울시 상권분석서비스 CSV → 표준 패널.

자치구 단위(OA-22173 점포-자치구 등)와 상권 단위(OA-15577 점포-상권 등)는 컬럼 구조가 같고
지역 키만 다르다(자치구_코드 ↔ 상권_코드). level 인자로 전환한다.

원본 컬럼 해석 (2019Q1~2025Q2 원본으로 역산 검증)
- 유사_업종_점포_수 = 점포_수 + 프랜차이즈_점포_수  (전 행 일치)  → '대체 업종'이 아님!
- 폐업_률 = 폐업_점포_수 / 유사_업종_점포_수 × 100   (99.8% 일치, 반올림 차)
- 당월_매출_금액 = 컬럼명과 달리 '분기 합계'로 판단
    근거: 한식 점포당 연매출 ≈ 2.7억 ↔ 외식업체 경영실태조사 2024 업체당 연매출 2.55억
"""
from __future__ import annotations
import re
import pandas as pd

LEVEL_KEYS = {
    "district":   ("자치구_코드", "자치구_코드_명"),
    "trade_area": ("상권_코드", "상권_코드_명"),
}


def _read(path: str) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"인코딩을 알 수 없음: {path}")


def load_stores(path: str, level: str = "district") -> pd.DataFrame:
    idc, nmc = LEVEL_KEYS[level]
    df = _read(path)
    out = pd.DataFrame({
        "area_id": df[idc].astype(str),
        "area_name": df[nmc],
        "industry_code": df["서비스_업종_코드"],
        "industry_name": df["서비스_업종_코드_명"],
        "quarter": df["기준_년분기_코드"].astype(int),
        "stores": df["유사_업종_점포_수"].fillna(0),          # 전체 점포(프랜차이즈 포함) = 폐업률 분모
        "stores_nf": df["점포_수"].fillna(0),
        "franchise": df["프랜차이즈_점포_수"].fillna(0),
        "openings": df["개업_점포_수"].fillna(0),
        "closures": df["폐업_점포_수"].fillna(0),
    })
    return out


def load_sales(path: str, level: str = "district") -> pd.DataFrame:
    idc, _ = LEVEL_KEYS[level]
    df = _read(path)
    return pd.DataFrame({
        "area_id": df[idc].astype(str),
        "industry_code": df["서비스_업종_코드"],
        "quarter": df["기준_년분기_코드"].astype(int),
        "sales_q": df["당월_매출_금액"],     # 분기 합계(원)
        "tx_q": df["당월_매출_건수"],         # 분기 결제 건수
    })


def load_area_metrics(pop_path: str, change_path: str, rent_path: str | None = None,
                      level: str = "district", parent_map: pd.DataFrame | None = None) -> pd.DataFrame:
    """지역 단위 지표: 유동인구, 폐업 점포 평균 영업개월, 임대시세.

    rent_path: 자치구 임대시세(기준_년분기_코드='2019년 1분기' 형식, 자치구_코드_명, 전체임대료).
               상권 단위에는 공개 임대료가 없으므로 parent_map(area_id→district_name)으로 자치구 값을 상속.
    """
    idc, nmc = LEVEL_KEYS[level]
    pop = _read(pop_path)
    pop = pd.DataFrame({"area_id": pop[idc].astype(str), "quarter": pop["기준_년분기_코드"].astype(int),
                        "floating_pop": pop["총_유동인구_수"]})
    ch = _read(change_path)
    ch = pd.DataFrame({"area_id": ch[idc].astype(str), "quarter": ch["기준_년분기_코드"].astype(int),
                       "closed_months": ch["폐업_영업_개월_평균"], "op_months": ch["운영_영업_개월_평균"],
                       "change_code": ch["상권_변화_지표"]})
    area = pop.merge(ch, on=["area_id", "quarter"], how="outer")
    if rent_path:
        r = _read(rent_path)
        r = r[r["자치구_코드_명"] != "서울시 전체"].copy()
        yq = r["기준_년분기_코드"].astype(str).str.extract(r"(\d{4})년\s*(\d)분기")
        r["quarter"] = yq[0].astype(int) * 10 + yq[1].astype(int)
        r = r.rename(columns={"자치구_코드_명": "district_name", "전체임대료": "rent"})[["district_name", "quarter", "rent"]]
        if level == "district":
            names = _read(pop_path)[[idc, nmc]].drop_duplicates()
            names = names.rename(columns={idc: "area_id", nmc: "district_name"})
            names["area_id"] = names["area_id"].astype(str)
        else:
            if parent_map is None:
                raise ValueError("상권 단위 임대료 상속에는 parent_map(area_id, district_name)이 필요")
            names = parent_map[["area_id", "district_name"]].astype({"area_id": str})
        area = area.merge(names, on="area_id", how="left").merge(r, on=["district_name", "quarter"], how="left")
        area = area.drop(columns=["district_name"])
    return area


def quarter_index(q: pd.Series | int):
    """20243 → 연속 정수 인덱스 (연*4 + 분기-1)."""
    return (q // 10) * 4 + (q % 10) - 1


def index_to_quarter(i):
    return (i // 4) * 10 + (i % 4) + 1
