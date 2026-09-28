import { HashRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppProvider } from "./state/app";
import { HistoryTracker } from "./components/ui";
import Start from "./screens/Start";
import AreaSelect from "./screens/AreaSelect";
import Conditions from "./screens/Conditions";
import Interests from "./screens/Interests";
import Results from "./screens/Results";
import Risk from "./screens/Risk";
import BreakEven from "./screens/BreakEven";
import ActionReport from "./screens/ActionReport";
import SavedReports from "./screens/SavedReports";

/** 0.1의 로그인·가입 주소(#/login?next=…): 로그인이 없어졌으니 가려던 앱 안 화면으로 바로 보낸다('로그인 후 저장' 표시는 뺀다).
 *  앱 밖 주소(//…, http…)는 시작 화면으로 */
function LegacyAuth() {
  const loc = useLocation();
  let to = "/";
  try {
    const u = new URL(new URLSearchParams(loc.search).get("next") || "/", "https://miri.invalid");
    u.searchParams.delete("save");
    if (u.origin === "https://miri.invalid") to = u.pathname + u.search;
  } catch { /* 잘못된 값 → 시작 화면 */ }
  return <Navigate to={to} replace />;
}

// 화면 흐름 = 보고서 6.2.3 사용자 이용 플로우 (SB-01 → … → SB-09)
export default function App() {
  return (
    <div className="app">
      <AppProvider>
        <HashRouter>
          <HistoryTracker />
          <Routes>
            <Route path="/" element={<Start />} />                                        {/* SB-01 (로그인 없음) */}
            <Route path="/login" element={<LegacyAuth />} />                              {/* 0.1의 로그인·가입 주소 */}
            <Route path="/signup" element={<LegacyAuth />} />
            <Route path="/area" element={<AreaSelect />} />                               {/* SB-02 */}
            <Route path="/conditions" element={<Conditions />} />                         {/* SB-03 */}
            <Route path="/interests" element={<Interests />} />                           {/* SB-04 */}
            <Route path="/analysis/:id" element={<Results />} />                          {/* SB-05 */}
            <Route path="/analysis/:id/risk/:code" element={<Risk />} />                  {/* SB-06 */}
            <Route path="/analysis/:id/breakeven/:code" element={<BreakEven />} />        {/* SB-07 */}
            <Route path="/report/:rid" element={<ActionReport />} />                      {/* SB-08 */}
            <Route path="/reports" element={<SavedReports />} />                          {/* SB-09 */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </HashRouter>
      </AppProvider>
    </div>
  );
}
