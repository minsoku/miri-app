"""API 런타임 엔진 상태: 활성 모델 + 최신 분기 특징(area_category_features)을 메모리에 올려 둔다.
요청 처리는 조회·가벼운 계산(필터·가중합·손익분기)만 한다."""
from __future__ import annotations
import json
import math
import threading
import time
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from miri_engine.risk import RiskModel
from miri_engine.config import RiskParams, SuitabilityParams
from .. import models as M
from .catalog import INDUSTRY_FAMILY
from .features_batch import EXPLICIT


class EngineNotReady(RuntimeError):
    pass


@dataclass
class EngineState:
    model: RiskModel
    model_version: str
    trained_at: str
    quarter: int
    table: pd.DataFrame                           # 엔진 컬럼명 그대로 (area_id = 지역 코드 문자열)
    areas: dict[str, dict] = field(default_factory=dict)        # code → {area_id, name, lat, lng, level, geometry}
    industries: dict[str, dict] = field(default_factory=dict)   # code → {category_id, name, category, ...}
    area_cards: dict[str, dict] = field(default_factory=dict)   # code → 후보 카드 지표(유동인구·점포 수·임대료 등)
    notices: list[str] = field(default_factory=list)            # 데이터 갱신 실패 등 전역 안내
    _index: dict = field(default_factory=dict, repr=False)

    # ── 조회 ──
    def area_rows(self, area_code: str) -> pd.DataFrame:
        return self.table[self.table["area_id"] == str(area_code)]

    def row(self, area_code: str, industry_code: str) -> pd.Series | None:
        i = self._index.get((str(area_code), industry_code))
        return None if i is None else self.table.loc[i]

    def industry_rows(self, industry_code: str) -> pd.DataFrame:
        return self.table[self.table["industry_code"] == industry_code]

    def grade_rate_bounds(self) -> dict:
        """등급 경계(점수 40/70/90)에 해당하는 예상 연간 폐업률. 점수는 예측 로그율의 기준분포 백분위라 모델 버전마다 고정."""
        ref = np.asarray(self.model.ref_quantiles)
        p = self.model.params

        def annual(k):            # 등급은 반올림 점수 기준 → 실제 경계는 cut − 0.5
            eta = float(np.interp(k - 0.5, np.linspace(0, 100, len(ref)), ref))
            return round(1 - (1 - min(math.exp(eta), 1.0)) ** 4, 4)
        return {"보통": annual(p.cut_normal), "높음": annual(p.cut_high), "고위험": annual(p.cut_critical)}


_state: EngineState | None = None
_lock = threading.Lock()


def load_state(db: Session) -> EngineState:
    mv = db.scalar(select(M.ScoringModelVersion).where(M.ScoringModelVersion.is_active))
    if mv is None:
        raise EngineNotReady("활성 모델이 없습니다. scripts/init_data.py 를 먼저 실행하세요.")
    model = RiskModel.from_json(mv.params_json)
    q = db.scalar(select(func.max(M.AreaCategoryFeature.base_quarter))
                  .where(M.AreaCategoryFeature.model_version == mv.model_version))
    if q is None:
        raise EngineNotReady("특징 테이블이 비어 있습니다. 배치를 다시 실행하세요.")
    A, C, X = M.CommercialArea, M.BusinessCategory, M.AreaCategoryFeature
    rows = db.execute(select(A.area_code, A.area_name, C.category_code, C.category_name, C.parent_category,
                             C.has_sales_data, X).join(A, A.area_id == X.area_id).join(C, C.category_id == X.category_id)
                      .where(X.base_quarter == q, X.model_version == mv.model_version).order_by(X.feature_id)).all()
    recs = []
    for acode, aname, ccode, cname, parent, has_sales, x in rows:
        rec = json.loads(x.payload_json)
        for src, dst in EXPLICIT.items():
            rec[src] = getattr(x, dst)
        rec.update({"area_id": acode, "area_name": aname, "industry_code": ccode, "industry_name": cname,
                    "category": parent, "has_sales_data": bool(has_sales), "quarter": q})
        recs.append(rec)
    table = pd.DataFrame(recs)
    num_cols = [c for c in table.columns if c not in ("area_id", "area_name", "industry_code", "industry_name", "category",
                                                      "has_sales_data", "risk_grade", "confidence", "change_code", "profile")]
    for c in num_cols:
        table[c] = pd.to_numeric(table[c], errors="coerce")
    table = table.reset_index(drop=True)
    # 점포당 매출 순위(같은 업종, 매출 있는 지역끼리 1위=최고). 화면은 백분위 대신 'n개 구 중 k위'로 보여준다
    table["sales_rank"] = table.groupby("industry_code")["sales_ps_m"].rank(method="min", ascending=False)
    table["sales_n"] = table.groupby("industry_code")["sales_ps_m"].transform("count")
    # 같은 업종의 서울 중간값(점포당 매출) — 도매시장 같은 대형 점포가 섞인 지역(중간값의 3배 이상)을 알려 주는 데 쓴다
    table["sales_med"] = table.groupby("industry_code")["sales_ps_m"].transform("median")
    areas = {}
    for a in db.scalars(select(A).order_by(A.area_id)):
        areas[a.area_code] = {"area_id": a.area_id, "code": a.area_code, "name": a.area_name, "level": a.area_level,
                              "lat": a.latitude, "lng": a.longitude,
                              "geometry": json.loads(a.boundary_geojson) if a.boundary_geojson else None}
    lic = {c: l for c, l in db.execute(select(C.category_code, M.IndustryLicense.license_name)
                                       .join(M.IndustryLicense, M.IndustryLicense.category_id == C.category_id))}
    seoul_ticket = _seoul_tickets(table)
    # 추천 대상이 될 수 있는 업종: 카드 매출이 있는 지역이 5곳 이상(SuitabilityParams.min_sales_areas) — SB-03 자격 칩 등
    sales_areas = table.groupby("industry_code")["sales_ps_m"].count().to_dict()
    min_areas = SuitabilityParams().min_sales_areas
    industries = {c.category_code: {"category_id": c.category_id, "code": c.category_code, "name": c.category_name,
                                    "category": c.parent_category, "has_sales_data": c.has_sales_data,
                                    "recommendable": bool(c.has_sales_data) and sales_areas.get(c.category_code, 0) >= min_areas,
                                    "display_group": c.display_group, "license": lic.get(c.category_code),
                                    "family": INDUSTRY_FAMILY.get(c.category_code),
                                    "seoul_ticket": seoul_ticket.get(c.category_code)}
                  for c in db.scalars(select(C).order_by(C.category_id))}
    st = EngineState(model=model, model_version=mv.model_version, trained_at=mv.trained_at.isoformat(timespec="seconds"),
                     quarter=int(q), table=table, areas=areas, industries=industries,
                     area_cards=_area_cards(db), notices=_ingestion_notices(db))
    st._index = {(r.area_id, r.industry_code): i for i, r in enumerate(table[["area_id", "industry_code"]].itertuples(index=False))}
    return st


def _seoul_tickets(table: pd.DataFrame) -> dict[str, int]:
    """UC-04 대안 흐름(객단가 미입력 → 업종 평균 객단가 제안)용 서울 같은 업종 평균 객단가(원, 정수).
    지역 객단가를 점포 수로 가중한 매출 ÷ 결제건수: Σ(점포당 월매출·점포) ÷ Σ(점포당 하루 결제·점포·월 일수).
    행 순서대로 더하고 정수로 반올림해 데모(TypeScript) 계산과 같은 값이 나오게 한다."""
    from miri_engine.config import BreakEvenParams
    dpm = BreakEvenParams().days_per_month
    acc: dict[str, list[float]] = {}
    for code, sales, tx, n in table[["industry_code", "sales_ps_m", "tx_ps_day", "stores_avg4"]].itertuples(index=False):
        if all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (sales, tx, n)):
            a = acc.setdefault(code, [0.0, 0.0])
            a[0] += sales * n
            a[1] += tx * n * dpm
    return {c: int(round(a[0] / a[1])) for c, a in acc.items() if a[1] > 0}


def _area_cards(db: Session) -> dict[str, dict]:
    """자치구 카드 지표: 각 원천의 최신 분기 값."""
    from .catalog import days_in_quarter, quarter_label
    A, AM, SS, R = M.CommercialArea, M.AreaMetric, M.StoreStatistic, M.RentMetric
    out: dict[str, dict] = {}
    q_am = db.scalar(select(func.max(AM.base_quarter)))
    q_ss = db.scalar(select(func.max(SS.base_quarter)))
    q_r = db.scalar(select(func.max(R.base_quarter)))
    codes = {i: c for c, i in db.execute(select(A.area_code, A.area_id))}
    for m in db.scalars(select(AM).where(AM.base_quarter == q_am)):
        out.setdefault(codes[m.area_id], {}).update({
            "floating_daily": round(m.floating_population / days_in_quarter(q_am)) if m.floating_population else None,
            "resident_population": m.resident_population, "working_population": m.working_population,
            "change_indicator": m.change_indicator, "change_name": m.change_indicator_name,
            "avg_open_months": m.avg_open_months, "avg_closed_months": m.avg_closed_months,
            "metrics_quarter": q_am})
    for aid, n in db.execute(select(SS.area_id, func.sum(SS.total_store_count)).where(SS.base_quarter == q_ss)
                             .group_by(SS.area_id)):
        out.setdefault(codes[aid], {}).update({"store_count": int(n or 0), "stores_quarter": q_ss})
    for r in db.scalars(select(R).where(R.base_quarter == q_r)):
        out.setdefault(codes[r.area_id], {}).update({"rent_per_3_3m2": r.rent_per_3_3m2, "rent_level": r.rent_level,
                                                     "rent_quarter": q_r})
    for c in out.values():
        c["quarter_label"] = quarter_label(c.get("metrics_quarter") or c.get("stores_quarter") or 0) \
            if (c.get("metrics_quarter") or c.get("stores_quarter")) else None
    return out


def _ingestion_notices(db: Session) -> list[str]:
    """가장 최근 적재가 실패한 원천이 있으면 '최신 데이터가 아닐 수 있음' 안내(예외 처리 흐름)."""
    L, S = M.DataIngestionLog, M.DataSource
    latest = {}
    for log in db.scalars(select(L).order_by(L.ingested_at, L.log_id)):
        latest[log.source_id] = log
    failed = [db.get(S, sid).source_name for sid, log in latest.items() if log.status == "FAIL"]
    if failed:
        return [f"최근 데이터 갱신에 실패한 원천이 있어 이전 데이터로 분석했어요: {', '.join(failed)}"]
    return []


_checked_at = 0.0
CHECK_EVERY_SEC = 10.0          # 여러 워커로 띄웠을 때: 다른 워커가 모델을 바꿨는지(재학습·재적재) 이 간격으로 확인


def _active_key(db: Session) -> tuple[str, str] | None:
    row = db.execute(select(M.ScoringModelVersion.model_version, M.ScoringModelVersion.trained_at)
                     .where(M.ScoringModelVersion.is_active)).first()
    if row is None:
        return None
    return row[0], row[1].isoformat(timespec="seconds") if row[1] else ""


def get_state(db: Session | None = None) -> EngineState:
    """엔진 상태(프로세스마다 하나). /admin/refresh는 요청을 받은 워커만 즉시 다시 올리므로,
    나머지 워커는 활성 모델(버전·학습 시각)이 바뀐 것을 CHECK_EVERY_SEC마다 확인해 스스로 다시 올린다."""
    global _state, _checked_at
    if _state is None:
        if db is None:
            raise EngineNotReady("엔진 상태가 로드되지 않았습니다")
        with _lock:
            if _state is None:
                _state = load_state(db)
                _checked_at = time.monotonic()
        return _state
    if db is not None and time.monotonic() - _checked_at >= CHECK_EVERY_SEC:
        _checked_at = time.monotonic()
        try:
            key = _active_key(db)
        except Exception:                       # 확인 실패는 다음 주기에 다시(요청은 지금 상태로 처리)
            key = None
        if key is not None and key != (_state.model_version, _state.trained_at):
            with _lock:
                if key != (_state.model_version, _state.trained_at):
                    _state = load_state(db)
    return _state


def reload_state(db: Session) -> EngineState:
    global _state, _checked_at
    with _lock:
        _state = load_state(db)
        _checked_at = time.monotonic()
    return _state


def reset_state():
    global _state
    _state = None
