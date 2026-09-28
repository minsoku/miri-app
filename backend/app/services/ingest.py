"""UC-07 상권 데이터 수집/갱신 (관리자 배치).

원천 CSV(서울시 상권분석서비스, 자치구 단위) → 검증 → DB 원천 테이블 적재 → data_ingestion_logs 기록.
- 파일별로 독립 트랜잭션(SAVEPOINT): 한 파일이 실패해도 나머지는 적재하고, 실패 사유를 로그에 남긴다(대안 흐름).
- 검증: 필수 컬럼, 분기 코드 형식, 알 수 없는 지역 코드, 음수 값. 제외 행이 5%를 넘으면 해당 파일 전체를 FAIL 처리.
- 통계 테이블은 전량 교체(full refresh) 방식. 원천이 분기마다 과거 분기까지 정정 배포되기 때문.
"""
from __future__ import annotations
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
import pandas as pd
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session
from miri_engine.config import CATEGORY_BY_PREFIX, DEFAULT_COGS_RATE, LICENSED_INDUSTRIES
from .. import models as M
from . import geo
from .catalog import CODE_TO_GROUP, DATA_SOURCES, PLANNED_SOURCES, quarter_start

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"
MAX_BAD_ROW_SHARE = 0.05

LICENSE_BASIS = {
    "의사": "의료법 제33조", "치과의사": "의료법 제33조", "한의사": "의료법 제33조", "수의사": "수의사법 제17조",
    "변호사": "변호사법", "변리사": "변리사법", "법무사": "법무사법", "공인회계사": "공인회계사법", "세무사": "세무사법",
    "약사": "약사법 제20조", "공인중개사": "공인중개사법 제9조", "안경사": "의료기사 등에 관한 법률 제12조",
    "미용사(일반)": "공중위생관리법 제6조", "미용사(네일)": "공중위생관리법 제6조", "미용사(피부)": "공중위생관리법 제6조",
}
COGS_SOURCE = {"외식업": "농림축산식품부·한국농촌경제연구원 「2024 외식업체 경영실태조사」 식재료비/매출 40.7%"}


class IngestError(Exception):
    pass


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise IngestError(f"파일 없음: {path.name}")
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise IngestError(f"인코딩을 알 수 없음: {path.name}")


def require_columns(df: pd.DataFrame, cols: list[str], name: str):
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise IngestError(f"{name}: 필수 컬럼 누락 {missing}")


def valid_quarter(s: pd.Series) -> pd.Series:
    q = pd.to_numeric(s, errors="coerce")
    return q.notna() & (q // 10).between(2000, 2100) & (q % 10).between(1, 4)


def _filter_rows(df: pd.DataFrame, mask: pd.Series, name: str, reasons: list[str], why: str) -> pd.DataFrame:
    n_bad = int((~mask).sum())
    if n_bad:
        reasons.append(f"{why} {n_bad}행")
    return df[mask]


def _finish_validation(n_total: int, n_kept: int, name: str, reasons: list[str]) -> str | None:
    if n_total == 0:
        raise IngestError(f"{name}: 데이터 0행")
    bad_share = 1 - n_kept / n_total
    if bad_share > MAX_BAD_ROW_SHARE:
        raise IngestError(f"{name}: 검증 제외 {bad_share:.1%} (> {MAX_BAD_ROW_SHARE:.0%}) — " + ", ".join(reasons))
    return ("검증 제외: " + ", ".join(reasons)) if reasons else None


# ─────────────────────────── 기준 데이터(시드) ───────────────────────────
def seed_sources(db: Session) -> dict[str, M.DataSource]:
    out = {}
    for s in DATA_SOURCES + PLANNED_SOURCES:
        row = db.scalar(select(M.DataSource).where(M.DataSource.source_name == s["source_name"]))
        if row is None:
            row = M.DataSource(source_name=s["source_name"])
            db.add(row)
        for k in ("source_type", "update_cycle", "description", "dataset_code", "url"):
            setattr(row, k, s.get(k))
        row.file_name = s.get("file_name")
        if "key" in s:
            out[s["key"]] = row
    db.flush()
    return out


def seed_policies(db: Session) -> int:
    d = json.loads((SEED_DIR / "policies.json").read_text(encoding="utf-8"))
    checked = date.fromisoformat(d["checked_at"])
    for p in d["policies"]:
        row = db.scalar(select(M.PolicySupport).where(M.PolicySupport.policy_name == p["policy_name"]))
        if row is None:
            row = M.PolicySupport(policy_name=p["policy_name"])
            db.add(row)
        for k, v in p.items():
            setattr(row, k, v)
        row.checked_at = checked
    db.flush()
    return len(d["policies"])


def seed_cost_profiles(db: Session):
    for cat, rate in DEFAULT_COGS_RATE.items():
        row = db.get(M.CategoryCostProfile, cat) or M.CategoryCostProfile(parent_category=cat)
        row.default_cogs_rate = rate
        row.source = COGS_SOURCE.get(cat, "공식 근거 없음 → 사용자 입력 필요")
        db.merge(row)
    db.flush()


# ─────────────────────────── 원천 적재 단계 ───────────────────────────
def ingest_areas(db: Session, data_dir: Path) -> tuple[int, int | None, str | None]:
    df = read_csv(data_dir / "점포_자치구.csv")
    require_columns(df, ["자치구_코드", "자치구_코드_명"], "자치구 목록")
    areas = df[["자치구_코드", "자치구_코드_명"]].drop_duplicates().astype({"자치구_코드": str})
    gj = geo.load_geojson(SEED_DIR / "seoul_districts.geojson")
    by_code = {f["properties"]["SIG_CD"]: f for f in gj["features"]}
    missing = sorted(set(areas["자치구_코드"]) - set(by_code))
    for code, name in areas.itertuples(index=False):
        row = db.scalar(select(M.CommercialArea).where(M.CommercialArea.area_code == code))
        if row is None:
            row = M.CommercialArea(area_code=code)
            db.add(row)
        row.area_name, row.area_level, row.city, row.province = name, "district", name, "서울특별시"
        feat = by_code.get(code)
        if feat is not None:
            lat, lng = geo.centroid(feat["geometry"])
            row.latitude, row.longitude = round(lat, 6), round(lng, 6)
            row.boundary_geojson = json.dumps(feat["geometry"], separators=(",", ":"))
    db.flush()
    note = f"경계 없음: {missing}" if missing else None
    return len(areas), None, note


def _area_map(db: Session) -> dict[str, int]:
    return {c: i for c, i in db.execute(select(M.CommercialArea.area_code, M.CommercialArea.area_id))}


def _area_name_map(db: Session) -> dict[str, int]:
    return {n: i for n, i in db.execute(select(M.CommercialArea.area_name, M.CommercialArea.area_id))}


def _cat_map(db: Session) -> dict[str, int]:
    return {c: i for c, i in db.execute(select(M.BusinessCategory.category_code, M.BusinessCategory.category_id))}


def ingest_stores(db: Session, data_dir: Path):
    name = "점포"
    df = read_csv(data_dir / "점포_자치구.csv")
    cols = ["기준_년분기_코드", "자치구_코드", "서비스_업종_코드", "서비스_업종_코드_명", "점포_수", "유사_업종_점포_수",
            "개업_점포_수", "폐업_점포_수", "프랜차이즈_점포_수"]
    require_columns(df, cols, name)
    n0, reasons = len(df), []
    amap = _area_map(db)
    df = _filter_rows(df, valid_quarter(df["기준_년분기_코드"]), name, reasons, "분기 코드 오류")
    df = _filter_rows(df, df["자치구_코드"].astype(str).isin(amap), name, reasons, "알 수 없는 지역")
    num = ["점포_수", "유사_업종_점포_수", "개업_점포_수", "폐업_점포_수", "프랜차이즈_점포_수"]
    df = _filter_rows(df, (df[num].fillna(0) >= 0).all(axis=1), name, reasons, "음수 값")
    n_blank = int(df[num].isna().any(axis=1).sum())
    if n_blank:
        reasons.append(f"빈 개수 칸 0으로 처리 {n_blank}행")
    df = df.assign(**{c: df[c].fillna(0) for c in num})
    df = _filter_rows(df, ~df.duplicated(["기준_년분기_코드", "자치구_코드", "서비스_업종_코드"]), name, reasons, "중복")
    note = _finish_validation(n0, len(df), name, reasons)

    # 업종 마스터 (업종 코드·명 → business_categories)
    inds = df[["서비스_업종_코드", "서비스_업종_코드_명"]].drop_duplicates("서비스_업종_코드")
    for code, nm in inds.itertuples(index=False):
        row = db.scalar(select(M.BusinessCategory).where(M.BusinessCategory.category_code == code))
        if row is None:
            row = M.BusinessCategory(category_code=code)
            db.add(row)
        row.category_name = nm
        row.parent_category = CATEGORY_BY_PREFIX.get(code[:3], "기타")
        row.display_group = CODE_TO_GROUP.get(code)
    db.flush()
    cmap = _cat_map(db)
    for code, lic in LICENSED_INDUSTRIES.items():
        if code in cmap:
            db.merge(M.IndustryLicense(category_id=cmap[code], license_name=lic, legal_basis=LICENSE_BASIS.get(lic)))

    db.execute(delete(M.StartupClosureHistory))
    db.execute(delete(M.StoreStatistic))
    recs = [{
        "area_id": amap[str(r.자치구_코드)], "category_id": cmap[r.서비스_업종_코드], "base_quarter": int(r.기준_년분기_코드),
        "base_date": quarter_start(int(r.기준_년분기_코드)), "store_count": int(r.점포_수 or 0),
        "total_store_count": int(r.유사_업종_점포_수 or 0), "franchise_count": int(r.프랜차이즈_점포_수 or 0),
        "opening_count": int(r.개업_점포_수 or 0), "closure_count": int(r.폐업_점포_수 or 0)}
        for r in df.itertuples(index=False)]
    for i in range(0, len(recs), 5000):
        db.execute(insert(M.StoreStatistic), recs[i:i + 5000])
    _build_yearly_history(db)
    return len(recs), int(df["기준_년분기_코드"].max()), note


def _build_yearly_history(db: Session):
    """완결된 연도(4개 분기 모두 있는 해)만 연 단위 창·폐업 집계."""
    rows = db.execute(select(M.StoreStatistic.area_id, M.StoreStatistic.category_id, M.StoreStatistic.base_quarter,
                             M.StoreStatistic.total_store_count, M.StoreStatistic.opening_count,
                             M.StoreStatistic.closure_count)).all()
    if not rows:
        return
    d = pd.DataFrame(rows, columns=["area_id", "category_id", "q", "stores", "open", "close"])
    d["year"] = d["q"] // 10
    full_years = [y for y, g in d.groupby("year") if g["q"].nunique() == 4]
    d = d[d["year"].isin(full_years)]
    agg = d.groupby(["area_id", "category_id", "year"]).agg(open=("open", "sum"), close=("close", "sum"),
                                                              stores=("stores", "mean")).reset_index()
    recs = [{"area_id": int(r.area_id), "category_id": int(r.category_id), "base_year": int(r.year),
             "startup_count": int(r.open), "closure_count": int(r.close),
             "closure_rate": round(100.0 * r.close / r.stores, 2) if r.stores > 0 else None}
            for r in agg.itertuples(index=False)]
    for i in range(0, len(recs), 5000):
        db.execute(insert(M.StartupClosureHistory), recs[i:i + 5000])


SALES_BREAKDOWN = {  # 저장 키 → 원천 컬럼
    "wd": "주중_매출_금액", "we": "주말_매출_금액",
    "t00": "시간대_00_06_매출_금액", "t06": "시간대_06_11_매출_금액", "t11": "시간대_11_14_매출_금액",
    "t14": "시간대_14_17_매출_금액", "t17": "시간대_17_21_매출_금액", "t21": "시간대_21_24_매출_금액",
    "m": "남성_매출_금액", "f": "여성_매출_금액",
    "a10": "연령대_10_매출_금액", "a20": "연령대_20_매출_금액", "a30": "연령대_30_매출_금액",
    "a40": "연령대_40_매출_금액", "a50": "연령대_50_매출_금액", "a60": "연령대_60_이상_매출_금액",
}


def ingest_sales(db: Session, data_dir: Path):
    name = "추정매출"
    df = read_csv(data_dir / "매출_자치구.csv")
    cols = ["기준_년분기_코드", "자치구_코드", "서비스_업종_코드", "당월_매출_금액", "당월_매출_건수"]
    require_columns(df, cols, name)
    n0, reasons = len(df), []
    amap, cmap = _area_map(db), _cat_map(db)
    if not cmap:
        raise IngestError("업종 마스터가 비어 있음(점포 파일 먼저 적재)")
    df = _filter_rows(df, valid_quarter(df["기준_년분기_코드"]), name, reasons, "분기 코드 오류")
    df = _filter_rows(df, df["자치구_코드"].astype(str).isin(amap), name, reasons, "알 수 없는 지역")
    df = _filter_rows(df, df["서비스_업종_코드"].isin(cmap), name, reasons, "알 수 없는 업종")
    df = _filter_rows(df, (df[["당월_매출_금액", "당월_매출_건수"]].fillna(0) >= 0).all(axis=1), name, reasons, "음수 값")
    df = _filter_rows(df, ~df.duplicated(["기준_년분기_코드", "자치구_코드", "서비스_업종_코드"]), name, reasons, "중복")
    note = _finish_validation(n0, len(df), name, reasons)
    have = [k for k, c in SALES_BREAKDOWN.items() if c in df.columns]
    db.execute(delete(M.SalesMetric))
    recs = []
    for r in df.to_dict("records"):
        bd = {k: (None if pd.isna(r[SALES_BREAKDOWN[k]]) else int(r[SALES_BREAKDOWN[k]])) for k in have}
        recs.append({"area_id": amap[str(r["자치구_코드"])], "category_id": cmap[r["서비스_업종_코드"]],
                     "base_quarter": int(r["기준_년분기_코드"]), "base_date": quarter_start(int(r["기준_년분기_코드"])),
                     "quarterly_sales": None if pd.isna(r["당월_매출_금액"]) else int(r["당월_매출_금액"]),
                     "quarterly_tx_count": None if pd.isna(r["당월_매출_건수"]) else int(r["당월_매출_건수"]),
                     "breakdown_json": json.dumps(bd, separators=(",", ":"))})
    for i in range(0, len(recs), 5000):
        db.execute(insert(M.SalesMetric), recs[i:i + 5000])
    with_sales = set(df["서비스_업종_코드"].unique())
    for cat in db.scalars(select(M.BusinessCategory)):
        cat.has_sales_data = cat.category_code in with_sales
    return len(recs), int(df["기준_년분기_코드"].max()), note


def _upsert_area_metric(db: Session, name: str, df: pd.DataFrame, colmap: dict[str, str]):
    """area_metrics 한 파일분 컬럼을 (지역, 분기) 행에 채운다."""
    amap = _area_map(db)
    n0, reasons = len(df), []
    df = _filter_rows(df, valid_quarter(df["기준_년분기_코드"]), name, reasons, "분기 코드 오류")
    df = _filter_rows(df, df["자치구_코드"].astype(str).isin(amap), name, reasons, "알 수 없는 지역")
    df = _filter_rows(df, ~df.duplicated(["기준_년분기_코드", "자치구_코드"]), name, reasons, "중복")
    note = _finish_validation(n0, len(df), name, reasons)
    existing = {(a, q): m for m in db.scalars(select(M.AreaMetric)) for a, q in [(m.area_id, m.base_quarter)]}
    for r in df.to_dict("records"):
        aid, q = amap[str(r["자치구_코드"])], int(r["기준_년분기_코드"])
        m = existing.get((aid, q))
        if m is None:
            m = M.AreaMetric(area_id=aid, base_quarter=q, metric_date=quarter_start(q))
            db.add(m)
            existing[(aid, q)] = m
        for attr, col in colmap.items():
            v = r[col]
            if isinstance(v, float) and math.isnan(v):
                v = None
            elif attr in ("floating_population", "resident_population", "working_population", "avg_monthly_income", "total_spending"):
                v = int(v)
            setattr(m, attr, v)
    db.flush()
    return len(df), int(df["기준_년분기_코드"].max()), note


def ingest_floating(db, data_dir):
    df = read_csv(data_dir / "유동인구_자치구.csv")
    require_columns(df, ["기준_년분기_코드", "자치구_코드", "총_유동인구_수"], "유동인구")
    return _upsert_area_metric(db, "유동인구", df, {"floating_population": "총_유동인구_수"})


def ingest_resident(db, data_dir):
    df = read_csv(data_dir / "상주인구_자치구.csv")
    require_columns(df, ["기준_년분기_코드", "자치구_코드", "총_상주인구_수"], "상주인구")
    return _upsert_area_metric(db, "상주인구", df, {"resident_population": "총_상주인구_수"})


def ingest_working(db, data_dir):
    df = read_csv(data_dir / "직장인구_자치구.csv")
    require_columns(df, ["기준_년분기_코드", "자치구_코드", "총_직장인구_수"], "직장인구")
    return _upsert_area_metric(db, "직장인구", df, {"working_population": "총_직장인구_수"})


def ingest_income(db, data_dir):
    df = read_csv(data_dir / "소득소비_자치구.csv")
    require_columns(df, ["기준_년분기_코드", "자치구_코드", "월_평균_소득_금액", "지출_총_금액"], "소득소비")
    return _upsert_area_metric(db, "소득소비", df, {"avg_monthly_income": "월_평균_소득_금액", "total_spending": "지출_총_금액"})


def ingest_change(db, data_dir):
    df = read_csv(data_dir / "상권변화_자치구.csv")
    require_columns(df, ["기준_년분기_코드", "자치구_코드", "상권_변화_지표", "상권_변화_지표_명", "운영_영업_개월_평균",
                         "폐업_영업_개월_평균"], "상권변화지표")
    return _upsert_area_metric(db, "상권변화지표", df, {
        "change_indicator": "상권_변화_지표", "change_indicator_name": "상권_변화_지표_명",
        "avg_open_months": "운영_영업_개월_평균", "avg_closed_months": "폐업_영업_개월_평균"})


def ingest_rent(db: Session, data_dir: Path):
    name = "임대시세"
    df = read_csv(data_dir / "임대료_자치구.csv")
    require_columns(df, ["기준_년분기_코드", "자치구_코드_명", "전체임대료"], name)
    df = df[df["자치구_코드_명"] != "서울시 전체"].copy()
    n0, reasons = len(df), []
    yq = df["기준_년분기_코드"].astype(str).str.extract(r"(\d{4})년\s*(\d)분기")
    df["q"] = pd.to_numeric(yq[0], errors="coerce") * 10 + pd.to_numeric(yq[1], errors="coerce")
    df = _filter_rows(df, valid_quarter(df["q"]), name, reasons, "분기 형식 오류")
    nmap = _area_name_map(db)
    df = _filter_rows(df, df["자치구_코드_명"].isin(nmap), name, reasons, "알 수 없는 지역")
    df = _filter_rows(df, pd.to_numeric(df["전체임대료"], errors="coerce") > 0, name, reasons, "임대료 결측/0")
    df = _filter_rows(df, ~df.duplicated(["q", "자치구_코드_명"]), name, reasons, "중복")
    note = _finish_validation(n0, len(df), name, reasons)
    df["q"] = df["q"].astype(int)
    df["level"] = df.groupby("q")["전체임대료"].transform(
        lambda s: pd.qcut(s.rank(method="first"), 3, labels=["낮음", "보통", "높음"]).astype(str))
    db.execute(delete(M.RentMetric))
    recs = [{"area_id": nmap[r["자치구_코드_명"]], "base_quarter": int(r["q"]), "base_date": quarter_start(int(r["q"])),
             "rent_per_3_3m2": int(r["전체임대료"]), "rent_per_square_meter": int(round(r["전체임대료"] / 3.305785)),
             "avg_monthly_rent": None, "rent_level": r["level"]} for r in df.to_dict("records")]
    db.execute(insert(M.RentMetric), recs)
    return len(recs), int(df["q"].max()), note


def seed_places(db: Session) -> int:
    d = json.loads((SEED_DIR / "places.json").read_text(encoding="utf-8"))
    areas = list(db.scalars(select(M.CommercialArea).where(M.CommercialArea.boundary_geojson.is_not(None))))
    geoms = [(a, json.loads(a.boundary_geojson)) for a in areas]

    def area_for(lat, lng):
        for a, g in geoms:
            if geo.point_in_geometry(lng, lat, g):
                return a.area_id
        best = min(geoms, key=lambda ag: geo.distance_to_geometry_m(lat, lng, ag[1]), default=None)
        return best[0].area_id if best else None

    entries = [dict(p) for p in d["places"]]
    for a in areas:                                   # 자치구 이름 자체도 검색되게
        # 별칭: '강남'(구 떼고), '강남구청'(구청 이름으로 찾는 사람이 많음)
        entries.append({"name": a.area_name, "aliases": f"{a.area_name.removesuffix('구')},{a.area_name}청", "kind": "district",
                        "lat": a.latitude, "lng": a.longitude})
    for p in entries:
        row = db.scalar(select(M.Place).where(M.Place.name == p["name"]))
        if row is None:
            row = M.Place(name=p["name"])
            db.add(row)
        row.aliases, row.kind = p.get("aliases", ""), p["kind"]
        row.latitude, row.longitude = p["lat"], p["lng"]
        row.area_id = area_for(p["lat"], p["lng"])
    db.flush()
    return len(entries)


STEPS = [
    ("boundary", ingest_areas), ("stores", ingest_stores), ("sales", ingest_sales),
    ("floating", ingest_floating), ("resident", ingest_resident), ("working", ingest_working),
    ("income", ingest_income), ("change", ingest_change), ("rent", ingest_rent),
]


def run_ingestion(db: Session, data_dir: Path, only: list[str] | None = None, log=print) -> list[dict]:
    """전체 적재. 반환: 파일별 결과(로그와 동일 내용)."""
    sources = seed_sources(db)
    seed_cost_profiles(db)
    seed_policies(db)
    db.commit()
    results = []
    for key, fn in STEPS:
        if only and key not in only:
            continue
        src = sources[key]
        started = _utcnow()
        sp = db.begin_nested()
        try:
            n, max_q, note = fn(db, Path(data_dir))
            sp.commit()
            db.add(M.DataIngestionLog(source_id=src.source_id, ingested_at=started, status="SUCCESS",
                                      row_count=n, error_message=note, max_quarter=max_q))
            results.append({"source": src.source_name, "status": "SUCCESS", "rows": n, "max_quarter": max_q, "note": note})
        except Exception as e:  # noqa: BLE001 — 실패 사유를 로그로 남기고 다음 파일 진행
            sp.rollback()
            msg = str(e) if isinstance(e, IngestError) else f"{type(e).__name__}: {e}"
            db.add(M.DataIngestionLog(source_id=src.source_id, ingested_at=started, status="FAIL", row_count=0,
                                      error_message=msg[:2000]))
            results.append({"source": src.source_name, "status": "FAIL", "rows": 0, "error": msg})
        db.commit()
        r = results[-1]
        log(f"  [{r['status']}] {r['source']}: {r.get('rows', 0):,}행" + (f" · {r.get('note') or r.get('error')}" if (r.get('note') or r.get('error')) else ""))
    n_places = seed_places(db)
    db.commit()
    log(f"  지명 사전 {n_places}건")
    return results
