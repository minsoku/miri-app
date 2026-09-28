"""지오 유틸 (외부 GIS 라이브러리 없이): 점-폴리곤 포함, 점-폴리곤 거리, 중심점, 단순화.
좌표는 WGS84 (lng, lat). 서울 범위(수십 km)에서는 지점 기준 등장방형 근사로 m 단위 계산 오차가 무시할 수준."""
from __future__ import annotations
import json
import math

R_EARTH = 6_371_008.8


def haversine_m(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_EARTH * math.asin(math.sqrt(a))


def _to_local(lat0, lng0):
    kx = math.cos(math.radians(lat0)) * math.pi * R_EARTH / 180.0
    ky = math.pi * R_EARTH / 180.0
    return lambda lng, lat: ((lng - lng0) * kx, (lat - lat0) * ky)


def rings_of(geometry: dict) -> list[list[list[float]]]:
    """GeoJSON Polygon/MultiPolygon → 외곽 링 목록 (구멍은 서울 자치구 경계에 없어 무시)."""
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"][0]]
    if geometry["type"] == "MultiPolygon":
        return [poly[0] for poly in geometry["coordinates"]]
    raise ValueError(f"지원하지 않는 형식: {geometry['type']}")


def point_in_ring(lng: float, lat: float, ring) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lng < x_cross:
                inside = not inside
        j = i
    return inside


def point_in_geometry(lng, lat, geometry) -> bool:
    return any(point_in_ring(lng, lat, r) for r in rings_of(geometry))


def distance_to_geometry_m(lat: float, lng: float, geometry: dict) -> float:
    """점이 안에 있으면 0, 밖이면 경계까지 최단거리(m)."""
    if point_in_geometry(lng, lat, geometry):
        return 0.0
    to = _to_local(lat, lng)
    best = float("inf")
    for ring in rings_of(geometry):
        pts = [to(x, y) for x, y in ring[:]]
        for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
            px, py = ax + t * dx, ay + t * dy
            best = min(best, math.hypot(px, py))
    return best


def centroid(geometry: dict) -> tuple[float, float]:
    """면적 가중 중심 (lat, lng). 가장 큰 링 기준."""
    ring = max(rings_of(geometry), key=len)
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        cr = x0 * y1 - x1 * y0
        a += cr
        cx += (x0 + x1) * cr
        cy += (y0 + y1) * cr
    if abs(a) < 1e-15:
        xs, ys = zip(*ring)
        return sum(ys) / len(ys), sum(xs) / len(xs)
    return cy / (3 * a), cx / (3 * a)


def _rdp(points, eps):
    if len(points) < 3:
        return points
    (x1, y1), (x2, y2) = points[0], points[-1]
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy)
    dmax, idx = -1.0, 0
    for i in range(1, len(points) - 1):
        x0, y0 = points[i]
        d = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / L if L > 0 else math.hypot(x0 - x1, y0 - y1)
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        left = _rdp(points[: idx + 1], eps)
        return left[:-1] + _rdp(points[idx:], eps)
    return [points[0], points[-1]]


def simplify_ring(ring, eps_deg: float = 0.0006, ndigits: int = 5):
    """Ramer–Douglas–Peucker (도 단위 허용오차; 0.0006° ≈ 50~65m). 지도 표시용."""
    pts = [(round(x, ndigits), round(y, ndigits)) for x, y in ring]
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    out = _rdp(pts, eps_deg)
    return [list(p) for p in out] if len(out) >= 4 else [list(p) for p in pts]


def load_geojson(path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
