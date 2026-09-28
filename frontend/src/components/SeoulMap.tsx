import { useMemo, useRef, useState } from "react";
import type { MapData } from "../api/types";

// 타일 없는 벡터 지도: 자치구 경계(서울 열린데이터 OA-11677 가공) + 반경 원 + 지명 라벨.
// 좌표는 중심점 기준 등장방형 투영(m). 실서비스에서 카카오맵으로 바꿀 때는 이 컴포넌트만 교체하면 된다.
const M_PER_DEG_LAT = 111_320;

interface Props {
  data: MapData | null;
  center: { lat: number; lng: number };
  radius: number;
  showPin?: boolean;
  selectedCode?: string | null;
  candidateCodes?: string[];
  onPick?(lat: number, lng: number): void;
}

export default function SeoulMap({ data, center, radius, selectedCode, candidateCodes = [], onPick, showPin = true }: Props) {
  const [zoom, setZoom] = useState(1);
  const svgRef = useRef<SVGSVGElement>(null);
  const down = useRef<{ x: number; y: number } | null>(null);     // 누른 자리 — 끌었다 놓은 것은 위치 선택으로 보지 않는다
  const kx = M_PER_DEG_LAT * Math.cos((center.lat * Math.PI) / 180);
  const W = Math.max(radius * 4.6, 2600) / zoom;
  const H = W * 0.6;
  const proj = (lng: number, lat: number) => [(lng - center.lng) * kx, -(lat - center.lat) * M_PER_DEG_LAT];

  const paths = useMemo(() => {
    if (!data) return [];
    return data.features.map((f) => {
      const polys: number[][][] = f.geometry.type === "Polygon" ? [f.geometry.coordinates[0]] : f.geometry.coordinates.map((p: any) => p[0]);
      const d = polys.map((ring) => ring.map(([x, y], i) => {
        const [px, py] = proj(x, y);
        return `${i ? "L" : "M"}${px.toFixed(1)},${py.toFixed(1)}`;
      }).join("") + "Z").join("");
      const [lx, ly] = proj(f.properties.lng, f.properties.lat);
      return { code: f.properties.code, name: f.properties.name, d, lx, ly };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, center.lat, center.lng]);

  const labels = useMemo(() => {
    if (!data?.places) return [];
    return data.places.map((p) => {
      const [x, y] = proj(p.lng, p.lat);
      return { ...p, x, y };
    }).filter((p) => Math.abs(p.x) < W / 2 - (W / 360) * 40 && Math.abs(p.y) < H / 2 - (W / 360) * 12
      && Math.hypot(p.x, p.y) > (W / 360) * 14);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, center.lat, center.lng, W, H]);

  function pick(e: React.MouseEvent<SVGSVGElement>) {
    if (!onPick || !svgRef.current) return;
    const d0 = down.current;
    down.current = null;
    if (d0 && Math.hypot(e.clientX - d0.x, e.clientY - d0.y) > 6) return;   // 끌기(드래그)는 무시
    const pt = svgRef.current.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    const ctm = svgRef.current.getScreenCTM();
    if (!ctm) return;
    const p = pt.matrixTransform(ctm.inverse());
    onPick(center.lat - p.y / M_PER_DEG_LAT, center.lng + p.x / kx);
  }
  /** 키보드로도 위치를 고를 수 있게: 방향키 = 화면 폭의 1/12만큼 이동, +/− = 확대·축소 */
  function onKey(e: React.KeyboardEvent<SVGSVGElement>) {
    if (!onPick) return;
    const step = W / 12;
    const move: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (e.key === "+" || e.key === "=") { e.preventDefault(); setZoom((z) => Math.min(z * 1.5, 4)); return; }
    if (e.key === "-" || e.key === "_") { e.preventDefault(); setZoom((z) => Math.max(z / 1.5, 0.3)); return; }
    const d = move[e.key];
    if (!d) return;
    e.preventDefault();
    onPick(center.lat - d[1] / M_PER_DEG_LAT, center.lng + d[0] / kx);
  }
  const s = W / 360;                // 화면 px ≈ s m (라벨·선 굵기 보정)
  return (
    <div className="map">
      <svg ref={svgRef} viewBox={`${-W / 2} ${-H / 2} ${W} ${H}`} preserveAspectRatio="xMidYMid meet" onClick={pick}
        onPointerDown={(e) => { down.current = { x: e.clientX, y: e.clientY }; }}
        tabIndex={onPick ? 0 : -1} onKeyDown={onKey} role="application" aria-roledescription="지도"
        aria-label="서울 지도. 방향키로 위치를 옮기고 +, − 키로 확대·축소해요. 지역 검색으로도 고를 수 있어요.">
        <rect x={-W / 2} y={-H / 2} width={W} height={H} fill="#e9edf4" />
        {paths.map((p) => (
          <path key={p.code} d={p.d}
            fill={p.code === selectedCode ? "#d3e0ff" : candidateCodes.includes(p.code) ? "#edf1fb" : "#f8f9fb"}
            stroke={p.code === selectedCode ? "#2563eb" : "#cdd4df"} strokeWidth={(p.code === selectedCode ? 2 : 1.1) * s}
            strokeLinejoin="round" />
        ))}
        {labels.map((p) => (
          <g key={p.name} opacity={0.9}>
            <circle cx={p.x} cy={p.y} r={2.6 * s} fill="#6b7280" />
            <text x={p.x + 5 * s} y={p.y + 3.5 * s} fontSize={10.5 * s} fill="#6b7280" fontWeight={600}>{p.name}</text>
          </g>
        ))}
        {paths.filter((p) => Math.abs(p.lx) < W / 2 && Math.abs(p.ly) < H / 2).map((p) => (
          <text key={p.code + "l"} x={p.lx} y={p.ly} fontSize={12 * s} fontWeight={800} textAnchor="middle"
            fill={p.code === selectedCode ? "#2563eb" : "#9aa3b2"}>{p.name}</text>
        ))}
        {showPin && <>{/* 위치를 고르기 전에는 반경·핀을 그리지 않는다(시청에 반경이 그려져 이미 고른 것처럼 보이지 않게) */}
          <circle cx={0} cy={0} r={radius} fill="rgba(37,99,235,0.14)" stroke="#2563eb" strokeWidth={1.6 * s} />
          <circle cx={0} cy={0} r={9 * s} fill="#fff" />
          <circle cx={0} cy={0} r={6 * s} fill="#2563eb" /></>}
      </svg>
      <div className="zoom">
        <button type="button" aria-label="확대" disabled={zoom >= 4} onClick={() => setZoom((z) => Math.min(z * 1.5, 4))}>+</button>
        <button type="button" aria-label="축소" disabled={zoom <= 0.3} onClick={() => setZoom((z) => Math.max(z / 1.5, 0.3))}>−</button>
      </div>
      <span className="hint" aria-hidden="true">지도를 눌러 위치를 옮길 수 있어요</span>
    </div>
  );
}
