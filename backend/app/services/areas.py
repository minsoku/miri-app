"""SB-02 상권 선택: 지명 검색, 반경 내 후보 지역, 지도 경계, 비교(UC-02)."""
from __future__ import annotations
import json
import re
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models as M
from ..errors import ApiError
from ..settings import settings
from . import geo
from .narrative import sales_outlier
from .engine import EngineState

SEOUL_RECT = "126.76,37.41,127.19,37.72"      # 카카오 검색 범위(서울)
DISTRICT_NOTICE = ("상권 단위 데이터가 아직 없어 자치구(구 전체) 단위로 분석해요. "
                   "반경은 후보 구를 고르는 데 쓰여요.")


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def _area_of_point(state: EngineState, lat: float, lng: float) -> tuple[str | None, float]:
    best, best_d = None, float("inf")
    for code, a in state.areas.items():
        if a.get("geometry") is None:
            continue
        d = geo.distance_to_geometry_m(lat, lng, a["geometry"])
        if d < best_d:
            best, best_d = code, d
    return best, best_d


SUFFIX_FALLBACK = ("거리", "시장", "동", "길", "로", "역", "공원", "광장", "호수")   # '망원동'이 사전에 없으면 '망원'(→ 망원역), '신촌역' → '신촌'(→ 신촌 연세로)


YEOK_TYPOS = "녁력넉"          # 소리대로 친 '역'(강남녁·잠실력) — 마지막 글자만
REUNG_TYPO = ("능", "릉")      # 선능 → 선릉, 정능 → 정릉


def typo_variants(nq: str) -> list[str]:
    """흔한 소리 오타를 고친 후보(원래 검색이 비었을 때만 쓴다): 마지막 녁·력·넉 → 역, 능 → 릉."""
    out = []
    a = nq[:-1] + "역" if len(nq) >= 3 and nq[-1] in YEOK_TYPOS else nq
    b = a.replace(*REUNG_TYPO) if len(a) >= 2 else a          # 한 글자('능')만으로는 고치지 않는다
    for v in (a, b):
        if v != nq and v not in out:
            out.append(v)
    return out


NOISE_TOKENS = {"사거리", "근처", "주변", "앞", "쪽", "출구"}
# 주소 검색어에서 그것만으로는 장소를 정할 수 없는 흔한 말(카페 → 성수동카페거리 같은 엉뚱한 부분 일치를 막는다)
GENERIC_TOKENS = {"카페", "맛집", "학원가", "학원", "시장", "거리", "골목", "역", "상권", "먹자골목", "카페거리", "동네", "입구", "근방",
                  "공원", "광장", "한강", "호수"}
SEOUL_TOKEN = re.compile(r"서울특별시|서울시|서울")
EXIT_TOKEN = re.compile(r"[0-9]+번(출구)?")
EXIT_TAIL = re.compile(r"(.{2,}?)[0-9]+번(출구)?$")


def _split_districts(t: str, districts: list[str]) -> list[str]:
    """띄어 쓰지 않은 구 이름을 떼어 낸다: '관악구신림동' → 관악구·신림동, '서울시강남구' → 서울시·강남구."""
    for d in districts:
        i = t.find(d)
        if i >= 0 and t != d:
            return [x for x in (t[:i], d, t[i + len(d):]) if x]
    return [t]


def address_tokens(q: str, districts: list[str] | tuple = ()) -> list[str]:
    """주소처럼 친 검색어의 낱말('서울 강남구', '관악구 신림동', '신림역 사거리', '강남역 2번 출구', '신촌역앞', '강남역2번출구') —
    서울·사거리·근처·앞·쪽·출구 번호는 뺀다. districts를 주면 붙여 쓴 구 이름도 떼어 낸다."""
    ds = sorted(districts, key=len, reverse=True)
    raw = [x for t in (q or "").split() for x in (_split_districts(t, ds) if ds else [t])]
    out = []
    for t in raw:
        if len(t) > 3 and t.endswith(("사거리", "근처", "주변")):
            t = t[:-3] if t.endswith("사거리") else t[:-2]
        elif len(t) > 2 and t.endswith(("앞", "쪽")):
            t = t[:-1]
        m = EXIT_TAIL.fullmatch(t)                    # '강남역2번출구앞' → 앞을 뗀 뒤 출구 번호
        if m:
            t = m.group(1)
        if not t or t in NOISE_TOKENS or SEOUL_TOKEN.fullmatch(t) or EXIT_TOKEN.fullmatch(t):
            continue
        out.append(t)
    return out


def _search_with_typos(db: Session, state: EngineState, nq: str, limit: int, strict: bool = False) -> list[dict]:
    out = _search_one(db, state, nq, limit, strict)
    if not out:
        for v in typo_variants(nq):
            out = _search_one(db, state, v, limit, strict)
            if out:
                break
    return out


def search_local(db: Session, state: EngineState, q: str, limit: int = 8) -> list[dict]:
    nq = _norm(q)
    out = _search_with_typos(db, state, nq, limit)
    if out:
        return out
    # 주소처럼 친 검색어: 서울·사거리 등을 뺀 낱말로 다시 찾는다.
    #  · 구 이름이 있으면 그 구 안의 결과만(은평구 신사동 → 강남구 신사역 X), 없으면 그 구 자체
    #  · 흔한 말(카페·학원가·시장·역)과 한 글자는 빼고, 남은 낱말을 붙인 말(홍대 입구 → 홍대입구)부터, 그다음 오른쪽 낱말부터
    districts = sorted({a["name"] for a in state.areas.values()})
    toks = address_tokens(q, districts)
    if not toks or [_norm(t) for t in toks] == [nq]:
        return []
    dist = next((t for t in reversed(toks) if t in districts), None)
    short = None                                      # '마포 연남동'의 마포처럼 '구'를 뺀 구 이름도 구 제한으로
    if dist is None:
        short = next((t for t in reversed(toks) if len(t) >= 2 and t + "구" in districts), None)
        dist = short + "구" if short else None
    words = [t for t in toks if t not in (dist, short) and len(t) >= 2 and t not in GENERIC_TOKENS]
    # 붙인 말 → 왼쪽 낱말부터(서울숲 공원·구로 테크노마트: 앞말이 장소 이름). 낱말 검색은 이름·별칭과 같거나 그 말로 시작할 때만
    terms = (["".join(words)] if len(words) >= 2 else []) + words
    for t in dict.fromkeys(_norm(x) for x in terms):
        res = _search_with_typos(db, state, t, limit, strict=True)
        if dist:
            res = [r for r in res if r.get("area_name") == dist]
        if res:
            return res
    if short:                                         # 다른 낱말로 못 찾으면 그 말 자체로(강남 카페 → 강남역)
        return _search_with_typos(db, state, _norm(short), limit) or _search_one(db, state, _norm(dist), limit)
    return _search_one(db, state, _norm(dist), limit) if dist else []


def _search_one(db: Session, state: EngineState, nq: str, limit: int, strict: bool = False) -> list[dict]:
    out = _search_local(db, state, nq, limit, strict=strict)
    if not out:
        for suf in SUFFIX_FALLBACK:
            if nq.endswith(suf) and len(nq) - len(suf) >= 2:
                # 대체 검색은 장소 이름이 그 말로 시작하거나 별칭과 똑같을 때만
                # (상암동 → 별칭 '상암'(DMC역)은 찾고, 대학동 → 별칭 '대학로'(혜화역)로 엉뚱하게 가지 않게)
                out = _search_local(db, state, nq[: -len(suf)], limit, names_only=True)
                if out:
                    break
    if not out and len(nq) >= 3 and _looks_like_yeok(nq[-1]):
        # '역'을 잘못 친 마지막 글자(강남억·강남역 → 강남): 첫소리가 ㅇ인 글자만 — 서울시·강남대가 서울역·강남역으로 가지 않게
        out = _search_local(db, state, nq[:-1], limit, names_only=True)
    return out


def _looks_like_yeok(ch: str) -> bool:
    """첫소리가 'ㅇ'인 한글 음절인지('역' 오타 후보: 억·엮·엿·약 등)."""
    return "가" <= ch <= "힣" and (ord(ch) - 0xAC00) // 588 == 11


def _search_local(db: Session, state: EngineState, nq: str, limit: int, names_only: bool = False,
                  strict: bool = False) -> list[dict]:
    if not nq:
        return []
    scored = []
    for p in db.scalars(select(M.Place).order_by(M.Place.place_id)):
        names = [p.name] + [a for a in (p.aliases or "").split(",") if a]
        nn = [_norm(n) for n in names]
        if names_only and not (nn[0].startswith(nq) or nq in nn[1:]):
            continue
        if nq == nn[0]:
            s = 0
        elif any(nq == n for n in nn[1:]):
            s = 1
        elif any(n.startswith(nq) for n in nn):
            s = 2
        elif not strict and any(nq in n for n in nn):     # 주소 낱말 검색(strict)은 가운데 일치를 쓰지 않는다
            s = 3
        else:
            continue
        kind_rank = {"station": 0, "street": 0, "district": 1}.get(p.kind, 2)
        scored.append((s, kind_rank, len(p.name), p))
    scored.sort(key=lambda t: t[:3])
    out = []
    code_by_id = {a["area_id"]: c for c, a in state.areas.items()}
    for *_, p in scored[:limit]:
        code = code_by_id.get(p.area_id)
        out.append({"name": p.name, "kind": p.kind, "lat": p.latitude, "lng": p.longitude, "area_code": code,
                    "area_name": state.areas[code]["name"] if code else None, "source": "local"})
    return out


def search_kakao(state: EngineState, q: str, limit: int = 8, client: httpx.Client | None = None) -> list[dict]:
    """카카오 로컬 키워드 검색(선택). 키가 없거나 실패하면 빈 목록 → 로컬 사전으로 대체."""
    if not settings.kakao_rest_key:
        return []
    own = client is None
    client = client or httpx.Client(timeout=3.0)
    try:
        r = client.get("https://dapi.kakao.com/v2/local/search/keyword.json",
                       params={"query": q, "rect": SEOUL_RECT, "size": min(limit, 15)},
                       headers={"Authorization": f"KakaoAK {settings.kakao_rest_key}"})
        r.raise_for_status()
        docs = r.json().get("documents", [])
    except (httpx.HTTPError, ValueError):
        return []
    finally:
        if own:
            client.close()
    out = []
    for d in docs[:limit]:
        try:
            lat, lng = float(d["y"]), float(d["x"])
        except (KeyError, ValueError):
            continue
        code, dist = _area_of_point(state, lat, lng)
        if code is None or dist > 0:          # 서울 밖
            continue
        out.append({"name": d.get("place_name", q), "kind": "kakao", "lat": lat, "lng": lng, "area_code": code,
                    "area_name": state.areas[code]["name"],
                    "address": d.get("road_address_name") or d.get("address_name"), "source": "kakao"})
    return out


def search(db: Session, state: EngineState, q: str, limit: int = 8) -> list[dict]:
    q = (q or "").strip()
    if not q:
        raise ApiError(422, "EMPTY_QUERY", "검색어를 입력해 주세요")
    res = search_kakao(state, q, limit) + search_local(db, state, q, limit)
    seen, out = set(), []
    for r in res:
        k = (r["name"], round(r["lat"], 4), round(r["lng"], 4))
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out[:limit]


def area_card(state: EngineState, code: str, is_center=False, distance_m=0) -> dict:
    a = state.areas[code]
    return {"area_code": code, "area_name": a["name"], "level": a["level"], "is_center": is_center,
            "distance_m": int(round(distance_m)), "lat": a["lat"], "lng": a["lng"],
            "metrics": state.area_cards.get(code, {})}


def candidates(state: EngineState, lat: float, lng: float, radius_m: int, place_name: str | None) -> dict:
    """반경 안에 걸치는 지역(자치구) 후보. 중심점을 포함하는 지역이 첫 번째."""
    hits = []
    for code, a in state.areas.items():
        if a.get("geometry") is None or state.area_rows(code).empty:
            continue
        d = geo.distance_to_geometry_m(lat, lng, a["geometry"])
        if d <= radius_m:
            inside = geo.point_in_geometry(lng, lat, a["geometry"])
            hits.append((d, 0 if inside else 1, geo.haversine_m(lat, lng, a["lat"], a["lng"]), code))
    notice = DISTRICT_NOTICE
    if not hits:
        code, d = _area_of_point(state, lat, lng)
        if code is None or d > 3000:
            raise ApiError(422, "OUT_OF_COVERAGE", "서울 밖 지역은 아직 분석할 수 없어요. 서울 안에서 골라 주세요")
        hits = [(d, 1, d, code)]
        dist = f"{d / 1000:.1f}km" if round(d) >= 1000 else f"{int(round(d))}m"   # 반경(300m)보다 먼데 0.3km로 보이지 않게
        notice = f"반경 안에 서울 자치구가 없어 가장 가까운 {state.areas[code]['name']}(경계까지 {dist}) 기준으로 분석해요."
    hits.sort()        # 거리 → 중심점 포함 여부 → 지역 중심까지 거리 (경계에 걸친 점의 동률 해소)
    cards = [area_card(state, c, is_center=(i == 0 and d == 0), distance_m=d) for i, (d, _, _, c) in enumerate(hits)]
    return {"lat": lat, "lng": lng, "radius_m": radius_m, "place_name": place_name, "analysis_level": "district",
            "notice": notice, "candidates": cards}


_map_cache: dict | None = None
_map_cache_for: tuple | None = None       # 어떤 엔진 상태(모델 버전·학습 시각)로 만든 지도인지 — 다른 워커가 갱신해도 맞춰 다시 만든다


def simplified_map(state: EngineState, db: Session | None = None) -> dict:
    """지도용: 단순화한 경계 + 지명(역·거리) 라벨."""
    global _map_cache, _map_cache_for
    key = (state.model_version, state.trained_at)
    if _map_cache is None or _map_cache_for != key:
        _map_cache_for = key
        feats = []
        for code, a in state.areas.items():
            if a.get("geometry") is None:
                continue
            rings = [geo.simplify_ring(r) for r in geo.rings_of(a["geometry"])]
            geom = {"type": "Polygon", "coordinates": [rings[0]]} if len(rings) == 1 else \
                   {"type": "MultiPolygon", "coordinates": [[r] for r in rings]}
            feats.append({"type": "Feature", "properties": {"code": code, "name": a["name"],
                                                            "lat": a["lat"], "lng": a["lng"]}, "geometry": geom})
        places = []
        if db is not None:
            places = [{"name": p.name, "kind": p.kind, "lat": p.latitude, "lng": p.longitude}
                      for p in db.scalars(select(M.Place).where(M.Place.kind != "district"))]
        _map_cache = {"type": "FeatureCollection", "features": feats, "places": places}
    return _map_cache


def compare(state: EngineState, codes: list[str], industry_code: str | None) -> dict:
    """UC-02 상권 비교. 같은 기준(최신 분기)으로 지역 지표와 (선택) 업종 위험·매출을 나란히."""
    codes = list(dict.fromkeys(codes))
    if len(codes) < 2:
        raise ApiError(422, "NEED_MORE_AREAS", "비교하려면 상권을 2개 이상 골라 주세요")
    unknown = [c for c in codes if c not in state.areas]
    if unknown:
        raise ApiError(404, "UNKNOWN_AREA", f"알 수 없는 지역 코드: {', '.join(unknown)}")
    if industry_code and industry_code not in state.industries:
        raise ApiError(404, "UNKNOWN_INDUSTRY", "알 수 없는 업종이에요")
    rows = []
    for c in codes:
        card = area_card(state, c)
        ar = state.area_rows(c)
        card["summary"] = {
            "avg_risk_score": round(float(ar["risk_score"].mean()), 1) if len(ar) else None,
            "high_risk_share": round(float((ar["risk_grade"].isin(["높음", "고위험"])).mean()), 3) if len(ar) else None,
        }
        if industry_code:
            r = state.row(c, industry_code)
            card["industry"] = None if r is None else {
                "risk_score": int(r["risk_score"]), "risk_grade": r["risk_grade"],
                "location_risk_pct": int(r["risk_pct_in_ind"]), "pred_annual_rate": float(r["pred_annual_rate"]),
                "sales_ps_m": None if r["sales_ps_m"] != r["sales_ps_m"] else float(r["sales_ps_m"]),
                "sales_outlier": None if (x := sales_outlier(r)) is None else round(x, 1),
                "demand_D": None if r["demand_D"] != r["demand_D"] else float(r["demand_D"]),
                "stores_avg": float(r["stores_avg4"])}
        rows.append(card)
    return {"industry_code": industry_code,
            "industry_name": state.industries[industry_code]["name"] if industry_code else None,
            "data_quarter": state.quarter, "areas": rows}
