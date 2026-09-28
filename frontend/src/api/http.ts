import { Api, ApiError } from "./types";
import { deviceKey } from "../lib/device";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) || "/api/v1";

export function createHttpApi(): Api {
  /** device: 로그인이 없으므로 저장 리포트는 이 브라우저의 저장 키로 구분한다 — 저장 목록과 리포트('저장됨' 표시) 요청에만 붙인다 */
  async function req<T>(method: string, path: string, body?: unknown, device = false): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (device) headers["X-Device-Key"] = deviceKey();
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let res: Response;
    try {
      res = await fetch(`${BASE}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    } catch {
      throw new ApiError(0, { code: "NETWORK", message: "서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요" });
    }
    if (res.status === 204) return undefined as T;
    let data: any = null;
    try { data = await res.json(); } catch { /* 본문 없음 */ }
    if (!res.ok) {
      const err = data?.error || { code: `HTTP_${res.status}`, message: "요청을 처리하지 못했어요" };
      throw new ApiError(res.status, err);
    }
    return data as T;
  }
  const q = (o: Record<string, any>) =>
    "?" + Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&");

  return {
    mode: "server",
    meta: () => req("GET", "/meta"),
    industries: () => req("GET", "/industries"),
    searchPlaces: (s) => req("GET", `/places/search${q({ q: s })}`),
    candidates: (lat, lng, radius_m, place_name) => req("GET", `/areas/candidates${q({ lat, lng, radius_m, place_name })}`),
    areaCard: (code) => req("GET", `/areas/${encodeURIComponent(code)}`),
    areaMap: () => req("GET", "/areas/map"),
    compareAreas: (area_codes, industry_code) => req("POST", "/areas/compare", { area_codes, industry_code: industry_code || null }),
    createAnalysis: (b) => req("POST", "/analyses", b),
    getAnalysis: (id) => req("GET", `/analyses/${id}`),
    risk: (id, code, be) => req("GET", `/analyses/${id}/risk/${code}${be ? q({ be }) : ""}`),
    breakeven: (id, b) => req("POST", `/analyses/${id}/breakeven`, b),
    getBreakeven: (id, beId) => req("GET", `/analyses/${id}/breakeven/${beId}`),
    createReport: (id, b) => req("POST", `/analyses/${id}/reports`, b, true),
    getReport: (id) => req("GET", `/reports/${id}`, undefined, true),
    saveReport: (report_id, memo) => req("POST", "/me/reports", { report_id, memo }, true),
    myReports: () => req("GET", "/me/reports", undefined, true),
    deleteSaved: (id, rid) => req("DELETE", `/me/reports/${id}${rid ? `?report_id=${encodeURIComponent(rid)}` : ""}`, undefined, true),
    deleteAllSaved: () => req("POST", "/me/reports/clear", undefined, true),
    updateMemo: (id, rid, memo) => req("PATCH", `/me/reports/${id}`, { report_id: rid, memo }, true),
    setItemDone: (rid, aid, done) => req("PATCH", `/reports/${rid}/items/${aid}`, { done }),
  };
}
